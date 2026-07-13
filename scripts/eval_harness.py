"""
Evaluation harness for Task 1 (triage) and Task 2 (account summarizer).
Runs rule-based and LLM-as-judge checks on a set of test cases.
"""

import json
import os
import re
import sys
import time
import random
import hashlib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.triage import triage_ticket
from src.account_summary import summarize_account

load_dotenv(project_root / ".env")

DATA_ROOT = project_root / "starter-repo" / "data"
REPORT_PATH = project_root / "eval_report.md"
CACHE_PATH = project_root / "eval_cache.json"

api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

# ---------------------------------------------------------------------------
# Caching Utilities
# ---------------------------------------------------------------------------

def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

_cache = load_cache()

def get_cache_key(func_name, payload=None):
    key_str = f"{func_name}:{json.dumps(payload, sort_keys=True)}"
    return hashlib.md5(key_str.encode("utf-8")).hexdigest()

def call_with_cache(func_name, func, payload=None):
    if "--no-cache" in sys.argv:
        return func()
        
    key = get_cache_key(func_name, payload)
    if key in _cache:
        print(f"    ⚡ Using cached result for {func_name}")
        
        # Inject ticket_id/account_id for auditability if not present
        result = _cache[key]
        if isinstance(payload, dict):
            if "ticket_id" in payload and isinstance(result, dict) and "ticket_id" not in result:
                result["ticket_id"] = payload["ticket_id"]
            if "account_id" in payload and isinstance(result, dict) and "account_id" not in result:
                result["account_id"] = payload["account_id"]
                
        return result
        
    result = func()
    
    # Inject ticket_id/account_id for auditability
    if isinstance(payload, dict) and isinstance(result, dict):
        if "ticket_id" in payload and "ticket_id" not in result:
            result["ticket_id"] = payload["ticket_id"]
        if "account_id" in payload and "account_id" not in result:
            result["account_id"] = payload["account_id"]
            
    _cache[key] = result
    save_cache(_cache)
    return result

# ---------------------------------------------------------------------------
# Retry and Backoff Utilities
# ---------------------------------------------------------------------------

def call_with_retry(func, *args, **kwargs):
    max_retries = 6
    base_delay = 10
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "rate_limit" in str(e):
                if attempt == max_retries - 1:
                    raise
                jitter = random.uniform(0, 1)
                delay = (base_delay * (2 ** attempt)) + jitter
                print(f"    ⏳ Rate limited (attempt {attempt+1}/{max_retries}). Retrying in {delay:.2f}s...")
                time.sleep(delay)
            elif "503" in str(e) or "UNAVAILABLE" in str(e):
                if attempt == max_retries - 1:
                    raise
                print(f"    ⏳ 503 Unavailable. Sleeping 15s...")
                time.sleep(15)
            else:
                raise

def ask_llm_structured(prompt: str, schema: dict) -> dict:
    def _call():
        time.sleep(4) # Rate limit pacing
        
        system_prompt = (
            "You are an expert grading judge. You must respond ONLY with a valid JSON object that strictly adheres to the following JSON schema:\n" + 
            json.dumps(schema, indent=2)
        )
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    
    # We cache the string prompt and a version number for the judge
    schema_dict = json.dumps(schema, sort_keys=True)
    payload = {"prompt": prompt, "schema": schema_dict, "version": "v2"}
    
    def _cached_call():
        return call_with_cache("ask_llm_structured", _call, payload=payload)
        
    if "--no-cache" not in sys.argv:
        key = get_cache_key("ask_llm_structured", payload)
        if key in _cache:
            print("    ⚡ Using cached judge result")
            return _cache[key]
        
    res = call_with_retry(_call)
    
    if "--no-cache" not in sys.argv:
        key = get_cache_key("ask_llm_structured", payload)
        _cache[key] = res
        save_cache(_cache)
        
    return res

# ---------------------------------------------------------------------------
# Task 1 Evaluation
# ---------------------------------------------------------------------------

def evaluate_task1(ticket: dict) -> tuple[str, float, str, str]:
    """Score triage output. Returns (status, score, notes, veto_reason)."""
    try:
        def _triage():
            time.sleep(4)
            return call_with_retry(triage_ticket, ticket)
            
        payload = {"ticket_id": ticket.get("ticket_id"), "version": "v3", "body": ticket.get("body")}
        output = call_with_cache("triage_ticket", _triage, payload=payload)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "rate_limit" in str(e):
            return "ERROR", 0.0, f"Rate limited: {e}", ""
        return "ERROR", 0.0, f"Exception during triage: {e}", ""

    score = 0.0
    notes = []
    veto_reason = ""

    # Hard Veto: If the true ticket urgency is P1, but the model didn't classify it as P1
    output_urgency = output.get("urgency_tier")
    if ticket.get("urgency") == "P1" and output_urgency != "P1":
        veto_reason = "Missed P1 Urgency"

    # Rule 1: urgency_tier is valid (0.2)
    if output.get("urgency_tier") in ["P1", "P2", "P3", "P4"]:
        score += 0.2
    else:
        notes.append("urgency_tier missing or invalid.")

    # Rule 2: recommended_team is non-empty (0.2)
    if output.get("recommended_team"):
        score += 0.2
    else:
        notes.append("recommended_team is missing.")

    # Rule 3: matched_kb_doc format (0.2)
    kb = output.get("matched_kb_doc")
    if kb is None or isinstance(kb, str) or isinstance(kb, list):
        score += 0.2
    else:
        notes.append("matched_kb_doc must be string, list or null.")

    # LLM Judge: draft_response quality (0.4)
    judge_prompt = (
        f"Evaluate the following support draft response.\n"
        f"Ticket Context: {ticket['subject']}\n{ticket['body']}\n\n"
        f"Draft Response: {output.get('draft_response')}\n\n"
        f"Score 1.0 if it is professional, empathetic, addresses the core issue, and makes no false promises. "
        f"Score 0.5 if it is mediocre. Score 0.0 if it is poor or missing."
    )
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "A score between 0.0 and 1.0", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"}
        },
        "required": ["score", "reasoning"]
    }
    
    try:
        res = ask_llm_structured(judge_prompt, schema)
        llm_score = float(res.get("score", 0.0))
        llm_score = max(0.0, min(1.0, llm_score)) # Clamp
        score += (llm_score * 0.4)
        if llm_score < 0.8:
            notes.append(f"LLM Judge score was {llm_score:.2f}")
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "rate_limit" in str(e):
            return "ERROR", score, f"Rate limited in judge: {e}", ""
        return "ERROR", score, f"Judge error: {e}", ""

    passed = score >= 0.8
    if veto_reason:
        passed = False
        
    if not notes:
        notes.append("All rules passed.")
    
    status = "PASS" if passed else "FAIL"
    return status, score, "; ".join(notes), veto_reason

# ---------------------------------------------------------------------------
# Task 2 Evaluation
# ---------------------------------------------------------------------------

def evaluate_task2(account_id: str, tickets_data: list) -> tuple[str, float, str, str]:
    """Score account summary output. Returns (status, score, notes, veto_reason)."""
    try:
        def _summary():
            time.sleep(4)
            return call_with_retry(summarize_account, account_id)
            
        payload = {"account_id": account_id, "version": "v3"}
        output = call_with_cache("summarize_account", _summary, payload=payload)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "rate_limit" in str(e):
            return "ERROR", 0.0, f"Rate limited: {e}", ""
        return "ERROR", 0.0, f"Exception during summary: {e}", ""

    score = 0.0
    notes = []
    veto_reason = ""
    
    account_tickets = [t for t in tickets_data if t["account_id"] == account_id]
    
    # Rule 1: executive_summary is 3-5 sentences (0.2)
    exec_sum = output.get("executive_summary", "")
    sentences = [s for s in re.split(r'[.!?]+', exec_sum) if s.strip()]
    if 3 <= len(sentences) <= 5:
        score += 0.2
    else:
        notes.append(f"Exec summary has {len(sentences)} sentences (expected 3-5).")

    # Rules 2 & 3: risks_and_flags validation (0.4 total)
    risks = output.get("risks_and_flags", [])
    valid_ids = True
    for risk in risks:
        tid = risk.get("ticket_id")
        # Must exist in account's tickets
        matching_ticket = next((t for t in account_tickets if t["ticket_id"] == tid), None)
        if not matching_ticket:
            valid_ids = False
            notes.append(f"Ticket {tid} not found in account's tickets.")
            
    if valid_ids: 
        score += 0.2
    else:
        notes.append("ticket_ids mismatch.")

    # Rule 2: Quotes match ticket bodies (0.2)
    valid_quotes = True
    for item in output.get("risks_and_flags", []):
        quote = item.get("verbatim_quote")
        tid = item.get("ticket_id")
        
        if not quote:
            valid_quotes = False
            notes.append(f"Blank verbatim_quote for {tid}.")
            continue
            
        matching_ticket = next((t for t in account_tickets if t["ticket_id"] == tid), None)
        if not matching_ticket:
            continue
            
        # Quote must literally exist in ticket body
        body_norm = re.sub(r"\s+", " ", matching_ticket["body"]).strip()
        quote_norm = re.sub(r"\s+", " ", quote).strip()
        if quote_norm not in body_norm:
            valid_quotes = False
            notes.append(f"Quote for {tid} not found in source text.")

    if valid_quotes: 
        score += 0.2

    # Combined LLM Judge: overconfidence (0.2) & talking points (0.2)
    judge_prompt = (
        f"Evaluate the following executive summary and talking points.\n"
        f"Summary: {exec_sum}\n"
        f"Talking Points: {output.get('talking_points')}\n\n"
        f"Task A (Epistemic Safety): If the summary presents claims about 'P1 tickets' or 'evaluating competing vendors' "
        f"as absolute verified facts without hedging (e.g. 'Customer had 3 P1 tickets'), score it 0.0.\n"
        f"If it correctly hedges them as reported context (e.g. 'TAM notes indicate...', 'Reportedly...', or there are no such claims), score it 1.0.\n\n"
        f"Task B (Talking Points Relevance): Score 1.0 if the talking points are actionable and relevant to the summary. "
        f"Score 0.0 if they are generic or irrelevant."
    )
    schema = {
        "type": "object",
        "properties": {
            "overconfidence_score": {"type": "number", "description": "Score for Task A (0.0 or 1.0)", "minimum": 0, "maximum": 1},
            "tp_score": {"type": "number", "description": "Score for Task B (0.0 or 1.0)", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"}
        },
        "required": ["overconfidence_score", "tp_score", "reasoning"]
    }
    
    try:
        res = ask_llm_structured(judge_prompt, schema)
        overconfidence_score = float(res.get("overconfidence_score", 0.0))
        tp_score = float(res.get("tp_score", 0.0))
        
        overconfidence_score = max(0.0, min(1.0, overconfidence_score))
        tp_score = max(0.0, min(1.0, tp_score))
        
        score += (overconfidence_score * 0.2)
        score += (tp_score * 0.2)
        
        if tp_score < 1.0:
            notes.append("Talking points were generic or irrelevant.")
            
        if overconfidence_score < 0.5:
            notes.append("Failed LLM-judge: Presented unverified claims as absolute fact.")
            veto_reason = "Epistemic Safety Veto"
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "rate_limit" in str(e):
            return "ERROR", score, f"Rate limited in judge: {e}", ""
        return "ERROR", score, f"Judge error: {e}", ""

    passed = score >= 0.8
    if veto_reason:
        passed = False
        
    if not notes:
        notes.append("All rules passed.")

    status = "PASS" if passed else "FAIL"
    return status, score, "; ".join(notes), veto_reason

# ---------------------------------------------------------------------------
# Main Harness
# ---------------------------------------------------------------------------

def main():
    tickets = json.loads((DATA_ROOT / "tickets.json").read_text(encoding="utf-8"))
    accounts = json.loads((DATA_ROOT / "accounts.json").read_text(encoding="utf-8"))

    # Select 5 tickets for Task 1
    t1 = next(t for t in tickets if t["category"] == "Bug" and t["urgency"] == "P1")
    t2 = next(t for t in tickets if t["category"] == "How-To")
    t3 = next(t for t in tickets if t["category"] == "Billing")
    t4 = next(t for t in tickets if t["category"] == "Feature Request")
    t5 = next(t for t in tickets if t["ticket_id"] == "TKT-10035") # Ambiguous

    task1_cases = [t5, t1, t2, t3, t4]

    # Select 5 accounts for Task 2
    a1 = next(a for a in accounts if a["health_status"] == "Healthy")
    a2 = next(a for a in accounts if a["health_status"] == "New")
    a3 = next(a for a in accounts if a["health_status"] == "Churning" and a["account_id"] != "ACC-3336")
    a4 = next(a for a in accounts if a["health_status"] == "At Risk" and len(a["escalation_notes"]) > 0 and a["account_id"] != "ACC-3336")
    a5 = next(a for a in accounts if a["account_id"] == "ACC-3336") # Adversarial

    task2_cases = [a5["account_id"], a1["account_id"], a2["account_id"], a3["account_id"], a4["account_id"]]

    results = []

    print("Running Task 1 (Triage) Evaluations...")
    for t in task1_cases:
        print(f"  Evaluating {t['ticket_id']}...")
        status, score, notes, veto_reason = evaluate_task1(t)
        if status == "ERROR":
            print(f"    ❌ ERROR hit: {notes}")
        results.append({
            "task": "Task 1",
            "case_id": t["ticket_id"],
            "status": status,
            "score": score,
            "notes": notes,
            "veto_reason": veto_reason
        })

    print("Running Task 2 (Summarizer) Evaluations...")
    for acc_id in task2_cases:
        print(f"  Evaluating {acc_id}...")
        status, score, notes, veto_reason = evaluate_task2(acc_id, tickets)
        if status == "ERROR":
            print(f"    ❌ ERROR hit: {notes}")
        results.append({
            "task": "Task 2",
            "case_id": acc_id,
            "status": status,
            "score": score,
            "notes": notes,
            "veto_reason": veto_reason
        })

    # Generate Markdown Report
    report_lines = [
        "# Evaluation Report",
        "",
        "| Task | Test Case ID | Status | Score | Veto Reason | Notes |",
        "|------|--------------|--------|-------|-------------|-------|"
    ]
    
    t1_passes = sum(1 for r in results if r["task"] == "Task 1" and r["status"] == "PASS")
    t1_errors = sum(1 for r in results if r["task"] == "Task 1" and r["status"] == "ERROR")
    t2_passes = sum(1 for r in results if r["task"] == "Task 2" and r["status"] == "PASS")
    t2_errors = sum(1 for r in results if r["task"] == "Task 2" and r["status"] == "ERROR")

    for r in results:
        if r["status"] == "PASS":
            status_icon = "✅ PASS"
        elif r["status"] == "FAIL":
            status_icon = "❌ FAIL"
        else:
            status_icon = "⚠️ ERROR"
        report_lines.append(
            f"| {r['task']} | {r['case_id']} | {status_icon} | {r['score']:.2f} | {r.get('veto_reason', '')} | {r['notes']} |"
        )
        
    report_lines.extend([
        "",
        "## Summary",
        f"- **Task 1 (Triage) Pass Rate**: {t1_passes}/5 ({(t1_passes/5)*100:.0f}%) | Errors: {t1_errors}",
        f"- **Task 2 (Summarizer) Pass Rate**: {t2_passes}/5 ({(t2_passes/5)*100:.0f}%) | Errors: {t2_errors}"
    ])

    REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Evaluation complete. Report saved to {REPORT_PATH}")

if __name__ == "__main__":
    main()

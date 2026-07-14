"""
Run triage_ticket on 3 real tickets from tickets.json and save outputs.

Selected tickets:
  - TKT-10088  (P1-looking) — URGENT: Missing data in WorkflowEngine Error Handling
  - TKT-10018  (P4-looking) — Best practice for Key Management setup — SecureVault
  - TKT-10035  (ambiguous)  — SecureVault running extremely slowly for our team
"""

import json
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.triage import triage_ticket

TICKETS_PATH = project_root / "starter-repo" / "data" / "tickets.json"
OUTPUT_PATH = project_root / "examples" / "task1_outputs.json"

SELECTED_IDS = ["TKT-10088", "TKT-10018", "TKT-10035"]
LABELS = {
    "TKT-10088": "P1-looking (critical data loss, business continuity at risk)",
    "TKT-10018": "P4-looking (new customer how-to question)",
    "TKT-10035": "Ambiguous (performance issue labelled as Integration, could be P1-P3)",
}

MAX_RETRIES = 4
RETRY_DELAYS = [5, 15, 30, 60]


def triage_with_retry(ticket: dict) -> dict:
    """Call triage_ticket with retries on transient errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return triage_ticket(ticket)
        except Exception as e:
            err_str = str(e)
            if "503" in err_str or "UNAVAILABLE" in err_str or "overloaded" in err_str or "429" in err_str or "rate_limit" in err_str:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    print(f"    [Retry] Transient error {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
            else:
                raise


def main() -> None:
    tickets = json.loads(TICKETS_PATH.read_text(encoding="utf-8"))
    ticket_map = {t["ticket_id"]: t for t in tickets}

    results = []

    for i, tid in enumerate(SELECTED_IDS):
        ticket = ticket_map[tid]
        label = LABELS[tid]
        print(f"\n{'='*60}")
        print(f"[{i+1}/3] Triaging {tid}: {ticket['subject']}")
        print(f"Selection reason: {label}")
        print(f"{'='*60}")

        if i > 0:
            print("  ⏳ Waiting 5s between requests...")
            time.sleep(5)

        triage_result = triage_with_retry(ticket)

        entry = {
            "ticket_id": tid,
            "selection_reason": label,
            "original_ticket": {
                "subject": ticket["subject"],
                "body": ticket["body"],
                "product": ticket["product"],
                "product_area": ticket["product_area"],
                "category": ticket["category"],
                "urgency": ticket["urgency"],
            },
            "triage_output": triage_result,
        }
        results.append(entry)

        print(json.dumps(triage_result, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n✅ Saved {len(results)} triage results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

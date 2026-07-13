"""
Intelligent ticket triage agent.

Accepts a support ticket (raw text or dict with subject+body) and returns
structured classification JSON using Groq with JSON mode.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional, Union

from dotenv import load_dotenv
from groq import Groq

from src.kb_retrieval import KBIndex

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "triage_system.md"
_KB_ROOT = _PROJECT_ROOT / "starter-repo" / "knowledge-base"

# ---------------------------------------------------------------------------
# Load env & system prompt
# ---------------------------------------------------------------------------

load_dotenv(_PROJECT_ROOT / ".env")

_SYSTEM_PROMPT: str = _PROMPT_PATH.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# KB index (module-level singleton — built once)
# ---------------------------------------------------------------------------

_kb_index = KBIndex(_KB_ROOT)

# ---------------------------------------------------------------------------
# JSON Schema for structured output
# ---------------------------------------------------------------------------

_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "product_area": {
            "type": "string",
            "description": "The specific product module affected (e.g. 'Data Ingestion', 'Dashboard', 'File Sync', 'Authentication', 'Error Handling')."
        },
        "issue_category": {
            "type": "string",
            "enum": [
                "Bug",
                "Feature Request",
                "How-To",
                "Performance",
                "Billing",
                "Integration",
                "Onboarding",
                "Data Loss"
            ],
            "description": "The primary issue category."
        },
        "urgency_tier": {
            "type": "string",
            "enum": ["P1", "P2", "P3", "P4"],
            "description": "Priority tier from P1 (critical) to P4 (low)."
        },
        "reasoning": {
            "type": "string",
            "description": "A short (1-3 sentence) justification for the classification."
        },
        "matched_kb_doc": {
            "type": ["string", "null"],
            "description": "The most relevant file path under starter-repo/knowledge-base/ if the ticket matches a known issue pattern, else null."
        },
        "recommended_team": {
            "type": "string",
            "enum": [
                "platform-engineering",
                "integrations",
                "billing-support",
                "customer-success",
                "security-team"
            ],
            "description": "The team best suited to handle this ticket."
        },
        "draft_response": {
            "type": "string",
            "description": "A professional, empathetic first-response draft for the support agent to send to the customer."
        }
    },
    "required": [
        "product_area",
        "issue_category",
        "urgency_tier",
        "reasoning",
        "matched_kb_doc",
        "recommended_team",
        "draft_response"
    ]
}

# ---------------------------------------------------------------------------
# Core triage function
# ---------------------------------------------------------------------------

from typing import Any, Union, Generator

def triage_ticket(
    ticket_input: Union[str, dict[str, Any]],
    *,
    model: str = "llama-3.1-8b-instant",
    stream: bool = False,
) -> Union[dict[str, Any], Generator[str, None, None]]:
    """
    Triage a support ticket.

    Parameters
    ----------
    ticket_input
        Either raw text (str) or a dict with at least ``subject`` and ``body``
        keys (matching the tickets.json schema).
    model
        Groq model identifier.

    Returns
    -------
    dict
        Structured triage result with keys: product_area, issue_category,
        urgency_tier, reasoning, matched_kb_doc, recommended_team,
        draft_response.
    """
    # -- normalise input ----------------------------------------------------
    if isinstance(ticket_input, str):
        ticket_text = ticket_input
        extra_fields = ""
    elif isinstance(ticket_input, dict):
        subject = ticket_input.get("subject", "")
        body = ticket_input.get("body", "")
        ticket_text = f"Subject: {subject}\n\nBody:\n{body}"
        # Include optional metadata the LLM can factor in
        extra_parts = []
        for key in ("product", "product_area", "plan_tier", "channel", "tags"):
            if key in ticket_input and ticket_input[key]:
                extra_parts.append(f"{key}: {ticket_input[key]}")
        extra_fields = "\n".join(extra_parts)
    else:
        raise TypeError(
            f"ticket_input must be str or dict, got {type(ticket_input).__name__}"
        )

    # -- KB retrieval -------------------------------------------------------
    kb_matches = _kb_index.search(ticket_text, top_k=2)
    kb_context = ""
    for kb_match_path, _score in kb_matches:
        kb_path = _KB_ROOT.parent / kb_match_path
        if kb_path.exists():
            kb_content = kb_path.read_text(encoding="utf-8")
            kb_context += (
                f"\n\n--- Potentially relevant KB document: {kb_match_path} ---\n"
                f"{kb_content[:2000]}"
            )
    kb_best = kb_matches[0][0] if kb_matches else None
    
    # Ensure kb_best has 'starter-repo/' prefix if it matched
    if kb_best and not kb_best.startswith("starter-repo/"):
        kb_best = f"starter-repo/{kb_best}"

    # -- build user message -------------------------------------------------
    user_message = f"Triage the following support ticket:\n\n{ticket_text}"
    if extra_fields:
        user_message += f"\n\nAdditional ticket metadata:\n{extra_fields}"
    if kb_context:
        user_message += kb_context

    # -- build system message with schema -----------------------------------
    system_prompt = (
        _SYSTEM_PROMPT + 
        "\n\nYou must respond ONLY with a valid JSON object that strictly adheres to the following JSON schema:\n" + 
        json.dumps(_TRIAGE_SCHEMA, indent=2)
    )

    # -- call Groq with JSON mode -------------------------------------------
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            stream=stream,
            timeout=30.0
        )
        
        if stream:
            def json_stream():
                for chunk in response:
                    text = chunk.choices[0].delta.content
                    if text:
                        yield text
            return json_stream()

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from API")
        result: dict[str, Any] = json.loads(content)
    except Exception as e:
        raise RuntimeError(f"Triage API failure: {e}") from e

    # Ensure matched_kb_doc uses our retrieval result when relevant
    if not result.get("matched_kb_doc") and kb_best:
        result["matched_kb_doc"] = kb_best

    return result

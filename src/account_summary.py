"""
TAM Account Health Summarizer (Task 2)
Pulls account metadata and the last 90 days of tickets to generate a structured 
account health summary with talking points and flagged risks.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

# ---------------------------------------------------------------------------
# Setup and Globals
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_ROOT = _PROJECT_ROOT / "starter-repo" / "data"
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "account_summary_system.md"

load_dotenv(_PROJECT_ROOT / ".env")

_SYSTEM_PROMPT: str = _PROMPT_PATH.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Schema Definition
# ---------------------------------------------------------------------------

_ACCOUNT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "A concise 3 to 5 sentence overview of the account's current health, recent ticket volume/themes, and any immediate retention risks."
        },
        "risks_and_flags": {
            "type": "array",
            "description": "List of flagged tickets indicating churn risk, severe defect, or deep frustration.",
            "items": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "description": "A short reason explaining why it was flagged."
                    },
                    "verbatim_quote": {
                        "type": "string",
                        "description": "A direct quote copied EXACTLY from the ticket's body justifying the flag."
                    }
                },
                "required": ["ticket_id", "reason", "verbatim_quote"]
            }
        },
        "talking_points": {
            "type": "array",
            "description": "Recommended talking points for the TAM's next sync with the customer.",
            "items": {"type": "string"}
        }
    },
    "required": ["executive_summary", "risks_and_flags", "talking_points"]
}

# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def summarize_account(account_id: str, model: str = "llama-3.1-8b-instant") -> dict[str, Any]:
    """
    Summarise an account's health based on its metadata and last 90 days of tickets.

    Parameters
    ----------
    account_id : str
        The account ID to summarize (e.g. 'ACC-3847')
    model : str
        The Groq model to use.

    Returns
    -------
    dict
        Structured account summary containing executive_summary, risks_and_flags,
        and talking_points.
    """
    accounts = json.loads((_DATA_ROOT / "accounts.json").read_text(encoding="utf-8"))
    tickets = json.loads((_DATA_ROOT / "tickets.json").read_text(encoding="utf-8"))

    # 1. Pull the account summary
    account_data = next((a for a in accounts if a["account_id"] == account_id), None)
    if not account_data:
        raise ValueError(f"Account {account_id} not found in accounts.json")

    # 2. Pull tickets from the last 90 days
    latest_ticket_date_str = max(t["created_at"] for t in tickets)
    latest_ticket_date = datetime.fromisoformat(latest_ticket_date_str.replace("Z", "+00:00"))
    cutoff_date = latest_ticket_date - timedelta(days=90)

    recent_tickets = []
    for t in tickets:
        if t["account_id"] == account_id:
            ticket_date = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
            if ticket_date >= cutoff_date:
                recent_tickets.append(t)

    # Build prompt context
    account_json = json.dumps(account_data, indent=2)
    tickets_json = json.dumps(recent_tickets, indent=2)
    
    user_message = (
        f"Please provide an account health summary for Account ID: {account_id}\n\n"
        f"--- ACCOUNT METADATA ---\n{account_json}\n\n"
        f"--- RECENT TICKETS (Last 90 Days) ---\n{tickets_json}"
    )
    
    system_prompt = (
        _SYSTEM_PROMPT + 
        "\n\nYou must respond ONLY with a valid JSON object that strictly adheres to the following JSON schema:\n" + 
        json.dumps(_ACCOUNT_SUMMARY_SCHEMA, indent=2)
    )

    # 3. Call Groq
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=45.0
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from API")
        result: dict[str, Any] = json.loads(content)
        
        # Runtime schema validation against _ACCOUNT_SUMMARY_SCHEMA
        if not isinstance(result, dict):
            raise ValueError("Response must be a JSON object")
        if not isinstance(result.get("executive_summary"), str):
            raise ValueError("executive_summary must be a string")
        if not isinstance(result.get("risks_and_flags"), list):
            raise ValueError("risks_and_flags must be a list")
        for flag in result["risks_and_flags"]:
            if not isinstance(flag, dict):
                raise ValueError("Each risk flag must be an object")
            if not isinstance(flag.get("ticket_id"), str) or not isinstance(flag.get("reason"), str) or not isinstance(flag.get("verbatim_quote"), str):
                raise ValueError("Flag fields (ticket_id, reason, verbatim_quote) must be strings")
        if not isinstance(result.get("talking_points"), list):
            raise ValueError("talking_points must be a list")

    except Exception as e:
        raise RuntimeError(f"Account summary API failure: {e}") from e

    # 4. Post-processing for determinism and quote validation
    valid_flags = []
    for flag in result["risks_and_flags"]:
        tid = flag["ticket_id"]
        quote = flag["verbatim_quote"]
        if not quote:
            continue
            
        # Deterministic quote validation exactly matching ticket body
        matching_ticket = next((t for t in recent_tickets if t["ticket_id"] == tid), None)
        if matching_ticket and isinstance(matching_ticket.get("body"), str):
            if quote in matching_ticket["body"]:
                valid_flags.append(flag)

    result["risks_and_flags"] = valid_flags
    result["risks_and_flags"].sort(key=lambda x: x["ticket_id"])

    return result

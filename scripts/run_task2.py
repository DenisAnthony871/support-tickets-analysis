"""
Run summarize_account on 2 real accounts from accounts.json (one healthy, one churning)
and save outputs.
"""

import json
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.account_summary import summarize_account

DATA_ROOT = project_root / "starter-repo" / "data"
OUTPUT_PATH = project_root / "examples" / "task2_outputs.json"

MAX_RETRIES = 4
RETRY_DELAYS = [5, 15, 30, 60]

def summarize_with_retry(account_id: str) -> dict:
    """Call summarize_account with retries on transient errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return summarize_account(account_id)
        except Exception as exc:
            err_str = str(exc).lower()
            if "503" in err_str or "unavailable" in err_str or "overloaded" in err_str or "429" in err_str or "rate_limit" in err_str:
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAYS[attempt]
                    print(f"  ⏳ Rate limited (attempt {attempt + 1}), retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
            else:
                raise

def main() -> None:
    accounts = json.loads((DATA_ROOT / "accounts.json").read_text(encoding="utf-8"))

    healthy_account = next(a for a in accounts if a["health_status"] == "Healthy")
    churning_account = next(a for a in accounts if a["health_status"] in ("At Risk", "Churning") and len(a["escalation_notes"]) > 0)

    selected_accounts = [
        (healthy_account["account_id"], "Healthy (Low Risk)"),
        (churning_account["account_id"], "Churning / At Risk (Escalation Signals)")
    ]

    results = []

    for i, (acc_id, label) in enumerate(selected_accounts):
        print(f"\n{'='*60}")
        print(f"[{i+1}/2] Summarizing {acc_id}")
        print(f"Selection reason: {label}")
        print(f"{'='*60}")

        if i > 0:
            print("  ⏳ Waiting 5s between requests...")
            time.sleep(5)

        summary_result = summarize_with_retry(acc_id)

        entry = {
            "account_id": acc_id,
            "selection_reason": label,
            "summary_output": summary_result,
        }
        results.append(entry)

        print(json.dumps(summary_result, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n✅ Saved {len(results)} summary results to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()

"""
Check determinism of the summarize_account function by running it twice
on the same account and diffing the JSON outputs.
"""

import json
import sys
import difflib
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.account_summary import summarize_account

def main():
    accounts = json.loads((project_root / "starter-repo" / "data" / "accounts.json").read_text(encoding="utf-8"))
    test_account = next(a for a in accounts if a["health_status"] == "Churning" and len(a["escalation_notes"]) > 0)
    acc_id = test_account["account_id"]

    print(f"Running summarize_account for {acc_id} (Run 1)...")
    res1 = summarize_account(acc_id)

    print(f"Running summarize_account for {acc_id} (Run 2)...")
    res2 = summarize_account(acc_id)

    str1 = json.dumps(res1, indent=2)
    str2 = json.dumps(res2, indent=2)

    if str1 == str2:
        print("\n✅ Determinism Check Passed: The two JSON outputs are completely identical.")
    else:
        print("\n❌ Determinism Check Failed: The outputs differ.")
        print("\nDiff:")
        diff = difflib.unified_diff(
            str1.splitlines(),
            str2.splitlines(),
            fromfile='Run 1',
            tofile='Run 2',
            lineterm=''
        )
        for line in diff:
            print(line)
        sys.exit(1)

if __name__ == "__main__":
    main()

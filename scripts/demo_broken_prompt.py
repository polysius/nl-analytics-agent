"""Run the CI subset with a deliberately broken SQL prompt, to show the accuracy gate failing.

    python scripts/demo_broken_prompt.py reports/broken.json
    python -m nlagent.regression --report reports/broken.json --baseline benchmark/ci_baseline.json

The second command should print FAIL and exit 1. The broken prompt tells the model to answer
with one word, so almost no query is valid SQL.
"""

import sys

from nlagent import prompts

BROKEN = "Reply with the single word hello and nothing else."
prompts.SQL_SYSTEM = BROKEN
prompts.REPAIR_SYSTEM = BROKEN

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "reports/broken.json"
    sys.argv = ["evaluate", "--config", "graph", "--limit", "20", "--out", out]
    from nlagent.evaluate import main

    main()

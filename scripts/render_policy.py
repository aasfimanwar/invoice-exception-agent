"""Write docs/POLICY.md from policy/policy.yaml, or verify it is in sync with --check."""

from __future__ import annotations

import sys
from pathlib import Path

from invoice_agent.policy_file import REPO_ROOT, load_valid_policy
from invoice_agent.policy_render import render_policy_markdown

TARGET = REPO_ROOT / "docs" / "POLICY.md"


def main(argv: list[str]) -> int:
    expected = render_policy_markdown(load_valid_policy())
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") != expected:
            print("docs/POLICY.md is out of sync with policy/policy.yaml.")
            print("Run: uv run python scripts/render_policy.py")
            return 1
        print("docs/POLICY.md is in sync.")
        return 0
    Path(TARGET).write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

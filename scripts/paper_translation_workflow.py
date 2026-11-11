# SPDX-License-Identifier: AGPL-3.0-only
"""DeepSeek Harness entry point for current-session PDF translation."""
import sys

from session_translate_entry import main


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "translate":
        sys.exit("Usage: paper_translation_workflow.py translate --help")
    sys.exit(main(sys.argv[2:]))

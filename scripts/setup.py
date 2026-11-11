# SPDX-License-Identifier: AGPL-3.0-only
"""Create this skill's local Python environment and install its PDF dependency."""
from pathlib import Path
import os
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 10):
        sys.exit("Run setup.py with Python 3.10 or newer (tested with Python 3.13).")
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
        check=True,
    )
    subprocess.run([str(python), "-c", "import pymupdf; print(pymupdf.__version__)"], check=True)
    print(f"PDF translation environment ready: {python}")


if __name__ == "__main__":
    main()

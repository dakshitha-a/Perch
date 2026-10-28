"""Block secrets and personal details before they reach git history.

The repo will be made public, so tracked files and commit messages must hold
no API keys, tokens, local paths, emails or session links.

Usage:
  python scripts/check_public.py --staged        # pre-commit: staged file contents
  python scripts/check_public.py --tracked       # all tracked files (used by tests)
  python scripts/check_public.py --message FILE  # commit-msg: the message file
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Built from pieces so this file does not match its own patterns.
PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API key": re.compile("sk-" + r"ant-[A-Za-z0-9_\-]{10,}"),
    "OpenAI-style API key": re.compile(r"\bsk-" + r"(?:proj-)?[A-Za-z0-9]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]" + r"_[A-Za-z0-9]{20,}"),
    "AWS access key": re.compile(r"\bAKIA" + r"[0-9A-Z]{16}\b"),
    "private key block": re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----"),
    "assigned secret": re.compile(
        r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[ \t]*=[ \t]*['\"]?[A-Za-z0-9_\-]{12,}"
    ),
    "local path": re.compile(r"(?<![\w.])/(?:home|data|Users)" + r"/[A-Za-z0-9_.\-]+/"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+\-]+@(?!users\.noreply\.github\.com)"
                                + r"[A-Za-z0-9\-]+\.[A-Za-z]{2,}\b"),
    "Claude session link": re.compile("claude" + r"\.ai/code/session_"),
}

# Allowed emails: the Claude co-author trailer only.
ALLOWED = ("noreply@" + "anthropic.com",)

# Files that may never be tracked, whatever they contain.
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env(\..+)?|CLAUDE\.local\.md|.*\.pem|.*\.key)$")
FORBIDDEN_OK = {".env.example"}


def scan_text(text: str) -> list[str]:
    hits = []
    for label, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            if any(a in m.group(0) or m.group(0) in a for a in ALLOWED):
                continue
            hits.append(f"{label}: {m.group(0)[:40]}")
    return hits


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def check_files(paths: list[str], staged: bool) -> list[str]:
    problems = []
    for path in paths:
        if FORBIDDEN_NAMES.search(path) and Path(path).name not in FORBIDDEN_OK:
            problems.append(f"{path}: file must not be committed")
            continue
        try:
            text = git("show", f":{path}") if staged else Path(path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, subprocess.CalledProcessError, FileNotFoundError):
            continue
        problems += [f"{path}: {hit}" for hit in scan_text(text)]
    return problems


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--message":
        problems = [f"commit message: {h}" for h in scan_text(Path(argv[2]).read_text())]
    elif len(argv) >= 2 and argv[1] == "--staged":
        paths = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").split()
        problems = check_files(paths, staged=True)
    else:
        problems = check_files(git("ls-files").split(), staged=False)
    for p in problems:
        print(f"check_public: {p}", file=sys.stderr)
    if problems:
        msg = "check_public: blocked. The repo will be public; remove these first."
        print(msg, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

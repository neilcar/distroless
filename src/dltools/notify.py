"""Upsert GitHub issues (one open issue per title) through the gh CLI."""

from __future__ import annotations

import json
import subprocess


def upsert_issue(title: str, body: str, label: str = "automation", runner=subprocess.run) -> None:
    listed = runner(
        ["gh", "issue", "list", "--label", label, "--state", "open",
         "--search", f"in:title {title}", "--json", "number,title"],
        check=True, capture_output=True, text=True,
    )
    match = next((i for i in json.loads(listed.stdout or "[]") if i["title"] == title), None)
    if match:
        runner(["gh", "issue", "comment", str(match["number"]), "--body", body], check=True)
    else:
        runner(
            ["gh", "label", "create", label, "--force", "--color", "BFD4F2",
             "--description", "Opened by the image automation"],
            check=True,
        )
        runner(
            ["gh", "issue", "create", "--title", title, "--body", body, "--label", label],
            check=True,
        )

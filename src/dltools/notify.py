"""Upsert GitHub issues (one open issue per title) through the gh CLI."""

from __future__ import annotations

import json
import subprocess


def upsert_issue(title: str, body: str, label: str = "automation", runner=subprocess.run,
                 dedupe: bool = False) -> None:
    """Open the issue, or comment on the open one. With `dedupe`, skip the comment when the
    issue body or its latest comment already says exactly `body` (for recurring reports)."""
    listed = runner(
        ["gh", "issue", "list", "--label", label, "--state", "open",
         "--search", f"in:title {title}", "--json", "number,title"],
        check=True, capture_output=True, text=True,
    )
    match = next((i for i in json.loads(listed.stdout or "[]") if i["title"] == title), None)
    if match:
        if dedupe:
            view = runner(["gh", "issue", "view", str(match["number"]), "--json", "body,comments"],
                          check=True, capture_output=True, text=True)
            data = json.loads(view.stdout or "{}")
            seen = [data.get("body", "")] + [c.get("body", "") for c in data.get("comments", [])[-1:]]
            if body.strip() in (b.strip() for b in seen):
                return
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

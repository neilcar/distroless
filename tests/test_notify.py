import json
import subprocess

from dltools.notify import upsert_issue


class FakeRunner:
    def __init__(self, existing):
        self.existing = existing
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        out = json.dumps(self.existing) if args[:3] == ["gh", "issue", "list"] else ""
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


def test_upsert_issue_comments_when_open():
    run = FakeRunner([{"number": 7, "title": "Build failed: python:3.12-runtime"}])
    upsert_issue("Build failed: python:3.12-runtime", "details", runner=run)
    assert run.calls[-1][:4] == ["gh", "issue", "comment", "7"]


def test_upsert_issue_creates_when_absent():
    run = FakeRunner([{"number": 9, "title": "Build failed: python:3.12-runtime-other"}])
    upsert_issue("Build failed: python:3.12-runtime", "details", runner=run)
    last = run.calls[-1]
    assert last[:3] == ["gh", "issue", "create"]
    assert "--label" in last and "automation" in last


def test_upsert_issue_ensures_label_before_creating():
    run = FakeRunner([])
    upsert_issue("New", "body", runner=run)
    names = [c[:3] for c in run.calls]
    assert ["gh", "label", "create"] in names
    assert names.index(["gh", "label", "create"]) < names.index(["gh", "issue", "create"])
    label_call = next(c for c in run.calls if c[:3] == ["gh", "label", "create"])
    assert "--force" in label_call

from dltools.lines import Line
from dltools.state import Event, diff, load_state, save_state


def test_state_round_trip(tmp_path):
    lines = [Line("python", "3.12", "python-3.12", "3.12.15-r6")]
    path = tmp_path / "lines.json"
    save_state(path, lines)
    assert load_state(path) == lines


def test_load_missing_state_is_empty(tmp_path):
    assert load_state(tmp_path / "nope.json") == []


def test_diff_events():
    old = [
        Line("python", "3.10", "python-3.10", "3.10.22-r5"),
        Line("python", "3.12", "python-3.12", "3.12.14-r0"),
        Line("nginx", "stable", "nginx-stable", "1.30.2-r0"),
    ]
    new = [
        Line("python", "3.12", "python-3.12", "3.12.15-r6"),
        Line("python", "3.15", "python-3.15", "3.15.0-r0"),
        Line("nginx", "stable", "nginx-stable", "1.32.0-r0"),
    ]
    events = diff(old, new)
    kinds = sorted(e.kind for e in events)
    assert kinds == [
        "line_added",
        "line_removed",
        "nginx_minor_changed",
        "version_changed",
        "version_changed",
    ]
    added = next(e for e in events if e.kind == "line_added")
    assert added.line.name == "3.15"
    removed = next(e for e in events if e.kind == "line_removed")
    assert removed.line.name == "3.10"
    minor = next(e for e in events if e.kind == "nginx_minor_changed")
    assert "1.30" in minor.detail and "1.32" in minor.detail


def test_diff_no_changes():
    lines = [Line("static", "latest", "ca-certificates-bundle", "20260909-r3")]
    assert diff(lines, lines) == []


def test_event_is_serialisable():
    e = Event("line_added", Line("python", "3.15", "python-3.15", "3.15.0-r0"), "new line")
    assert e.to_dict()["line"]["name"] == "3.15"

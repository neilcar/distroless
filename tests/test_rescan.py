from dltools.rescan import decide


def report(*vulns):
    return {"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": i, "Severity": s, "FixedVersion": f, "PkgName": "p"}
        for i, s, f in vulns
    ]}]}


def test_rescan_fixed_critical_rebuilds():
    d = decide(report(("CVE-1", "CRITICAL", "1.2")), set(), set())
    assert d.open_issue and d.rebuild
    assert "CVE-1" in d.summary


def test_rescan_unfixed_opens_issue_without_rebuild():
    d = decide(report(("CVE-2", "CRITICAL", "")), set(), set())
    assert d.open_issue and not d.rebuild


def test_rescan_known_ids_no_issue():
    d = decide(report(("CVE-3", "HIGH", "")), set(), {"CVE-3"})
    assert not d.open_issue and not d.rebuild


def test_rescan_known_but_now_fixable_rebuilds_without_new_issue():
    d = decide(report(("CVE-3", "HIGH", "2.0")), set(), {"CVE-3"})
    assert d.rebuild and not d.open_issue


def test_rescan_ignored_and_low_are_quiet():
    d = decide(report(("CVE-4", "HIGH", "1"), ("CVE-5", "LOW", "1")), {"CVE-4"}, set())
    assert not d.open_issue and not d.rebuild


def test_rescan_fix_not_available_does_not_rebuild():
    idx = {a: {"p": ["1.0-r0"]} for a in ("x86_64", "aarch64")}
    d = decide(report(("CVE-6", "HIGH", "2.0-r0")), set(), set(), idx)
    assert d.open_issue and not d.rebuild

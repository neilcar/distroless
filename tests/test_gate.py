from dltools.gate import evaluate, findings, load_ignore


def report(*vulns):
    """Trivy JSON shape: Results[].Vulnerabilities[]."""
    return {
        "Results": [
            {
                "Target": "img",
                "Vulnerabilities": [
                    {"VulnerabilityID": vid, "Severity": sev, "FixedVersion": fixed,
                     "PkgName": "pkg", "InstalledVersion": "1"}
                    for vid, sev, fixed in vulns
                ],
            },
            {"Target": "no-vulns"},
        ]
    }


CLEAN = report()


def test_gate_passes_clean():
    r = evaluate(CLEAN, CLEAN, set())
    assert r.passed and r.reasons == []
    assert r.candidate_counts == {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}


def test_gate_blocks_fixable_high():
    r = evaluate(report(("CVE-1", "HIGH", "1.2.3")), CLEAN, set())
    assert not r.passed
    assert any("CVE-1" in reason for reason in r.reasons)


def test_gate_blocks_fixable_critical_on_first_publish():
    assert not evaluate(report(("CVE-9", "CRITICAL", "2.0")), None, set()).passed


def test_gate_allows_unfixed_high_when_not_worse():
    unfixed = report(("CVE-2", "HIGH", ""))
    assert evaluate(unfixed, unfixed, set()).passed


def test_gate_blocks_worse_than_published():
    cand = report(("A", "MEDIUM", ""), ("B", "MEDIUM", ""), ("C", "MEDIUM", ""))
    pub = report(("A", "MEDIUM", ""), ("B", "MEDIUM", ""))
    r = evaluate(cand, pub, set())
    assert not r.passed
    assert any("MEDIUM" in reason and "3" in reason and "2" in reason for reason in r.reasons)


def test_gate_respects_ignore():
    cand = report(("CVE-1", "HIGH", "1.2.3"), ("CVE-3", "LOW", ""))
    r = evaluate(cand, CLEAN, {"CVE-1", "CVE-3"})
    assert r.passed


def test_gate_first_publish():
    r = evaluate(report(("CVE-2", "HIGH", "")), None, set())
    assert r.passed and r.published_counts is None


def test_findings_dedupes_same_id_and_package():
    rep = report(("CVE-1", "LOW", ""), ("CVE-1", "LOW", ""))
    assert len(findings(rep, set())) == 1


def test_load_ignore(tmp_path):
    p = tmp_path / ".trivyignore"
    p.write_text("# owner only\n\nCVE-2026-0001\n  GHSA-xxxx-yyyy-zzzz  # why\n")
    assert load_ignore(p) == {"CVE-2026-0001", "GHSA-xxxx-yyyy-zzzz"}


def test_load_ignore_missing_file(tmp_path):
    assert load_ignore(tmp_path / "missing") == set()


INDEXES = {a: {
    "python-3.13": ["3.13.15-r8", "3.13.15_git20260912-r0"],
    "nginx-stable": ["1.30.2-r0"],
    "zlib": ["1.3.2-r7"],
} for a in ("x86_64", "aarch64")}


def report_pkg(vid, sev, pkg, fixed):
    return {"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": vid, "Severity": sev, "PkgName": pkg, "FixedVersion": fixed}]}]}


def test_gate_fix_only_in_snapshot_is_not_blocking():
    rep = report_pkg("CVE-2026-82049", "HIGH", "python-3.13", "3.13.15_git20260912-r0")
    assert evaluate(rep, None, set(), INDEXES).passed


def test_gate_fix_not_in_wolfi_is_not_blocking():
    rep = report_pkg("CVE-2026-42055", "HIGH", "nginx-stable", "1.30.3-r0")
    assert evaluate(rep, None, set(), INDEXES).passed


def test_gate_released_fix_in_wolfi_blocks():
    rep = report_pkg("CVE-1", "CRITICAL", "zlib", "1.3.2-r5")
    r = evaluate(rep, None, set(), INDEXES)
    assert not r.passed and "zlib" in r.reasons[0]


def test_gate_any_of_several_fixed_versions_counts():
    rep = report_pkg("CVE-2", "HIGH", "zlib", "1.2.13-r9, 1.3.2-r7")
    assert not evaluate(rep, None, set(), INDEXES).passed


def test_gate_unavailable_fixes_are_listed_but_not_blocking():
    rep = report_pkg("CVE-2026-42055", "HIGH", "nginx-stable", "1.30.3-r0")
    r = evaluate(rep, None, set(), INDEXES)
    assert any("CVE-2026-42055" in n and "no released fix" in n for n in r.notes)


def report_typed(vid, sev, pkg, installed, fixed, rtype="wolfi", klass="os-pkgs"):
    return {"Results": [{"Class": klass, "Type": rtype, "Vulnerabilities": [
        {"VulnerabilityID": vid, "Severity": sev, "PkgName": pkg,
         "InstalledVersion": installed, "FixedVersion": fixed}]}]}


def test_gate_note_for_language_package_says_not_a_wolfi_package():
    rep = report_typed("CVE-7", "HIGH", "pip", "24.0", "24.1", "python-pkg", "lang-pkgs")
    r = evaluate(rep, None, set(), INDEXES)
    assert r.passed
    assert any("not a Wolfi package" in n and "python-pkg" in n for n in r.notes)


def test_gate_multi_branch_fixed_versions_compare_against_installed_branch():
    idx = {a: {"python-3.12": ["3.12.15-r6"]} for a in ("x86_64", "aarch64")}
    # fixed on 3.11 (3.11.20) and on 3.12 (3.12.16); installed 3.12.15 is NOT fixed
    rep = report_typed("CVE-8", "HIGH", "python-3.12", "3.12.15-r6", "3.11.20-r0, 3.12.16-r0")
    r = evaluate(rep, None, set(), idx)
    assert r.passed  # newest released 3.12.15 < 3.12.16: no available fix


def test_gate_multi_branch_fix_available():
    idx = {a: {"python-3.12": ["3.12.16-r0"]} for a in ("x86_64", "aarch64")}
    rep = report_typed("CVE-8", "HIGH", "python-3.12", "3.12.15-r6", "3.11.20-r0, 3.12.16-r0")
    assert not evaluate(rep, None, set(), idx).passed


def test_gate_unparseable_fixed_version_noted():
    rep = report_typed("CVE-9", "HIGH", "zlib", "1.3.2-r7", "not-a-version!")
    r = evaluate(rep, None, set(), INDEXES)
    assert r.passed and any("unparseable" in n for n in r.notes)

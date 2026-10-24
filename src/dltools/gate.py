"""Trivy scan gate: block fixable Critical/High findings and regressions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
BLOCKING = ("CRITICAL", "HIGH")


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    package: str
    fixed_version: str


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]
    candidate_counts: dict[str, int]
    published_counts: dict[str, int] | None


def load_ignore(path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    ids = set()
    for line in p.read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.add(entry)
    return ids


def findings(report: dict, ignore: set[str]) -> list[Finding]:
    """Unique findings in a Trivy JSON report, minus ignored IDs."""
    seen: dict[tuple[str, str], Finding] = {}
    for result in report.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            if v["VulnerabilityID"] in ignore:
                continue
            f = Finding(
                v["VulnerabilityID"],
                v.get("Severity", "UNKNOWN").upper(),
                v.get("PkgName", ""),
                v.get("FixedVersion") or "",
            )
            seen.setdefault((f.id, f.package), f)
    return list(seen.values())


def counts(items: list[Finding]) -> dict[str, int]:
    c = dict.fromkeys(SEVERITIES, 0)
    for f in items:
        c[f.severity if f.severity in c else "UNKNOWN"] += 1
    return c


def evaluate(candidate: dict, published: dict | None, ignore: set[str]) -> GateResult:
    cand = findings(candidate, ignore)
    reasons = [
        f"{f.severity} {f.id} in {f.package} has a fix ({f.fixed_version})"
        for f in cand
        if f.severity in BLOCKING and f.fixed_version
    ]
    cand_counts = counts(cand)
    pub_counts = None
    if published is not None:
        pub_counts = counts(findings(published, ignore))
        reasons += [
            f"{sev}: {cand_counts[sev]} findings vs {pub_counts[sev]} in the published image"
            for sev in SEVERITIES
            if cand_counts[sev] > pub_counts[sev]
        ]
    return GateResult(not reasons, reasons, cand_counts, pub_counts)


def summary_markdown(result: GateResult, label: str) -> str:
    rows = [f"### Scan gate: {label} — {'PASS' if result.passed else 'FAIL'}", "",
            "| Severity | Candidate | Published |", "|---|---|---|"]
    for sev in SEVERITIES:
        pub = "—" if result.published_counts is None else result.published_counts[sev]
        rows.append(f"| {sev} | {result.candidate_counts[sev]} | {pub} |")
    rows += [""] + [f"- {r}" for r in result.reasons]
    return "\n".join(rows) + "\n"

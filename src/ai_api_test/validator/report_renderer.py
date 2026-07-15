import json

from .models import Finding, ValidationReport


def render_report(report: ValidationReport, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return _render_markdown(report)
    return _render_text(report)


def _render_text(report: ValidationReport) -> str:
    lines = [
        (
            "Validation finished: "
            f"{report.cases_count} case(s), "
            f"{len(report.errors)} error(s), "
            f"{len(report.warnings)} warning(s), "
            f"{len(report.ai_warnings)} ai warning(s), "
            f"{len(report.infos)} info(s)"
        )
    ]
    if not report.findings:
        lines.append("No findings.")
        return "\n".join(lines)

    lines.append("")
    for finding in report.findings:
        lines.append(_format_finding_text(finding))
        if finding.suggestion:
            lines.append(f"  suggestion: {finding.suggestion}")
    return "\n".join(lines)


def _format_finding_text(finding: Finding) -> str:
    location = []
    if finding.index is not None:
        location.append(f"index={finding.index}")
    if finding.case_id:
        location.append(f"case_id={finding.case_id}")
    if finding.risk:
        location.append(f"risk={finding.risk}")
    location_text = f" ({', '.join(location)})" if location else ""
    return f"[{finding.severity}] {finding.code}{location_text}: {finding.message}"


def _render_markdown(report: ValidationReport) -> str:
    lines = [
        "# Cases Validation Report",
        "",
        "## Summary",
        "",
        f"- Cases: {report.cases_count}",
        f"- Errors: {len(report.errors)}",
        f"- Warnings: {len(report.warnings)}",
        f"- AI Warnings: {len(report.ai_warnings)}",
        f"- Infos: {len(report.infos)}",
        "",
        "## Findings",
        "",
    ]

    if not report.findings:
        lines.append("No findings.")
        return "\n".join(lines)

    lines.extend(
        [
            "| Severity | Risk | Code | Case | Message | Suggestion |",
            "|---|---|---|---|---|---|",
        ]
    )
    for finding in report.findings:
        case_label = finding.case_id or (f"index {finding.index}" if finding.index is not None else "")
        lines.append(
            "| "
            f"{_escape_table(finding.severity)} | "
            f"{_escape_table(finding.risk or '')} | "
            f"{_escape_table(finding.code)} | "
            f"{_escape_table(case_label)} | "
            f"{_escape_table(finding.message)} | "
            f"{_escape_table(finding.suggestion or '')} |"
        )
    return "\n".join(lines)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")

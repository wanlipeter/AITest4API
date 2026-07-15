from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    case_id: str | None = None
    index: int | None = None
    risk: str | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.case_id is not None:
            payload["case_id"] = self.case_id
        if self.index is not None:
            payload["index"] = self.index
        if self.risk:
            payload["risk"] = self.risk
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


@dataclass(frozen=True)
class ValidationReport:
    cases_count: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def infos(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "info"]

    @property
    def ai_warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "ai_warning"]

    def exit_code(self, strict: bool = False) -> int:
        if self.errors:
            return 1
        if strict and self.warnings:
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "cases": self.cases_count,
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "ai_warnings": len(self.ai_warnings),
                "infos": len(self.infos),
            },
            "findings": [finding.to_dict() for finding in self.findings],
        }

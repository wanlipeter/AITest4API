import json
from pathlib import Path
from typing import Any

from ..knowledge.apifox_parser import ApiEndpoint, ApifoxOpenApiParser
from ..providers.config import AiProviderConfig, normalize_provider_name
from ..providers.openai_compatible_provider import OpenAICompatibleProvider
from .models import Finding, ValidationReport


class AiCaseReviewer:
    def review_file(
        self,
        cases_path: Path,
        openapi_path: Path | None,
        rule_report: ValidationReport,
        provider: str,
    ) -> list[Finding]:
        try:
            provider = normalize_provider_name(provider)
            raw_cases = json.loads(cases_path.read_text(encoding="utf-8"))
            cases = self._extract_cases(raw_cases)
            endpoints = self._load_endpoints(openapi_path)
            payload = self._build_review_payload(cases, endpoints, rule_report)
            settings = AiProviderConfig.load(Path.cwd()).chat_settings(provider)
            response_text = OpenAICompatibleProvider(settings)._chat(
                system_prompt=(
                    "你是资深接口自动化测试用例评审专家。"
                    "你只返回合法 JSON，不要 Markdown，不要解释。"
                    "你的结论是语义建议，不要重复本地规则已经明确指出的问题。"
                ),
                user_prompt=self._build_prompt(payload),
            )
            return self._findings_from_response(response_text)
        except Exception as error:
            return [
                Finding(
                    severity="error",
                    code="AI_REVIEW_FAILED",
                    message=f"AI 语义审查失败: {error}",
                    suggestion="请检查 --provider 对应的 API Key、base_url、model 和网络连通性。",
                )
            ]

    def _extract_cases(self, raw_data: Any) -> list[dict[str, Any]]:
        if isinstance(raw_data, list):
            return [case for case in raw_data if isinstance(case, dict)]
        if isinstance(raw_data, dict) and isinstance(raw_data.get("cases"), list):
            return [case for case in raw_data["cases"] if isinstance(case, dict)]
        return []

    def _load_endpoints(self, openapi_path: Path | None) -> list[ApiEndpoint]:
        if openapi_path is None:
            return []
        try:
            return ApifoxOpenApiParser().parse(openapi_path)
        except Exception:
            return []

    def _build_review_payload(
        self,
        cases: list[dict[str, Any]],
        endpoints: list[ApiEndpoint],
        rule_report: ValidationReport,
    ) -> dict[str, Any]:
        return {
            "review_focus": [
                "假通过风险：用例通过但实际验证的是失败响应、错误数据或无意义断言",
                "业务语义不一致：case_id/name/request/assertions 的场景含义互相矛盾",
                "覆盖不足：缺少正向、必填缺失、类型/边界、鉴权、空值、枚举非法等重要场景",
            ],
            "cases": cases,
            "openapi_summary": [self._endpoint_to_summary(endpoint) for endpoint in endpoints],
            "rule_findings": [finding.to_dict() for finding in rule_report.findings],
        }

    def _endpoint_to_summary(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        return {
            "method": endpoint.method,
            "path": endpoint.path,
            "name": endpoint.name,
            "success_status": endpoint.success_status,
            "path_fields": [field.__dict__ for field in endpoint.path_fields],
            "query_fields": [field.__dict__ for field in endpoint.query_fields],
            "request_fields": [field.__dict__ for field in endpoint.request_fields],
        }

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        return (
            "请评审下面的接口测试 cases。\n"
            "重点检查：\n"
            "1. 假通过风险：例如正向用例断言 success=false、错误 code、数据不存在，"
            "或只断言 status_code 导致业务失败也通过。\n"
            "2. 业务语义不一致：例如 case_id/name 说 success，但 request/assertions 是失败场景；"
            "missing_required 但没有缺参；invalid_type 但值类型正常。\n"
            "3. 覆盖不足：指出当前用例集缺少的重要场景，如鉴权失败、边界值、空值、枚举非法、"
            "必填缺失、有效数据正向成功等。\n"
            "4. 不要重复 rule_findings 中已经明确列出的问题，除非你能补充更具体的业务风险。\n\n"
            "输出要求：\n"
            "1. 只返回合法 JSON，不要 Markdown，不要代码块。\n"
            "2. 顶层格式必须是 {\"findings\": [...], \"coverage_suggestions\": [...]}。\n"
            "3. findings 中每项格式："
            "{\"risk\":\"high|medium|low\",\"case_id\":\"...\",\"code\":\"...\","
            "\"message\":\"...\",\"suggestion\":\"...\"}。\n"
            "4. code 建议使用 FALSE_PASS_RISK、SEMANTIC_MISMATCH、WEAK_ASSERTION、"
            "COVERAGE_GAP、TEST_DATA_RISK。\n"
            "5. 没有发现问题时返回 {\"findings\": [], \"coverage_suggestions\": []}。\n\n"
            f"评审输入 JSON：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _findings_from_response(self, response_text: str) -> list[Finding]:
        data = self._parse_json_response(response_text)
        findings: list[Finding] = []

        for item in data.get("findings", []):
            if not isinstance(item, dict):
                continue
            findings.append(
                Finding(
                    severity="ai_warning",
                    code=str(item.get("code") or "AI_SEMANTIC_RISK"),
                    case_id=self._optional_str(item.get("case_id")),
                    risk=str(item.get("risk") or "medium"),
                    message=str(item.get("message") or "AI 发现潜在语义风险。"),
                    suggestion=self._optional_str(item.get("suggestion")),
                )
            )

        for suggestion in data.get("coverage_suggestions", []):
            if not suggestion:
                continue
            findings.append(
                Finding(
                    severity="ai_warning",
                    code="AI_COVERAGE_SUGGESTION",
                    risk="medium",
                    message=str(suggestion),
                )
            )

        return findings

    def _parse_json_response(self, response_text: str) -> dict[str, Any]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        data = json.loads(text)
        return data if isinstance(data, dict) else {}

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

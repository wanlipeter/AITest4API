import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..generator.assertions import normalize_assertions
from ..knowledge.apifox_parser import ApiEndpoint, ApiField, ApifoxOpenApiParser
from ..profile import Profile
from .models import Finding, ValidationReport


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SUPPORTED_ASSERTION_TYPES = {"status_code", "json_field", "body_field", "response_field"}
# 负向场景不参与请求字段类型检查（这些场景本来就传非法值）。
TYPE_CHECK_EXEMPT_SCENARIOS = {
    "invalid_type",
    "boundary",
    "empty_value",
    "not_found",
    "auth_or_permission",
}


def validate_cases_file(
    cases_path: Path,
    openapi_path: Path | None = None,
    profile: Profile | None = None,
) -> ValidationReport:
    return CaseValidator(profile or Profile()).validate_file(cases_path, openapi_path)


class CaseValidator:
    def __init__(self, profile: Profile = Profile()) -> None:
        self.profile = profile

    def validate_file(self, cases_path: Path, openapi_path: Path | None = None) -> ValidationReport:
        try:
            raw_data = json.loads(cases_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            return ValidationReport(
                cases_count=0,
                findings=[
                    Finding(
                        severity="error",
                        code="INVALID_JSON",
                        message=f"cases 文件不是合法 JSON: {error}",
                        suggestion="请修复 JSON 语法后重新执行 validate-cases。",
                    )
                ],
            )

        endpoints, openapi_findings = self._load_openapi_endpoints(openapi_path)
        report = self.validate(raw_data, endpoints)
        return ValidationReport(
            cases_count=report.cases_count,
            findings=[*openapi_findings, *report.findings],
        )

    def validate(self, raw_data: Any, endpoints: list[ApiEndpoint] | None = None) -> ValidationReport:
        cases = self._extract_cases(raw_data)
        if cases is None:
            return ValidationReport(
                cases_count=0,
                findings=[
                    Finding(
                        severity="error",
                        code="INVALID_CASES_ROOT",
                        message='cases 文件根节点必须是数组，或包含 "cases" 数组字段的对象。',
                        suggestion='推荐格式: {"cases": [...]}',
                    )
                ],
            )

        findings: list[Finding] = []
        case_ids = []
        seen_signatures: dict[str, int] = {}

        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                findings.append(
                    Finding(
                        severity="error",
                        code="INVALID_CASE_ITEM",
                        index=index,
                        message="case 必须是 JSON 对象。",
                    )
                )
                continue

            case_id = self._case_id(case)
            if case_id:
                case_ids.append(case_id)

            findings.extend(self._validate_required_fields(case, index, case_id))
            findings.extend(self._validate_api(case, index, case_id))
            findings.extend(self._validate_assertions(case, index, case_id))
            findings.extend(self._validate_case_semantics(case, index, case_id))
            if endpoints is not None:
                findings.extend(self._validate_openapi_alignment(case, index, case_id, endpoints))

            signature = self._request_assertion_signature(case)
            if signature in seen_signatures:
                findings.append(
                    Finding(
                        severity="warning",
                        code="DUPLICATE_REQUEST_AND_ASSERTION",
                        index=index,
                        case_id=case_id,
                        message=f"该 case 与第 {seen_signatures[signature]} 个 case 的请求和断言完全一致。",
                        suggestion="请确认是否存在重复用例，或补充不同的输入/断言。",
                    )
                )
            else:
                seen_signatures[signature] = index

        findings.extend(self._validate_duplicate_case_ids(case_ids))
        return ValidationReport(cases_count=len(cases), findings=findings)

    def _load_openapi_endpoints(self, openapi_path: Path | None) -> tuple[list[ApiEndpoint] | None, list[Finding]]:
        if openapi_path is None:
            return None, []

        try:
            parser = ApifoxOpenApiParser()
            endpoints = parser.parse(openapi_path)
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as error:
            return None, [
                Finding(
                    severity="error",
                    code="INVALID_OPENAPI_DOCUMENT",
                    message=f"无法读取或解析 OpenAPI 文档: {error}",
                    suggestion="请确认 --openapi 指向有效的 Apifox/OpenAPI JSON 文件。",
                )
            ]

        # 解析器对不支持的结构（外部 $ref、oneOf 截断、超层嵌套等）不静默吞掉，转成 warning。
        limitation_findings = [
            Finding(
                severity="warning",
                code="OPENAPI_PARSE_LIMITATION",
                message=message,
                suggestion="请人工确认相关接口的用例是否覆盖完整。",
            )
            for message in parser.last_warnings
        ]

        if not endpoints:
            return endpoints, [
                *limitation_findings,
                Finding(
                    severity="warning",
                    code="EMPTY_OPENAPI_ENDPOINTS",
                    message="OpenAPI 文档中没有解析到可校验的接口。",
                    suggestion="请确认文档 paths 中包含 GET/POST/PUT/PATCH/DELETE 接口。",
                ),
            ]

        return endpoints, limitation_findings

    def _extract_cases(self, raw_data: Any) -> list[Any] | None:
        if isinstance(raw_data, list):
            return raw_data
        if isinstance(raw_data, dict) and isinstance(raw_data.get("cases"), list):
            return raw_data["cases"]
        return None

    def _validate_required_fields(self, case: dict[str, Any], index: int, case_id: str | None) -> list[Finding]:
        findings: list[Finding] = []
        for field in ("case_id", "name", "api", "request", "assertions"):
            if field not in case:
                findings.append(
                    Finding(
                        severity="error",
                        code="MISSING_REQUIRED_CASE_FIELD",
                        index=index,
                        case_id=case_id,
                        message=f"case 缺少必填字段: {field}",
                        suggestion="请补齐 case_id、name、api、request、assertions。",
                    )
                )

        if "case_id" in case and not str(case.get("case_id", "")).strip():
            findings.append(
                Finding(
                    severity="error",
                    code="EMPTY_CASE_ID",
                    index=index,
                    message="case_id 不能为空。",
                )
            )

        if "api" in case and not isinstance(case.get("api"), dict):
            findings.append(
                Finding(
                    severity="error",
                    code="INVALID_API_OBJECT",
                    index=index,
                    case_id=case_id,
                    message="api 必须是 JSON 对象。",
                )
            )

        if "request" in case and not isinstance(case.get("request"), dict):
            findings.append(
                Finding(
                    severity="error",
                    code="INVALID_REQUEST_OBJECT",
                    index=index,
                    case_id=case_id,
                    message="request 必须是 JSON 对象。",
                )
            )

        return findings

    def _validate_api(self, case: dict[str, Any], index: int, case_id: str | None) -> list[Finding]:
        api = case.get("api")
        if not isinstance(api, dict):
            return []

        findings: list[Finding] = []
        method = str(api.get("method", "")).upper()
        path = api.get("path")

        if not method:
            findings.append(
                Finding(
                    severity="error",
                    code="MISSING_API_METHOD",
                    index=index,
                    case_id=case_id,
                    message="api.method 不能为空。",
                )
            )
        elif method not in HTTP_METHODS:
            findings.append(
                Finding(
                    severity="error",
                    code="INVALID_HTTP_METHOD",
                    index=index,
                    case_id=case_id,
                    message=f"不支持的 HTTP method: {method}",
                    suggestion=f"method 只能是: {', '.join(sorted(HTTP_METHODS))}",
                )
            )

        if not isinstance(path, str) or not path.strip():
            findings.append(
                Finding(
                    severity="error",
                    code="MISSING_API_PATH",
                    index=index,
                    case_id=case_id,
                    message="api.path 不能为空。",
                )
            )
        elif not path.startswith("/"):
            findings.append(
                Finding(
                    severity="error",
                    code="INVALID_API_PATH",
                    index=index,
                    case_id=case_id,
                    message="api.path 必须以 / 开头。",
                )
            )

        request = case.get("request")
        if method == "GET" and isinstance(request, dict) and request.get("body") not in (None, {}, ""):
            findings.append(
                Finding(
                    severity="warning",
                    code="GET_REQUEST_HAS_BODY",
                    index=index,
                    case_id=case_id,
                    message="GET 用例包含 request.body，部分服务端或网关可能忽略该请求体。",
                    suggestion="请确认该参数是否应该放到 request.query。",
                )
            )

        return findings

    def _validate_assertions(self, case: dict[str, Any], index: int, case_id: str | None) -> list[Finding]:
        assertions = case.get("assertions")
        normalized_assertions = self._normalize_assertions(assertions)
        findings: list[Finding] = []

        if not normalized_assertions:
            findings.append(
                Finding(
                    severity="error",
                    code="EMPTY_ASSERTIONS",
                    index=index,
                    case_id=case_id,
                    message="assertions 不能为空。",
                )
            )
            return findings

        if len(normalized_assertions) == 1 and normalized_assertions[0].get("type") == "status_code":
            findings.append(
                Finding(
                    severity="warning",
                    code="ONLY_STATUS_CODE_ASSERTION",
                    index=index,
                    case_id=case_id,
                    message="该用例只断言了 HTTP 状态码，可能无法发现业务失败。",
                    suggestion="建议增加 code、success、data 或 message 等响应字段断言。",
                )
            )

        for assertion in normalized_assertions:
            assertion_type = assertion.get("type")
            if assertion_type not in SUPPORTED_ASSERTION_TYPES:
                findings.append(
                    Finding(
                        severity="error",
                        code="INVALID_ASSERTION_TYPE",
                        index=index,
                        case_id=case_id,
                        message=f"不支持的断言类型: {assertion_type}",
                        suggestion=f"当前支持: {', '.join(sorted(SUPPORTED_ASSERTION_TYPES))}",
                    )
                )
                continue

            if assertion_type in {"json_field", "body_field", "response_field"}:
                path = assertion.get("path") or assertion.get("field") or assertion.get("json_path")
                if not path:
                    findings.append(
                        Finding(
                            severity="error",
                            code="JSON_FIELD_ASSERTION_MISSING_PATH",
                            index=index,
                            case_id=case_id,
                            message="json_field/body_field/response_field 断言缺少 path。",
                        )
                    )

                operator = assertion.get("operator", "eq")
                if operator == "contains" and assertion.get("expected") in ("", None):
                    findings.append(
                        Finding(
                            severity="warning",
                            code="ASSERTION_EXPECTED_EMPTY_CONTAINS",
                            index=index,
                            case_id=case_id,
                            message="contains 断言的 expected 为空，容易产生无意义通过。",
                        )
                    )

                if operator == "exists" and "expected" in assertion:
                    findings.append(
                        Finding(
                            severity="info",
                            code="ASSERTION_EXISTS_HAS_EXPECTED",
                            index=index,
                            case_id=case_id,
                            message="exists 断言会忽略 expected 字段。",
                            suggestion="可以删除 expected，让断言意图更清晰。",
                        )
                    )

        return findings

    def _validate_case_semantics(self, case: dict[str, Any], index: int, case_id: str | None) -> list[Finding]:
        # 只对场景为 success 的用例检查失败语义，避免接口名带“成功”连累负向用例。
        if self._case_scenario(case) != "success":
            return []

        findings: list[Finding] = []
        failure_values = self._failure_field_values()
        for assertion in normalize_assertions(case.get("assertions")):
            assertion_type = assertion.get("type")
            if assertion_type not in {"json_field", "body_field", "response_field"}:
                continue

            path = str(assertion.get("path") or assertion.get("field") or assertion.get("json_path") or "")
            short_path = path.split(".")[-1]
            expected = assertion.get("expected")
            if not isinstance(expected, (str, int, float, bool)):
                continue
            if expected in failure_values.get(short_path, set()):
                findings.append(
                    Finding(
                        severity="warning",
                        code="SUCCESS_CASE_ASSERTS_FAILURE_SEMANTICS",
                        index=index,
                        case_id=case_id,
                        message=f"正向用例断言了疑似失败语义: {path}={expected!r}",
                        suggestion="请确认该用例是否应准备有效测试数据，并断言业务成功结果。",
                    )
                )

        return findings

    def _validate_openapi_alignment(
        self,
        case: dict[str, Any],
        index: int,
        case_id: str | None,
        endpoints: list[ApiEndpoint],
    ) -> list[Finding]:
        api = case.get("api")
        if not isinstance(api, dict):
            return []

        method = str(api.get("method", "")).upper()
        path = api.get("path")
        if not method or not isinstance(path, str):
            return []

        endpoint = self._find_endpoint(endpoints, method, path)
        if endpoint is None:
            return [
                Finding(
                    severity="warning",
                    code="UNKNOWN_OPENAPI_ENDPOINT",
                    index=index,
                    case_id=case_id,
                    message=f"OpenAPI 文档中找不到接口: {method} {path}",
                    suggestion="请确认 case 的 api.method/api.path 是否和接口文档完全一致。",
                )
            ]

        request = case.get("request") if isinstance(case.get("request"), dict) else {}
        scenario = self._case_scenario(case)
        findings: list[Finding] = []
        sections = (
            ("path", endpoint.path_fields),
            ("query", endpoint.query_fields),
            ("body", endpoint.request_fields),
        )

        # 各 section 展开成点号键后再比对，与解析器的嵌套展开规则对齐。
        flattened_sections: dict[str, dict[str, Any]] = {}
        for section_name, expected_fields in sections:
            actual = self._request_section(request, api, section_name)
            actual_dict = actual if isinstance(actual, dict) else {}
            opaque_fields = {field.name for field in expected_fields if field.type == "object"}
            flattened_sections[section_name] = self._flatten_request_fields(actual_dict, opaque_fields)

        required_field_count = 0
        missing_required_count = 0
        for section_name, expected_fields in sections:
            flattened = flattened_sections[section_name]
            required_fields = [field for field in expected_fields if field.required]
            required_field_count += len(required_fields)
            missing_required_count += sum(1 for field in required_fields if field.name not in flattened)

        if scenario == "missing_required" and required_field_count > 0 and missing_required_count == 0:
            findings.append(
                Finding(
                    severity="warning",
                    code="MISSING_REQUIRED_CASE_DID_NOT_REMOVE_REQUIRED_FIELD",
                    index=index,
                    case_id=case_id,
                    message="missing_required 用例没有移除任何 OpenAPI 必填字段。",
                    suggestion="请至少移除一个 OpenAPI 标记 required=true 的字段。",
                )
            )

        for section_name, expected_fields in sections:
            findings.extend(
                self._validate_openapi_fields(
                    index=index,
                    case_id=case_id,
                    section_name=section_name,
                    actual_fields=flattened_sections[section_name],
                    expected_fields=expected_fields,
                    scenario=scenario,
                )
            )

        return findings

    @staticmethod
    def _flatten_request_fields(actual: dict[str, Any], opaque_fields: set[str]) -> dict[str, Any]:
        # 嵌套 dict 展开为点号键；opaque 前缀（按整体 object 处理的字段）和空 dict 保持叶节点。
        flattened: dict[str, Any] = {}

        def walk(node: dict[str, Any], prefix: str) -> None:
            for key, value in node.items():
                full_name = f"{prefix}.{key}" if prefix else key
                if full_name in opaque_fields or not isinstance(value, dict) or not value:
                    flattened[full_name] = value
                else:
                    walk(value, full_name)

        walk(actual, "")
        return flattened

    def _validate_openapi_fields(
        self,
        index: int,
        case_id: str | None,
        section_name: str,
        actual_fields: Any,
        expected_fields: list[ApiField],
        scenario: str,
    ) -> list[Finding]:
        findings: list[Finding] = []
        actual = actual_fields if isinstance(actual_fields, dict) else {}
        expected_by_name = {field.name: field for field in expected_fields}
        required_fields = [field for field in expected_fields if field.required]
        missing_required = [field.name for field in required_fields if field.name not in actual]

        if missing_required and scenario != "missing_required":
            findings.append(
                Finding(
                    severity="warning",
                    code="REQUIRED_FIELD_MISSING",
                    index=index,
                    case_id=case_id,
                    message=f"request.{section_name} 缺少 OpenAPI 必填字段: {', '.join(missing_required)}",
                    suggestion="如果这是正向用例，请补齐必填字段；如果是缺参用例，请在 case_id/name 中标记 missing_required。",
                )
            )

        for field_name, value in actual.items():
            expected_field = expected_by_name.get(field_name)
            if expected_field is None:
                if scenario != "invalid_extra":
                    findings.append(
                        Finding(
                            severity="warning",
                            code="UNDECLARED_REQUEST_FIELD",
                            index=index,
                            case_id=case_id,
                            message=f"request.{section_name}.{field_name} 未在 OpenAPI 文档中声明。",
                            suggestion="请确认字段名是否拼写错误，或将该用例标记为 invalid_extra_query/invalid_extra_body。",
                        )
                    )
                continue

            if scenario in TYPE_CHECK_EXEMPT_SCENARIOS:
                continue

            if not self._value_matches_type(value, expected_field.type, section_name):
                findings.append(
                    Finding(
                        severity="warning",
                        code="REQUEST_FIELD_TYPE_MISMATCH",
                        index=index,
                        case_id=case_id,
                        message=(
                            f"request.{section_name}.{field_name} 的值 {value!r} "
                            f"与 OpenAPI 类型 {expected_field.type} 不匹配。"
                        ),
                        suggestion="请修正测试数据类型；如果这是类型异常用例，请在 case_id/name 中标记 invalid_type。",
                    )
                )

        return findings

    def _find_endpoint(self, endpoints: list[ApiEndpoint], method: str, path: str) -> ApiEndpoint | None:
        for endpoint in endpoints:
            if endpoint.method.upper() == method and endpoint.path == path:
                return endpoint
        return None

    def _request_section(self, request: dict[str, Any], api: dict[str, Any], section_name: str) -> Any:
        if section_name in request:
            return request.get(section_name)
        if section_name == "path" and "path_params" in api:
            return api.get("path_params")
        return api.get(section_name)

    def _case_scenario(self, case: dict[str, Any]) -> str:
        # 优先读显式 scenario 字段；手改或 AI 漏写时退回关键词猜测。
        scenario = case.get("scenario")
        if isinstance(scenario, str) and scenario.strip():
            return scenario.strip().lower()

        case_text = f"{case.get('case_id', '')} {case.get('name', '')}".lower()
        keyword_scenarios = (
            ("missing_required", ("missing_required", "缺少必填", "缺参")),
            ("invalid_extra", ("invalid_extra", "额外参数", "多余参数")),
            ("invalid_type", ("invalid_type", "类型错误")),
            ("boundary", ("boundary", "边界")),
            ("empty_value", ("empty_value", "空值")),
            ("not_found", ("not_found", "不存在")),
            ("auth_or_permission", ("auth_or_permission", "鉴权", "未登录", "无权限")),
        )
        for canonical, keywords in keyword_scenarios:
            if any(keyword in case_text for keyword in keywords):
                return canonical
        if any(token in case_text for token in ("success", "正向", "成功")):
            return "success"
        return "other"

    def _failure_field_values(self) -> dict[str, set]:
        # 失败语义表来自 profile：换公司只需改 profiles/<公司>/profile.json。
        envelope = self.profile.response_envelope
        table: dict[str, set] = {}
        if envelope.success_field:
            table[envelope.success_field] = set(envelope.failure_values)
        if envelope.code_field:
            table[envelope.code_field] = set(envelope.code_failure_values)
        return table

    def _value_matches_type(self, value: Any, expected_type: str, section_name: str) -> bool:
        expected_type = (expected_type or "string").lower()
        if value is None:
            return True
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            if isinstance(value, bool):
                return False
            if isinstance(value, int):
                return True
            return section_name in {"query", "path"} and isinstance(value, str) and value.isdigit()
        if expected_type == "number":
            if isinstance(value, bool):
                return False
            if isinstance(value, (int, float)):
                return True
            if section_name in {"query", "path"} and isinstance(value, str):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False
            return False
        if expected_type == "boolean":
            if isinstance(value, bool):
                return True
            return section_name in {"query", "path"} and str(value).lower() in {"true", "false"}
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return True

    def _validate_duplicate_case_ids(self, case_ids: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        counts = Counter(case_ids)
        for case_id, count in sorted(counts.items()):
            if count > 1:
                findings.append(
                    Finding(
                        severity="error",
                        code="DUPLICATE_CASE_ID",
                        case_id=case_id,
                        message=f"case_id 重复出现 {count} 次。",
                        suggestion="请为每个 case 使用唯一 case_id。",
                    )
                )
        return findings

    def _normalize_assertions(self, assertions: Any) -> list[dict[str, Any]]:
        # 归一化逻辑统一放在 generator.assertions，避免多份实现漂移。
        return normalize_assertions(assertions)

    def _request_assertion_signature(self, case: dict[str, Any]) -> str:
        payload = {
            "api": case.get("api"),
            "request": case.get("request"),
            "assertions": case.get("assertions"),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    def _case_id(self, case: dict[str, Any]) -> str | None:
        case_id = case.get("case_id")
        if case_id is None:
            return None
        return str(case_id)

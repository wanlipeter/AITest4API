from typing import Any

from ..knowledge.apifox_parser import ApiEndpoint, ApiField
from ..profile import Profile


class MinimalAiCaseGenerator:
    """最小可用的本地“AI 用例生成器”。

    当前实现不调用外部大模型，而是用确定性规则模拟 AI 生成结果。
    成功/失败断言模板来自 profile 的响应包络约定，换公司不用改这里的代码。
    """

    def __init__(self, profile: Profile = Profile()) -> None:
        self.envelope = profile.response_envelope

    def generate(self, endpoints: list[ApiEndpoint]) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        for endpoint in endpoints:
            cases.extend(self._generate_endpoint_cases(endpoint))
        return cases

    def _generate_endpoint_cases(self, endpoint: ApiEndpoint) -> list[dict[str, Any]]:
        cases = [self._generate_success_case(endpoint)]

        required_field = self._first_required_field(endpoint)
        if required_field is None:
            cases.append(self._generate_invalid_extra_case(endpoint))
        else:
            cases.append(self._generate_missing_required_case(endpoint, required_field))

        first_field = self._first_field(endpoint)
        if first_field is None:
            cases.append(self._generate_invalid_extra_body_case(endpoint))
            cases.append(self._generate_auth_or_header_case(endpoint))
        else:
            cases.append(self._generate_empty_value_case(endpoint, first_field))
            cases.append(self._generate_invalid_type_case(endpoint, first_field))

        cases.append(self._generate_not_found_case(endpoint))
        return cases

    def _generate_success_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        case_id = self._case_id(endpoint)
        request: dict[str, Any] = {}
        request.update(self._success_request(endpoint))

        assertions: list[dict[str, Any]] = [
            {
                "type": "status_code",
                "expected": endpoint.success_status,
            }
        ]
        success_assertion = self.envelope.success_assertion()
        if success_assertion is not None:
            assertions.append(success_assertion)

        return {
            "case_id": case_id,
            "case_type": "interface",
            "scenario": "success",
            "name": f"{endpoint.name} - 正向用例",
            "api": {
                "method": endpoint.method,
                "path": endpoint.path,
            },
            "request": request,
            "assertions": assertions,
        }

    def _generate_missing_required_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        if section in request:
            self._pop_path_value(request[section], field.name)

        assertions = self._failure_assertions()
        message_assertion = self.envelope.message_assertion(contains=field.name)
        if message_assertion is not None:
            assertions.append(message_assertion)

        return self._case(
            endpoint,
            scenario="missing_required",
            suffix="missing_required",
            name=f"{endpoint.name} - 缺少必填参数 {field.name}",
            request=request,
            assertions=assertions,
        )

    def _generate_empty_value_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        self._set_path_value(request.setdefault(section, {}), field.name, self._empty_value(field))
        return self._failure_case(
            endpoint,
            scenario="empty_value",
            suffix="empty_value",
            name=f"{endpoint.name} - 空值参数 {field.name}",
            request=request,
        )

    def _generate_invalid_type_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        self._set_path_value(request.setdefault(section, {}), field.name, self._invalid_value(field))
        return self._failure_case(
            endpoint,
            scenario="invalid_type",
            suffix="invalid_type",
            name=f"{endpoint.name} - 参数类型错误 {field.name}",
            request=request,
        )

    def _generate_invalid_extra_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        target_section = "query" if endpoint.method == "GET" else "body"
        request.setdefault(target_section, {})["unexpectedField"] = "unexpected"
        return self._failure_case(
            endpoint,
            scenario="invalid_extra",
            suffix="invalid_extra",
            name=f"{endpoint.name} - 额外参数",
            request=request,
        )

    def _generate_invalid_extra_body_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        request.setdefault("body", {})["unexpectedField"] = "unexpected"
        return self._failure_case(
            endpoint,
            scenario="invalid_extra",
            suffix="invalid_extra_body",
            name=f"{endpoint.name} - 额外 body 字段",
            request=request,
        )

    def _generate_not_found_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        target = self._first_id_like_field(endpoint) or self._first_field(endpoint)
        if target is not None:
            section, field = target
            leaf = self._leaf_name(field.name)
            self._set_path_value(
                request.setdefault(section, {}), field.name, f"not_exist_{leaf}_999999"
            )

        return self._case(
            endpoint,
            scenario="not_found",
            suffix="not_found_or_not_exist",
            name=f"{endpoint.name} - 数据不存在",
            request=request,
            assertions=self._failure_assertions(),
        )

    def _generate_auth_or_header_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        request["headers"] = {"Token": ""}
        return self._failure_case(
            endpoint,
            scenario="auth_or_permission",
            suffix="auth_or_permission",
            name=f"{endpoint.name} - 缺少鉴权",
            request=request,
        )

    def _failure_assertions(self) -> list[dict[str, Any]]:
        # 失败用例：业务错误 HTTP 状态码 + 失败语义断言 + message 存在断言，全部来自 profile。
        assertions: list[dict[str, Any]] = [
            {"type": "status_code", "expected": self.envelope.business_error_http_status}
        ]
        failure_assertion = self.envelope.failure_assertion()
        if failure_assertion is not None:
            assertions.append(failure_assertion)
        message_assertion = self.envelope.message_assertion()
        if message_assertion is not None:
            assertions.append(message_assertion)
        return assertions

    def _failure_case(
        self,
        endpoint: ApiEndpoint,
        scenario: str,
        suffix: str,
        name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self._case(
            endpoint,
            scenario=scenario,
            suffix=suffix,
            name=name,
            request=request,
            assertions=self._failure_assertions(),
        )

    def _case(
        self,
        endpoint: ApiEndpoint,
        scenario: str,
        suffix: str,
        name: str,
        request: dict[str, Any],
        assertions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "case_id": f"{self._case_id_prefix(endpoint)}_{suffix}",
            "case_type": "interface",
            "scenario": scenario,
            "name": name,
            "api": {
                "method": endpoint.method,
                "path": endpoint.path,
            },
            "request": request,
            "assertions": assertions,
        }

    def _case_id(self, endpoint: ApiEndpoint) -> str:
        return f"{self._case_id_prefix(endpoint)}_success"

    def _case_id_prefix(self, endpoint: ApiEndpoint) -> str:
        normalized_path = endpoint.path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        return f"{endpoint.method.lower()}_{normalized_path or 'root'}"

    def _sample_value(self, field: ApiField) -> Any:
        if field.enum_values:
            return field.enum_values[0]
        if field.type == "integer":
            return 1
        if field.type == "number":
            return 1.0
        if field.type == "boolean":
            return True
        if field.type == "object":
            # 超层截断的整体 object 字段，给空对象而不是字符串，避免类型不匹配。
            return {}
        if field.type == "array":
            if field.item_type == "integer":
                return [1]
            if field.item_type == "number":
                return [1.0]
            if field.item_type == "boolean":
                return [True]
            if field.item_type in (None, "object"):
                return []
            return [f"demo_{self._leaf_name(field.name)}"]
        return f"demo_{self._leaf_name(field.name)}"

    @staticmethod
    def _leaf_name(field_name: str) -> str:
        # 嵌套字段用叶子名生成可读样例值，例如 address.city -> demo_city。
        return field_name.split(".")[-1]

    @staticmethod
    def _set_path_value(container: dict[str, Any], dotted_name: str, value: Any) -> None:
        # 点号路径写入嵌套 dict，例如 address.city -> {"address": {"city": ...}}。
        parts = dotted_name.split(".")
        node = container
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                return
            node = child
        node[parts[-1]] = value

    @staticmethod
    def _pop_path_value(container: dict[str, Any], dotted_name: str) -> None:
        parts = dotted_name.split(".")
        node = container
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                return
            node = node[part]
        if isinstance(node, dict):
            node.pop(parts[-1], None)

    def _success_request(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request: dict[str, Any] = {}
        if endpoint.path_fields:
            request["path"] = {
                field.name: self._sample_value(field) for field in endpoint.path_fields
            }
        if endpoint.query_fields:
            request["query"] = {
                field.name: self._sample_value(field) for field in endpoint.query_fields
            }
        if endpoint.request_fields:
            body: dict[str, Any] = {}
            for field in endpoint.request_fields:
                self._set_path_value(body, field.name, self._sample_value(field))
            request["body"] = body
        return request

    def _first_required_field(self, endpoint: ApiEndpoint) -> tuple[str, ApiField] | None:
        for section, field in self._all_fields(endpoint):
            if field.required:
                return section, field
        return None

    def _first_field(self, endpoint: ApiEndpoint) -> tuple[str, ApiField] | None:
        fields = self._all_fields(endpoint)
        return fields[0] if fields else None

    def _first_id_like_field(self, endpoint: ApiEndpoint) -> tuple[str, ApiField] | None:
        for section, field in self._all_fields(endpoint):
            if self._leaf_name(field.name).lower().endswith("id"):
                return section, field
        return None

    def _all_fields(self, endpoint: ApiEndpoint) -> list[tuple[str, ApiField]]:
        return [
            *[("path", field) for field in endpoint.path_fields],
            *[("query", field) for field in endpoint.query_fields],
            *[("body", field) for field in endpoint.request_fields],
        ]

    def _empty_value(self, field: ApiField) -> Any:
        if field.type == "array":
            return []
        if field.type == "object":
            return {}
        return ""

    def _invalid_value(self, field: ApiField) -> Any:
        if field.type in {"integer", "number"}:
            return "not_a_number"
        if field.type == "boolean":
            return "not_a_boolean"
        if field.type == "array":
            return "not_an_array"
        if field.type == "object":
            return "not_an_object"
        return 999999

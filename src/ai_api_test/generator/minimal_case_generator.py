from typing import Any

from ..knowledge.apifox_parser import ApiEndpoint, ApiField


class MinimalAiCaseGenerator:
    """最小可用的本地“AI 用例生成器”。

    当前实现不调用外部大模型，而是用确定性规则模拟 AI 生成结果：
    每个接口先生成一个正向用例。后续可以把这个类替换为真实 LLM Provider。
    """

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

        if endpoint.path_fields:
            request["path"] = {
                field.name: self._sample_value(field) for field in endpoint.path_fields
            }

        if endpoint.query_fields:
            request["query"] = {
                field.name: self._sample_value(field) for field in endpoint.query_fields
            }

        if endpoint.request_fields:
            request["body"] = {
                field.name: self._sample_value(field) for field in endpoint.request_fields
            }

        return {
            "case_id": case_id,
            "case_type": "interface",
            "name": f"{endpoint.name} - 正向用例",
            "api": {
                "method": endpoint.method,
                "path": endpoint.path,
            },
            "request": request,
            "assertions": [
                {
                    "type": "status_code",
                    "expected": endpoint.success_status,
                },
                {
                    "type": "json_field",
                    "path": "success",
                    "operator": "eq",
                    "expected": True,
                }
            ],
        }

    def _generate_missing_required_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        if section in request:
            request[section].pop(field.name, None)

        return self._case(
            endpoint,
            suffix="missing_required",
            name=f"{endpoint.name} - 缺少必填参数 {field.name}",
            request=request,
            assertions=[
                {"type": "status_code", "expected": endpoint.success_status},
                {"type": "json_field", "path": "success", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "message", "operator": "contains", "expected": field.name},
            ],
        )

    def _generate_empty_value_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        request.setdefault(section, {})[field.name] = self._empty_value(field)
        return self._failure_case(endpoint, "empty_value", f"{endpoint.name} - 空值参数 {field.name}", request)

    def _generate_invalid_type_case(self, endpoint: ApiEndpoint, target: tuple[str, ApiField]) -> dict[str, Any]:
        section, field = target
        request = self._success_request(endpoint)
        request.setdefault(section, {})[field.name] = self._invalid_value(field)
        return self._failure_case(endpoint, "invalid_type", f"{endpoint.name} - 参数类型错误 {field.name}", request)

    def _generate_invalid_extra_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        target_section = "query" if endpoint.method == "GET" else "body"
        request.setdefault(target_section, {})["unexpectedField"] = "unexpected"
        return self._failure_case(endpoint, "invalid_extra", f"{endpoint.name} - 额外参数", request)

    def _generate_invalid_extra_body_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        request.setdefault("body", {})["unexpectedField"] = "unexpected"
        return self._failure_case(endpoint, "invalid_extra_body", f"{endpoint.name} - 额外 body 字段", request)

    def _generate_not_found_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        target = self._first_id_like_field(endpoint) or self._first_field(endpoint)
        if target is not None:
            section, field = target
            request.setdefault(section, {})[field.name] = f"not_exist_{field.name}_999999"

        return self._case(
            endpoint,
            suffix="not_found_or_not_exist",
            name=f"{endpoint.name} - 数据不存在",
            request=request,
            assertions=[
                {"type": "status_code", "expected": endpoint.success_status},
                {"type": "json_field", "path": "success", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "message", "operator": "exists"},
            ],
        )

    def _generate_auth_or_header_case(self, endpoint: ApiEndpoint) -> dict[str, Any]:
        request = self._success_request(endpoint)
        request["headers"] = {"Token": ""}
        return self._failure_case(endpoint, "auth_or_permission", f"{endpoint.name} - 缺少鉴权", request)

    def _failure_case(
        self,
        endpoint: ApiEndpoint,
        suffix: str,
        name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self._case(
            endpoint,
            suffix=suffix,
            name=name,
            request=request,
            assertions=[
                {"type": "status_code", "expected": endpoint.success_status},
                {"type": "json_field", "path": "success", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "message", "operator": "exists"},
            ],
        )

    def _case(
        self,
        endpoint: ApiEndpoint,
        suffix: str,
        name: str,
        request: dict[str, Any],
        assertions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "case_id": f"{self._case_id_prefix(endpoint)}_{suffix}",
            "case_type": "interface",
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
        if field.type == "integer":
            return 1
        if field.type == "number":
            return 1.0
        if field.type == "boolean":
            return True
        if field.name.lower().endswith("id"):
            return f"demo_{field.name}"
        return f"demo_{field.name}"

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
            request["body"] = {
                field.name: self._sample_value(field) for field in endpoint.request_fields
            }
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
            if field.name.lower().endswith("id"):
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

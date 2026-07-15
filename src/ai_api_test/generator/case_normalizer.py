from typing import Any


class CaseNormalizer:
    """把模型输出归一化为框架内部固定用例格式。"""

    def normalize_many(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.normalize(case) for case in cases]

    def normalize(self, case: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(case)
        normalized["case_id"] = str(normalized.get("case_id", "generated_case"))
        normalized["case_type"] = "interface"

        api = dict(normalized.get("api") or {})
        request = dict(normalized.get("request") or {})

        if "query" in api and "query" not in request:
            request["query"] = api.pop("query")
        if "path_params" in api and "path" not in request:
            request["path"] = api.pop("path_params")
        if "body" in api and "body" not in request:
            request["body"] = api.pop("body")

        normalized["api"] = api
        normalized["request"] = request
        normalized["assertions"] = self._normalize_assertions(normalized.get("assertions"))
        return normalized

    def _normalize_assertions(self, assertions: Any) -> list[dict[str, Any]]:
        if isinstance(assertions, list):
            return [self._normalize_single_assertion(item) for item in assertions]

        if isinstance(assertions, dict):
            return [
                self._normalize_single_assertion({assertion_type: expected})
                for assertion_type, expected in assertions.items()
            ]

        if isinstance(assertions, str):
            return [{"type": assertions, "expected": 200}]

        return [{"type": "status_code", "expected": 200}]

    def _normalize_single_assertion(self, assertion: Any) -> dict[str, Any]:
        if isinstance(assertion, dict):
            if "type" in assertion:
                return assertion
            if len(assertion) == 1:
                assertion_type, expected = next(iter(assertion.items()))
                return self._normalize_short_assertion(assertion_type, expected)

        if isinstance(assertion, str):
            return {"type": assertion, "expected": 200}

        return {"type": "status_code", "expected": 200}

    def _normalize_short_assertion(self, assertion_type: str, expected: Any) -> dict[str, Any]:
        if assertion_type in {"status_code", "http_code"}:
            return {"type": "status_code", "expected": expected}

        if assertion_type in {"json_field", "body_field", "response_field"}:
            if isinstance(expected, dict):
                return {"type": "json_field", **expected}
            return {"type": "json_field", "path": assertion_type, "expected": expected}

        # 兼容 {"success": false}、{"code": "101"} 这类响应字段断言简写。
        return {"type": "json_field", "path": assertion_type, "expected": expected}

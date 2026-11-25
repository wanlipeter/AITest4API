from typing import Any

from .assertions import normalize_assertions


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
        # 归一化逻辑统一放在 generator.assertions，这里只补齐默认值。
        normalized = normalize_assertions(assertions)
        if not normalized:
            return [{"type": "status_code", "expected": 200}]
        return normalized

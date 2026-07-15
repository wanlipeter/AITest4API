import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


@dataclass(frozen=True)
class ApiField:
    name: str
    type: str = "string"
    required: bool = False


@dataclass(frozen=True)
class ApiEndpoint:
    method: str
    path: str
    name: str
    request_fields: list[ApiField] = field(default_factory=list)
    query_fields: list[ApiField] = field(default_factory=list)
    path_fields: list[ApiField] = field(default_factory=list)
    success_status: int = 200


class ApifoxOpenApiParser:
    """解析 Apifox 导出的 OpenAPI JSON。

    Apifox 可以导出 OpenAPI/Swagger 文档。最小链路先支持 JSON 格式，
    后续如果要支持 Apifox 私有格式，可以在这里继续扩展适配。
    """

    def parse(self, document_path: str | Path) -> list[ApiEndpoint]:
        document = json.loads(Path(document_path).read_text(encoding="utf-8"))
        endpoints: list[ApiEndpoint] = []

        for path, path_item in document.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue

            for method, operation in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                    continue

                endpoints.append(
                    ApiEndpoint(
                        method=method.upper(),
                        path=path,
                        name=self._operation_name(method, path, operation),
                        request_fields=self._request_fields(operation),
                        query_fields=self._parameter_fields(operation, "query"),
                        path_fields=self._parameter_fields(operation, "path"),
                        success_status=self._success_status(operation),
                    )
                )

        return endpoints

    def _operation_name(self, method: str, path: str, operation: dict[str, Any]) -> str:
        return operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}"

    def _request_fields(self, operation: dict[str, Any]) -> list[ApiField]:
        content = operation.get("requestBody", {}).get("content", {})
        json_schema = content.get("application/json", {}).get("schema", {})
        schema = self._resolve_inline_schema(json_schema)
        required = set(schema.get("required", []))
        properties = schema.get("properties", {})

        return [
            ApiField(name=name, type=field_schema.get("type", "string"), required=name in required)
            for name, field_schema in properties.items()
        ]

    def _parameter_fields(self, operation: dict[str, Any], location: str) -> list[ApiField]:
        fields: list[ApiField] = []
        for parameter in operation.get("parameters", []):
            if parameter.get("in") != location:
                continue
            schema = parameter.get("schema", {})
            fields.append(
                ApiField(
                    name=parameter["name"],
                    type=schema.get("type", "string"),
                    required=parameter.get("required", False),
                )
            )
        return fields

    def _success_status(self, operation: dict[str, Any]) -> int:
        responses = operation.get("responses", {})
        for status in responses:
            if str(status).startswith("2"):
                return int(status)
        return 200

    def _resolve_inline_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type") == "object":
            return schema
        return {}

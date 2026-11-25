import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
MAX_NESTED_DEPTH = 2


@dataclass(frozen=True)
class ApiField:
    name: str
    type: str = "string"
    required: bool = False
    enum_values: list[Any] | None = None
    item_type: str | None = None


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

    支持本地 $ref（#/components/schemas/...）链式解析、allOf 合并、
    oneOf/anyOf 按第一分支解析、嵌套 object 展开（默认 2 层）和 enum 提取。
    暂不支持的结构不会静默吞掉，会记录到 last_warnings，
    由 workflow 打印或校验器转成 warning finding。
    """

    def __init__(self) -> None:
        self.last_warnings: list[str] = []
        self._components: dict[str, Any] = {}

    def parse(self, document_path: str | Path) -> list[ApiEndpoint]:
        self.last_warnings = []
        document = json.loads(Path(document_path).read_text(encoding="utf-8"))
        self._components = document.get("components", {}).get("schemas", {}) or {}

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
                        request_fields=self._request_fields(operation, path),
                        query_fields=self._parameter_fields(operation, "query"),
                        path_fields=self._parameter_fields(operation, "path"),
                        success_status=self._success_status(operation),
                    )
                )

        return endpoints

    def _operation_name(self, method: str, path: str, operation: dict[str, Any]) -> str:
        return operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}"

    # ---- schema 解析 ----

    def _resolve_schema(self, schema: Any, seen: set[str] | None = None) -> dict[str, Any]:
        # 跟随本地 $ref 链；外部 ref、无法解析的目标、循环引用返回空并记录 warning。
        if not isinstance(schema, dict):
            return {}

        if "$ref" not in schema:
            return schema

        seen = seen or set()
        ref = schema["$ref"]
        if not ref.startswith("#/components/schemas/"):
            self._warn(f"暂不支持外部或非 schemas 的 $ref: {ref}，相关字段已跳过。")
            return {}

        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            self._warn(f"检测到循环引用: {ref}，已在解析时截断。")
            return {}

        target = self._components.get(name)
        if not isinstance(target, dict):
            self._warn(f"$ref 目标不存在: {ref}。")
            return {}

        return self._resolve_schema(target, seen | {name})

    def _merge_composite(self, schema: dict[str, Any]) -> dict[str, Any]:
        # allOf 合并所有子 schema 的 properties/required；oneOf/anyOf 取第一分支。
        if "allOf" in schema and isinstance(schema["allOf"], list):
            merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            for sub_schema in schema["allOf"]:
                resolved = self._resolve_schema(sub_schema)
                if not isinstance(resolved, dict):
                    continue
                merged["properties"].update(resolved.get("properties", {}) or {})
                merged["required"].extend(resolved.get("required", []) or [])
            return merged

        for composite_key in ("oneOf", "anyOf"):
            branches = schema.get(composite_key)
            if isinstance(branches, list) and branches:
                self._warn(
                    f"schema 使用 {composite_key}，已按第一分支解析，其余分支忽略。"
                )
                return self._resolve_schema(branches[0])
        return schema

    def _request_fields(self, operation: dict[str, Any], path: str) -> list[ApiField]:
        content = operation.get("requestBody", {}).get("content", {})
        json_schema = content.get("application/json", {}).get("schema", {})
        schema = self._merge_composite(self._resolve_schema(json_schema))
        if not schema:
            return []

        if schema.get("type") not in (None, "object"):
            self._warn(
                f"{path} 请求体根 schema 类型为 {schema.get('type')}，当前只展开 object 结构。"
            )
            return []

        return self._flatten_properties(schema, "", 0)

    def _flatten_properties(
        self,
        schema: dict[str, Any],
        prefix: str,
        depth: int,
    ) -> list[ApiField]:
        if not isinstance(schema, dict):
            return []

        fields: list[ApiField] = []
        required = set(schema.get("required", []) or [])
        for name, raw_property in (schema.get("properties", {}) or {}).items():
            prop = self._merge_composite(self._resolve_schema(raw_property))
            full_name = f"{prefix}.{name}" if prefix else name
            is_required = name in required

            if isinstance(prop.get("enum"), list) and prop.get("enum"):
                fields.append(
                    ApiField(
                        name=full_name,
                        type=prop.get("type", "string"),
                        required=is_required,
                        enum_values=list(prop["enum"]),
                    )
                )
                continue

            property_type = prop.get("type", "string")
            if property_type == "object":
                if depth >= MAX_NESTED_DEPTH:
                    self._warn(
                        f"字段 {full_name} 嵌套超过 {MAX_NESTED_DEPTH} 层，按整体 object 处理。"
                    )
                    fields.append(ApiField(name=full_name, type="object", required=is_required))
                    continue

                nested_fields = self._flatten_properties(prop, full_name, depth + 1)
                if nested_fields:
                    fields.extend(nested_fields)
                else:
                    fields.append(ApiField(name=full_name, type="object", required=is_required))
                continue

            item_type = None
            if property_type == "array":
                items = self._merge_composite(self._resolve_schema(prop.get("items", {}) or {}))
                item_type = items.get("type", "string")
            fields.append(
                ApiField(name=full_name, type=property_type, required=is_required, item_type=item_type)
            )

        return fields

    def _parameter_fields(self, operation: dict[str, Any], location: str) -> list[ApiField]:
        fields: list[ApiField] = []
        for parameter in operation.get("parameters", []) or []:
            if parameter.get("in") != location:
                continue
            schema = self._merge_composite(self._resolve_schema(parameter.get("schema", {}) or {}))
            enum_values = schema.get("enum") if isinstance(schema.get("enum"), list) else None
            fields.append(
                ApiField(
                    name=parameter["name"],
                    type=schema.get("type", "string"),
                    required=parameter.get("required", False),
                    enum_values=enum_values,
                )
            )
        return fields

    def _success_status(self, operation: dict[str, Any]) -> int:
        responses = operation.get("responses", {})
        for status in responses:
            if str(status).startswith("2"):
                return int(status)
        return 200

    def _warn(self, message: str) -> None:
        self.last_warnings.append(message)

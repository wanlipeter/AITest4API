from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResponseEnvelope:
    """响应包络约定：不同公司后端的成功/失败语义差异都收敛在这里。"""

    success_field: str | None = "success"
    success_values: list[Any] = field(default_factory=lambda: [True])
    failure_values: list[Any] = field(default_factory=lambda: [False])
    code_field: str | None = "code"
    code_success_values: list[Any] = field(default_factory=lambda: ["200", 200])
    code_failure_values: list[Any] = field(default_factory=lambda: [101, 400, 401, 403, 404, 500])
    message_field: str | None = "message"
    data_field: str | None = "data"
    business_error_http_status: int = 200

    def success_assertion(self) -> dict[str, Any] | None:
        # 成功断言优先用 success 字段；没有布尔标识的系统退回 code 字段等于成功值。
        if self.success_field and self.success_values:
            return {
                "type": "json_field",
                "path": self.success_field,
                "operator": "eq",
                "expected": self.success_values[0],
            }
        if self.code_field and self.code_success_values:
            return {
                "type": "json_field",
                "path": self.code_field,
                "operator": "eq",
                "expected": self.code_success_values[0],
            }
        return None

    def failure_assertion(self) -> dict[str, Any] | None:
        # 失败断言优先断言 success 字段为失败值；没有 success 字段时退回 code 不等于成功值。
        if self.success_field and self.failure_values:
            return {
                "type": "json_field",
                "path": self.success_field,
                "operator": "eq",
                "expected": self.failure_values[0],
            }
        if self.code_field and self.code_success_values:
            return {
                "type": "json_field",
                "path": self.code_field,
                "operator": "ne",
                "expected": self.code_success_values[0],
            }
        return None

    def message_assertion(self, contains: str | None = None) -> dict[str, Any] | None:
        if not self.message_field:
            return None
        if contains is not None:
            return {
                "type": "json_field",
                "path": self.message_field,
                "operator": "contains",
                "expected": contains,
            }
        return {"type": "json_field", "path": self.message_field, "operator": "exists"}

    def describe(self) -> str:
        """生成给 AI prompt 用的系统响应约定描述。"""
        lines: list[str] = []
        if self.success_field and self.success_values:
            failure_text = repr(self.failure_values[0]) if self.failure_values else "非成功值"
            lines.append(
                f"- 业务成功标识字段 {self.success_field}："
                f"成功值 {self.success_values[0]!r}，失败值 {failure_text}。"
            )
        if self.code_field and self.code_success_values:
            lines.append(
                f"- 响应码字段 {self.code_field}："
                f"成功值 {self._values_text(self.code_success_values)}，"
                f"常见失败值 {self._values_text(self.code_failure_values)}。"
            )
        if self.message_field:
            lines.append(f"- 错误信息字段 {self.message_field}，失败断言可用 contains 字段名或 exists。")
        if self.data_field:
            lines.append(f"- 业务数据字段 {self.data_field}，成功用例可对其下关键字段追加断言。")
        lines.append(
            f"- 业务失败时 HTTP 状态码通常为 {self.business_error_http_status}，"
            "失败用例的 status_code 断言按此填写。"
        )
        return "\n".join(lines)

    @staticmethod
    def _values_text(values: list[Any]) -> str:
        return "、".join(repr(value) for value in values) if values else "无"


@dataclass(frozen=True)
class Profile:
    name: str = "default"
    response_envelope: ResponseEnvelope = field(default_factory=ResponseEnvelope)

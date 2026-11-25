import json
from pathlib import Path
from typing import Any
from urllib import request as url_request
from urllib.error import HTTPError, URLError

from ..knowledge.apifox_parser import ApiEndpoint
from ..profile import Profile
from .config import ChatProviderSettings


class OpenAICompatibleProvider:
    """复用 OpenAI-compatible Chat Completions 协议的 AI Provider。"""

    def __init__(self, settings: ChatProviderSettings) -> None:
        if not settings.api_key:
            raise ValueError(f"未配置 {settings.provider} API Key")
        if not settings.model:
            raise ValueError(f"未配置 {settings.provider} 模型名称")
        self.settings = settings

    def generate_cases(self, endpoints: list[ApiEndpoint], profile: Profile) -> list[dict[str, Any]]:
        response_text = self._chat(
            system_prompt="你是接口自动化测试用例生成助手，只返回合法 JSON。",
            user_prompt=self._build_case_prompt(endpoints, profile),
        )
        data = self._parse_json_response_with_repair(response_text)
        cases = data.get("cases")
        if not isinstance(cases, list):
            raise ValueError("AI 返回内容缺少 cases 数组")
        return cases

    def analyze_result(self, result_path: Path) -> str:
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        return self._chat(
            system_prompt="你是接口自动化测试结果分析助手，请输出简洁、可执行的中文分析。",
            user_prompt=self._build_analysis_prompt(result_payload),
        )

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = url_request.Request(
            self.settings.base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with url_request.urlopen(request, timeout=60) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.settings.provider} 请求失败，HTTP {error.code}。\n"
                f"base_url={self.settings.base_url}\n"
                f"model={self.settings.model}\n"
                f"response={error_body}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"{self.settings.provider} 请求失败，无法连接服务。\n"
                f"base_url={self.settings.base_url}\n"
                f"model={self.settings.model}\n"
                f"reason={error.reason}"
            ) from error

        data = json.loads(response_body)
        return data["choices"][0]["message"]["content"]

    def _build_case_prompt(self, endpoints: list[ApiEndpoint], profile: Profile) -> str:
        api_payload = [
            {
                "method": endpoint.method,
                "path": endpoint.path,
                "name": endpoint.name,
                "success_status": endpoint.success_status,
                "path_fields": [field.__dict__ for field in endpoint.path_fields],
                "query_fields": [field.__dict__ for field in endpoint.query_fields],
                "request_fields": [field.__dict__ for field in endpoint.request_fields],
            }
            for endpoint in endpoints
        ]
        envelope = profile.response_envelope

        # 示例 case 的断言按 profile 组装，让模型直接看到本系统的成功/失败语义。
        success_example_assertions: list[dict[str, Any]] = [{"type": "status_code", "expected": 200}]
        success_assertion = envelope.success_assertion()
        if success_assertion is not None:
            success_example_assertions.append(success_assertion)

        failure_example_assertions: list[dict[str, Any]] = [
            {"type": "status_code", "expected": envelope.business_error_http_status}
        ]
        failure_assertion = envelope.failure_assertion()
        if failure_assertion is not None:
            failure_example_assertions.append(failure_assertion)
        message_contains = envelope.message_assertion(contains="id")
        if message_contains is not None:
            failure_example_assertions.append(message_contains)

        success_example = {
            "case_id": "get_user_success",
            "case_type": "interface",
            "scenario": "success",
            "name": "正向用例-获取用户",
            "api": {"method": "GET", "path": "/api/user"},
            "request": {"query": {"id": "1"}},
            "assertions": success_example_assertions,
        }
        failure_example = {
            "case_id": "get_user_missing_required",
            "case_type": "interface",
            "scenario": "missing_required",
            "name": "缺少必填参数-id",
            "api": {"method": "GET", "path": "/api/user"},
            "request": {"query": {}},
            "assertions": failure_example_assertions,
        }

        return (
            "请根据下面的接口信息生成接口级测试用例。\n"
            "输出要求：\n"
            "1. 只返回合法 JSON，不要 Markdown，不要解释，不要代码块。\n"
            "2. JSON 顶层格式必须是 {\"cases\": [...]}。\n"
            "3. 输出前必须确保 JSON 可被 Python json.loads 直接解析：所有对象字段之间必须有逗号，字符串必须用双引号，不能有尾随逗号，不能有注释。\n"
            "4. JSON 值必须是具体字面量，禁止使用表达式或函数调用，例如禁止 \"a\".repeat(1000)、Date.now()、undefined、None、True、False。\n"
            "5. 需要超长字符串时，直接写具体字符串值；不想展开过长内容时使用可读样例值，例如 \"very_long_order_id_1000_chars\"。\n"
            "6. 每个 case 必须包含 case_id、case_type、name、scenario、api、request、assertions。\n"
            "7. case_type 固定为 \"interface\"；scenario 只能取以下值之一："
            "success、missing_required、empty_value、invalid_type、boundary、invalid_extra、not_found、auth_or_permission。\n"
            "8. api 只能包含 method、path、headers；method 和 path 必须和输入接口完全一致。\n"
            "9. query/path/body/header 参数必须分别放到 request.query/request.path/request.body/request.headers。\n"
            "10. assertions 必须是数组，至少包含 1 条 status_code 断言。\n"
            "11. HTTP 状态码断言格式：{\"type\":\"status_code\",\"expected\":200}。\n"
            "12. 响应 JSON 字段断言格式：{\"type\":\"json_field\",\"path\":\"success\",\"operator\":\"eq\",\"expected\":true}。\n"
            "13. json_field.path 使用点号路径，例如 code、success、data.id、data.items[0].id。\n"
            "14. json_field.operator 只允许 eq、ne、exists、contains；不写 operator 时默认为 eq。\n"
            "15. operator 为 eq、ne、contains 时必须写 expected；operator 为 exists 时禁止写 expected。\n"
            "16. exists 断言正确格式：{\"type\":\"json_field\",\"path\":\"success\",\"operator\":\"exists\"}。\n"
            "17. exists 断言错误格式：{\"type\":\"json_field\",\"path\":\"success\",\"operator\":\"exists\",\"expected\":true}。\n"
            "18. case_id 必须可读且唯一，建议包含接口名、场景类型，例如 get_user_success。\n"
            "19. 不要编造输入接口列表之外的接口、路径、方法或字段。\n\n"
            "系统响应约定（所有业务断言必须遵循）：\n"
            f"{envelope.describe()}\n\n"
            "用例生成策略：\n"
            "1. 每个接口目标生成 6-8 条 case，至少生成 5 条；不要只生成 success、missing_required、invalid_type 三类。\n"
            "2. 必须优先生成 success 用例：使用合法参数，status_code 使用接口 success_status，业务断言按系统响应约定断言成功语义。\n"
            "3. success 用例不要断言失败语义，即系统响应约定中的失败取值、失败 code 或失败 message。\n"
            "4. 不要把约定字段的 exists 断言当作核心业务断言；exists 只能作为辅助结构检查。\n"
            "5. success 用例如果无法确认测试数据真实存在，不要断言失败语义；可以在 name 中标记需要有效测试数据。\n"
            "6. 异常用例不能只断言 status_code 或字段存在，必须断言失败语义：HTTP 4xx，"
            "或业务返回 200 时按系统响应约定断言失败取值、错误 code、message 包含错误原因。\n"
            "7. missing_required 用例必须让 message contains 缺失字段名，或至少断言系统响应约定中的失败语义。\n"
            "8. invalid_type 或 boundary 用例必须断言接口拒绝非法参数，不能只断言字段存在。\n"
            "9. 只有存在 required=true 字段时，才生成 missing_required；否则生成 invalid_extra。\n"
            "10. 不要编造强业务断言；无法确定具体 code/message 时，按系统响应约定断言失败语义，"
            "或 message exists/contains 字段名，不要只用 exists。\n"
            "11. 如果接口没有请求参数，也要生成：success、缺少公共 header 或无鉴权、异常 query 或 path 参数用例。\n\n"
            "场景覆盖矩阵，按接口能力尽量覆盖（scenario 字段按矩阵名称填写）：\n"
            "- success：合法请求，断言 status_code 和系统响应约定的成功语义；如果能从请求字段对应响应字段，增加数据字段中关键字段断言。\n"
            "- missing_required：每次移除一个 required=true 字段；如果有多个 required 字段，至少覆盖 1-2 个关键字段。\n"
            "- empty_value：必填字符串传空字符串，数组传空数组，对象传空对象，断言失败语义。\n"
            "- invalid_type：字段类型错误，例如 integer 传字符串、boolean 传非 true/false、object 传字符串。\n"
            "- boundary：数字传 0、-1、超大值；字符串传超长、空白字符串、特殊字符。\n"
            "- invalid_extra：传入 OpenAPI 未声明的 query/body 字段，验证接口是否忽略或拒绝异常字段。\n"
            "- not_found：传入格式合法但通常不存在的数据，按系统响应约定断言数据不存在。\n"
            "- auth_or_permission：未登录、Token 失效、无权限；如果接口明确 security=[]，可以跳过该类。\n"
            "如果某类场景不适用于当前接口，不要硬凑；改用其它适用场景补足至少 5 条 case。\n\n"
            "输出前自检：\n"
            "1. 不允许任何 operator=exists 的断言包含 expected 字段。\n"
            "2. 每个 case_id 必须唯一。\n"
            "3. 每个 case 至少包含一条 status_code 断言。\n"
            "4. 每个 case 必须带 scenario 字段，且取值在允许列表内。\n"
            "5. success/正向用例不能只断言 status_code 或字段 exists，必须有系统响应约定中的成功语义断言，且不能断言失败语义。\n"
            "6. 异常用例不能只断言 status_code 或字段 exists，必须有失败语义断言。\n"
            "7. 每个接口至少包含 1 条 success，1 条缺参或空值，1 条类型/边界，1 条不存在数据或额外参数，"
            "1 条鉴权/header/权限相关场景；不适用时用其它负向场景补足。\n"
            "8. 同一个接口的不同 case 请求参数和断言不能完全相同。\n"
            "9. 不要生成框架不支持的断言类型。\n"
            "10. 不要输出 Markdown、解释文字或代码块。\n"
            "11. 不允许输出任何 JavaScript/Python 表达式；所有 request 和 expected 的值都必须是 JSON 字面量。\n\n"
            "最小合法 case 示例：\n"
            f"{json.dumps(success_example, ensure_ascii=False, indent=2)}\n\n"
            "异常 case 断言示例：\n"
            f"{json.dumps(failure_example, ensure_ascii=False, indent=2)}\n\n"
            f"接口信息：\n{json.dumps(api_payload, ensure_ascii=False, indent=2)}"
        )

    def _build_analysis_prompt(self, result_payload: dict[str, Any]) -> str:
        return (
            "请分析下面的接口自动化测试执行结果。\n"
            "请按以下结构输出：\n"
            "1. 总体结论\n"
            "2. 失败用例列表\n"
            "3. 可能原因\n"
            "4. 建议修复动作\n"
            "5. 是否更像环境问题、数据问题、脚本问题或接口缺陷\n\n"
            f"测试结果 JSON：\n{json.dumps(result_payload, ensure_ascii=False, indent=2)}"
        )

    def _parse_json_response_with_repair(self, response_text: str) -> dict[str, Any]:
        try:
            return self._parse_json_response(response_text)
        except json.JSONDecodeError as error:
            repaired_text = self._repair_json_response(response_text, error)
            try:
                return self._parse_json_response(repaired_text)
            except json.JSONDecodeError as repaired_error:
                raise ValueError(
                    "AI 返回内容不是合法 JSON，自动修复后仍解析失败。\n"
                    f"原始错误: {self._json_error_detail(response_text, error)}\n"
                    f"修复后错误: {self._json_error_detail(repaired_text, repaired_error)}"
                ) from repaired_error

    def _repair_json_response(self, response_text: str, error: json.JSONDecodeError) -> str:
        return self._chat(
            system_prompt="你是 JSON 修复器，只返回修复后的合法 JSON，不要 Markdown，不要解释。",
            user_prompt=(
                "下面内容本应是 {\"cases\": [...]} 格式，但 JSON 语法无效。\n"
                "请只修复 JSON 语法，不要新增、删除或改写用例语义。\n"
                "如果发现 JavaScript/Python 表达式，请转换为等价或近似的 JSON 字面量；"
                "例如把 \"a\".repeat(1000) 改成一个具体字符串或 \"very_long_string_1000_chars\"。\n"
                "要求：只返回可被 Python json.loads 解析的 JSON；不要代码块；不要解释。\n\n"
                f"解析错误：{error}\n\n"
                f"待修复内容：\n{response_text}"
            ),
        )

    def _parse_json_response(self, response_text: str) -> dict[str, Any]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        text = self._extract_json_text(text)
        text = self._replace_common_non_json_expressions(text)
        return json.loads(text)

    def _extract_json_text(self, text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _json_error_detail(self, text: str, error: json.JSONDecodeError) -> str:
        start = max(0, error.pos - 120)
        end = min(len(text), error.pos + 120)
        excerpt = text[start:end].replace("\n", "\\n")
        return f"{error.msg} at line {error.lineno} column {error.colno}; nearby={excerpt!r}"

    def _replace_common_non_json_expressions(self, text: str) -> str:
        # Some models occasionally emit JavaScript-style repeat expressions inside JSON.
        # Convert the common bounded form into a concrete JSON string before parsing.
        import re

        def replace_repeat(match: re.Match[str]) -> str:
            value = match.group("value")
            count = int(match.group("count"))
            if count > 2000:
                value = f"{value}_repeated_{count}_times"
                return json.dumps(value, ensure_ascii=False)
            return json.dumps(value * count, ensure_ascii=False)

        pattern = re.compile(
            r'"(?P<value>(?:\\.|[^"\\])*)"\s*\.\s*repeat\s*\(\s*(?P<count>\d{1,5})\s*\)'
        )
        return pattern.sub(replace_repeat, text)

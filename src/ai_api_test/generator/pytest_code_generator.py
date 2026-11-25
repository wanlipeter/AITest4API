import json
from typing import Any


class PytestCodeGenerator:
    """把用例 DSL 转换成最小 pytest 风格代码。"""

    def generate(self, cases: list[dict[str, Any]]) -> str:
        cases_literal = json.dumps(cases, ensure_ascii=False, indent=2)
        cases_literal_for_python = repr(cases_literal)
        return f'''import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib import request as url_request
from urllib.error import HTTPError
from urllib.parse import urlencode


def _add_project_src_to_path():
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for directory in candidates:
        src_dir = directory / "src"
        if (src_dir / "ai_api_test").exists():
            sys.path.insert(0, str(src_dir))
            return


def _load_dotenv():
    # 只加载 .env；.env.example 是纯文档模板，不能作为配置来源。
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for directory in candidates:
        env_path = directory / ".env"
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_add_project_src_to_path()
_load_dotenv()

from ai_api_test.auth.login_auth import LoginSession


BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
RESULT_PATH = Path(os.getenv("TEST_RESULT_PATH", Path(__file__).with_name("test_results.json")))
AUTH_SESSION = LoginSession.from_env()
CASES = json.loads({cases_literal_for_python})
RESULTS = []


def _send(case):
    api = case["api"]
    req = case.get("request", {{}})
    path = api["path"]

    for key, value in req.get("path", {{}}).items():
        path = path.replace("{{" + key + "}}", str(value))

    query = req.get("query") or api.get("query") or {{}}
    if query:
        path = path + "?" + urlencode(query)

    body = req.get("body")
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = AUTH_SESSION.get_headers()
    headers.update(api.get("headers") or {{}})
    headers.update(req.get("headers") or {{}})
    http_request = url_request.Request(
        BASE_URL + path,
        data=payload,
        headers=headers,
        method=api["method"],
    )

    try:
        with url_request.urlopen(http_request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8")


def _write_results():
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps({{"base_url": BASE_URL, "results": RESULTS}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_case_value(case, key, default=None):
    return case.get(key, default) if isinstance(case, dict) else default


def _fallback_case_id(index):
    # 当 AI 返回的用例缺少 case_id 时，使用序号生成可定位的兜底编号。
    return f"generated_case_{{index + 1:03d}}"


def _normalize_assertions(assertions):
    # cases 在生成阶段已经由 CaseNormalizer 归一化；这里只做最小防御，异常输入交给断言阶段报错。
    if isinstance(assertions, list):
        return assertions
    return []


def _response_json(response_body):
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as error:
        raise AssertionError(f"响应不是合法 JSON，无法进行字段断言: {{response_body[:500]}}") from error


def _field_tokens(path):
    normalized_path = str(path).strip()
    if normalized_path.startswith("$."):
        normalized_path = normalized_path[2:]
    elif normalized_path.startswith("$"):
        normalized_path = normalized_path[1:]

    tokens = []
    for part in normalized_path.split("."):
        if not part:
            continue
        matches = re.finditer(r"([^\\[\\]]+)|\\[(\\d+)\\]", part)
        for match in matches:
            name, index = match.groups()
            tokens.append(int(index) if index is not None else name)
    return tokens


def _read_json_field(data, path):
    current = data
    for token in _field_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise AssertionError(f"响应 JSON 路径不存在: {{path}}")
            current = current[token]
            continue

        if not isinstance(current, dict) or token not in current:
            raise AssertionError(f"响应 JSON 路径不存在: {{path}}")
        current = current[token]
    return current


def _scalar_eq(actual, expected):
    # 标量宽松比较：兼容 code "200" 和 200 这类字符串/数字混用。
    if actual == expected:
        return True
    if isinstance(actual, (str, int, float, bool)) and isinstance(expected, (str, int, float, bool)):
        return str(actual).strip().lower() == str(expected).strip().lower()
    return False


def _contains_value(actual, expected):
    # contains 对非容器值转字符串比较，避免 TypeError 中断用例。
    try:
        return expected in actual
    except TypeError:
        return str(expected) in str(actual)


def _assert_json_field(response_body, assertion):
    path = assertion.get("path") or assertion.get("field") or assertion.get("json_path")
    if not path:
        raise AssertionError(f"json_field 断言缺少 path: {{assertion}}")

    actual = _read_json_field(_response_json(response_body), path)
    expected = assertion.get("expected")
    operator = assertion.get("operator", "eq")

    if operator == "eq":
        assert _scalar_eq(actual, expected), f"JSON 字段 {{path}} 期望 {{expected!r}}，实际 {{actual!r}}"
    elif operator == "ne":
        assert not _scalar_eq(actual, expected), f"JSON 字段 {{path}} 不应等于 {{expected!r}}，实际 {{actual!r}}"
    elif operator == "exists":
        assert actual is not None, f"JSON 字段 {{path}} 期望存在且非 None"
    elif operator == "contains":
        assert _contains_value(actual, expected), f"JSON 字段 {{path}} 期望包含 {{expected!r}}，实际 {{actual!r}}"
    else:
        raise AssertionError(f"不支持的 json_field operator: {{operator}}")


def _assert_case(case, status_code, response_body):
    # cases 在生成阶段已由 CaseNormalizer 归一化为标准列表结构。
    for assertion in _normalize_assertions(_safe_case_value(case, "assertions", [])):
        assertion_type = assertion["type"]
        if assertion_type == "status_code":
            assert status_code == assertion["expected"], (
                f"HTTP 状态码期望 {{assertion['expected']}}，实际 {{status_code}}"
            )
        elif assertion_type in {{"json_field", "body_field", "response_field"}}:
            _assert_json_field(response_body, assertion)
        else:
            raise AssertionError(f"不支持的断言类型: {{assertion_type}}")


def _execute_case(case, index):
    result = {{
        "case_id": _safe_case_value(case, "case_id", _fallback_case_id(index)),
        "name": _safe_case_value(case, "name"),
        "api": _safe_case_value(case, "api"),
        "request": _safe_case_value(case, "request", {{}}),
        "passed": False,
    }}

    try:
        status_code, response_body = _send(case)
        result["status_code"] = status_code
        result["response_body"] = response_body[:2000]
        _assert_case(case, status_code, response_body)
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
    finally:
        RESULTS.append(result)
        try:
            _write_results()
        except Exception as write_error:
            result["result_write_error"] = str(write_error)
    return result


def test_generated_api_cases():
    failed_results = []
    for index, case in enumerate(CASES):
        result = _execute_case(case, index)
        if not result["passed"]:
            failed_results.append(result)

    if failed_results:
        failed_case_ids = [str(item.get("case_id")) for item in failed_results]
        assert False, (
            f"{{len(failed_results)}} case(s) failed. "
            f"Failed case ids: {{', '.join(failed_case_ids)}}. "
            f"See result file: {{RESULT_PATH}}"
        )
'''

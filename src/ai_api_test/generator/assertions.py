from typing import Any


def normalize_assertions(assertions: Any) -> list[dict[str, Any]]:
    """把各种断言简写归一化为标准列表；非法输入归一化为 type=None，交给校验器报错。

    这是框架内唯一的断言归一化实现，normalizer、validator 共用，
    生成脚本里嵌入的数据在生成阶段已经归一化过。
    """
    if isinstance(assertions, list):
        return [normalize_single_assertion(item) for item in assertions]
    if isinstance(assertions, dict):
        return [normalize_single_assertion({key: value}) for key, value in assertions.items()]
    if isinstance(assertions, str):
        return [{"type": assertions, "expected": 200}]
    return []


def normalize_single_assertion(assertion: Any) -> dict[str, Any]:
    if isinstance(assertion, dict):
        if "type" in assertion:
            return assertion
        if len(assertion) == 1:
            assertion_type, expected = next(iter(assertion.items()))
            if assertion_type in {"status_code", "http_code"}:
                return {"type": "status_code", "expected": expected}
            if assertion_type in {"json_field", "body_field", "response_field"}:
                if isinstance(expected, dict):
                    return {"type": "json_field", **expected}
                return {"type": "json_field", "path": assertion_type, "expected": expected}
            # 兼容 {"success": false}、{"code": "101"} 这类响应字段断言简写。
            return {"type": "json_field", "path": assertion_type, "expected": expected}
    if isinstance(assertion, str):
        return {"type": assertion, "expected": 200}
    return {"type": None}

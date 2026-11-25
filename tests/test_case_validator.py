from ai_api_test.knowledge.apifox_parser import ApiEndpoint, ApiField
from ai_api_test.profile import Profile, ResponseEnvelope
from ai_api_test.validator.case_validator import CaseValidator

MOCK_ENVELOPE = ResponseEnvelope(
    success_field="ok",
    success_values=[True],
    failure_values=[False],
    code_field="errCode",
    code_success_values=[0],
    code_failure_values=[1, "SYS_ERROR"],
    message_field="msg",
    data_field="payload",
)


def _endpoints():
    return [
        ApiEndpoint(
            method="POST",
            path="/api/login",
            name="登录成功",
            request_fields=[
                ApiField(name="username", type="string", required=True),
                ApiField(name="age", type="integer", required=False),
            ],
        )
    ]


def _codes(report):
    return [finding.code for finding in report.findings]


def test_negative_scenario_cases_skip_type_check():
    # 回归：本地生成器的 empty_value/not_found 用例对整型字段传字符串/空串，
    # 不应再触发 REQUEST_FIELD_TYPE_MISMATCH 假警告。
    validator = CaseValidator(Profile(name="mock", response_envelope=MOCK_ENVELOPE))
    cases = [
        {
            "case_id": "post_api_login_empty_value",
            "case_type": "interface",
            "scenario": "empty_value",
            "name": "登录成功 - 空值参数 age",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user", "age": ""}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "msg", "operator": "exists"},
            ],
        },
        {
            "case_id": "post_api_login_not_found",
            "case_type": "interface",
            "scenario": "not_found",
            "name": "登录成功 - 数据不存在",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user", "age": "not_exist_age_999999"}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "msg", "operator": "exists"},
            ],
        },
    ]
    report = validator.validate({"cases": cases}, _endpoints())
    assert "REQUEST_FIELD_TYPE_MISMATCH" not in _codes(report)


def test_keyword_fallback_without_scenario_field():
    # 手改/AI 漏写 scenario 字段时，关键词猜测也要识别 empty_value/not_found。
    validator = CaseValidator(Profile(name="mock", response_envelope=MOCK_ENVELOPE))
    cases = [
        {
            "case_id": "post_api_login_empty_value",
            "case_type": "interface",
            "name": "登录成功 - 空值参数 age",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user", "age": ""}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
            ],
        }
    ]
    report = validator.validate({"cases": cases}, _endpoints())
    assert "REQUEST_FIELD_TYPE_MISMATCH" not in _codes(report)


def test_negative_case_with_success_in_endpoint_name_not_flagged():
    # 回归：接口名带“成功”时，负向用例不应被当作正向用例检查失败语义。
    validator = CaseValidator(Profile(name="mock", response_envelope=MOCK_ENVELOPE))
    cases = [
        {
            "case_id": "post_api_login_missing_required",
            "case_type": "interface",
            "scenario": "missing_required",
            "name": "登录成功 - 缺少必填参数 username",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"age": 1}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "msg", "operator": "contains", "expected": "username"},
            ],
        }
    ]
    report = validator.validate({"cases": cases}, _endpoints())
    assert "SUCCESS_CASE_ASSERTS_FAILURE_SEMANTICS" not in _codes(report)


def test_success_case_asserting_failure_semantics_flagged_with_profile_fields():
    # 真正的正向用例断言失败语义，要按 profile 的字段名识别出来。
    validator = CaseValidator(Profile(name="mock", response_envelope=MOCK_ENVELOPE))
    cases = [
        {
            "case_id": "post_api_login_success",
            "case_type": "interface",
            "scenario": "success",
            "name": "登录成功 - 正向用例",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user"}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
                {"type": "json_field", "path": "errCode", "operator": "eq", "expected": 1},
            ],
        }
    ]
    report = validator.validate({"cases": cases}, _endpoints())
    semantics = [f for f in report.findings if f.code == "SUCCESS_CASE_ASSERTS_FAILURE_SEMANTICS"]
    assert len(semantics) == 2


def test_default_profile_flags_success_false():
    validator = CaseValidator()
    cases = [
        {
            "case_id": "post_api_login_success",
            "case_type": "interface",
            "scenario": "success",
            "name": "登录 - 正向用例",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user"}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "success", "operator": "eq", "expected": False},
            ],
        }
    ]
    report = validator.validate({"cases": cases}, None)
    assert "SUCCESS_CASE_ASSERTS_FAILURE_SEMANTICS" in _codes(report)


def test_explicit_scenario_overrides_name_keywords():
    # scenario 字段优先级高于名称关键词：名称像正向用例，但场景标了 invalid_type。
    validator = CaseValidator(Profile(name="mock", response_envelope=MOCK_ENVELOPE))
    cases = [
        {
            "case_id": "post_api_login_invalid_type",
            "case_type": "interface",
            "scenario": "invalid_type",
            "name": "登录成功 - 正向探索",
            "api": {"method": "POST", "path": "/api/login"},
            "request": {"body": {"username": "demo_user", "age": "not_a_number"}},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_field", "path": "ok", "operator": "eq", "expected": False},
            ],
        }
    ]
    report = validator.validate({"cases": cases}, _endpoints())
    assert "SUCCESS_CASE_ASSERTS_FAILURE_SEMANTICS" not in _codes(report)
    assert "REQUEST_FIELD_TYPE_MISMATCH" not in _codes(report)

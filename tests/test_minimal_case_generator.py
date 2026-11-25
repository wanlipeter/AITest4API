from ai_api_test.generator.minimal_case_generator import MinimalAiCaseGenerator
from ai_api_test.knowledge.apifox_parser import ApiEndpoint, ApiField
from ai_api_test.profile import Profile, ResponseEnvelope

CANONICAL_SCENARIOS = {
    "success",
    "missing_required",
    "empty_value",
    "invalid_type",
    "invalid_extra",
    "not_found",
    "auth_or_permission",
}

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


def _endpoint():
    return ApiEndpoint(
        method="POST",
        path="/api/orders",
        name="创建订单",
        request_fields=[
            ApiField(name="orderId", type="string", required=True),
            ApiField(name="amount", type="integer", required=False),
        ],
    )


def _json_assertions(case):
    return [a for a in case["assertions"] if a["type"] == "json_field"]


def _by_scenario(cases, scenario):
    return next(case for case in cases if case["scenario"] == scenario)


def test_all_cases_have_canonical_scenario():
    cases = MinimalAiCaseGenerator().generate([_endpoint()])
    assert cases
    for case in cases:
        assert case["scenario"] in CANONICAL_SCENARIOS


def test_default_profile_success_asserts_success_true():
    cases = MinimalAiCaseGenerator().generate([_endpoint()])
    success = _by_scenario(cases, "success")
    assert _json_assertions(success) == [
        {"type": "json_field", "path": "success", "operator": "eq", "expected": True}
    ]


def test_default_profile_failure_asserts_success_false_and_message():
    cases = MinimalAiCaseGenerator().generate([_endpoint()])
    missing = _by_scenario(cases, "missing_required")
    assert {"type": "json_field", "path": "success", "operator": "eq", "expected": False} in missing["assertions"]
    assert {"type": "json_field", "path": "message", "operator": "contains", "expected": "orderId"} in missing["assertions"]
    assert {"type": "status_code", "expected": 200} in missing["assertions"]


def test_mock_company_profile_changes_assertion_fields():
    generator = MinimalAiCaseGenerator(Profile(name="mockco", response_envelope=MOCK_ENVELOPE))
    cases = generator.generate([_endpoint()])

    success = _by_scenario(cases, "success")
    assert _json_assertions(success) == [
        {"type": "json_field", "path": "ok", "operator": "eq", "expected": True}
    ]

    missing = _by_scenario(cases, "missing_required")
    assert {"type": "json_field", "path": "ok", "operator": "eq", "expected": False} in missing["assertions"]
    assert {"type": "json_field", "path": "msg", "operator": "contains", "expected": "orderId"} in missing["assertions"]

    not_found = _by_scenario(cases, "not_found")
    assert {"type": "json_field", "path": "ok", "operator": "eq", "expected": False} in not_found["assertions"]
    assert {"type": "json_field", "path": "msg", "operator": "exists"} in not_found["assertions"]


def test_code_only_envelope_falls_back_to_code_assertions():
    envelope = ResponseEnvelope(
        success_field=None,
        code_field="errCode",
        code_success_values=[0],
        code_failure_values=[1],
    )
    cases = MinimalAiCaseGenerator(Profile(response_envelope=envelope)).generate([_endpoint()])

    success = _by_scenario(cases, "success")
    assert _json_assertions(success) == [
        {"type": "json_field", "path": "errCode", "operator": "eq", "expected": 0}
    ]

    failure = _by_scenario(cases, "not_found")
    assert {"type": "json_field", "path": "errCode", "operator": "ne", "expected": 0} in failure["assertions"]


def test_business_error_http_status_used_for_negative_cases():
    envelope = ResponseEnvelope(business_error_http_status=400)
    cases = MinimalAiCaseGenerator(Profile(response_envelope=envelope)).generate([_endpoint()])

    not_found = _by_scenario(cases, "not_found")
    assert {"type": "status_code", "expected": 400} in not_found["assertions"]

    success = _by_scenario(cases, "success")
    assert {"type": "status_code", "expected": 200} in success["assertions"]

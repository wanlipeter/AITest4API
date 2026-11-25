from ai_api_test.generator.assertions import normalize_assertions


def test_list_passthrough():
    assertions = [{"type": "status_code", "expected": 200}]
    assert normalize_assertions(assertions) == assertions


def test_dict_shorthand_expands_to_field_assertions():
    assert normalize_assertions({"success": False, "code": "101"}) == [
        {"type": "json_field", "path": "success", "expected": False},
        {"type": "json_field", "path": "code", "expected": "101"},
    ]


def test_http_code_shorthand_becomes_status_code():
    assert normalize_assertions({"http_code": 404}) == [{"type": "status_code", "expected": 404}]


def test_json_field_dict_shorthand_expands():
    item = {"json_field": {"path": "data.id", "operator": "exists"}}
    assert normalize_assertions([item]) == [{"type": "json_field", "path": "data.id", "operator": "exists"}]


def test_body_field_alias_shorthand_expands():
    item = {"body_field": {"path": "code", "expected": 200}}
    assert normalize_assertions([item]) == [{"type": "json_field", "path": "code", "expected": 200}]


def test_string_becomes_status_code():
    assert normalize_assertions("status_code") == [{"type": "status_code", "expected": 200}]


def test_none_returns_empty():
    assert normalize_assertions(None) == []


def test_garbage_item_becomes_type_none_for_validator_to_flag():
    assert normalize_assertions([42]) == [{"type": None}]

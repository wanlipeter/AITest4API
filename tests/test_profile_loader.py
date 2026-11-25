import json
from pathlib import Path

import pytest

from ai_api_test.profile import load_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_default_profile_from_repo():
    profile = load_profile("default", PROJECT_ROOT / "profiles")
    assert profile.name == "default"
    envelope = profile.response_envelope
    assert envelope.success_field == "success"
    assert envelope.success_values == [True]
    assert envelope.failure_values == [False]
    assert envelope.code_field == "code"
    assert envelope.code_failure_values == [101, 400, 401, 403, 404, 500]
    assert envelope.message_field == "message"
    assert envelope.business_error_http_status == 200


def test_missing_profile_raises(tmp_path):
    with pytest.raises(ValueError, match="找不到 profile"):
        load_profile("nope", tmp_path)


def test_unknown_envelope_field_raises(tmp_path):
    profile_dir = tmp_path / "mockco"
    profile_dir.mkdir()
    (profile_dir / "profile.json").write_text(
        json.dumps({"response_envelope": {"succss_field": "success"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未知字段"):
        load_profile("mockco", tmp_path)


def test_mock_company_profile_overrides_defaults(tmp_path):
    profile_dir = tmp_path / "mockco"
    profile_dir.mkdir()
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "name": "mockco",
                "response_envelope": {
                    "success_field": "ok",
                    "success_values": [True],
                    "failure_values": [False],
                    "code_field": "errCode",
                    "code_success_values": [0],
                    "code_failure_values": [1, "SYS_ERROR"],
                    "message_field": "msg",
                    "data_field": "payload",
                    "business_error_http_status": 200,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile = load_profile("mockco", tmp_path)
    envelope = profile.response_envelope
    assert envelope.success_field == "ok"
    assert envelope.code_success_values == [0]
    assert envelope.message_field == "msg"
    assert envelope.success_assertion() == {
        "type": "json_field",
        "path": "ok",
        "operator": "eq",
        "expected": True,
    }

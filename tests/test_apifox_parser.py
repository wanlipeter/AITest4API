import json
from pathlib import Path

from ai_api_test.generator.minimal_case_generator import MinimalAiCaseGenerator
from ai_api_test.knowledge.apifox_parser import ApifoxOpenApiParser
from ai_api_test.validator.case_validator import CaseValidator

RICH_DOC = Path(__file__).resolve().parents[1] / "examples" / "apifox" / "rich-models.openapi.json"


def _parse():
    parser = ApifoxOpenApiParser()
    endpoints = parser.parse(RICH_DOC)
    return parser, endpoints


def _fields(endpoints, method, path, section="request_fields"):
    endpoint = next(e for e in endpoints if e.method == method and e.path == path)
    return getattr(endpoint, section)


def test_ref_and_nested_expansion():
    _, endpoints = _parse()
    fields = _fields(endpoints, "POST", "/api/customers")
    names = [f.name for f in fields]
    assert names == [
        "name",
        "level",
        "address.city",
        "address.street",
        "tags",
        "amounts",
        "profile.nickname",
        "profile.preference.lang",
        "profile.preference.meta",
    ]
    by_name = {f.name: f for f in fields}
    assert by_name["name"].required is True
    assert by_name["address.city"].required is True
    assert by_name["address.street"].required is False
    assert by_name["level"].enum_values == ["GOLD", "SILVER", "BRONZE"]
    assert by_name["tags"].type == "array" and by_name["tags"].item_type == "string"
    assert by_name["amounts"].type == "array" and by_name["amounts"].item_type == "number"
    # meta 超过 2 层，按整体 object 处理并产生 warning
    assert by_name["profile.preference.meta"].type == "object"


def test_oneof_takes_first_branch_with_warning():
    parser, endpoints = _parse()
    fields = _fields(endpoints, "POST", "/api/payments")
    assert [f.name for f in fields] == ["cardNo", "cvv"]
    assert any("oneOf" in warning for warning in parser.last_warnings)


def test_query_enum_and_ref_parameter():
    _, endpoints = _parse()
    fields = _fields(endpoints, "GET", "/api/orders", section="query_fields")
    by_name = {f.name: f for f in fields}
    assert by_name["status"].enum_values == ["PAID", "UNPAID", "CANCELLED"]
    assert by_name["status"].required is True
    assert by_name["tag"].enum_values == ["vip", "normal"]
    assert by_name["pageNum"].type == "integer"


def test_self_referencing_schema_terminates():
    parser, endpoints = _parse()
    fields = _fields(endpoints, "POST", "/api/orgs")
    # 自引用通过深度上限截断，不会无限递归
    assert any(f.name == "name" for f in fields)
    assert parser.last_warnings  # 深度截断会产生 warning


def test_circular_ref_chain_detected(tmp_path):
    doc = {
        "paths": {
            "/api/a": {
                "post": {
                    "summary": "A",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"x": {"$ref": "#/components/schemas/SchemaA"}},
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "SchemaA": {"$ref": "#/components/schemas/SchemaB"},
                "SchemaB": {"$ref": "#/components/schemas/SchemaA"},
            }
        },
    }
    doc_path = tmp_path / "cycle.openapi.json"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")

    parser = ApifoxOpenApiParser()
    endpoints = parser.parse(doc_path)
    assert any("循环引用" in warning for warning in parser.last_warnings)
    # 循环字段被截断，但接口本身仍解析出来
    assert len(endpoints) == 1


def test_external_ref_skipped_with_warning(tmp_path):
    doc = {
        "paths": {
            "/api/b": {
                "post": {
                    "summary": "B",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"y": {"$ref": "other-file.yaml#/components/schemas/Y"}},
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    doc_path = tmp_path / "external.openapi.json"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")

    parser = ApifoxOpenApiParser()
    parser.parse(doc_path)
    assert any("外部" in warning for warning in parser.last_warnings)


def test_generator_builds_nested_body_and_enum_samples():
    _, endpoints = _parse()
    cases = MinimalAiCaseGenerator().generate(endpoints)
    success = next(
        c for c in cases if c["api"]["path"] == "/api/customers" and c["scenario"] == "success"
    )
    body = success["request"]["body"]
    assert body["level"] == "GOLD"  # enum 第一项作为合法样例
    assert body["address"] == {"city": "demo_city", "street": "demo_street"}
    assert body["tags"] == ["demo_tags"]
    assert body["amounts"] == [1.0]
    assert body["profile"]["preference"]["lang"] == "demo_lang"
    assert body["profile"]["preference"]["meta"] == {}


def test_generator_missing_required_pops_nested_field():
    _, endpoints = _parse()
    cases = MinimalAiCaseGenerator().generate(endpoints)
    missing = next(
        c for c in cases if c["api"]["path"] == "/api/customers" and c["scenario"] == "missing_required"
    )
    # 第一个必填字段是 name；address.city 也是必填但排在后面
    assert "name" not in missing["request"]["body"]
    assert missing["request"]["body"]["address"] == {"city": "demo_city", "street": "demo_street"}


def test_validator_accepts_nested_success_case_without_false_positives():
    parser, endpoints = _parse()
    cases = MinimalAiCaseGenerator().generate(endpoints)
    report = CaseValidator().validate({"cases": cases}, endpoints)
    finding_codes = {f.code for f in report.findings}
    # 生成器产物（含嵌套 body、enum、数组字段）不应触发字段未声明/类型不匹配/必填缺失
    assert "UNDECLARED_REQUEST_FIELD" not in finding_codes
    assert "REQUEST_FIELD_TYPE_MISMATCH" not in finding_codes
    assert "REQUIRED_FIELD_MISSING" not in finding_codes


def test_validator_flags_missing_nested_required_field():
    parser, endpoints = _parse()
    cases = MinimalAiCaseGenerator().generate(endpoints)
    success = next(
        c for c in cases if c["api"]["path"] == "/api/customers" and c["scenario"] == "success"
    )
    broken = json.loads(json.dumps(success))
    broken["case_id"] = "post_api_customers_success_broken"
    broken["request"]["body"].pop("address")
    report = CaseValidator().validate({"cases": [broken]}, endpoints)
    finding_codes = {f.code for f in report.findings}
    assert "REQUIRED_FIELD_MISSING" in finding_codes

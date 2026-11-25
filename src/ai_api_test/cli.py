import argparse
from pathlib import Path

from .profile import DEFAULT_PROFILE_NAME, Profile, load_profile
from .providers.config import AiProviderConfig, normalize_provider_name
from .validator import AiCaseReviewer, Finding, ValidationReport, validate_cases_file
from .validator.report_renderer import render_report
from .workflow.apifox_workflow import ApifoxGenerateWorkflow
from .workflow.result_analysis_workflow import ResultAnalysisWorkflow


AI_PROVIDERS = ["local", "deepseek", "volcengine", "qwen"]
ANALYSIS_PROVIDERS = ["deepseek", "volcengine", "qwen"]
REPORT_FORMATS = ["text", "json", "markdown"]


def generate_from_apifox(
    document_path: Path,
    output_dir: Path,
    provider: str,
    cases_only: bool,
    profile_name: str,
) -> int:
    provider = normalize_provider_name(provider)
    cases_path, code_path = ApifoxGenerateWorkflow().run(
        document_path, output_dir, provider, cases_only, profile_name
    )
    print(f"[GENERATED] cases: {cases_path}")
    if code_path is None:
        print("[WAITING] 请人工检查并修改 cases.json，然后执行 generate-script 重新生成测试脚本。")
    else:
        print(f"[GENERATED] code: {code_path}")
    return 0


def generate_script_from_cases(cases_path: Path, output_path: Path | None) -> int:
    code_path = ApifoxGenerateWorkflow().render_code_from_cases(cases_path, output_path)
    print(f"[GENERATED] code: {code_path}")
    return 0


def analyze_result(result_path: Path, output_path: Path, provider: str) -> int:
    provider = normalize_provider_name(provider)
    analysis_path = ResultAnalysisWorkflow().run(result_path, output_path, provider)
    print(f"[GENERATED] analysis: {analysis_path}")
    return 0


def show_config(provider: str) -> int:
    provider = normalize_provider_name(provider)
    config = AiProviderConfig.load(Path.cwd())
    settings = config.chat_settings(provider)
    masked_key = settings.api_key[:6] + "..." + settings.api_key[-4:] if settings.api_key else ""
    print(f"provider={settings.provider}")
    print(f"base_url={settings.base_url}")
    print(f"model={settings.model}")
    print(f"api_key={masked_key}")
    return 0


def validate_cases(
    cases_path: Path,
    output_path: Path | None,
    output_format: str,
    strict: bool,
    openapi_path: Path | None,
    ai_enabled: bool,
    provider: str,
    profile_name: str,
) -> int:
    profile = load_profile(profile_name)
    report = validate_cases_file(cases_path, openapi_path, profile)
    if ai_enabled:
        report = _append_ai_review(report, cases_path, openapi_path, provider, profile)
    rendered_report = render_report(report, output_format)
    if output_path is None:
        print(rendered_report)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered_report, encoding="utf-8")
        print(f"[GENERATED] validation report: {output_path}")
    return report.exit_code(strict=strict)


def _append_ai_review(
    report: ValidationReport,
    cases_path: Path,
    openapi_path: Path | None,
    provider: str,
    profile: Profile,
) -> ValidationReport:
    if report.errors:
        return ValidationReport(
            cases_count=report.cases_count,
            findings=[
                *report.findings,
                Finding(
                    severity="info",
                    code="AI_REVIEW_SKIPPED",
                    message="存在本地规则 error，已跳过 AI 语义审查。",
                    suggestion="请先修复结构或配置错误，再执行 --ai。",
                ),
            ],
        )

    ai_findings = AiCaseReviewer().review_file(cases_path, openapi_path, report, provider, profile)
    return ValidationReport(
        cases_count=report.cases_count,
        findings=[*report.findings, *ai_findings],
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="aitest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    apifox_parser = subparsers.add_parser("generate-apifox")
    apifox_parser.add_argument("document_path", type=Path)
    apifox_parser.add_argument("--out", type=Path, default=Path("generated/apifox"))
    apifox_parser.add_argument("--provider", choices=AI_PROVIDERS, default="local")
    apifox_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="响应包络约定 profile 名称，对应 profiles/<名称>/profile.json。",
    )
    apifox_parser.add_argument(
        "--cases-only",
        action="store_true",
        help="只生成 cases.json，方便人工检查、删减、修改后再生成测试脚本。",
    )

    script_parser = subparsers.add_parser("generate-script")
    script_parser.add_argument("cases_path", type=Path)
    script_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="测试脚本输出路径，默认覆盖 cases.json 同目录下的 test_generated_api.py。",
    )

    analysis_parser = subparsers.add_parser("analyze-result")
    analysis_parser.add_argument("result_path", type=Path)
    analysis_parser.add_argument("--out", type=Path, default=Path("generated/apifox/analysis.md"))
    analysis_parser.add_argument("--provider", choices=ANALYSIS_PROVIDERS, default="deepseek")

    config_parser = subparsers.add_parser("show-config")
    config_parser.add_argument("--provider", choices=ANALYSIS_PROVIDERS, default="deepseek")

    validate_parser = subparsers.add_parser("validate-cases")
    validate_parser.add_argument("cases_path", type=Path)
    validate_parser.add_argument("--openapi", type=Path, default=None)
    validate_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="响应包络约定 profile 名称，对应 profiles/<名称>/profile.json。",
    )
    validate_parser.add_argument("--ai", action="store_true", help="Use AI to review semantic risks.")
    validate_parser.add_argument("--provider", choices=ANALYSIS_PROVIDERS, default="deepseek")
    validate_parser.add_argument("--out", type=Path, default=None)
    validate_parser.add_argument("--format", choices=REPORT_FORMATS, default="text")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when warnings exist.",
    )

    args = parser.parse_args()
    if args.command == "generate-apifox":
        return generate_from_apifox(
            args.document_path, args.out, args.provider, args.cases_only, args.profile
        )
    if args.command == "generate-script":
        return generate_script_from_cases(args.cases_path, args.out)
    if args.command == "analyze-result":
        return analyze_result(args.result_path, args.out, args.provider)
    if args.command == "show-config":
        return show_config(args.provider)
    if args.command == "validate-cases":
        return validate_cases(
            args.cases_path,
            args.out,
            args.format,
            args.strict,
            args.openapi,
            args.ai,
            args.provider,
            args.profile,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

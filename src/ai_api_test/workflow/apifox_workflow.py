import json
from pathlib import Path
from typing import Any

from ..generator.case_normalizer import CaseNormalizer
from ..generator.minimal_case_generator import MinimalAiCaseGenerator
from ..generator.pytest_code_generator import PytestCodeGenerator
from ..knowledge.apifox_parser import ApifoxOpenApiParser
from ..providers.config import AiProviderConfig, normalize_provider_name
from ..providers.openai_compatible_provider import OpenAICompatibleProvider


MIN_CLOUD_CASES_PER_ENDPOINT = 5


class ApifoxGenerateWorkflow:
    """APIFOX/OpenAPI 文档到用例和 pytest 脚本的最小链路。"""

    def run(
        self,
        document_path: Path,
        output_dir: Path,
        provider: str = "local",
        cases_only: bool = False,
    ) -> tuple[Path, Path | None]:
        output_dir.mkdir(parents=True, exist_ok=True)

        endpoints = ApifoxOpenApiParser().parse(document_path)
        provider = normalize_provider_name(provider)
        cases = CaseNormalizer().normalize_many(self._generate_cases(endpoints, provider))
        if provider != "local":
            self._validate_cloud_case_count(endpoints, cases)

        cases_path = output_dir / "cases.json"
        code_path = output_dir / "test_generated_api.py"

        cases_path.write_text(
            json.dumps({"cases": cases}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if cases_only:
            return cases_path, None

        self._write_pytest_code(cases, code_path)
        return cases_path, code_path

    def render_code_from_cases(self, cases_path: Path, code_path: Path | None = None) -> Path:
        # 人工检查、删减、修改 cases.json 后，通过这个入口重新覆盖生成 pytest 脚本。
        raw_data = json.loads(cases_path.read_text(encoding="utf-8"))
        cases = self._extract_cases(raw_data)
        normalized_cases = CaseNormalizer().normalize_many(cases)

        target_path = code_path or cases_path.with_name("test_generated_api.py")
        self._write_pytest_code(normalized_cases, target_path)
        return target_path

    def _extract_cases(self, raw_data: Any) -> list[dict[str, Any]]:
        # 兼容两种人工编辑格式：直接写数组，或保留 {"cases": [...]} 包装。
        cases = raw_data if isinstance(raw_data, list) else None
        if isinstance(raw_data, dict):
            cases = raw_data.get("cases")
        if not isinstance(cases, list):
            raise ValueError("cases.json 格式不正确，根节点需要是列表，或包含 cases 列表字段。")
        return cases

    def _write_pytest_code(self, cases: list[dict[str, Any]], code_path: Path) -> None:
        # 统一脚本写入逻辑，避免直接生成和人工复核后再生成出现差异。
        code_path.parent.mkdir(parents=True, exist_ok=True)
        code_path.write_text(PytestCodeGenerator().generate(cases), encoding="utf-8")

    def _generate_cases(self, endpoints, provider: str):
        provider = normalize_provider_name(provider)
        if provider == "local":
            return MinimalAiCaseGenerator().generate(endpoints)

        if provider in {"deepseek", "volcengine", "qwen"}:
            config = AiProviderConfig.load(Path.cwd())
            return OpenAICompatibleProvider(config.chat_settings(provider)).generate_cases(endpoints)

        raise ValueError(f"不支持的 AI Provider: {provider}")

    def _validate_cloud_case_count(self, endpoints, cases) -> None:
        counts = {
            (endpoint.method.upper(), endpoint.path): 0
            for endpoint in endpoints
        }
        for case in cases:
            api = case.get("api") or {}
            key = (str(api.get("method", "")).upper(), api.get("path"))
            if key in counts:
                counts[key] += 1

        not_enough = [
            f"{method} {path}: {count}/{MIN_CLOUD_CASES_PER_ENDPOINT}"
            for (method, path), count in counts.items()
            if count < MIN_CLOUD_CASES_PER_ENDPOINT
        ]
        if not_enough:
            detail = "\n".join(not_enough)
            raise ValueError(
                f"云端模型生成的 case 数量不足。每个接口至少需要 {MIN_CLOUD_CASES_PER_ENDPOINT} 条 case：\n"
                f"{detail}\n"
                "请重新执行生成命令，或检查模型是否严格遵守 Prompt。"
            )

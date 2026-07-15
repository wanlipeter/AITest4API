from pathlib import Path

from ..providers.config import AiProviderConfig, normalize_provider_name
from ..providers.openai_compatible_provider import OpenAICompatibleProvider


class ResultAnalysisWorkflow:
    """测试结果到 AI 分析报告的最小链路。"""

    def run(self, result_path: Path, output_path: Path, provider: str) -> Path:
        provider = normalize_provider_name(provider)
        if provider not in {"deepseek", "volcengine", "qwen"}:
            raise ValueError(f"当前不支持 {provider} 分析执行结果")

        config = AiProviderConfig.load(Path.cwd())
        analysis = OpenAICompatibleProvider(config.chat_settings(provider)).analyze_result(result_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(analysis, encoding="utf-8")
        return output_path

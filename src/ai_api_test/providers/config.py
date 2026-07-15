import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChatProviderSettings:
    provider: str
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class AiProviderConfig:
    provider: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    volcengine_api_key: str
    volcengine_base_url: str
    volcengine_model: str
    qwen_api_key: str
    qwen_base_url: str
    qwen_model: str

    @classmethod
    def load(cls, project_dir: Path) -> "AiProviderConfig":
        _load_env_files(project_dir)
        return cls(
            provider=os.getenv("AI_PROVIDER", "local").strip().lower(),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            volcengine_api_key=os.getenv("VOLCENGINE_API_KEY", "").strip(),
            volcengine_base_url=os.getenv(
                "VOLCENGINE_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ).strip(),
            volcengine_model=os.getenv("VOLCENGINE_MODEL", "").strip(),
            qwen_api_key=os.getenv("QWEN_API_KEY", "").strip(),
            qwen_base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            qwen_model=os.getenv("QWEN_MODEL", "qwen-plus").strip(),
        )

    def chat_settings(self, provider: str) -> ChatProviderSettings:
        provider = normalize_provider_name(provider)
        if provider == "deepseek":
            return ChatProviderSettings(
                provider=provider,
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                model=self.deepseek_model,
            )
        if provider == "volcengine":
            return ChatProviderSettings(
                provider=provider,
                api_key=self.volcengine_api_key,
                base_url=self.volcengine_base_url,
                model=self.volcengine_model,
            )
        if provider == "qwen":
            return ChatProviderSettings(
                provider=provider,
                api_key=self.qwen_api_key,
                base_url=self.qwen_base_url,
                model=self.qwen_model,
            )

        raise ValueError(f"不支持的 AI Provider: {provider}")


def normalize_provider_name(provider: str) -> str:
    aliases = {
        "deepseek": "deepseek",
        "volcengine": "volcengine",
        "volcano": "volcengine",
        "ark": "volcengine",
        "qwen": "qwen",
        "qianwen": "qwen",
        "tongyi": "qwen",
    }
    key = provider.strip().lower()
    return aliases.get(key, key)


def _load_env_files(project_dir: Path) -> None:
    for directory in _candidate_dirs(project_dir):
        _load_dotenv(directory / ".env")
        _load_dotenv(directory / ".env.example")


def _candidate_dirs(project_dir: Path) -> list[Path]:
    current_file = Path(__file__).resolve()
    package_project_dir = current_file.parents[3]
    candidates = [project_dir.resolve(), package_project_dir]

    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

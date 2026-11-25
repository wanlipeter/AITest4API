import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .models import Profile, ResponseEnvelope

DEFAULT_PROFILE_NAME = "default"


def load_profile(name: str = DEFAULT_PROFILE_NAME, profile_dir: Path | None = None) -> Profile:
    """加载 profiles/<name>/profile.json；换公司只需新增目录和配置，不改框架代码。"""
    base_dir = (profile_dir or Path.cwd() / "profiles").resolve()
    profile_path = base_dir / name / "profile.json"
    if not profile_path.exists():
        raise ValueError(
            f"找不到 profile 配置: {profile_path}\n"
            f"请在 profiles/{name}/profile.json 写入响应包络约定，或使用 --profile default。"
        )

    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"profile 文件根节点必须是 JSON 对象: {profile_path}")

    envelope_raw = raw.get("response_envelope", {})
    if not isinstance(envelope_raw, dict):
        raise ValueError("profile.response_envelope 必须是 JSON 对象。")

    valid_names = {item.name for item in fields(ResponseEnvelope)}
    unknown = set(envelope_raw) - valid_names
    if unknown:
        raise ValueError(
            f"profile.response_envelope 包含未知字段: {', '.join(sorted(unknown))}。\n"
            f"允许的字段: {', '.join(sorted(valid_names))}。"
        )

    return Profile(
        name=str(raw.get("name") or name),
        response_envelope=ResponseEnvelope(**envelope_raw),
    )

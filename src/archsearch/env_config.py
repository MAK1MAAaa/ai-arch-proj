"""Read an explicitly selected dotenv file without interpolation, logging or side effects."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import SecretStr

from archsearch.llm import (
    MAX_API_KEYS,
    ConfigApply,
    ConfigDraft,
    LlmProvider,
    canonical_base_url,
)

MAX_ENV_BYTES = 256 * 1024
_KNOWN = {
    "provider", "base_url", "api_keys", "apikey", "model",
    "ARCHSEARCH_LLM_PROVIDER", "ARCHSEARCH_LLM_BASE_URL", "ARCHSEARCH_LLM_API_KEYS",
    "ARCHSEARCH_LLM_API_KEY", "ARCHSEARCH_LLM_MODEL",
}
_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


class EnvConfigError(ValueError):
    """A safe dotenv error whose message never contains configuration values."""


@dataclass(frozen=True)
class EnvLlmConfig:
    provider: LlmProvider
    base_url: str
    model: str
    api_keys: tuple[SecretStr, ...] = field(default=(), repr=False)


def _value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("'"):
        end = value.find("'", 1)
        if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith("#")):
            raise EnvConfigError("LLM环境配置的引号格式无效。")
        return value[1:end]
    if value.startswith(('"', '[')):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
        except (ValueError, RecursionError):
            raise EnvConfigError("LLM环境配置的JSON或引号格式无效。") from None
        tail = value[end:].strip()
        if tail and not tail.startswith("#"):
            raise EnvConfigError("LLM环境配置行包含无效的附加内容。")
        if value.startswith('"'):
            if not isinstance(parsed, str):
                raise EnvConfigError("LLM环境配置值格式无效。")
            return parsed
        return value[:end]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _file_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            raise EnvConfigError(f"LLM环境配置第{number}行格式无效。")
        key, raw_value = match.groups()
        if key not in _KNOWN:
            continue
        if key in result:
            raise EnvConfigError(f"LLM环境配置第{number}行重复定义变量。")
        result[key] = _value(raw_value)
    return result


def parse_env_config(
    text: str, environ: Mapping[str, str] | None = None,
) -> EnvLlmConfig | None:
    """Canonical process variables override the file; explicit lists override legacy singles."""
    try:
        encoded_size = len(text.encode("utf8"))
    except UnicodeError:
        raise EnvConfigError("LLM环境配置文件须使用UTF-8编码。") from None
    if encoded_size > MAX_ENV_BYTES:
        raise EnvConfigError("LLM环境配置文件超过大小限制。")
    values = _file_values(text)
    process = os.environ if environ is None else environ

    def choose(canonical: str, lower: str, default: str = "") -> str:
        if canonical in process:
            return process[canonical]
        return values.get(canonical, values.get(lower, default))

    if "ARCHSEARCH_LLM_API_KEYS" in process:
        raw_keys, plural = process["ARCHSEARCH_LLM_API_KEYS"], True
    elif "ARCHSEARCH_LLM_API_KEY" in process:
        raw_keys, plural = process["ARCHSEARCH_LLM_API_KEY"], False
    elif "ARCHSEARCH_LLM_API_KEYS" in values or "api_keys" in values:
        raw_keys = values.get("ARCHSEARCH_LLM_API_KEYS", values.get("api_keys", ""))
        plural = True
    else:
        raw_keys = values.get("ARCHSEARCH_LLM_API_KEY", values.get("apikey", ""))
        plural = False
    try:
        decoded = json.loads(raw_keys) if plural and raw_keys else ([] if plural else raw_keys)
    except (ValueError, RecursionError):
        raise EnvConfigError("api_keys必须是严格JSON字符串列表。") from None
    rows = decoded if plural else ([decoded] if decoded else [])
    if (not isinstance(rows, list) or len(rows) > MAX_API_KEYS
            or any(not isinstance(row, str) or not row.strip() for row in rows)):
        raise EnvConfigError("api_keys必须是最多8个非空字符串的JSON列表。")
    if len(set(rows)) != len(rows):
        raise EnvConfigError("api_keys不能包含重复密钥。")
    model = choose("ARCHSEARCH_LLM_MODEL", "model").strip(" ")
    if not rows and not model:
        return None
    provider = choose("ARCHSEARCH_LLM_PROVIDER", "provider", "openai").strip(" ")
    base = choose("ARCHSEARCH_LLM_BASE_URL", "base_url").strip(" ")
    try:
        checked = ConfigApply.model_validate({
            "provider": provider, "base_url": base, "model": model, "expected_revision": 0,
        })
        canonical = canonical_base_url(checked.base_url)
        keys = []
        for row in rows:
            key = ConfigDraft(
                provider=checked.provider, base_url=canonical, api_key=SecretStr(row),
            ).api_key
            assert key is not None
            if row in canonical or row in checked.model:
                raise EnvConfigError("密钥必须放在独立列表中。")
            keys.append(key)
        if checked.provider == "ollama" and keys:
            raise EnvConfigError("本地Ollama配置不使用API密钥列表。")
        return EnvLlmConfig(checked.provider, canonical, checked.model, tuple(keys))
    except ValueError:
        raise EnvConfigError("LLM环境配置无效，请检查服务地址、模型和密钥列表。") from None


def load_env_config(
    path: Path, environ: Mapping[str, str] | None = None,
) -> EnvLlmConfig | None:
    """Only serve opts in; importing modules and create_app never read dotenv implicitly."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_ENV_BYTES + 1)
    except FileNotFoundError:
        return parse_env_config("", environ)
    except OSError:
        raise EnvConfigError("无法读取LLM环境配置文件。") from None
    if len(raw) > MAX_ENV_BYTES:
        raise EnvConfigError("LLM环境配置文件超过大小限制。")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise EnvConfigError("LLM环境配置文件须使用UTF-8编码。") from None
    return parse_env_config(text, environ)

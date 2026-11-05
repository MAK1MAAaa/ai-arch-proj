"""Check explicit dotenv loading with synthetic credentials and no upstream traffic."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from archsearch.env_config import MAX_ENV_BYTES, EnvConfigError, load_env_config, parse_env_config
from archsearch.llm import LlmManager

KEYS = ("fixture-env-key-one-not-real", "fixture-env-key-two-not-real")
BASE = "https://api.example.test/v1"


def env_text(*, keys: tuple[str, ...] = KEYS, model: str = "qwen-fixture") -> str:
    return (f"provider=openai\nbase_url='{BASE}'\n"
            f"api_keys='{json.dumps(keys)}'\nmodel='{model}'\n")


def tokens(config: Any) -> list[str]:
    return [key.get_secret_value() for key in config.api_keys]


def test_lowercase_list_and_old_single_key_are_both_supported_without_repr_leaks() -> None:
    config = parse_env_config(env_text(), {})
    assert config is not None and config.provider == "openai"
    assert config.base_url == BASE and config.model == "qwen-fixture"
    assert tokens(config) == list(KEYS)
    assert all(key not in repr(config) for key in KEYS)
    old = parse_env_config(f"base_url={BASE}\napikey='{KEYS[0]}'\nmodel=qwen-fixture", {})
    assert old is not None and tokens(old) == [KEYS[0]]


def test_explicit_empty_list_does_not_fall_back_to_legacy_single_key() -> None:
    config = parse_env_config(
        f"base_url={BASE}\napi_keys=[]\napikey='{KEYS[0]}'\nmodel=qwen-fixture", {},
    )
    assert config is not None and config.api_keys == ()


def test_process_canonical_fields_override_file_aliases_without_modifying_environment() -> None:
    process = {
        "ARCHSEARCH_LLM_PROVIDER": "openai", "ARCHSEARCH_LLM_BASE_URL": "https://override.test/v1",
        "ARCHSEARCH_LLM_API_KEYS": json.dumps([KEYS[1]]), "ARCHSEARCH_LLM_MODEL": "override-model",
    }
    before = dict(process)
    config = parse_env_config(env_text(), process)
    assert config is not None and config.base_url == "https://override.test/v1"
    assert config.model == "override-model" and tokens(config) == [KEYS[1]]
    assert process == before


def test_file_canonical_aliases_and_new_plural_take_precedence_over_old_singles() -> None:
    text = env_text(keys=(KEYS[0],)) + (
        "ARCHSEARCH_LLM_BASE_URL=https://canonical.test/v1\n"
        "ARCHSEARCH_LLM_MODEL=canonical-model\n"
        f"ARCHSEARCH_LLM_API_KEY='{KEYS[1]}'\n"
    )
    config = parse_env_config(text, {})
    assert config is not None and config.base_url == "https://canonical.test/v1"
    assert config.model == "canonical-model" and tokens(config) == [KEYS[0]]
    override = parse_env_config(text, {"ARCHSEARCH_LLM_API_KEY": KEYS[1]})
    assert override is not None and tokens(override) == [KEYS[1]]


def test_example_and_unrelated_empty_configuration_do_not_activate_remote_service() -> None:
    assert parse_env_config(Path(".env.example").read_text("utf8"), {}) is None
    assert parse_env_config("unrelated=keep\nbase_url=https://api.example.com/v1", {}) is None
    assert parse_env_config("", {}) is None


def test_dotenv_quoting_comments_and_export_preserve_literal_values_without_expansion() -> None:
    content = (
        f"# comment\nexport base_url='{BASE}' # safe comment\n"
        f"api_keys={json.dumps([KEYS[0]])} # list comment\n"
        'model="${NOT_EXPANDED}"\n'
    )
    config = parse_env_config(content, {})
    assert config is not None and config.model == "${NOT_EXPANDED}"
    assert tokens(config) == [KEYS[0]]
    double_encoded = json.dumps(json.dumps([KEYS[1]]))
    double = parse_env_config(f"base_url={BASE}\napi_keys={double_encoded}\nmodel=x", {})
    assert double is not None and tokens(double) == [KEYS[1]]


@pytest.mark.parametrize(
    "value",
    ["not-json", '"single"', "null", "{}", "[1]", "[true]", '[""]', '[" "]',
     json.dumps([KEYS[0], KEYS[0]]), json.dumps([f"fixture-{i}" for i in range(9)]),
     json.dumps([KEYS[0] + "\n"]), json.dumps([KEYS[0] * 1000])],
)
def test_invalid_pools_fail_safely_without_echoing_secret_values(value: str) -> None:
    with pytest.raises(EnvConfigError) as caught:
        parse_env_config(f"base_url={BASE}\napi_keys={value}\nmodel=x", {})
    assert all(key not in str(caught.value) for key in KEYS)


@pytest.mark.parametrize(
    "text",
    [
        "model='unterminated", "model=x\nmodel=y", "api_keys 'missing equals'",
        'model="x" trailing', "provider=unknown\nbase_url=https://example.test\nmodel=x",
        f"base_url='https://example.test?key={KEYS[0]}'\nmodel=x",
        f"provider=ollama\nbase_url=http://127.0.0.1:11434\napi_keys='{json.dumps(KEYS)}'\nmodel=x",
        "base_url='file:///invalid'\nmodel=x", "base_url='https://example.test'\nmodel='bad\u200b'",
    ],
)
def test_bad_file_fields_have_safe_errors(text: str) -> None:
    with pytest.raises(EnvConfigError) as caught:
        parse_env_config(text, {})
    assert all(key not in str(caught.value) for key in KEYS)


def test_explicit_file_read_is_bounded_utf8_and_missing_files_stay_optional(tmp_path: Path) -> None:
    source = tmp_path / "fixture.env"
    assert load_env_config(source, {}) is None
    source.write_bytes(b"\xef\xbb\xbf" + env_text().encode("utf8"))
    assert load_env_config(source, {}) is not None
    source.write_bytes(b"\xff")
    with pytest.raises(EnvConfigError, match="UTF-8"):
        load_env_config(source, {})
    source.write_bytes(b"x" * (MAX_ENV_BYTES + 1))
    with pytest.raises(EnvConfigError, match="大小"):
        load_env_config(source, {})


def test_seeded_manager_is_offline_and_only_exposes_safe_pool_metadata() -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("environment seeding must not contact an upstream")

    config = parse_env_config(env_text(), {})
    manager = LlmManager.from_environment(config, transport=httpx.MockTransport(forbidden))
    public = manager.public_config()
    assert public.model == "qwen-fixture" and public.revision == 1
    assert public.key_count == 2 and public.active_key_index is None
    assert public.config_source == "env"
    assert all(key not in public.model_dump_json() for key in KEYS)
    assert tokens(manager.snapshot(1)) == list(KEYS)


def test_clear_only_affects_runtime_and_reloading_explicit_file_restores_it(tmp_path: Path) -> None:
    from archsearch.llm import ConfigApply

    source = tmp_path / "fixture.env"
    source.write_text(env_text(), encoding="utf8")
    original = source.read_bytes()
    manager = LlmManager.from_environment(load_env_config(source, {}))
    manager.apply(ConfigApply(
        provider="openai", base_url=BASE, model="", api_key="", expected_revision=1,
    ))
    assert manager.public_config().key_count == 0 and not manager.public_config().model
    assert source.read_bytes() == original
    restarted = LlmManager.from_environment(load_env_config(source, {}))
    assert restarted.public_config().key_count == 2
    assert restarted.public_config().model == "qwen-fixture"


def test_only_serve_loads_the_explicit_cwd_file_and_does_not_print_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    import uvicorn

    from archsearch import api, cli, env_config

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(env_text(), encoding="utf8")
    loader = env_config.load_env_config
    reads: list[Path] = []

    def isolated(path: Path) -> Any:
        reads.append(path)
        return loader(path, {})

    captured: dict[str, Any] = {}

    def app(home: Path, *, llm: LlmManager) -> str:
        captured["llm"] = llm
        return "fixture-app"

    def run(application: Any, **kwargs: Any) -> None:
        captured["application"] = application

    monkeypatch.setattr(env_config, "load_env_config", isolated)
    monkeypatch.setattr(api, "create_app", app)
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(sys, "argv", ["archsearch", "serve"])
    cli.main()
    assert reads == [tmp_path / ".env"]
    assert captured["application"] == "fixture-app"
    assert captured["llm"].public_config().key_count == 2
    output = capsys.readouterr()
    assert all(key not in output.out + output.err for key in KEYS)


def test_help_and_prepare_never_load_dotenv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from archsearch import cli, env_config

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("non-serve commands must not read dotenv")

    monkeypatch.setattr(env_config, "load_env_config", forbidden)
    monkeypatch.setattr(sys, "argv", ["archsearch", "--help"])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 0
    monkeypatch.setattr(cli, "load_corpus", lambda: [])
    monkeypatch.setattr(cli, "prepare_index", lambda *args: {"site_ids": []})
    monkeypatch.setattr(sys, "argv", ["archsearch", "prepare"])
    cli.main()
    assert '"ready": true' in capsys.readouterr().out

"""Exercise provider configuration and enhanced search without a network or model."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from archsearch.api import create_app
from archsearch.domain import Site
from archsearch.llm import LlmManager

SECRET = "fixture-key-never-public-123"
MODEL = "qwen3.5:2b"


def manager_fixture(*, fail_chat: bool = False) -> tuple[LlmManager, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json={"models": [{"name": MODEL, "size": 2048}]})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        if fail_chat:
            return httpx.Response(500, json={"error": "untrusted upstream " + SECRET})
        content = json.dumps({"queries": ["bath"]})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(200, json={"message": {"content": content}})

    return LlmManager(transport=httpx.MockTransport(upstream)), calls


def configure(client: TestClient, *, api: bool = False) -> dict[str, object]:
    draft: dict[str, object] = {
        "provider": "openai" if api else "ollama",
        "base_url": "https://provider.example/v1" if api else "http://127.0.0.1:11434",
    }
    if api:
        draft["api_key"] = SECRET
    discovered = client.post("/api/llm/models", json=draft)
    assert discovered.status_code == 200 and discovered.json()["models"][0]["id"] == MODEL
    applied = client.post(
        "/api/llm/config",
        json={
            **draft,
            "model": MODEL,
            "expected_revision": 0,
        },
    )
    assert applied.status_code == 200 and applied.json()["revision"] == 1
    assert SECRET not in discovered.text + applied.text
    return applied.json()


def test_disabled_default_has_no_llm_network_or_changes_to_base_search(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        config = client.get("/api/llm/config").json()
        assert config == {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "",
            "revision": 0,
            "has_api_key": False,
            "key_count": 0,
            "active_key_index": None,
            "config_source": "default",
        }
        assert client.get("/api/status").json()["llm"] == config
        result = client.post("/api/search", json={"query": "bath", "mode": "bm25"})
        assert result.status_code == 200 and result.json()["enhancement"] is None
        assert result.json()["results"][0]["site"]["id"] == "1"
    assert calls == []


@pytest.mark.parametrize("api", [False, True])
def test_real_provider_contract_drives_fusion_without_modifying_evidence(
    tmp_path: Path,
    sample_sites: list[Site],
    api: bool,
) -> None:
    manager, calls = manager_fixture()
    before = sample_sites[1].model_dump(mode="json")
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        config = configure(client, api=api)
        assert config["has_api_key"] is api
        response = client.post(
            "/api/search",
            json={
                "query": "沐浴",
                "mode": "bm25",
                "type": "bath",
                "enhance": True,
                "llm_revision": config["revision"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["site"] == before and data["total_candidates"] == 1
        assert data["enhancement"]["applied"] is True
        assert data["enhancement"]["queries"] == ["沐浴", "bath"]
        assert data["enhancement"]["model"] == MODEL
        assert data["enhancement"]["ranking_method"] == "rrf"
        assert SECRET not in response.text + client.get("/api/status").text
    assert len(calls) == 2
    payload = json.loads(calls[-1].content)
    assert payload["model"] == MODEL and payload["stream"] is False
    assert "Fixture Author" not in str(payload) and "Excavated" not in str(payload)
    assert (calls[-1].headers.get("authorization") == "Bearer " + SECRET) is api


def test_unavailable_rewrite_returns_explicit_original_query_results(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    manager, _ = manager_fixture(fail_chat=True)
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        config = configure(client)
        response = client.post(
            "/api/search",
            json={
                "query": "bath",
                "mode": "bm25",
                "enhance": True,
                "llm_revision": config["revision"],
            },
        )
        assert response.status_code == 200 and response.json()["results"]
        metadata = response.json()["enhancement"]
        assert not metadata["applied"] and metadata["queries"] == ["bath"]
        assert metadata["ranking_method"] == "original" and "原查询" in metadata["reason"]
        assert SECRET not in response.text


def test_missing_config_stale_revision_and_missing_semantic_model_are_explicit(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        body = {"query": "bath", "mode": "bm25", "enhance": True, "llm_revision": 0}
        assert client.post("/api/search", json=body).status_code == 503
        assert calls == []
        configure(client)
        assert client.post("/api/search", json=body).status_code == 409
        assert (
            client.post(
                "/api/search", json={**body, "mode": "semantic", "llm_revision": 1}
            ).status_code
            == 503
        )
        assert len(calls) == 1
        assert (
            client.post(
                "/api/search", json={**body, "type": "invented", "llm_revision": 1}
            ).status_code
            == 422
        )
        assert len(calls) == 1


def test_clear_configuration_drops_key_without_needing_working_upstream_authentication(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        configure(client, api=True)
        response = client.post(
            "/api/llm/config",
            json={
                "provider": "openai",
                "base_url": "",
                "api_key": "",
                "model": "",
                "expected_revision": 1,
            },
        )
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert not response.json()["has_api_key"] and response.json()["model"] == ""
        assert len(calls) == 1 and SECRET not in client.get("/api/status").text


@pytest.mark.parametrize("endpoint", ["models", "config"])
def test_validation_errors_never_echo_secret_inputs(
    tmp_path: Path,
    sample_sites: list[Site],
    endpoint: str,
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        response = client.post(
            "/api/llm/" + endpoint,
            json={
                "provider": "invalid",
                "base_url": SECRET,
                "api_key": "\n" + SECRET,
            },
        )
        assert response.status_code == 422 and SECRET not in response.text
    assert calls == []


@pytest.mark.parametrize("origin", ["https://foreign.example", "null", "http://testserver@evil"])
def test_browser_cross_origin_config_and_enhanced_requests_are_refused(
    tmp_path: Path,
    sample_sites: list[Site],
    origin: str,
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://localhost"
    ) as client:
        draft = {"provider": "ollama", "base_url": "http://127.0.0.1:11434"}
        assert (
            client.post("/api/llm/models", json=draft, headers={"Origin": origin}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/llm/config",
                json={**draft, "model": "", "expected_revision": 0},
                headers={"Origin": origin},
            ).status_code
            == 403
        )
        configure(client)
        before = len(calls)
        assert (
            client.post(
                "/api/search",
                json={"query": "bath", "mode": "bm25", "enhance": True, "llm_revision": 1},
                headers={"Origin": origin},
            ).status_code
            == 403
        )
        assert len(calls) == before


def test_matching_untrusted_host_and_origin_cannot_access_llm_configuration(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    manager, calls = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="http://untrusted.example"
    ) as client:
        assert client.get("/api/llm/config").status_code == 403
        response = client.post(
            "/api/llm/models",
            json={
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434",
            },
            headers={"Origin": "http://untrusted.example"},
        )
        assert response.status_code == 403
        assert client.post("/api/search", json={"query": "bath", "mode": "bm25"}).status_code == 200
    assert calls == []


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8767", "https://windows.example.ts.net"])
def test_local_ip_and_tailscale_origins_can_manage_llm(
    tmp_path: Path,
    sample_sites: list[Site],
    origin: str,
) -> None:
    manager, _ = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url=origin
    ) as client:
        assert client.get("/api/llm/config").status_code == 200
        response = client.post(
            "/api/llm/models",
            json={
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434",
            },
            headers={"Origin": origin},
        )
        assert response.status_code == 200


def test_additional_host_requires_explicit_process_configuration(
    tmp_path: Path,
    sample_sites: list[Site],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHSEARCH_LLM_TRUSTED_HOSTS", "research.example")
    manager, _ = manager_fixture()
    with TestClient(
        create_app(tmp_path, sites=sample_sites, llm=manager), base_url="https://research.example"
    ) as client:
        assert client.get("/api/llm/config").status_code == 200

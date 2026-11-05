"""CLI routing uses explicit preparation and never starts a service during tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from archsearch import api, cli
from archsearch.history import HistoryUnavailable


def test_prepare_history_uses_home_without_loading_corpus_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare = Mock(return_value={"ready": True, "version": "v0.2.1", "feature_count": 4})
    monkeypatch.setattr(cli, "prepare_history", prepare)
    monkeypatch.setattr(
        cli, "load_corpus", Mock(side_effect=AssertionError("not a search prepare"))
    )
    monkeypatch.setattr(
        cli, "prepare_index", Mock(side_effect=AssertionError("no model preparation"))
    )
    monkeypatch.setattr("sys.argv", ["archsearch", "--home", str(tmp_path), "prepare-history"])
    cli.main()
    assert json.loads(capsys.readouterr().out) == {
        "ready": True,
        "version": "v0.2.1",
        "feature_count": 4,
    }
    prepare.assert_called_once_with(tmp_path)


def test_prepare_history_failure_has_nonzero_exit_and_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "prepare_history", Mock(side_effect=HistoryUnavailable("SHA256 mismatch"))
    )
    monkeypatch.setattr("sys.argv", ["archsearch", "--home", str(tmp_path), "prepare-history"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "ArchSearch: SHA256 mismatch" in captured.err


def test_serve_stays_offline_and_does_not_prepare_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in tuple(os.environ):
        if name.startswith("ARCHSEARCH_LLM_"):
            monkeypatch.delenv(name, raising=False)
    application = object()
    create = Mock(return_value=application)
    run = Mock()
    monkeypatch.setattr(api, "create_app", create)
    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setattr(
        cli, "prepare_history", Mock(side_effect=AssertionError("must stay offline"))
    )
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setattr("sys.argv", ["archsearch", "--home", str(tmp_path), "serve"])
    cli.main()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    create.assert_called_once()
    assert create.call_args.args == (tmp_path,)
    manager = create.call_args.kwargs["llm"]
    assert manager.public_config().config_source == "default"
    assert manager.public_config().key_count == 0 and not manager.public_config().model
    run.assert_called_once_with(application, host="127.0.0.1", port=8000)


def test_coverage_is_available_without_preparing_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from archsearch.coverage import CatalogueIndex

    monkeypatch.setattr(cli, "load_corpus", Mock(return_value=[]))
    monkeypatch.setattr(cli, "prepare_index", Mock(side_effect=AssertionError("no model")))
    monkeypatch.setattr("sys.argv", ["archsearch", "coverage"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 0 and result["countries"] == []
    assert result["chronology"]["not_reviewed"] == 0
    assert CatalogueIndex([], "fixture").coverage().total == 0


def test_evaluate_passes_the_selected_global_query_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archsearch import evaluation

    run = Mock(return_value={"metrics": None})
    monkeypatch.setattr(evaluation, "evaluate_corpus", run)
    queries = tmp_path / "queries-global.json"
    monkeypatch.setattr("sys.argv", [
        "archsearch", "--home", str(tmp_path), "evaluate", "--queries", str(queries)
    ])
    cli.main()
    run.assert_called_once_with(
        tmp_path, tmp_path / "reports" / "evaluation.json", None, queries=queries
    )

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
    create.assert_called_once_with(tmp_path)
    run.assert_called_once_with(application, host="127.0.0.1", port=8000)

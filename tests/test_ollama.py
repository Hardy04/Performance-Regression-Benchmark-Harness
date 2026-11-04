"""Tests for the Ollama proposer (HTTP mocked: no Ollama install needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from click.testing import CliRunner

from benchmark_harness.agent import Attempt, OllamaProposer, make_proposer
from benchmark_harness.cli import cli


def _reply(text: str) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {"message": {"role": "assistant", "content": text}}
    return r


def test_proposes_from_ollama_reply() -> None:
    with patch("requests.post", return_value=_reply("Use a set.\n```python\nprint(1)\n```")) as post:
        p = OllamaProposer(model="m", host="localhost:1234").propose("print(0)", "python x.py", [])
    assert p is not None and p.source == "print(1)\n" and p.rationale == "Use a set."
    assert post.call_args.args[0] == "http://localhost:1234/api/chat"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "m" and body["stream"] is False


def test_history_is_sent_to_model() -> None:
    hist = [Attempt(1, "try X", False, "stdout differs from the original", output_matches=False)]
    with patch("requests.post", return_value=_reply("no code here")) as post:
        assert OllamaProposer().propose("print(0)", "python x.py", hist) is None
    assert "try X" in post.call_args.kwargs["json"]["messages"][1]["content"]


def test_unreachable_server_gives_actionable_error() -> None:
    with patch("requests.post", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(RuntimeError, match="ollama pull"):
            OllamaProposer(model="qwen2.5-coder:7b").propose("x", "y", [])


def test_factory_and_cli_surface_error_cleanly(tmp_path: Path) -> None:
    assert isinstance(make_proposer("ollama"), OllamaProposer)
    f = tmp_path / "w.py"
    f.write_text("print(1)\n")
    with patch("requests.post", side_effect=requests.ConnectionError("refused")):
        res = CliRunner().invoke(cli, ["optimize", str(f), "-c", f"python {f.as_posix()}",
                                       "--proposer", "ollama", "-n", "2", "-w", "0"])
    assert res.exit_code == 1 and "Cannot reach Ollama" in res.output
    assert f.read_text() == "print(1)\n"  # target left untouched

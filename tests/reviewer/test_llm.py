from pathlib import Path

import pytest

from reviewer import llm


def test_dotenv_fills_missing_variables_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nANTHROPIC_API_KEY=sk-from-file\nANTHROPIC_WORKSPACE_ID='ws-1'\nEMPTY=\n\n"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws-from-shell")
    monkeypatch.delenv("EMPTY", raising=False)
    loaded = llm.load_dotenv(env)
    assert loaded == {"ANTHROPIC_API_KEY": "sk-from-file"}
    assert llm.os.environ["ANTHROPIC_API_KEY"] == "sk-from-file"
    assert llm.os.environ["ANTHROPIC_WORKSPACE_ID"] == "ws-from-shell"
    assert "EMPTY" not in llm.os.environ


def test_dotenv_missing_file_is_fine(tmp_path: Path) -> None:
    assert llm.load_dotenv(tmp_path / ".env") == {}


def test_client_without_a_key_explains_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "DOTENV_PATH", tmp_path / ".env")
    with pytest.raises(llm.MissingApiKeyError, match=r"\.env"):
        llm.client()

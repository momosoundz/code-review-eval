"""The one place that builds the Anthropic client. Both the reviewer and the judge use it."""

import os
from pathlib import Path

import anthropic

DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class MissingApiKeyError(RuntimeError):
    """No API key in the environment or in the repository's ``.env``."""


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Read ``KEY=value`` lines from ``path`` into the environment, never overriding a set one.

    Blank lines, comments and empty values are skipped; single or double quotes around a value
    are removed. Returns what was set. A missing file sets nothing. ``path`` defaults to the
    repository's ``.env``.
    """
    path = DOTENV_PATH if path is None else path
    if not path.exists():
        return {}
    loaded: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def client() -> anthropic.Anthropic:
    """Anthropic client; loads ``.env`` from the repo root when the key is not in the environment.

    Raises:
        MissingApiKeyError: When no key is found either place.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        msg = (
            f"ANTHROPIC_API_KEY is not set and {DOTENV_PATH} does not provide it; "
            "copy .env.example to .env and add the key (make score needs none)"
        )
        raise MissingApiKeyError(msg)
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(default_headers=headers)

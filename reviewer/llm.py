"""The one place that builds the Anthropic client. Both the reviewer and the judge use it."""

import os

import anthropic


def client() -> anthropic.Anthropic:
    """Anthropic client; a user-scoped key needs ``ANTHROPIC_WORKSPACE_ID`` sent as a header."""
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(default_headers=headers)

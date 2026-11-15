# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Unit/UI tests must not inherit credentials from local server secrets."""
import pytest


@pytest.fixture(autouse=True)
def no_ambient_api_keys(monkeypatch, tmp_path):
    from engine import fetch_nass
    monkeypatch.setattr(fetch_nass, "SECRETS_PATH", tmp_path / "no-secrets.toml")
    # Empty (rather than missing) prevents app.py's setdefault from importing real
    # credentials during Streamlit AppTest. A provider test can override explicitly.
    monkeypatch.setenv('NASS_API_KEY', '')
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')

"""Shared helpers for the Streamlit pages: bootstrap, secrets, eval report loading."""

import json
import os
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = PROJECT_ROOT / "evals" / "faithfulness_results.json"


def _bridge_secrets() -> None:
    """Expose Streamlit Cloud secrets as env vars (the agent reads os.environ)."""
    try:
        for key in ("OPENAI_API_KEY",):
            if key in st.secrets and key not in os.environ:
                os.environ[key] = str(st.secrets[key])
    except Exception:  # no secrets.toml locally is fine
        pass


@st.cache_resource
def bootstrap() -> None:
    """Seed the SQLite circuit catalog on first boot (the .db is gitignored)."""
    _bridge_secrets()
    from src.telemetry_db import DB_PATH, initialize_telemetry_db

    if not Path(DB_PATH).exists():
        initialize_telemetry_db()

    # The Chroma index is gitignored, so a fresh deploy builds it once (20 small SOPs).
    chroma = PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")
    if os.environ.get("OPENAI_API_KEY") and not (chroma / "chroma.sqlite3").exists():
        from src.rag.indexer import build_vector_index

        build_vector_index(force_rebuild=True)


def live_agent_available() -> tuple[bool, str]:
    """Live drafting needs an OpenAI key and a built Chroma index."""
    _bridge_secrets()
    if not os.environ.get("OPENAI_API_KEY"):
        return False, "No `OPENAI_API_KEY` configured, so live drafting is disabled."
    chroma = PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")
    if not (chroma / "chroma.sqlite3").exists():
        return False, "Vector index not built. Run the indexer to enable live drafting."
    return True, ""


@st.cache_data(ttl=60)
def load_faithfulness_report() -> dict | None:
    if not RESULTS_PATH.exists():
        return None
    return json.loads(RESULTS_PATH.read_text())

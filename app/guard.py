"""Abuse and cost guard for the public demo's live (OpenAI-backed) console.

Layers, cheapest first:
  1. Kill switch        DEMO_LIVE_ENABLED=false turns live drafting off for everyone.
  2. Access code        optional DEMO_ACCESS_CODE; unset means the demo is open to everyone.
  3. Per-session cap    DEMO_SESSION_LIMIT drafts per browser session.
  4. Cooldown           DEMO_COOLDOWN_SECONDS between drafts in one session.
  5. Per-client cap     DEMO_CLIENT_DAILY_LIMIT per day per client IP (best effort).
  6. Global daily cap   DEMO_DAILY_LIMIT drafts per UTC day across all visitors.
  7. Input cap          DEMO_MAX_INPUT_CHARS on free-text telemetry.

Counters live in process memory, so a restart resets them. The hard backstop is a
monthly budget limit on the OpenAI project that owns the key (see README).
"""

from __future__ import annotations

import datetime as dt
import hmac
import os
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    session: int = 5
    cooldown_s: int = 10
    client_daily: int = 10
    global_daily: int = 100
    max_input_chars: int = 500


def limits_from(get) -> Limits:
    """Build Limits from a `get(name, default)` callable (secrets/env)."""
    d = Limits()

    def num(name: str, default: int) -> int:
        try:
            return max(0, int(get(name, default)))
        except (TypeError, ValueError):
            return default

    return Limits(
        session=num("DEMO_SESSION_LIMIT", d.session),
        cooldown_s=num("DEMO_COOLDOWN_SECONDS", d.cooldown_s),
        client_daily=num("DEMO_CLIENT_DAILY_LIMIT", d.client_daily),
        global_daily=num("DEMO_DAILY_LIMIT", d.global_daily),
        max_input_chars=num("DEMO_MAX_INPUT_CHARS", d.max_input_chars),
    )


class UsageLedger:
    """Thread-safe daily counters shared by every session in this process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day = ""
        self._global = 0
        self._clients: dict[str, int] = {}

    def _roll(self, today: str) -> None:
        if today != self._day:
            self._day, self._global, self._clients = today, 0, {}

    def try_consume(self, client: str, limits: Limits, today: str | None = None) -> str | None:
        """Reserve one draft. Returns None on success, else a user-facing refusal."""
        today = today or dt.datetime.now(dt.UTC).date().isoformat()
        with self._lock:
            self._roll(today)
            if self._global >= limits.global_daily:
                return "The demo's daily live-draft budget is used up. It resets at 00:00 UTC."
            if self._clients.get(client, 0) >= limits.client_daily:
                return f"Daily limit of {limits.client_daily} live drafts reached for your network."
            self._global += 1
            self._clients[client] = self._clients.get(client, 0) + 1
            return None

    def refund(self, client: str) -> None:
        """Give the slot back when the call failed before reaching OpenAI."""
        with self._lock:
            self._global = max(0, self._global - 1)
            if self._clients.get(client, 0) > 0:
                self._clients[client] -= 1

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self._global, len(self._clients)


def check_session(used: int, last_ts: float | None, limits: Limits, now: float | None = None) -> str | None:
    """Per-session checks (cap + cooldown). Pure function so it is unit-testable."""
    now = time.monotonic() if now is None else now
    if used >= limits.session:
        return f"Session limit of {limits.session} live drafts reached. Reload later to continue."
    if last_ts is not None and now - last_ts < limits.cooldown_s:
        wait = int(limits.cooldown_s - (now - last_ts)) + 1
        return f"Please wait {wait}s before the next draft."
    return None


def code_matches(supplied: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(supplied.encode(), expected.encode())


def truthy(value) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


# --------------------------- Streamlit wiring ---------------------------


def _setting(name: str, default=None):
    import streamlit as st

    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def _ledger() -> UsageLedger:
    import streamlit as st

    @st.cache_resource
    def _get() -> UsageLedger:
        return UsageLedger()

    return _get()


def _client_id() -> str:
    import streamlit as st

    try:
        headers = st.context.headers
        fwd = headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    except Exception:
        pass
    return "unknown"


def live_gate() -> Limits | None:
    """Render the access gate. Returns Limits when the visitor may use live mode, else None."""
    import streamlit as st

    if not truthy(_setting("DEMO_LIVE_ENABLED", "true")):
        st.warning(
            "Live drafting is switched off right now. The Eval dashboard and Guardrail lab remain available."
        )
        return None

    limits = limits_from(_setting)
    expected = str(_setting("DEMO_ACCESS_CODE", "") or "")
    if not expected:  # open demo: caps below are the protection
        return limits

    if not st.session_state.get("live_unlocked"):
        with st.form("access"):
            code = st.text_input("Access code", type="password", help="Ask the demo owner for a code.")
            if st.form_submit_button("Unlock live drafting"):
                # Slow down guessing: 2s per attempt and 5 attempts per session.
                tries = st.session_state.get("code_tries", 0)
                if tries >= 5:
                    st.error("Too many attempts in this session.")
                else:
                    st.session_state.code_tries = tries + 1
                    time.sleep(2)
                    if code_matches(code, expected):
                        st.session_state.live_unlocked = True
                        st.rerun()
                    else:
                        st.error("Incorrect code.")
        return None
    return limits


def authorize_draft(limits: Limits, raw_text: str) -> tuple[str | None, str]:
    """Run all per-request checks. Returns (refusal_or_None, client_id)."""
    import streamlit as st

    client = _client_id()
    if len(raw_text) > limits.max_input_chars:
        return f"Telemetry text is limited to {limits.max_input_chars} characters.", client
    refusal = check_session(
        st.session_state.get("draft_count", 0), st.session_state.get("last_draft_ts"), limits
    )
    if refusal:
        return refusal, client
    refusal = _ledger().try_consume(client, limits)
    if refusal:
        return refusal, client
    st.session_state.draft_count = st.session_state.get("draft_count", 0) + 1
    st.session_state.last_draft_ts = time.monotonic()
    return None, client


def refund_draft(client: str) -> None:
    import streamlit as st

    _ledger().refund(client)
    st.session_state.draft_count = max(0, st.session_state.get("draft_count", 1) - 1)


def remaining_caption(limits: Limits) -> str:
    import streamlit as st

    left = max(0, limits.session - st.session_state.get("draft_count", 0))
    return f"{left} of {limits.session} live drafts left in this session."

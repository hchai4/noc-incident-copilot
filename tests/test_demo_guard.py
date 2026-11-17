import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from guard import Limits, UsageLedger, check_session, code_matches, limits_from, truthy


def test_session_cap_and_cooldown():
    lim = Limits(session=2, cooldown_s=10)
    assert check_session(0, None, lim) is None
    assert "wait" in check_session(1, 100.0, lim, now=103.0)
    assert check_session(1, 100.0, lim, now=111.0) is None
    assert "Session limit" in check_session(2, 0.0, lim, now=999.0)


def test_global_and_client_caps_roll_daily():
    lim = Limits(client_daily=2, global_daily=3)
    led = UsageLedger()
    assert led.try_consume("a", lim, "d1") is None
    assert led.try_consume("a", lim, "d1") is None
    assert "Daily limit" in led.try_consume("a", lim, "d1")
    assert led.try_consume("b", lim, "d1") is None
    assert "budget" in led.try_consume("c", lim, "d1")
    assert led.try_consume("c", lim, "d2") is None  # new day resets


def test_refund_returns_slot():
    lim = Limits(client_daily=1, global_daily=1)
    led = UsageLedger()
    assert led.try_consume("a", lim, "d") is None
    led.refund("a")
    assert led.try_consume("a", lim, "d") is None


def test_access_code_and_flags():
    assert code_matches("x", "x") and not code_matches("y", "x") and not code_matches("", "")
    assert truthy("true") and not truthy("false") and not truthy("0")
    assert limits_from(lambda n, d: "bad").session == 5

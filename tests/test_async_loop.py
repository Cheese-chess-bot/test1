import json
import threading
import time

import pytest

from jevloop import decisions, loop
from jevloop.limits import Limits


class Broker:
    _order_seq = 0
    is_live = True
    def get_account(self):
        return {"id": "offline-account", "status": "ACTIVE", "equity": "1000", "cash": "1000"}
    def get_position_qty(self):
        return 0
    def get_orders(self, **kwargs):
        return []
    def get_minute_bars(self, *args, **kwargs):
        return []
    def get_orderbook(self):
        return {"t": loop._iso(time.time()), "b": [{"p": 99, "s": 1}], "a": [{"p": 101, "s": 1}]}
    def get_recent_trades(self, **kwargs):
        return []
    def close(self):
        pass


class Client:
    name = "OpenRouter"
    model = "typesafe/jev-1.14"
    def close(self):
        pass


def setup_loop(monkeypatch):
    monkeypatch.setattr(loop, "client_from_env", lambda **kw: Broker())
    monkeypatch.setattr(loop, "resolve_decision_client", lambda **kw: Client())
    monkeypatch.setattr(loop, "_sleep_remaining", lambda *a: None)


def test_loop_keeps_ticking_and_hard_stop_works_while_jev_is_blocked(monkeypatch):
    setup_loop(monkeypatch)
    started, release = threading.Event(), threading.Event()
    def blocked(*a):
        started.set()
        assert release.wait(2)
        return {}, {}
    monkeypatch.setattr(decisions, "run_battery", blocked)
    original = loop.build_snapshot
    calls, flattened = [], []
    def build(**kwargs):
        calls.append(1)
        snap = original(**kwargs)
        if len(calls) == 2:
            snap["drawdown_pct"] = .1
        return snap
    monkeypatch.setattr(loop, "build_snapshot", build)
    monkeypatch.setattr(loop, "_flatten", lambda *a: flattened.append(True) or "dry: flattened")
    try:
        assert loop.run("BTC/USD", 3, False, Limits(), dry_execution=True) == 0
        assert started.is_set()
        assert len(calls) == 2 and flattened == [True]
        records = [json.loads(line) for line in loop.LOG_FILE.read_text().splitlines()]
        assert records[0]["decision_pending"]
        assert records[1]["rung"] == "kill"
        assert "timing_ms" in records[0]
    finally:
        release.set()


def test_live_provider_outage_never_uses_rules_fallback(monkeypatch):
    setup_loop(monkeypatch)
    class Unavailable:
        def __init__(self, *a): pass
        def poll(self, *a):
            return None, {"status": "unavailable", "pending": False}
        def close(self): pass
    monkeypatch.setattr(loop, "BackgroundDecisions", Unavailable)
    monkeypatch.setattr(loop, "fallback_action", lambda *a: pytest.fail("live cannot use fallback"))
    monkeypatch.setattr(loop, "_execute_action", lambda **kw: pytest.fail("live cannot submit"))
    assert loop.run("BTC/USD", 2, False, Limits(), live=True, dry_execution=True) == 0
    records = [json.loads(line) for line in loop.LOG_FILE.read_text().splitlines()]
    assert len(records) == 2
    assert all(r["late"] and r["decision_status"] == "unavailable" for r in records)


def test_live_bar_mode_refused_before_connections(monkeypatch):
    monkeypatch.setattr(loop, "client_from_env", lambda **kw: pytest.fail("must refuse first"))
    assert loop.run("BTC/USD", 1, False, Limits(), live=True, bar_seconds=1800) == 1

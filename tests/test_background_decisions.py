import threading

import pytest

from jevloop import decisions
from jevloop.client import JevThrottle, DecisionClientError, RateLimited

SNAP = {"mid": 100.0, "spread_bps": 5.0, "inventory": 0.0}


class Client:
    name = "OpenRouter"
    model = "typesafe/jev-1.14"
    def close(self):
        pass


def worker(monkeypatch, fn):
    monkeypatch.setattr(decisions, "run_battery", fn)
    return decisions.BackgroundDecisions(Client(), JevThrottle(4, 3, 15, 10))


def test_poll_returns_while_request_blocks_and_never_overlaps(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def battery(client, snap, timeout):
        calls.append(snap)
        started.set()
        assert release.wait(2)
        return {"ok": True}, {"latency_ms": 50}
    service = worker(monkeypatch, battery)
    try:
        assert service.poll(SNAP, now=0)[0] is None
        assert started.wait(1)
        assert service.poll(SNAP, now=5)[0] is None
        assert len(calls) == 1
    finally:
        release.set()
        service.wait_for_current()
        service.close()


def test_age_includes_network_time_and_expired_arrival_is_dropped(monkeypatch):
    service = worker(monkeypatch, lambda *a: ({"ok": True}, {"latency_ms": 100}))
    try:
        service.poll(SNAP, now=0)
        service.wait_for_current()
        ans, meta = service.poll(SNAP, now=7, launch=False)
        assert ans and meta["age_s"] == 7
        ans, meta = service.poll(SNAP, now=11, launch=False)
        assert ans is None and meta["status"] == "stale judgment"
    finally:
        service.close()


@pytest.mark.parametrize("changed", [dict(SNAP, mid=101), dict(SNAP, inventory=.001), dict(SNAP, spread_bps=30)])
def test_result_from_changed_state_is_not_used(monkeypatch, changed):
    service = worker(monkeypatch, lambda *a: ({"ok": True}, {}))
    try:
        service.poll(SNAP, now=0)
        service.wait_for_current()
        assert service.poll(changed, now=1, launch=False)[0] is None
    finally:
        service.close()


def test_rate_limit_backs_off_without_blocking(monkeypatch):
    def fail(*a):
        raise RateLimited("rate limited")
    service = worker(monkeypatch, fail)
    try:
        service.poll(SNAP, now=0)
        service.wait_for_current()
        ans, meta = service.poll(SNAP, now=1)
        assert ans is None and meta["status"] == "rate limited"
        assert not service.pending
        assert service.throttle.cooldown_until > 5
    finally:
        service.close()

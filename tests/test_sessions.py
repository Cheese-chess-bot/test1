"""Offline scheduling and stock execution regression tests."""
import json
import time

import pytest

from jevloop import loop
from jevloop.assets import resolve_symbol
from jevloop.execution.alpaca import AlpacaPaperClient, AlpacaAPIError, AlpacaConfigError, MarketClosedError
from jevloop.limits import Limits
from jevloop.sessions import timestamp, describe_clock, closed_wait, next_stock_bar


def clock(opened=False, next_open="2026-11-02T09:30:00-05:00", close="2026-11-02T16:00:00-05:00"):
    return dict(is_open=opened, next_open=next_open, next_close=close)


def test_exchange_schedule_handles_weekend_and_dst():
    c = clock()
    assert closed_wait(c, timestamp("2026-10-30T16:01:00-04:00")) == 30
    assert "20:00 IST" in describe_clock(c)
    assert "EST" in describe_clock(c)
    summer = clock(next_open="2026-10-21T09:30:00-04:00")
    assert "19:00 IST" in describe_clock(summer)
    assert "EDT" in describe_clock(summer)
    assert closed_wait(c, timestamp(c["next_open"]) - 7) == 7


def test_holiday_open_comes_from_broker_not_weekday_guess():
    c = clock(next_open="2026-12-28T09:30:00-05:00")
    assert "2026-12-28" in describe_clock(c)
    assert closed_wait(c, timestamp("2026-12-25T10:00:00-05:00")) == 30


def test_stock_hour_bars_anchor_to_session_and_respect_early_close():
    c = clock(True, close="2026-11-27T13:00:00-05:00")
    assert next_stock_bar(c, timestamp("2026-11-27T09:45:00-05:00"), 3600, 2) == timestamp("2026-11-27T10:30:02-05:00")
    assert next_stock_bar(c, timestamp("2026-11-27T12:30:03-05:00"), 3600, 2) == timestamp(c["next_close"])


@pytest.mark.parametrize("symbol,expected", [("AAPL", "day"), ("BTC/USD", "gtc")])
def test_fractional_limit_default_and_stock_feed(symbol, expected):
    client = AlpacaPaperClient(api_key="offline", secret_key="offline", spec=resolve_symbol(symbol))
    client.is_market_open = lambda: True
    requests = []
    client._request = lambda *a, **kw: requests.append(kw) or {}
    client.submit_limit_order("buy", .1234, 100)
    assert requests[-1]["json"]["time_in_force"] == expected
    client.get_latest_quote()
    assert requests[-1]["params"].get("feed") == ("iex" if symbol == "AAPL" else None)
    client.close()


def test_fractional_ioc_is_refused():
    client = AlpacaPaperClient(api_key="x", secret_key="y", spec=resolve_symbol("AAPL"))
    with pytest.raises(AlpacaConfigError, match="DAY"):
        client.submit_limit_order("buy", .12, 100, tif="ioc")
    client.close()


def test_malformed_clock_fails_closed():
    client = AlpacaPaperClient(api_key="x", secret_key="y", spec=resolve_symbol("AAPL"))
    client._request = lambda *a, **kw: {"is_open": "false"}
    with pytest.raises(AlpacaAPIError, match="invalid exchange clock"):
        client.is_market_open()
    client.close()


def test_close_during_rate_limit_prevents_order(monkeypatch):
    client = AlpacaPaperClient(api_key="x", secret_key="y", spec=resolve_symbol("AAPL"))
    c = clock(True)
    client._clock_cache = (time.monotonic(), c)
    client._limiter.wait = lambda: None
    monkeypatch.setattr("jevloop.execution.alpaca.time.time", lambda: timestamp(c["next_close"]))
    monkeypatch.setattr(client._session, "request", lambda *a, **kw: pytest.fail("no order after close"))
    with pytest.raises(MarketClosedError):
        client._request("POST", client.base_url + "/v2/orders", json={"side": "buy"})
    client.close()


def test_loop_waits_then_resumes_without_decisions_while_closed(monkeypatch):
    class Broker:
        _order_seq = 0
        phase = -1
        bars = 0
        def get_account(self): return {"equity": "1000"}
        def get_position_qty(self): return 0
        def get_minute_bars(self, *a):
            self.bars += 1
            return []
        def is_market_open(self):
            self.phase += 1
            return self.phase == 1
        def get_clock(self): return clock(self.phase == 1)
        def get_latest_quote(self):
            assert self.phase == 1
            return {"t": loop._iso(time.time()), "bp": 99, "ap": 101, "bs": 1, "as": 1}
        def get_recent_trades(self, **kw): return []
        def close(self): pass
    broker = Broker()
    polls = []
    class Decisions:
        def __init__(self, *a): pass
        def poll(self, *a, **kw):
            assert broker.phase == 1
            polls.append(1)
            return None, {"pending": False, "status": "waiting for Jev"}
        def close(self): pass
    monkeypatch.setattr(loop, "client_from_env", lambda **kw: broker)
    monkeypatch.setattr(loop, "BackgroundDecisions", Decisions)
    waits = []
    monkeypatch.setattr(loop, "_sleep_remaining", lambda start, seconds: waits.append(seconds))
    assert loop.run("AAPL", 3, True, Limits(), dry_execution=True) == 0
    records = [json.loads(s) for s in loop.LOG_FILE.read_text().splitlines()]
    assert [r["action"] for r in records] == ["MARKET_CLOSED", "HOLD_LATE", "MARKET_CLOSED"]
    assert records[0]["next_open"] and "IST" in records[0]["action_reason"]
    assert records[0]["unrealised_pnl_usd"] is None
    assert broker.bars == 2 and len(polls) == 1
    assert json.loads(loop.LATEST_FILE.read_text())["stats"]["late_count"] == 1


def test_market_selection_rejects_mismatch_before_credentials(monkeypatch):
    import start_jev
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: pytest.fail("no credentials on mismatch"))
    assert start_jev.main(["--mode", "full", "--market", "stocks", "--symbol", "BTC/USD"]) == 1

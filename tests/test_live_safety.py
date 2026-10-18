import time

import pytest

from jevloop.assets import resolve_symbol
from jevloop.execution.alpaca import AlpacaPaperClient, AlpacaAPIError, LIVE_TRADING_BASE_URL
from jevloop.live_guard import LiveGuard
from jevloop.limits import Limits


def account(equity=1000):
    return dict(id="fake-account", status="ACTIVE", equity=str(equity), cash="1000", non_marginable_buying_power="1000")


def test_daily_stop_survives_restart_and_recovery(tmp_path):
    guard = LiveGuard(tmp_path, account(), Limits())
    assert guard.check(account(974))
    guard.close()
    with pytest.raises(ValueError, match="latched"):
        LiveGuard(tmp_path, account(1000), Limits())


def test_account_lock_prevents_parallel_live_process(tmp_path):
    guard = LiveGuard(tmp_path, account(), Limits())
    try:
        with pytest.raises(ValueError, match="lock already exists"):
            LiveGuard(tmp_path, account(), Limits())
    finally:
        guard.close()
    guard = LiveGuard(tmp_path, account(), Limits())
    guard.close()


@pytest.mark.parametrize("bad", [dict(account(), equity="nan"), dict(account(), cash="-1"), dict(account(), trading_blocked=True)])
def test_invalid_account_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        LiveGuard(tmp_path, bad, Limits())


def broker():
    client = AlpacaPaperClient("fake", "fake", resolve_symbol("BTC/USD"),
        base_url=LIVE_TRADING_BASE_URL, _live_gate_passed=True)
    client.get_account = lambda: account()
    client.get_position_qty = lambda: 0
    client.get_orders = lambda **kw: []
    client.market_data_timestamp = time.time()
    client._request = lambda *a, **kw: {"qty": "0.2", "qty_available": "0.1", "id": "fake"}
    return client


def test_live_entry_caps_cash_and_pending_orders():
    client = broker()
    client._live_order_guard("buy", .2, 100)
    with pytest.raises(AlpacaAPIError, match="order cap"):
        client._live_order_guard("buy", .3, 100)
    client.get_orders = lambda **kw: [dict(symbol="BTCUSD", side="buy", qty=".4", limit_price="100", filled_qty="0")]
    with pytest.raises(AlpacaAPIError, match="position cap"):
        client._live_order_guard("buy", .2, 100)
    client.get_account = lambda: dict(account(), cash="10")
    with pytest.raises(AlpacaAPIError, match="available cash"):
        client._live_order_guard("buy", .2, 100)


def test_live_market_buy_and_short_sell_refused():
    client = broker()
    with pytest.raises(AlpacaAPIError, match="limit price"):
        client.submit_market_order("buy", .1)
    with pytest.raises(AlpacaAPIError, match="shorting refused"):
        client.submit_market_order("sell", .15)
    assert client.submit_market_order("sell", .1)["id"] == "fake"


def test_stale_data_checked_after_rate_limiter_before_post(monkeypatch):
    client = broker()
    client._request = AlpacaPaperClient._request.__get__(client)
    client._limiter.wait = lambda: setattr(client, "market_data_timestamp", time.time() - 6)
    monkeypatch.setattr(client._session, "request", lambda *a, **kw: pytest.fail("must not submit"))
    with pytest.raises(AlpacaAPIError, match="stale"):
        client._request("POST", client.base_url + "/v2/orders", json={"side": "buy"})

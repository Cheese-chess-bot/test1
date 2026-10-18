import os

import pytest

import start_jev
from jevloop import loop
from jevloop.client import DecisionClientError


def credentials():
    return {"OPENROUTER_API_KEY": "test-or", "ALPACA_API_KEY": "test-id", "ALPACA_SECRET_KEY": "test-secret"}


def test_collect_three_hidden_prompts(monkeypatch):
    prompts = []
    values = iter(credentials().values())
    def hidden(prompt):
        prompts.append(prompt)
        return next(values)
    monkeypatch.setattr(start_jev.getpass, "getpass", hidden)
    assert start_jev.collect_credentials() == credentials()
    assert len(prompts) == 3


def test_empty_secret_reprompts(monkeypatch):
    values = iter(["", "  ", "key"])
    monkeypatch.setattr(start_jev.getpass, "getpass", lambda _: next(values))
    assert start_jev.secret("Key: ") == "key"


def test_check_only_never_starts_loop(monkeypatch):
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: credentials())
    monkeypatch.setattr(start_jev, "verify_connections", lambda *a: None)
    monkeypatch.setattr(loop, "main", lambda _: pytest.fail("loop must not run"))
    assert start_jev.main(["--mode", "test", "--check-only", "--symbol", "BTC/USD"]) == 0


def test_failed_verification_never_starts_loop(monkeypatch):
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: credentials())
    def fail(*a):
        raise DecisionClientError("invalid key")
    monkeypatch.setattr(start_jev, "verify_connections", fail)
    monkeypatch.setattr(loop, "main", lambda _: pytest.fail("loop must not run"))
    assert start_jev.main(["--mode", "test", "--symbol", "BTC/USD"]) == 1


def test_launcher_pins_paper_and_restores_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    existing_files = set(tmp_path.rglob("*"))
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("JEV_LOOP_ALLOW_LIVE", "i-understand-the-risk")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: credentials())
    monkeypatch.setattr(start_jev, "verify_connections", lambda *a: None)
    def run(argv):
        assert "--paper" in argv and "--live" not in argv
        assert os.environ["ALPACA_BASE_URL"] == "https://paper-api.alpaca.markets"
        assert os.environ["OPENROUTER_API_KEY"] == "test-or"
        return 0
    monkeypatch.setattr(loop, "main", run)
    assert start_jev.main(["--mode", "test", "--symbol", "BTC/USD"]) == 0
    assert "OPENROUTER_API_KEY" not in os.environ
    assert os.environ["ALPACA_BASE_URL"] == "https://api.alpaca.markets"
    assert set(tmp_path.rglob("*")) == existing_files


def test_live_flag_is_rejected():
    with pytest.raises(SystemExit) as error:
        start_jev.main(["--live"])
    assert error.value.code == 2


def test_invalid_symbol_returns_clean_error():
    assert start_jev.main(["--mode", "test", "--symbol", "not a symbol"]) == 1


def test_connection_checks_use_paper_and_separate_credentials(monkeypatch):
    import requests
    from jevloop import battery
    class Account:
        status_code = 200
        def json(self):
            return {"status": "ACTIVE", "trading_blocked": False}
    def get(url, **kwargs):
        assert url == "https://paper-api.alpaca.markets/v2/account"
        assert kwargs["headers"] == {"APCA-API-KEY-ID": "test-id", "APCA-API-SECRET-KEY": "test-secret"}
        assert kwargs["allow_redirects"] is False
        return Account()
    def battery_call(client, state, timeout):
        assert client._api_key == "test-or"
        assert "test-secret" not in str(state)
        return {}, {"model": "typesafe/jev-1.14"}
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(battery, "run_battery", battery_call)
    start_jev.verify_connections(credentials(), "typesafe/jev-1.14")


def test_alpaca_rejection_stops_before_billed_call(monkeypatch):
    import requests
    from jevloop import battery
    class Denied:
        status_code = 401
    monkeypatch.setattr(requests, "get", lambda *a, **k: Denied())
    monkeypatch.setattr(battery, "run_battery", lambda *a, **k: pytest.fail("must not call Jev"))
    with pytest.raises(RuntimeError, match="401"):
        start_jev.verify_connections(credentials(), "typesafe/jev-1.14")


@pytest.mark.parametrize("mode,ticks,flag", [("test", "30", "--paper"), ("full", "0", "--paper"), ("irl", "0", "--live")])
def test_modes_route_to_correct_endpoint_and_tick_bound(monkeypatch, mode, ticks, flag):
    monkeypatch.setenv("JEV_LOOP_ALLOW_LIVE", "i-understand-the-risk")
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: credentials())
    checked = []
    monkeypatch.setattr(start_jev, "verify_connections", lambda *a: checked.append(a))
    def run(argv):
        assert flag in argv
        assert argv[argv.index("--ticks") + 1] == ticks
        expected = "https://api.alpaca.markets" if mode == "irl" else "https://paper-api.alpaca.markets"
        assert os.environ["ALPACA_BASE_URL"] == expected
        return 0
    monkeypatch.setattr(loop, "main", run)
    assert start_jev.main(["--mode", mode, "--symbol", "BTC/USD"]) == 0
    assert checked[0][2] is (mode == "irl")


def test_live_requires_opt_in_before_collecting_keys(monkeypatch):
    monkeypatch.delenv("JEV_LOOP_ALLOW_LIVE", raising=False)
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: pytest.fail("must stop first"))
    assert start_jev.main(["--mode", "irl", "--symbol", "BTC/USD"]) == 1


def test_live_env_does_not_reuse_paper_credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-id")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.delenv("ALPACA_LIVE_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_SECRET_KEY", raising=False)
    values = iter(["live-id", "live-secret"])
    monkeypatch.setattr(start_jev, "secret", lambda prompt: next(values))
    assert start_jev.collect_credentials(True, True) == dict(OPENROUTER_API_KEY="router", ALPACA_API_KEY="live-id", ALPACA_SECRET_KEY="live-secret")


def test_mode_prompt_defaults_to_test(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(start_jev, "collect_credentials", lambda *a: credentials())
    monkeypatch.setattr(start_jev, "verify_connections", lambda *a: None)
    monkeypatch.setattr(loop, "main", lambda args: 0 if args[-1] == "30" else 1)
    assert start_jev.main(["--symbol", "BTC/USD"]) == 0

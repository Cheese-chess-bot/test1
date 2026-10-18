"""Prompt locally for credentials, verify them, and launch Jev on Alpaca paper."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import warnings


def secret(prompt: str) -> str:
    # Refuse getpass's echoing fallback in terminals that cannot hide input.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        while True:
            try:
                value = getpass.getpass(prompt).strip()
            except getpass.GetPassWarning:
                raise RuntimeError("Use a normal terminal so credential input can be hidden.") from None
            if value:
                if any(c.isspace() for c in value):
                    print("Keys cannot contain whitespace. Please paste again.")
                    continue
                return value
            print("A value is required. Ctrl+C cancels.")


def collect_credentials(use_env: bool = False) -> dict[str, str]:
    prompts = {
        "OPENROUTER_API_KEY": "OpenRouter API key (hidden): ",
        "ALPACA_API_KEY": "Alpaca PAPER API key ID (hidden): ",
        "ALPACA_SECRET_KEY": "Alpaca PAPER secret key (hidden): ",
    }
    return {
        name: ((os.environ.get(name) or "").strip() if use_env else "") or secret(prompt)
        for name, prompt in prompts.items()
    }


def verify_connections(credentials: dict[str, str], model: str) -> None:
    import requests
    from jevloop.battery import run_battery
    from jevloop.client import OpenRouterDecisionClient

    try:
        response = requests.get(
            "https://paper-api.alpaca.markets/v2/account",
            headers={
                "APCA-API-KEY-ID": credentials["ALPACA_API_KEY"],
                "APCA-API-SECRET-KEY": credentials["ALPACA_SECRET_KEY"],
            },
            timeout=15,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise RuntimeError("Could not reach Alpaca paper. Check your connection and retry.") from None
    if response.status_code != 200:
        raise RuntimeError(
            f"Alpaca paper HTTP {response.status_code}. Check your PAPER key ID and secret."
        )
    try:
        account = response.json()
    except ValueError:
        raise RuntimeError("Alpaca returned invalid JSON.") from None
    if not isinstance(account, dict) or account.get("status") != "ACTIVE":
        raise RuntimeError("The Alpaca paper account is not ACTIVE.")
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise RuntimeError("Trading is blocked on this Alpaca paper account.")
    print("Alpaca paper connection verified.")
    # Synthetic state validates all seven answer schemas without placing orders.
    state = {
        "purpose": "connection test; synthetic data; no order will be submitted",
        "mid": 100.0, "spread_bps": 5.0, "imbalance": 0.0,
        "inventory": 0.0, "fill_ratio": 1.0, "reject_count": 0,
        "last_10_latencies_ms": [100.0], "last_10_slippage_bps": [0.0],
    }
    _, meta = run_battery(
        OpenRouterDecisionClient(credentials["OPENROUTER_API_KEY"], model),
        state, timeout=20,
    )
    print(f"OpenRouter Jev verified: {meta['model']}.")


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Use 0 for continuous mode or a positive tick count.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="Alpaca symbol, e.g. BTC/USD or AAPL")
    parser.add_argument("--ticks", type=nonnegative_int, default=30,
                        help="Number of ticks; default 30, 0 runs until Ctrl+C")
    parser.add_argument("--bar", choices=["1m", "5m", "15m", "30m", "1h"])
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_JEV_MODEL") or "typesafe/jev-1.14")
    parser.add_argument("--use-env", action="store_true",
                        help="Reuse credentials already in the environment; prompt for missing ones")
    parser.add_argument("--check-only", action="store_true", help="Verify connections and exit without orders")
    parser.add_argument("--dry-execution", action="store_true", help="Run with market data and Jev, without orders")
    args = parser.parse_args(argv)
    try:
        from jevloop import loop
        from jevloop.assets import UnknownSymbolError, resolve_symbol
        from jevloop.client import DecisionClientError
    except ImportError:
        print('Install dependencies first: python -m pip install -e ".[dev]"', file=sys.stderr)
        return 1

    previous: dict[str, str | None] = {}
    try:
        print("Jev via OpenRouter | Alpaca PAPER only")
        print("Keys are hidden and kept in this process only; no credentials are saved.")
        print("Verification sends one billed Jev request; a running loop makes further billed calls.")
        symbol = args.symbol or input("Symbol [BTC/USD]: ").strip() or "BTC/USD"
        symbol = resolve_symbol(symbol).symbol
        credentials = collect_credentials(args.use_env)
        verify_connections(credentials, args.model)
        if args.check_only:
            print("Checks passed. No orders submitted.")
            return 0
        settings = dict(credentials, OPENROUTER_JEV_MODEL=args.model,
                        ALPACA_BASE_URL="https://paper-api.alpaca.markets")
        previous = {name: os.environ.get(name) for name in settings}
        os.environ.update(settings)
        command = ["--paper", "--symbol", symbol, "--ticks", str(args.ticks)]
        if args.bar:
            command += ["--bar", args.bar]
        if args.dry_execution:
            command += ["--dry-execution"]
        print("Starting paper loop. Ctrl+C stops the loop; existing positions may remain open.")
        return loop.main(command)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130
    except (RuntimeError, ValueError, UnknownSymbolError, DecisionClientError) as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 1
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())

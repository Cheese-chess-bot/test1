"""Run Jev via OpenRouter: test (30 paper ticks), full (paper), or irl (live)."""
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


def collect_credentials(use_env: bool = False, live: bool = False) -> dict[str, str]:
    label = "LIVE" if live else "PAPER"
    prompts = {
        "OPENROUTER_API_KEY": "OpenRouter API key (hidden): ",
        "ALPACA_API_KEY": f"Alpaca {label} API key ID (hidden): ",
        "ALPACA_SECRET_KEY": f"Alpaca {label} secret key (hidden): ",
    }
    result = {}
    for name, prompt in prompts.items():
        env_name = name.replace("ALPACA_", "ALPACA_LIVE_") if live and name.startswith("ALPACA_") else name
        result[name] = ((os.environ.get(env_name) or "").strip() if use_env else "") or secret(prompt)
    return result


def verify_connections(credentials: dict[str, str], model: str, live: bool = False) -> None:
    import requests
    from jevloop.battery import run_battery
    from jevloop.client import OpenRouterDecisionClient

    label = "LIVE" if live else "paper"
    base = "https://api.alpaca.markets" if live else "https://paper-api.alpaca.markets"
    try:
        response = requests.get(
            f"{base}/v2/account",
            headers={
                "APCA-API-KEY-ID": credentials["ALPACA_API_KEY"],
                "APCA-API-SECRET-KEY": credentials["ALPACA_SECRET_KEY"],
            },
            timeout=15,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise RuntimeError(f"Could not reach Alpaca {label}. Check your connection and retry.") from None
    if response.status_code != 200:
        raise RuntimeError(
            f"Alpaca {label} HTTP {response.status_code}. Check your {label} key ID and secret."
        )
    try:
        account = response.json()
    except ValueError:
        raise RuntimeError("Alpaca returned invalid JSON.") from None
    if not isinstance(account, dict) or account.get("status") != "ACTIVE":
        raise RuntimeError(f"The Alpaca {label} account is not ACTIVE.")
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise RuntimeError(f"Trading is blocked on this Alpaca {label} account.")
    print(f"Alpaca {label} connection verified.")
    # Synthetic state validates all seven answer schemas without placing orders.
    state = {
        "purpose": "connection test; synthetic data; no order will be submitted",
        "mid": 100.0, "spread_bps": 5.0, "imbalance": 0.0,
        "inventory": 0.0, "fill_ratio": 1.0, "reject_count": 0,
        "last_10_latencies_ms": [100.0], "last_10_slippage_bps": [0.0],
    }
    client = OpenRouterDecisionClient(credentials["OPENROUTER_API_KEY"], model)
    try:
        _, meta = run_battery(client, state, timeout=20)
    finally:
        client.close()
    print(f"OpenRouter Jev verified: {meta['model']}.")


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Use 0 for continuous mode or a positive tick count.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["test", "full", "irl"], help="Prompted when omitted")
    parser.add_argument("--symbol", help="Alpaca symbol, e.g. BTC/USD or AAPL")
    parser.add_argument("--ticks", type=nonnegative_int, default=None,
                        help="Optional tick bound for full/irl; test is always 30 ticks, 0 is continuous")
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
        mode = args.mode
        while mode not in ("test", "full", "irl"):
            mode = input("Mode [test/full/irl] (default test): ").strip().lower() or "test"
            if mode not in ("test", "full", "irl"):
                print("Choose test, full, or irl.")
        if mode == "test" and args.ticks not in (None, 30):
            raise ValueError("test mode is exactly 30 ticks; use full with --ticks for another count")
        live = mode == "irl"
        if live and args.bar:
            raise ValueError("irl requires regular ticks so risk checks keep running; omit --bar")
        ticks = args.ticks if args.ticks is not None else (30 if mode == "test" else 0)
        if live and os.environ.get("JEV_LOOP_ALLOW_LIVE") != "i-understand-the-risk":
            raise ValueError("irl needs explicit opt-in: set JEV_LOOP_ALLOW_LIVE=i-understand-the-risk, then run again")
        print(f"Jev via OpenRouter | mode={mode} | Alpaca {'LIVE REAL MONEY' if live else 'PAPER'}")
        if live:
            print("Live limits: $25/order, $50 position, $25 UTC-day loss, 5% drawdown, 15-minute holding limit.")
            print("Fresh market data and Jev judgments required. Use a dedicated account; no other bots or manual orders.")
        print("Keys are hidden and kept in this process only; no credentials are saved.")
        print("Verification sends one billed Jev request; a running loop makes further billed calls.")
        symbol = args.symbol or input("Symbol [BTC/USD]: ").strip() or "BTC/USD"
        symbol = resolve_symbol(symbol).symbol
        credentials = collect_credentials(args.use_env, live)
        verify_connections(credentials, args.model, live)
        if args.check_only:
            print("Checks passed. No orders submitted.")
            return 0
        settings = dict(credentials, OPENROUTER_JEV_MODEL=args.model,
                        ALPACA_BASE_URL="https://api.alpaca.markets" if live else "https://paper-api.alpaca.markets")
        previous = {name: os.environ.get(name) for name in settings}
        os.environ.update(settings)
        command = ["--live" if live else "--paper", "--symbol", symbol, "--ticks", str(ticks)]
        if args.bar:
            command += ["--bar", args.bar]
        if args.dry_execution:
            command += ["--dry-execution"]
        print(f"Starting {mode} loop. Ctrl+C stops the loop; existing positions may remain open.")
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

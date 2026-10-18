# jev-loop

A 24/7 paper-trading loop built around a Jev decision battery, for the video
*How to Use Jev to Build a 24/7 HFT Trading System*.

The split, in one sentence: code computes the state, Jev answers seven typed
questions about it in one call, your code composes those answers into an
action using thresholds you set in `strategy.py`, a risk engine can veto
any of it, and execution defaults to Alpaca's paper API everywhere.

## Quick start (Windows, macOS, Linux)

Requires Python 3.10 or newer. Clone this repository, open a terminal in its folder, and run:

```bash
python -m pip install -e ".[dev]"
python start_jev.py
```

On Windows, `py` can be used instead of `python`. The launcher prompts for:

1. Symbol (default BTC/USD).
2. OpenRouter API key (hidden).
3. Alpaca **paper** API key ID (hidden).
4. Alpaca **paper** secret key (hidden).

It checks the paper account and makes one billed Jev connection-test call,
then runs 30 paper ticks. It saves no credentials. Enter keys only in your
local terminal. A terminal that cannot hide input is refused. Ctrl+C cancels.
No Vercel account or direct TypeSafe API key is used.

```bash
python start_jev.py --check-only            # checks only; no orders
python start_jev.py --dry-execution         # market data and Jev; no orders
python start_jev.py --symbol AAPL --ticks 30
python start_jev.py --symbol BTC/USD --ticks 0  # continuous; Ctrl+C stops
python start_jev.py --bar 30m --ticks 10
python -m jevloop serve                    # second terminal; localhost:8765
python -m pytest -q                       # offline tests
```

`--use-env` reuses existing environment credentials and prompts for missing
ones. The launcher does not load or write `.env`. The `.env.example` is for
advanced users loading configuration themselves. The launcher never accepts
`--live` and pins Alpaca to its paper endpoint, even if the environment says
otherwise. The original lower-level CLI retains its existing three live gates.

OpenRouter requests use `https://openrouter.ai/api/alpha/decisions`, with
`model`, `state`, and `questions`. The default model is `typesafe/jev-1.14`;
change it with `--model` or `OPENROUTER_JEV_MODEL`. Model availability is checked
by the actual connection-test call. Usage is billed by OpenRouter, including
when Alpaca is paper or execution is dry. No monthly-cost or latency guarantee
is made. Your snapshot is sent to OpenRouter; Alpaca credentials are not.

Official references checked October 18, 2026:
- https://openrouter.ai/docs/guides/community/jev
- https://openrouter.ai/docs/guides/community/jev-tutorial
- https://docs.alpaca.markets/us/docs/authentication

This is a standalone adaptation of the supplied installation scaffold. It
includes the supplied dashboard, strategy, risk layers, and tests; it does not
install a Claude Code skill or start a background service.

## Start and Stop

The dashboard has a **Start** and a **Stop** button, and shows **RUNNING**
or **PAUSED** next to them.

- **Stop** pauses new orders. The loop keeps running: it still reads the
  market, asks Jev, writes the log and updates the dashboard. It pulls
  the quotes this run has resting so nothing new fills, then places no
  orders until you press Start.
- **Stop does not close positions.** Whatever you hold stays held. The
  KILL switch (the hard risk limits, such as the drawdown cap) is what
  closes a position, and it still works while paused.
- **Start** lets it place orders again from the next tick.
- The state is saved in `~/.jev-loop/control.json`, so it stays the same
  after a page refresh or a restart. The loop checks it before every order.
- No dashboard open? `uv run python -m jevloop pause` and
  `uv run python -m jevloop resume` do the same thing from a terminal.

The buttons only work from the page `jevloop serve` gives you at
http://127.0.0.1:8765. The server only listens on your own machine, each
press is a POST carrying a random token made for your install (in
`~/.jev-loop/control.token`), and it sends no CORS headers, so another
website open in your browser can't press Stop or Start for you. Same on
Mac, Windows and Linux.

`--symbol` takes any crypto pair (24/7) or US equity ticker (market hours
only); `jevloop/assets.py` resolves it into endpoints, order-size rules,
and session rules. Orders are sized from a dollar target, not a fixed
quantity, so the same defaults work across assets.

No `OPENROUTER_API_KEY` when using the lower-level CLI? The loop runs on a
clearly-labelled mock decision client. It says so on the first line. The
mock answers with random numbers, so it never places orders, not even on
paper: a mock run is always a dry run.

## Running continuously

Use `python start_jev.py --ticks 0` in a terminal. Keep that process running.
Add `--bar 30m` (or `1m`, `5m`, `15m`, `1h`) for decisions on UTC bar closes.
Ctrl+C stops the foreground loop and attempts to cancel its own resting orders.
It does not automatically flatten positions. A forced process kill can skip
cleanup. The dashboard reads `~/.jev-loop/latest.json`.

## Your strategy lives in strategy.py

Everything this loop ships with is a harness, not an edge: a generic
strategy pulled out of thin air, wired in only so a demo run shows real
fills. `jevloop/strategy.py` owns the seven tunable thresholds behind
`compose_action()` and an `apply_strategy()` hook that gets one last
look at every action before it goes near an order, free to change or
veto it. The supplied demo strategy is retained; its profitability is unverified.

## The nine-stage loop

```
block event -> read the book -> state snapshot -> battery (seven Jev judgments)
  -> policy engine (strategy.py's thresholds + hook) -> pricing (Avellaneda-Stoikov, your code)
  -> risk veto (your code, absolute) -> post-only quotes + directional leg
  -> log, fills, inventory
```

## Jev call rate

The existing throttle is retained; tune it for your OpenRouter limits and budget.

- The fast loop runs every tick on price and risk, and reuses the last
  Jev judgment between calls.
- Jev is called at most once every `JEV_MIN_INTERVAL_S` seconds (default
  4, so 15 a minute), or sooner when the state changes materially: price
  or spread moves `JEV_MATERIAL_MOVE_BPS` (default 15 bps) or the
  position flips. Even then never more often than `JEV_MIN_GAP_S`
  (default 3s, 20 a minute).
- On a 429 or a "frequency" error the loop backs off exponentially (5s,
  10s, 20s, up to 120s) and keeps the last judgment meanwhile.
- A judgment older than `JEV_MAX_JUDGMENT_AGE_S` (default 60s) is not
  reused: the ladder drops to RULES_ONLY until Jev answers again.
- One shared client, one call at a time. Never parallel Jev calls, never
  a second client or a thread pool.

## The fallback ladder

```
healthy + high confidence -> RUN
healthy + low confidence  -> REDUCE
late past the tick budget -> HOLD_LATE (never quote on stale state)
Jev unavailable            -> RULES_ONLY (deterministic fallback, no model)
hard limit breached        -> KILL (cancel own orders, market-close the position it built, stop)
```

## Live trading (opt-in, off by default)

Paper is the default everywhere: `execution/alpaca.py` will not reach
Alpaca's live endpoint unless all three of the following are true at
once.

```bash
export JEV_LOOP_ALLOW_LIVE=i-understand-the-risk
uv run python -m jevloop run --live --ticks 30 --symbol BTC/USD
# then type the exact confirmation phrase the CLI prints and asks for
```

Windows PowerShell sets the variable with
`$env:JEV_LOOP_ALLOW_LIVE = "i-understand-the-risk"` and runs
`uv run --env-file .env python -m jevloop run --live --ticks 30 --symbol BTC/USD`.

Missing the environment variable, missing `--live`, or typing anything
other than the exact confirmation phrase refuses to start; it never
falls back to paper silently. This is real money with no paper safety
net, at the same small dollar caps `limits.py` enforces on paper -- a
strategy can never raise them. Treat `--live` as what it is: a flip of
a switch made deliberately awkward so it only ever happens on purpose.

## Safety

- Paper by default, everywhere. Live trading exists only behind the
  three-gate opt-in above.
- The hard risk caps live in `jevloop/limits.py` and never change between
  paper and live. The tunable strategy thresholds live in `jevloop/strategy.py`
  instead -- change a number, restart, see different behaviour.
- The risk engine (`jevloop/risk.py`) never calls Jev and never delegates,
  and runs after `strategy.py`'s hook has had its say, not before.
- Long or flat only. Alpaca crypto is spot and this account can't short,
  so a SELL signal closes the long this run holds (never more than Alpaca
  says is held) and does nothing when flat ("no position to close").
- Stop on the dashboard pauses new orders and never closes a position;
  the KILL switch closes positions and still works while paused.
- This is not investment advice and it does not claim a profit. It is a
  scaffold for a decision battery, a policy engine, and a risk layer around
  a fast model. Edge is still your job, and it lives in `strategy.py`.

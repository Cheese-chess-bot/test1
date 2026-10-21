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

On Windows, `py` can be used instead of `python`. The launcher asks for mode,
symbol, OpenRouter API key, and the selected Alpaca account's key ID and secret.
Keys are hidden in your terminal and never saved. It verifies the account and
makes one billed Jev connection-test call before starting.

| Mode | Account | Duration |
| --- | --- | --- |
| `test` (default) | Paper | Exactly 30 ticks |
| `full` | Paper | Continuous until Ctrl+C |
| `irl` | Live, real money | Continuous, with explicit opt-in and live checks below |

```bash
python start_jev.py --mode test
python start_jev.py --mode full
python start_jev.py --mode test --check-only       # verification; no orders
python start_jev.py --mode test --dry-execution    # real data/Jev; no orders
python start_jev.py --mode full --ticks 100        # optional bound on full/irl
python start_jev.py --mode full --bar 30m --ticks 10  # paper only
python -m jevloop serve                            # second terminal; localhost:8765
python -m pytest -q                               # offline tests
```

`--use-env` reuses environment credentials and prompts for missing ones. Paper
uses `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`; irl uses `ALPACA_LIVE_API_KEY` and
`ALPACA_LIVE_SECRET_KEY`. Both use `OPENROUTER_API_KEY`. Live never silently
reuses paper keys. The launcher does not load or write `.env`; `.env.example`
is for users loading configuration themselves. No Vercel account or direct
TypeSafe API key is used. The server is optional and starts only when requested.

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

### Automatic US-stock sessions

Update dependencies after pulling this version (includes Windows timezone data):

```bash
python -m pip install -e ".[dev]"
python start_jev.py --mode full --market stocks --symbol AAPL
```

`AAPL` is an example, not a recommendation. Use an Alpaca-tradable, fractionable
US stock/ETF. `--market auto` is the default and detects stocks versus crypto
from the symbol; `--market stocks` and `--market crypto` reject mismatches.
With `--market stocks` and no symbol, the launcher prompts with `AAPL` as its default.

- Stocks use Alpaca's regular-session clock, including weekends, holidays,
  early closes and US daylight saving. There is no fixed India-time schedule.
- Closed sessions display `MARKET_CLOSED` and the next opening in New York and
  India time. The loop rechecks at most 30 seconds apart, waking sooner near
  the scheduled open. No trading decisions are requested while closed (the
  launcher's one initial billed connection check still runs).
- At reopening, history and trade-flow buffers refresh and normal processing
  resumes. A dashboard PAUSED state stays paused: press Start to allow orders.
- Stock `--bar` intervals are anchored to 09:30 New York time. A final partial
  bar at an early close does not cause after-hours trading. Bar mode is paper only.
- Fractional stock limit orders default to DAY; crypto defaults to GTC. Live
  stock entries use price-capped DAY limits, which may rest until filled,
  canceled or expired. The stock data adapter consistently requests IEX data.
- On observing closure the bot attempts to cancel its own orders and reconciles
  their final fills. It does **not** automatically liquidate positions at close;
  market exits wait until the venue reopens. Cancellation failure stops the run
  for inspection. Existing holdings from other runs remain outside its tracking.
- `full` waits across sessions until stopped. `test` still stops after 30 loop
  iterations, including closed-market checks; 30 such checks may take about 15 minutes.
- Crypto retains its 24/7 schedule. Switching symbols requires restarting with
  the new symbol and does not sell or manage positions in the previous symbol.

The dashboard remains a separate command: `python -m jevloop serve`.
This update does not enable extended-hours trading or add indicator strategies.

References: [Alpaca clock](https://docs.alpaca.markets/us/reference/legacyclock),
[fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading).

Use `python start_jev.py --mode full` in a terminal. Keep that process running.
Add `--bar 30m` (or `1m`, `5m`, `15m`, `1h`) for decisions on bar closes.
Crypto bars are UTC-aligned; stock bars start at 09:30 America/New_York.
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

## Responsiveness and Jev call rate

Jev runs in one background worker with an independent 8-second HTTP timeout
budget. The ordinary 2-second tick no longer waits for the response. Alpaca and
OpenRouter reuse HTTP connections. Broker calls still run on the tick thread:
network delays and the shared 90-call/minute limiter can extend a tick. This is
not a WebSocket feed or a latency guarantee. Explicit paper bar mode waits for
a result at the bar close; live mode refuses bar scheduling so risk checks are
not postponed for minutes.

Logs now include `timing_ms` for market reads, state/reconciliation, decision
polling, execution and the whole tick (excluding cadence sleep), alongside Jev's
own request latency, judgment age and status. The terminal shows market and tick
timing and `waiting for Jev`, `cached`, `stale judgment`, or `state changed`.
The first tick normally holds while the first background judgment is pending.

- Calls start at most once every `JEV_MIN_INTERVAL_S` (default 4 seconds),
  or after `JEV_MIN_GAP_S` (3 seconds) on material changes. Only one request
  can be in flight. Slower requests lower the call rate further.
- The price/spread threshold is `JEV_MATERIAL_MOVE_BPS` (15 bps). Inventory
  changes over 1% also invalidate a judgment, including new fills.
- Judgment age is measured from request launch, including network time. The
  default and hard maximum are 10 seconds; `JEV_MAX_JUDGMENT_AGE_S` can lower it.
  Expired answers and answers from materially changed states are not reused.
- Rate limits trigger exponential cooldown. A previous answer is usable only
  while still fresh and relevant. Paper can use the existing deterministic
  fallback during provider outages. Live always holds without a usable Jev
  answer and attempts to cancel this run's orders.
- Risk checks run even while Jev is pending. A hard stop takes precedence over HOLD.

## Live mode (`irl`)

Select `irl`, use LIVE Alpaca credentials, explicitly set the environment opt-in,
and type `I understand this trades real money` at the confirmation prompt.
The launcher never sets the opt-in on your behalf.

```bash
# macOS/Linux
export JEV_LOOP_ALLOW_LIVE=i-understand-the-risk
python start_jev.py --mode irl
```

```powershell
# Windows PowerShell
$env:JEV_LOOP_ALLOW_LIVE = "i-understand-the-risk"
python start_jev.py --mode irl
```

Live boundaries:

- $25 maximum entry order, $50 position cap including pending buys, no short
  sales, and cash/non-margin buying-power checks with a 1% fee reserve.
  Live directional buys use IOC limit orders with a price ceiling. Protective
  market sells may exceed the entry-order cap to close the position.
- $25 account-equity loss or 5% drawdown latches a stop for the UTC day.
  The baseline starts at the first live launch that day, persists across
  restarts, and includes other account activity. It is not a broker statement
  of trading-only daily P&L. Account checks run about every 10 seconds, subject
  to network/limiter delays; a stop attempts to flatten this run's position.
- A 15-minute holding limit triggers an exit and stop even if Jev is unavailable.
  Market data must have a valid venue timestamp no older than 5 seconds for
  new entries; this is checked again after the API limiter before submission.
- Startup requires the selected symbol to be flat, no account orders open,
  an active account with cash, and a real Jev client. A local account lock
  prevents concurrent live runs sharing the same `JEV_LOOP_HOME`.
- Failed market/account checks stop live execution and attempt to cancel
  this run's orders. Use a dedicated account without other bots/manual orders;
  the local lock cannot coordinate other computers or different log directories.

Safety state and the account lock are under `~/.jev-loop/live-safety-*` (or
`JEV_LOOP_HOME`). After a crash, inspect Alpaca orders/positions and stop any other
process before manually removing a stale `.lock`. Keep the `.json` loss record.
Ctrl+C or an exhausted tick count cancels own resting orders but may leave a
position open. Gaps, fees, outages, cancellation races and slippage can exceed
the configured loss/cap thresholds. These are application checks, not guaranteed
broker-side stops. No real trade was made during development.

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

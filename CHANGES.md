# Modes and responsiveness

- Added prompted/CLI test (30 paper ticks), full (continuous paper), and irl
  (guarded live) modes, with separate live environment credentials.
- Moved Jev to a single background worker; reused HTTP sessions; added stage
  timings and explicit pending/stale status. Exact default model remains
  typesafe/jev-1.14 through OpenRouter Decisions API.
- Count judgment age from its source request; invalidate on material market or
  inventory changes. Keep risk checks active while Jev is pending.
- Added persistent UTC-day live loss stops and a local account lock, startup
  account checks, cash/long-only order guards, live IOC limit entries, and
  fresh venue-data checks. Live never uses the paper rules-only fallback.
- Added offline concurrency, mode-routing and live-boundary regression tests.
  No authenticated API call or order was made during this update.

# OpenRouter adaptation

- Extracted the runnable project from the supplied Pasted text(3).txt scaffold.
- Added start_jev.py: hidden local prompts for OpenRouter key, Alpaca paper key ID,
  and Alpaca paper secret. Keys are never saved by the launcher.
- Added paper-account verification and a seven-question Jev connection check.
- Replaced direct TypeSafe/Vercel routing with OpenRouter Decisions API.
- Default model: typesafe/jev-1.14; model ID is configurable.
- Retained the original dashboard, strategy, risk engine, throttle, paper defaults,
  explicit mock mode, and lower-level CLI live-trading gates.
- Added typed answer validation and sanitized OpenRouter error handling.
- Updated setup instructions and environment example.
- Added offline provider and launcher tests. No authenticated API call or order
  was made during development; real connectivity is verified on your machine.

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

"""Local live-account interlock and persistent UTC-day loss stop."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone


class LiveGuard:
    def __init__(self, directory, account, limits):
        account_id = account.get("id")
        if not account_id:
            raise ValueError("Live account identity is missing; refusing to trade")
        self._validate(account)
        self.limits = limits
        key = hashlib.sha256(str(account_id).encode()).hexdigest()[:24]
        self.path = directory / f"live-safety-{key}.json"
        self.lock = directory / f"live-safety-{key}.lock"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError(
                "A live-account lock already exists. Stop the other live process first. "
                "After a crash, check Alpaca orders and positions before removing the stale .lock file."
            ) from None
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        self.state = {}
        try:
            if self.path.exists():
                self.state = json.loads(self.path.read_text())
                for k in ("baseline", "peak"):
                    if not math.isfinite(float(self.state[k])) or float(self.state[k]) <= 0:
                        raise ValueError("invalid live safety state")
                if not isinstance(self.state.get("stopped"), bool) or not isinstance(self.state.get("day"), str):
                    raise ValueError("invalid live safety state")
            reason = self.check(account)
            if reason:
                raise ValueError(reason)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _validate(account):
        if account.get("status") != "ACTIVE" or account.get("trading_blocked") or account.get("account_blocked") or account.get("trade_suspended_by_user"):
            raise ValueError("Live account is inactive or blocked")
        equity = float(account.get("equity", 0))
        cash = float(account.get("cash", 0))
        if not math.isfinite(equity) or equity <= 0 or not math.isfinite(cash) or cash <= 0:
            raise ValueError("Live account must have positive equity and available cash")
        return equity

    def check(self, account):
        equity = self._validate(account)
        day = datetime.now(timezone.utc).date().isoformat()
        if self.state.get("day") != day:
            self.state = {"day": day, "baseline": equity, "peak": equity, "stopped": False}
        self.state["peak"] = max(float(self.state["peak"]), equity)
        loss = float(self.state["baseline"]) - equity
        drawdown = 1 - equity / float(self.state["peak"])
        if loss >= self.limits.max_daily_loss_usd or drawdown >= self.limits.max_drawdown_pct:
            self.state["stopped"] = True
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state))
        os.replace(temporary, self.path)
        return "Live account daily loss/drawdown stop is latched until the next UTC day" if self.state["stopped"] else None

    def close(self):
        self.lock.unlink(missing_ok=True)

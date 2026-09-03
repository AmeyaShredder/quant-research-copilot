"""
Small parameter sweep over decay rate / rebalance threshold. Each sweep
point is its own backtest_runs row (label='sweep_...', config carries
the actual params) — turns results into a queryable table instead of a
one-off print statement.
"""
from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any

from sqlalchemy.orm import Session

from backtest.engine import run_backtest
from signal.construct import build_cross_sectional_signal


def sweep(
    session: Session,
    returns_by_ticker_date: dict[str, dict[date, float]],
    decay_rates: list[float] = [0.8, 0.9, 0.95],
    window_days_options: list[int] = [10, 20, 40],
) -> list[dict[str, Any]]:
    results = []
    for decay, window_days in product(decay_rates, window_days_options):
        signal_by_ticker = build_cross_sectional_signal(session, window_days=window_days)
        # decay is applied as a simple recency multiplier on the score;
        # kept explicit here rather than folded into the SQL so the
        # sweep dimension is obviously visible in this file.
        decayed = {
            ticker: [
                {**row, "rolling_zscore": (row["rolling_zscore"] or 0) * decay}
                for row in rows
            ]
            for ticker, rows in signal_by_ticker.items()
        }
        run = run_backtest(
            session,
            label=f"sweep_decay_{decay}_win_{window_days}",
            signal_by_ticker=decayed,
            returns_by_ticker_date=returns_by_ticker_date,
            config={"decay": decay, "window_days": window_days},
        )
        results.append({"run_id": run.run_id, "decay": decay, "window_days": window_days, "sharpe": float(run.sharpe or 0)})
    return results

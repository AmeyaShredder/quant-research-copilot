"""
Long top-decile / short bottom-decile backtest, driven off the
cross-sectional rolling z-score signal. Results persisted to
backtest_runs / backtest_positions via BacktestRepository.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from db.models import BacktestRun
from db.repositories import BacktestRepository


def _decile_positions(scores_by_ticker_for_date: dict[str, float]) -> dict[str, float]:
    """Equal-weight long the top decile by score, short the bottom decile."""
    items = sorted(scores_by_ticker_for_date.items(), key=lambda kv: kv[1])
    n = len(items)
    if n < 10:
        # Too few names for a clean decile split; long top half, short bottom half.
        cut = max(1, n // 2)
        shorts, longs = items[:cut], items[-cut:]
    else:
        decile = max(1, n // 10)
        shorts, longs = items[:decile], items[-decile:]

    positions: dict[str, float] = {}
    if longs:
        w = 1.0 / len(longs)
        for ticker, _ in longs:
            positions[ticker] = w
    if shorts:
        w = -1.0 / len(shorts)
        for ticker, _ in shorts:
            positions[ticker] = positions.get(ticker, 0.0) + w
    return positions


def run_backtest(
    session: Session,
    *,
    label: str,
    signal_by_ticker: dict[str, list[dict[str, Any]]],
    returns_by_ticker_date: dict[str, dict[date, float]],
    config: dict[str, Any],
) -> BacktestRun:
    """
    signal_by_ticker: {ticker: [{"date": date, "rolling_zscore": float}, ...]}
    returns_by_ticker_date: {ticker: {date: forward_1d_return}}
    """
    # Reshape into {date: {ticker: score}}
    scores_by_date: dict[date, dict[str, float]] = defaultdict(dict)
    for ticker, rows in signal_by_ticker.items():
        for row in rows:
            if row.get("rolling_zscore") is not None:
                scores_by_date[row["date"]][ticker] = float(row["rolling_zscore"])

    repo = BacktestRepository(session)
    run = repo.create_run(label=label, config=config)

    daily_returns: list[float] = []
    position_rows: list[dict[str, Any]] = []
    prev_positions: dict[str, float] = {}
    turnovers: list[float] = []

    for as_of in sorted(scores_by_date):
        positions = _decile_positions(scores_by_date[as_of])

        day_pnl = 0.0
        for ticker, pos in positions.items():
            fwd_ret = returns_by_ticker_date.get(ticker, {}).get(as_of, 0.0)
            pnl = pos * fwd_ret
            day_pnl += pnl
            position_rows.append({"date": as_of, "ticker": ticker, "position": round(pos, 3), "pnl": round(pnl, 4)})

        daily_returns.append(day_pnl)

        traded = set(positions) | set(prev_positions)
        turnover_today = sum(abs(positions.get(t, 0.0) - prev_positions.get(t, 0.0)) for t in traded)
        turnovers.append(turnover_today)
        prev_positions = positions

    metrics = compute_metrics(daily_returns, turnovers)
    repo.record_metrics(run, **metrics)
    if position_rows:
        repo.add_positions(run.run_id, position_rows)

    return run


def compute_metrics(daily_returns: list[float], turnovers: list[float]) -> dict[str, float]:
    if not daily_returns:
        return {"sharpe": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0, "turnover": 0.0}

    arr = np.array(daily_returns)
    mean, std = arr.mean(), arr.std(ddof=1) if len(arr) > 1 else 0.0
    sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0.0

    cum = np.cumsum(arr)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0

    hit_rate = float((arr > 0).mean())
    avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0

    return {
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(max_drawdown, 4),
        "hit_rate": round(hit_rate, 4),
        "turnover": round(avg_turnover, 4),
    }

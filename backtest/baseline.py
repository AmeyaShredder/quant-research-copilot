"""
Naive baselines, run through the exact same run_backtest() engine so
that comparisons are just a SQL query between two run_ids (see
BacktestRepository.compare_runs and v_signal_vs_baseline_performance),
never a special-cased script.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backtest.engine import run_backtest
from db.models import BacktestRun


def momentum_baseline_signal(
    returns_by_ticker_date: dict[str, dict[date, float]], lookback_days: int = 5
) -> dict[str, list[dict[str, Any]]]:
    """Score(t) = trailing `lookback_days` cumulative return, used as a naive momentum signal."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticker, series in returns_by_ticker_date.items():
        dates = sorted(series)
        for i, d in enumerate(dates):
            window = dates[max(0, i - lookback_days):i]
            score = sum(series[w] for w in window) if window else 0.0
            out[ticker].append({"date": d, "rolling_zscore": score})
    return dict(out)


def random_baseline_signal(
    returns_by_ticker_date: dict[str, dict[date, float]], seed: int = 42
) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticker, series in returns_by_ticker_date.items():
        for d in sorted(series):
            out[ticker].append({"date": d, "rolling_zscore": rng.uniform(-1, 1)})
    return dict(out)


def run_baselines(session: Session, returns_by_ticker_date: dict[str, dict[date, float]]) -> list[BacktestRun]:
    runs = []
    runs.append(run_backtest(
        session, label="baseline_momentum",
        signal_by_ticker=momentum_baseline_signal(returns_by_ticker_date),
        returns_by_ticker_date=returns_by_ticker_date,
        config={"type": "momentum", "lookback_days": 5},
    ))
    runs.append(run_backtest(
        session, label="baseline_random",
        signal_by_ticker=random_baseline_signal(returns_by_ticker_date),
        returns_by_ticker_date=returns_by_ticker_date,
        config={"type": "random", "seed": 42},
    ))
    return runs

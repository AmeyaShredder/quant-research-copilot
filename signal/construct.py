"""
Cross-sectional, recency-weighted signal: rolling z-score per ticker,
computed in SQL via SignalRepository.rolling_zscore (window functions),
not recomputed in pandas. This module just shapes that result into what
the backtest engine expects.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from db.repositories import SignalRepository


def build_cross_sectional_signal(session: Session, window_days: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Returns {ticker: [{date, rolling_zscore, ...}, ...]} ready for the backtest engine."""
    rows = SignalRepository(session).rolling_zscore(window_days=window_days)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_ticker[row["ticker"]].append(row)
    return dict(by_ticker)

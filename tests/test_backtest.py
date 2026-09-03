import math

from backtest.engine import _decile_positions, compute_metrics


def test_decile_positions_small_universe_splits_in_half():
    scores = {"A": -1.0, "B": -0.5, "C": 0.0, "D": 0.5}
    positions = _decile_positions(scores)
    assert positions["A"] < 0  # lowest score -> short
    assert positions["D"] > 0  # highest score -> long
    # equal-weight, dollar neutral for an even split
    assert abs(sum(positions.values())) < 1e-9


def test_compute_metrics_known_answer_all_positive_returns():
    # constant positive daily return -> Sharpe should be a large positive
    # finite number (std=0 handled), hit_rate should be exactly 1.0,
    # max_drawdown should be 0 (monotonically increasing cum returns).
    daily_returns = [0.01] * 10
    metrics = compute_metrics(daily_returns, turnovers=[0.5] * 10)
    assert metrics["hit_rate"] == 1.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["turnover"] == 0.5
    # std is 0 for constant returns -> our guard returns sharpe 0.0 rather than inf/nan
    assert metrics["sharpe"] == 0.0


def test_compute_metrics_known_answer_mixed_returns():
    daily_returns = [0.02, -0.01, 0.02, -0.01, 0.02]
    metrics = compute_metrics(daily_returns, turnovers=[0.2] * 5)
    assert metrics["hit_rate"] == 0.6  # 3 of 5 positive
    assert metrics["max_drawdown"] <= 0
    assert isinstance(metrics["sharpe"], float)
    assert not math.isnan(metrics["sharpe"])


def test_compute_metrics_empty_returns_zeroed_out():
    metrics = compute_metrics([], turnovers=[])
    assert metrics == {"sharpe": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0, "turnover": 0.0}

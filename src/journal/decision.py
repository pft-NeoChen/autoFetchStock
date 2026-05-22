"""TASK-D03c — V2 §6.1 quantitative threshold gating.

Evaluates a strategy's metrics against the V2 §6.1 升 paper 門檻：
- 扣成本每筆期望值 ≥ +5 bp
- Profit Factor ≥ 1.3
- Max Drawdown ≤ 20%
- Sharpe (年化) ≥ 1.0
- OOS / IS 期望值比 ≥ 0.7
- Top-5 大賺剔除後仍正報酬
- OOS 期至少打敗含息加權報酬指數與 0050
- OOS 年化 alpha > 0
- Regime 涵蓋 ≥ 1多 + 1空 + 1盤整
- 交易次數 ≥ 50
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.journal.performance import PerformanceMetrics

__all__ = [
    "DecisionInput",
    "DecisionResult",
    "evaluate_v2_thresholds",
]


# V2 §6.1 thresholds (module-top for monkeypatching)
EXPECTANCY_BP_MIN = 5.0
PROFIT_FACTOR_MIN = 1.3
MAX_DRAWDOWN_MAX = 0.20
SHARPE_MIN = 1.0
OOS_IS_RATIO_MIN = 0.7
N_TRADES_MIN = 50


@dataclass
class DecisionInput:
    metrics: PerformanceMetrics
    oos_is_ratio: float
    top5_excluded_return: float
    beats_weighted_index: bool
    beats_etf_0050: bool
    oos_alpha: float
    regime_coverage_bull: int
    regime_coverage_bear: int
    regime_coverage_range: int


@dataclass
class DecisionResult:
    passed: bool
    checks: dict[str, bool]
    reasons: list[str] = field(default_factory=list)


def evaluate_v2_thresholds(inp: DecisionInput) -> DecisionResult:
    m = inp.metrics
    checks: dict[str, bool] = {
        "expectancy_bp": m.expectancy_bp >= EXPECTANCY_BP_MIN,
        "profit_factor": m.profit_factor >= PROFIT_FACTOR_MIN,
        "max_drawdown": m.max_drawdown <= MAX_DRAWDOWN_MAX,
        "sharpe": m.sharpe >= SHARPE_MIN,
        "oos_is_ratio": inp.oos_is_ratio >= OOS_IS_RATIO_MIN,
        "top5_excluded": inp.top5_excluded_return > 0,
        "beats_benchmarks": bool(inp.beats_weighted_index and inp.beats_etf_0050),
        "oos_alpha": inp.oos_alpha > 0,
        "regime_coverage": (
            inp.regime_coverage_bull >= 1
            and inp.regime_coverage_bear >= 1
            and inp.regime_coverage_range >= 1
        ),
        "n_trades": m.n_trades >= N_TRADES_MIN,
    }
    reasons: list[str] = []
    if not checks["expectancy_bp"]:
        reasons.append(f"expectancy_bp {m.expectancy_bp:.2f} < {EXPECTANCY_BP_MIN}")
    if not checks["profit_factor"]:
        reasons.append(f"profit_factor {m.profit_factor:.2f} < {PROFIT_FACTOR_MIN}")
    if not checks["max_drawdown"]:
        reasons.append(f"max_drawdown {m.max_drawdown:.2%} > {MAX_DRAWDOWN_MAX:.0%}")
    if not checks["sharpe"]:
        reasons.append(f"sharpe {m.sharpe:.2f} < {SHARPE_MIN}")
    if not checks["oos_is_ratio"]:
        reasons.append(f"oos_is_ratio {inp.oos_is_ratio:.2f} < {OOS_IS_RATIO_MIN}")
    if not checks["top5_excluded"]:
        reasons.append(f"top5_excluded_return {inp.top5_excluded_return:.2%} ≤ 0")
    if not checks["beats_benchmarks"]:
        reasons.append("did not beat both weighted_index and 0050")
    if not checks["oos_alpha"]:
        reasons.append(f"oos_alpha {inp.oos_alpha:.2%} ≤ 0")
    if not checks["regime_coverage"]:
        reasons.append(
            f"regime coverage incomplete (bull={inp.regime_coverage_bull}, "
            f"bear={inp.regime_coverage_bear}, range={inp.regime_coverage_range})"
        )
    if not checks["n_trades"]:
        reasons.append(f"n_trades {m.n_trades} < {N_TRADES_MIN}")
    return DecisionResult(passed=all(checks.values()), checks=checks, reasons=reasons)

"""
src/analytics/inference.py
--------------------------
Shared model bundle loading, multi-quantile prediction, Direct flip
economics, and Flipper gate evaluation across API, market scan, and backtest.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Optional, Protocol
import joblib
import numpy as np
import pandas as pd

from src.analytics.condition import ConditionPolicy, DEFAULT_CONDITION_POLICY
from src.analytics.sizing import FixedCapSizingPolicy, SizingPolicy
from src.config import FEATURE_COLS, FEE_CONFIG, MODEL_CONFIG, MODEL_PATH, SIZING_CONFIG
from src.pricing.fees import (
    calculate_direct_payout,
    calculate_direct_payout_series,
    landed_basis,
    landed_basis_series,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForecastBundle:
    """Loaded quantile regressors, spike calibrator, and artifact metadata."""

    quantile_models: dict[float, Any]
    isotonic_calibrator: Any
    feature_cols: tuple[str, ...]
    tau_buyer_radar: float
    mae_pct: float
    split_date: Optional[str]

    @classmethod
    def from_artifact(cls, artifact: dict[str, Any]) -> "ForecastBundle":
        metrics = artifact.get("metrics") or {}
        tau_raw = metrics.get("tau_buyer_radar")
        if tau_raw is None:
            tau_raw = metrics.get("prob_threshold")
        if tau_raw is None:
            tau_raw = artifact.get("optimal_tau_buyer", 0.40)

        feature_cols = tuple(artifact.get("feature_cols") or FEATURE_COLS)
        return cls(
            quantile_models=dict(artifact.get("quantile_models") or {}),
            isotonic_calibrator=artifact.get("isotonic_calibrator"),
            feature_cols=feature_cols,
            tau_buyer_radar=float(tau_raw),
            mae_pct=float(metrics.get("mae_pct", 0.0)),
            split_date=metrics.get("split_date"),
        )

    @property
    def has_full_quantiles(self) -> bool:
        return self.isotonic_calibrator is not None and all(
            q in self.quantile_models for q in (0.10, 0.50, 0.90)
        )

    @property
    def has_buyer_radar(self) -> bool:
        return self.isotonic_calibrator is not None and 0.90 in self.quantile_models


@dataclass(frozen=True)
class QuantilePredictions:
    """Monotonic quantile return predictions and calibrated spike probabilities."""

    q10: np.ndarray
    q50: np.ndarray
    q90: np.ndarray
    move_prob: np.ndarray


@dataclass(frozen=True)
class DirectFlipScalar:
    """Unit economics for a single Direct flip forecast."""

    basis: float
    expected_exit_price: float
    expected_payout: float
    expected_net_profit: float
    exp_net_roi_pct: float
    kappa_risk: float
    allocated_units: int
    is_dead_zone_clamped: bool


@dataclass(frozen=True)
class FlipperGates:
    """Vectorized Flipper gate masks and structured funnel/veto inspection."""

    stage1_spike: pd.Series
    q10_floor_ok: pd.Series
    decay_ok: pd.Series
    roi_hurdle_ok: pd.Series
    sized_ok: pd.Series
    passed: pd.Series

    def funnel_counts(self, total_label: str, include_sizing: bool = True) -> dict[str, int]:
        hurdle_mask = (
            self.passed
            if include_sizing
            else (self.stage1_spike & self.q10_floor_ok & self.decay_ok & self.roi_hurdle_ok)
        )
        return {
            total_label: len(self.stage1_spike),
            "Stage 1 Spike Mover (τ)": int(self.stage1_spike.sum()),
            "q10 Downside Floor Passed": int((self.stage1_spike & self.q10_floor_ok).sum()),
            "Set Decay Filter Passed": int(
                (self.stage1_spike & self.q10_floor_ok & self.decay_ok).sum()
            ),
            "Net ROI Hurdle Cleared": int(hurdle_mask.sum()),
        }


class FlipperEntryRule(Protocol):
    """Swap point for HQ-01 Flipper entry logic."""

    prob_threshold: float
    q10_floor_pct: float
    decay_floor_pct: float
    min_net_roi_pct: float
    max_position_dollars: float

    def evaluate_batch(self, df: pd.DataFrame) -> FlipperGates: ...

    def veto_reasons_scalar(
        self,
        move_prob: float,
        cqr_lpb: float,
        decay_3d: float,
        net_expected_roi_pct: float,
        basis: float,
        allocated_units: int,
    ) -> list[str]: ...

    def primary_veto_reason(self, row: pd.Series) -> str: ...


@dataclass(frozen=True)
class BuyerRadarProxyFlipperRule:
    """
    PLACEHOLDER (HQ-01): Reuses calibrated Buyer Radar tau on q_0.90 pending
    a dedicated Flipper entry specification.
    """

    prob_threshold: float
    q10_floor_pct: float = MODEL_CONFIG["Q10_FLOOR_PCT"]
    decay_floor_pct: float = MODEL_CONFIG["DECAY_VELOCITY_FLOOR_PCT"]
    min_net_roi_pct: float = MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"]
    max_position_dollars: float = SIZING_CONFIG["MAX_POSITION_DOLLARS"]

    def evaluate_batch(self, df: pd.DataFrame) -> FlipperGates:
        stage1 = (df["move_prob"] >= self.prob_threshold) & (df["pred_magnitude"] > 0.0)
        q10_ok = df["cqr_lpb"] >= self.q10_floor_pct
        decay_ok = df["price_decay_velocity_3d"] >= self.decay_floor_pct
        roi_ok = df["exp_net_roi_pct"] >= self.min_net_roi_pct
        sized_ok = df["allocated_units"] > 0
        passed = stage1 & q10_ok & decay_ok & roi_ok & sized_ok
        return FlipperGates(
            stage1_spike=stage1,
            q10_floor_ok=q10_ok,
            decay_ok=decay_ok,
            roi_hurdle_ok=roi_ok,
            sized_ok=sized_ok,
            passed=passed,
        )

    def veto_reasons_scalar(
        self,
        move_prob: float,
        cqr_lpb: float,
        decay_3d: float,
        net_expected_roi_pct: float,
        basis: float,
        allocated_units: int,
    ) -> list[str]:
        reasons = []
        if move_prob < self.prob_threshold:
            reasons.append(
                f"Insufficient Spike Probability ({move_prob:.1%} < {self.prob_threshold:.1%})"
            )
        if cqr_lpb < self.q10_floor_pct:
            reasons.append(f"Downside Floor Breach ({cqr_lpb:.1f}% < {self.q10_floor_pct:.1f}%)")
        if decay_3d < self.decay_floor_pct:
            reasons.append(
                f"Active Price Decay / Falling Knife "
                f"({decay_3d:.2f}%/day < {self.decay_floor_pct:.2f}%/day)"
            )
        if net_expected_roi_pct < self.min_net_roi_pct:
            reasons.append(
                f"Net ROI Below Hurdle ({net_expected_roi_pct:.1f}% < {self.min_net_roi_pct:.1f}%)"
            )
        if basis > self.max_position_dollars or (
            allocated_units <= 0 and cqr_lpb >= self.q10_floor_pct and net_expected_roi_pct > 0.0
        ):
            reasons.append(f"Position Exceeds Capital Ceiling (${self.max_position_dollars:.2f})")
        return reasons

    def primary_veto_reason(self, row: pd.Series) -> str:
        if row["cqr_lpb"] < self.q10_floor_pct:
            return f"Downside Floor Breach ({row['cqr_lpb']:.1f}% < {self.q10_floor_pct:.1f}%)"
        if row["price_decay_velocity_3d"] < self.decay_floor_pct:
            return f"Active Falling Knife ({row['price_decay_velocity_3d']:.2f}%/d)"
        if row["exp_net_roi_pct"] < self.min_net_roi_pct:
            return (
                f"Sub-Hurdle E[ROI] "
                f"({row['exp_net_roi_pct']:.1f}% < {self.min_net_roi_pct:.1f}%)"
            )
        if row["allocated_units"] <= 0:
            return "Exceeds Position Dollar Ceiling"
        return "Microstructural Drag"


def load_forecast_bundle(model_path: Path = MODEL_PATH) -> ForecastBundle:
    artifact = joblib.load(model_path)
    return ForecastBundle.from_artifact(artifact)


def try_load_forecast_bundle(model_path: Path = MODEL_PATH) -> Optional[ForecastBundle]:
    if not model_path.exists():
        return None
    try:
        return load_forecast_bundle(model_path)
    except Exception as exc:
        logger.warning("Failed to load model bundle from %s: %s", model_path, exc)
        return None


def predict_quantiles(bundle: Optional[ForecastBundle], X: pd.DataFrame) -> QuantilePredictions:
    n_rows = len(X)
    if n_rows == 0 or bundle is None or not bundle.has_full_quantiles:
        return QuantilePredictions(
            q10=np.full(n_rows, MODEL_CONFIG["Q10_FLOOR_PCT"], dtype=float),
            q50=np.zeros(n_rows, dtype=float),
            q90=np.zeros(n_rows, dtype=float),
            move_prob=np.zeros(n_rows, dtype=float),
        )

    q_models = bundle.quantile_models
    q50 = np.nan_to_num(np.asarray(q_models[0.50].predict(X), dtype=float), nan=0.0)
    q90_raw = np.nan_to_num(np.asarray(q_models[0.90].predict(X), dtype=float), nan=0.0)
    q10_raw = np.nan_to_num(np.asarray(q_models[0.10].predict(X), dtype=float), nan=0.0)

    q90 = np.maximum(q90_raw, q50)
    q10 = np.minimum(q10_raw, q50)
    move_prob = np.nan_to_num(
        np.asarray(bundle.isotonic_calibrator.transform(q90), dtype=float), nan=0.0
    )
    return QuantilePredictions(q10=q10, q50=q50, q90=q90, move_prob=move_prob)


def predict_buyer_breakout(
    bundle: Optional[ForecastBundle], X: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    n_rows = len(X)
    if n_rows == 0 or bundle is None or not bundle.has_buyer_radar:
        return np.zeros(n_rows, dtype=float), np.zeros(n_rows, dtype=float)

    q_models = bundle.quantile_models
    q90 = np.nan_to_num(np.asarray(q_models[0.90].predict(X), dtype=float), nan=0.0)
    if 0.50 in q_models:
        q50 = np.nan_to_num(np.asarray(q_models[0.50].predict(X), dtype=float), nan=0.0)
        q90 = np.maximum(q90, q50)
    move_prob = np.nan_to_num(
        np.asarray(bundle.isotonic_calibrator.transform(q90), dtype=float), nan=0.0
    )
    return move_prob, q90


def evaluate_direct_flip_scalar(
    current_price: float,
    pred_return_pct: float,
    q10_return_pct: float,
    amihud: float = 0.0,
    is_pro: bool = False,
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    condition_policy: ConditionPolicy = DEFAULT_CONDITION_POLICY,
    sizing_policy: Optional[SizingPolicy] = None,
) -> DirectFlipScalar:
    expected_exit_price = max(0.01, round(current_price * (1.0 + (pred_return_pct / 100.0)), 2))
    basis = landed_basis(current_price, tax_rate=tax_rate, channel="direct")
    raw_payout = calculate_direct_payout(
        expected_exit_price, tax_rate=tax_rate, clamp_dead_zone=True, is_pro=is_pro
    )
    kappa_risk = float(condition_policy.evaluate(expected_exit_price))
    expected_payout = raw_payout * kappa_risk
    expected_net_profit = expected_payout - basis
    exp_net_roi_pct = (expected_net_profit / basis) * 100.0

    allocator = sizing_policy or FixedCapSizingPolicy()
    allocated_units = int(
        allocator.allocate(
            expected_roi_pct=exp_net_roi_pct,
            lower_bound_return_pct=q10_return_pct,
            basis=basis,
            amihud=amihud,
        )
    )
    dead_zone_max = (
        FEE_CONFIG["DIRECT_DEAD_ZONE_MAX_PRO"] if is_pro else FEE_CONFIG["DIRECT_DEAD_ZONE_MAX"]
    )
    is_clamped = FEE_CONFIG["DIRECT_DEAD_ZONE_MIN"] <= expected_exit_price <= dead_zone_max
    return DirectFlipScalar(
        basis=basis,
        expected_exit_price=expected_exit_price,
        expected_payout=expected_payout,
        expected_net_profit=expected_net_profit,
        exp_net_roi_pct=exp_net_roi_pct,
        kappa_risk=kappa_risk,
        allocated_units=allocated_units,
        is_dead_zone_clamped=is_clamped,
    )


def evaluate_direct_flip_frame(
    df: pd.DataFrame,
    is_pro: bool = False,
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    condition_policy: ConditionPolicy = DEFAULT_CONDITION_POLICY,
    sizing_policy: Optional[SizingPolicy] = None,
) -> pd.DataFrame:
    out = df.copy()
    out["basis"] = landed_basis_series(out["current_price"], tax_rate=tax_rate, channel="direct")
    out["exp_exit"] = np.maximum(0.01, out["current_price"] * (1.0 + out["pred_magnitude"] / 100.0))
    raw_payout = calculate_direct_payout_series(
        out["exp_exit"], tax_rate=tax_rate, clamp_dead_zone=True, is_pro=is_pro
    )
    kappa_risk = condition_policy.evaluate(out["exp_exit"])
    out["exp_exit_payout"] = raw_payout * kappa_risk
    out["exp_net_profit"] = out["exp_exit_payout"] - out["basis"]
    out["exp_net_roi_pct"] = (out["exp_net_profit"] / out["basis"]) * 100.0

    allocator = sizing_policy or FixedCapSizingPolicy()
    amihud_col = out["amihud_illiquidity_30d"] if "amihud_illiquidity_30d" in out else None
    out["allocated_units"] = allocator.allocate(
        expected_roi_pct=out["exp_net_roi_pct"],
        lower_bound_return_pct=out["cqr_lpb"],
        basis=out["basis"],
        amihud=amihud_col,
    )
    return out

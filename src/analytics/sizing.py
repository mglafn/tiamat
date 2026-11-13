"""
src/analytics/sizing.py
-----------------------
Position sizing and capital allocation policies.
"""
import numpy as np
import pandas as pd

def calculate_position_size(
    expected_roi_pct: pd.Series,
    lower_bound_return_pct: pd.Series,
    basis: pd.Series,
    amihud: pd.Series = None,
    portfolio_equity: float = 10000.0,
    max_position_dollars: float = 50.0,
    max_units_per_asset: int = 4
) -> pd.Series:
    """
    Allocates integer units bounded by capital ceilings and downside bounds.
    """
    # Defensive Floor: Veto sizing if lower bound indicates severe negative drift
    viable_mask = lower_bound_return_pct >= -15.0
    
    # Placeholder: Allocates fractional capital capped at max_position_dollars
    est_downside = np.maximum(0.05, (expected_roi_pct - lower_bound_return_pct) / 100.0)
    est_upside = np.maximum(0.05, expected_roi_pct / 100.0)
    
    # Quarter-Kelly scaling fraction
    f_kelly = np.clip(0.25 * (est_upside / np.square(est_downside)), 0.0, 0.05)
    target_dollars = np.minimum(f_kelly * portfolio_equity, max_position_dollars)
    
    raw_units = np.floor(target_dollars / np.maximum(basis, 0.01))
    bounded_units = np.clip(raw_units, 1.0, float(max_units_per_asset))
    
    return np.where(viable_mask, bounded_units, 0.0)    expected_roi_pct: pd.Series,
    lower_bound_return_pct: pd.Series,
    basis: pd.Series,
    amihud: pd.Series = None,
    portfolio_equity: float = 10000.0,
    max_position_dollars: float = 50.0
) -> pd.Series:
    """
    Allocates integer units bounded by capital ceiling and downside risk.
    Replaces arbitrary Amihud heuristics (0.02 / max(amihud, 1e-5)).
    """
    # 1. Uncertainty envelope: penalize size when lower bound return is deeply negative
    est_downside = np.maximum(0.05, (expected_roi_pct - lower_bound_return_pct) / 100.0)
    est_upside = np.maximum(0.05, expected_roi_pct / 100.0)
    
    # 2. Conservative quarter-Kelly fraction capped at 5% of portfolio
    f_kelly = np.clip(0.25 * (est_upside / np.square(est_downside)), 0.0, 0.05)
    target_dollars = np.minimum(f_kelly * portfolio_equity, max_position_dollars)
    
    # 3. Discrete unit conversion
    units = np.floor(target_dollars / np.maximum(basis, 0.01))
    return np.maximum(1.0, units)
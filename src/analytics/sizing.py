"""
src/analytics/sizing.py
-----------------------
Position sizing and capital allocation policies.
"""
import numpy as np
import pandas as pd

from src.config import MODEL_CONFIG


def calculate_position_size(
    expected_roi_pct: pd.Series,
    lower_bound_return_pct: pd.Series,
    basis: pd.Series,
    amihud: pd.Series = None,
    portfolio_equity: float = 10000.0,
    max_position_dollars: float = 50.0,
    max_units_per_asset: int = 4,
) -> pd.Series:
    """
    Allocates integer units bounded by a fixed per-asset dollar ceiling and unit cap.
    """
    del amihud, portfolio_equity  # PLACEHOLDER: Unused pending real volume/depth liquidity policy

    viable_mask = (
        lower_bound_return_pct >= MODEL_CONFIG["Q10_FLOOR_PCT"]
    ) & (expected_roi_pct > 0.0)

    # PLACEHOLDER: Explicit fixed dollar/unit cap (replaced inert Kelly math)
    raw_units = np.floor(max_position_dollars / np.maximum(basis, 0.01))
    bounded_units = np.clip(raw_units, 0.0, float(max_units_per_asset))

    result = np.where(viable_mask, bounded_units, 0.0)
    if isinstance(expected_roi_pct, pd.Series):
        return pd.Series(result, index=expected_roi_pct.index)
    return int(np.asarray(result).item())
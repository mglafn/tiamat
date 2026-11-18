"""
src/analytics/sizing.py
-----------------------
Position sizing and capital allocation policies.
"""

from typing import Optional, Protocol, Union
import numpy as np
import pandas as pd

from src.config import MODEL_CONFIG, SIZING_CONFIG

NumericOrSeries = Union[float, pd.Series]
UnitsOrSeries = Union[int, pd.Series]


class SizingPolicy(Protocol):
    """Policy interface returning integer unit allocations for candidate trades."""

    def allocate(
        self,
        expected_roi_pct: NumericOrSeries,
        lower_bound_return_pct: NumericOrSeries,
        basis: NumericOrSeries,
        amihud: Optional[NumericOrSeries] = None,
    ) -> UnitsOrSeries: ...


class FixedCapSizingPolicy:
    """PLACEHOLDER (HQ-02): Fixed per-asset dollar ceiling and unit cap."""

    def __init__(
        self,
        max_position_dollars: float = SIZING_CONFIG["MAX_POSITION_DOLLARS"],
        max_units_per_asset: int = SIZING_CONFIG["MAX_UNITS_PER_ASSET"],
        q10_floor_pct: float = MODEL_CONFIG["Q10_FLOOR_PCT"],
    ):
        self.max_position_dollars = max_position_dollars
        self.max_units_per_asset = max_units_per_asset
        self.q10_floor_pct = q10_floor_pct

    def allocate(
        self,
        expected_roi_pct: NumericOrSeries,
        lower_bound_return_pct: NumericOrSeries,
        basis: NumericOrSeries,
        amihud: Optional[NumericOrSeries] = None,
    ) -> UnitsOrSeries:
        del amihud  # PLACEHOLDER: Unused pending real volume/depth liquidity policy
        viable_mask = (lower_bound_return_pct >= self.q10_floor_pct) & (expected_roi_pct > 0.0)
        raw_units = np.floor(self.max_position_dollars / np.maximum(basis, 0.01))
        bounded_units = np.clip(raw_units, 0.0, float(self.max_units_per_asset))
        result = np.where(viable_mask, bounded_units, 0.0)
        if isinstance(expected_roi_pct, pd.Series):
            return pd.Series(result, index=expected_roi_pct.index)
        return int(np.asarray(result).item())


class FlatSizingPolicy:
    """Allocates a single unit per asset regardless of capital basis."""

    def allocate(
        self,
        expected_roi_pct: NumericOrSeries,
        lower_bound_return_pct: NumericOrSeries,
        basis: NumericOrSeries,
        amihud: Optional[NumericOrSeries] = None,
    ) -> UnitsOrSeries:
        del lower_bound_return_pct, basis, amihud
        if isinstance(expected_roi_pct, pd.Series):
            return pd.Series(1.0, index=expected_roi_pct.index)
        return 1


def calculate_position_size(
    expected_roi_pct: NumericOrSeries,
    lower_bound_return_pct: NumericOrSeries,
    basis: NumericOrSeries,
    amihud: Optional[NumericOrSeries] = None,
    portfolio_equity: float = SIZING_CONFIG["PORTFOLIO_EQUITY_USD"],
    max_position_dollars: float = SIZING_CONFIG["MAX_POSITION_DOLLARS"],
    max_units_per_asset: int = SIZING_CONFIG["MAX_UNITS_PER_ASSET"],
) -> UnitsOrSeries:
    """Allocates integer units bounded by a fixed per-asset dollar ceiling and unit cap."""
    del portfolio_equity  # PLACEHOLDER: Unused pending portfolio-level equity allocator
    policy = FixedCapSizingPolicy(
        max_position_dollars=max_position_dollars,
        max_units_per_asset=max_units_per_asset,
    )
    return policy.allocate(expected_roi_pct, lower_bound_return_pct, basis, amihud=amihud)

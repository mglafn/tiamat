"""
src/analytics/condition.py
--------------------------
Condition risk haircut and intake grading deduction rules.
"""
import numpy as np
import pandas as pd

def evaluate_condition_haircut(
    prices: pd.Series,
    target_venue: str = "cardkingdom",
    declared_grade: str = "NM"
) -> pd.Series:
    """
    Evaluates haircut factor kappa in [0.0, 1.0].
    Default baseline: 98.5% recovery value for Direct/CK intake.
    """
    # Open for venue deduction matrix lookup
    if isinstance(prices, pd.Series):
        return pd.Series(0.985, index=prices.index)
    return 0.985    prices: pd.Series,
    venue: str = "tcgplayer_direct"
) -> pd.Series:
    """
    Uniform condition risk haircut factor (kappa).
    Direct/CK intake historical SLA: ~98.5% recovery value.
    """
    # Default baseline: conservative 1.5% deduction for transit/grading friction
    if isinstance(prices, pd.Series):
        return pd.Series(0.985, index=prices.index)
    return 0.985
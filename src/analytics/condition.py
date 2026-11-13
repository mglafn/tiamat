"""
src/analytics/condition.py
--------------------------
Condition risk haircut and intake grading deduction rules.
"""
import pandas as pd


def evaluate_condition_haircut(
    prices: pd.Series,
    target_venue: str = "cardkingdom",
    declared_grade: str = "NM",
) -> pd.Series:
    """
    Evaluates condition risk haircut factor kappa in [0.0, 1.0].
    PLACEHOLDER: Uniform 0.985 scalar pending venue-specific grading matrix decision.
    """
    del target_venue, declared_grade
    if isinstance(prices, pd.Series):
        return pd.Series(0.985, index=prices.index)
    return 0.985
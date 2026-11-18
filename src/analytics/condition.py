"""
src/analytics/condition.py
--------------------------
Condition risk haircut and intake grading deduction rules.
"""

from typing import Protocol, Union
import pandas as pd

NumericOrSeries = Union[float, pd.Series]


class ConditionPolicy(Protocol):
    """Policy interface returning expected condition realization factor kappa in [0, 1]."""

    def evaluate(
        self,
        prices: NumericOrSeries,
        target_venue: str = "cardkingdom",
        declared_grade: str = "NM",
    ) -> NumericOrSeries: ...


class FlatConditionPolicy:
    """PLACEHOLDER (HQ-03): Uniform scalar haircut pending venue grading matrix."""

    def __init__(self, kappa: float = 0.985):
        self.kappa = kappa

    def evaluate(
        self,
        prices: NumericOrSeries,
        target_venue: str = "cardkingdom",
        declared_grade: str = "NM",
    ) -> NumericOrSeries:
        del target_venue, declared_grade
        if isinstance(prices, pd.Series):
            return pd.Series(self.kappa, index=prices.index)
        return self.kappa


DEFAULT_CONDITION_POLICY = FlatConditionPolicy()


def evaluate_condition_haircut(
    prices: NumericOrSeries,
    target_venue: str = "cardkingdom",
    declared_grade: str = "NM",
) -> NumericOrSeries:
    """
    Evaluates condition risk haircut factor kappa in [0.0, 1.0].
    PLACEHOLDER: Uniform 0.985 scalar pending venue-specific grading matrix decision.
    """
    return DEFAULT_CONDITION_POLICY.evaluate(
        prices, target_venue=target_venue, declared_grade=declared_grade
    )

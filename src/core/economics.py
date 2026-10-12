"""
src/core/economics.py
---------------------
Centralized unit economics math, fee structures, condition risk haircuts,
and Kelly position sizing logic for the Tiamat Quant Terminal.
"""
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Tuple, Union
import numpy as np
import pandas as pd

# Standard Marketplace & Fulfillment Constants
DEFAULT_TAX_RATE = 0.075
COMMISSION_STANDARD = Decimal("0.1075")
COMMISSION_PRO = Decimal("0.0895")
COMMISSION_CAP = Decimal("75.00")
DIRECT_TIER2_FIXED = Decimal("1.12")
PROCESSING_RATE = Decimal("0.025")
HUB_COURIER_FREIGHT = 0.012
OUTBOUND_BATCH_FREIGHT = 0.09


def calculate_direct_payout_scalar(
    price: float,
    tax_rate: float = DEFAULT_TAX_RATE,
    clamp_dead_zone: bool = True,
    is_pro: bool = False,
) -> float:
    """Calculates TCGplayer Direct payout for a single price tick using Banker's Rounding."""
    d_price = Decimal(str(round(price, 4)))
    d_tax = Decimal(str(tax_rate))

    if d_price < Decimal("0.40"):
        return 0.00

    if clamp_dead_zone and Decimal("2.50") <= d_price <= Decimal("2.67"):
        d_price = Decimal("2.49")

    if d_price < Decimal("2.50"):
        fee = (d_price * Decimal("0.50")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        return float(d_price - fee)

    commission_rate = COMMISSION_PRO if is_pro else COMMISSION_STANDARD
    commission = min(d_price * commission_rate, COMMISSION_CAP)
    gross_total = d_price * (Decimal("1.00") + d_tax)
    processing_fee = gross_total * PROCESSING_RATE
    total_fee = (DIRECT_TIER2_FIXED + commission + processing_fee).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )

    payout = max(Decimal("0.00"), d_price - total_fee)
    return float(payout.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def calculate_direct_payout_series(
    prices: pd.Series,
    tax_rate: float = DEFAULT_TAX_RATE,
    clamp_dead_zone: bool = True,
    is_pro: bool = False,
) -> pd.Series:
    """Vectorized calculation of TCGplayer Direct payout across a Pandas Series."""
    p = prices.copy().astype(float)
    if clamp_dead_zone:
        p = np.where((p >= 2.50) & (p <= 2.67), 2.49, p)

    sub_tier_fee = np.round(p * 0.50, 2)
    sub_tier_payout = p - sub_tier_fee

    commission_rate = 0.0895 if is_pro else 0.1075
    commission = np.minimum(p * commission_rate, 75.00)
    gross_total = p * (1.0 + tax_rate)
    processing = gross_total * 0.025
    standard_fee = np.round(1.12 + commission + processing, 2)
    standard_payout = p - standard_fee

    payout = np.where(
        p < 0.40,
        0.0,
        np.where(p < 2.50, sub_tier_payout, standard_payout),
    )
    return np.maximum(0.0, payout)


def calculate_condition_risk_haircut_scalar(
    direct_price: float,
    acq_cost: float,
    downgrade_rate: float = 0.035,
    reject_rate: float = 0.005,
    salvage_factor: float = 0.75,
) -> float:
    """Calculates condition risk haircut factor kappa in [0.80, 1.00] for a single unit."""
    safe_direct = max(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = 1.0
    penalty = (downgrade_rate * max(0.0, downgrade_penalty)) + (
        reject_rate * reject_penalty
    )
    kappa_risk = 1.0 - penalty
    return float(max(0.80, min(1.00, kappa_risk)))


def calculate_condition_risk_haircut_series(
    direct_price: pd.Series,
    acq_cost: pd.Series,
    downgrade_rate: float = 0.035,
    reject_rate: float = 0.005,
    salvage_factor: float = 0.75,
) -> pd.Series:
    """Vectorized condition risk haircut factor kappa in [0.80, 1.00]."""
    safe_direct = np.maximum(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = safe_direct / safe_direct
    kappa_risk = 1.0 - (
        downgrade_rate * np.maximum(0.0, downgrade_penalty)
        + reject_rate * reject_penalty
    )
    return np.clip(kappa_risk, 0.80, 1.00)


def compute_uncertainty_kelly_scalar(
    expected_roi_pct: float,
    cqr_lpb: float,
    basis: float,
    amihud: float,
    portfolio_value: float = 10000.0,
    max_position_dollars: float = 50.0,
    kappa_kelly: float = 0.25,
) -> int:
    """Computes uncertainty-penalized fractional Kelly integer unit allocation for a single SKU."""
    est_downside = max(0.05, (expected_roi_pct - cqr_lpb) / 100.0)
    est_upside = max(0.05, expected_roi_pct / 100.0)
    f_kelly = kappa_kelly * (est_upside / (est_downside**2))
    f_kelly = min(0.05, max(0.0, f_kelly))

    dollar_kelly = f_kelly * portfolio_value
    amihud_cap = 0.02 / max(amihud, 1e-5)
    final_dollar = min(dollar_kelly, max_position_dollars, amihud_cap)

    units_raw = np.floor(final_dollar / max(basis, 0.01))
    return int(max(1.0, units_raw))


def compute_uncertainty_kelly_units(
    expected_roi_pct: pd.Series,
    cqr_lpb: pd.Series,
    basis: pd.Series,
    amihud: pd.Series,
    portfolio_value: float = 10000.0,
    max_position_dollars: float = 50.0,
    kappa_kelly: float = 0.25,
) -> pd.Series:
    """Vectorized calculation of fractional Kelly units across a Pandas Series."""
    est_downside = np.maximum(0.05, (expected_roi_pct - cqr_lpb) / 100.0)
    est_upside = np.maximum(0.05, expected_roi_pct / 100.0)
    f_kelly = kappa_kelly * (est_upside / np.square(est_downside))
    f_kelly = np.clip(f_kelly, 0.0, 0.05)

    dollar_kelly = f_kelly * portfolio_value
    amihud_dollar_cap = 0.02 / np.maximum(amihud, 1e-5)
    final_dollar_size = np.minimum(
        dollar_kelly, np.minimum(max_position_dollars, amihud_dollar_cap)
    )
    units = np.floor(final_dollar_size / np.maximum(basis, 0.01))
    return np.maximum(1.0, units)


def compute_landed_basis_scalar(
    current_price: float, tax_rate: float = DEFAULT_TAX_RATE
) -> float:
    """Computes total acquisition basis: price + sales tax + tiered inbound postage + hub courier freight."""
    inbound_postage = 0.99 if current_price < 5.00 else 0.15
    return (current_price * (1.0 + tax_rate)) + inbound_postage + HUB_COURIER_FREIGHT


def compute_landed_basis_series(
    prices: pd.Series, tax_rate: float = DEFAULT_TAX_RATE
) -> pd.Series:
    """Vectorized total acquisition basis calculation."""
    inbound_postage = np.where(prices < 5.00, 0.99, 0.15)
    return (prices * (1.0 + tax_rate)) + inbound_postage + HUB_COURIER_FREIGHT
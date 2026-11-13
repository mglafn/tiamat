"""
src/pricing/fees.py
-------------------
Single source of truth for TCGplayer Direct fee schedules, Card Kingdom store
credit multipliers, and channel-aware landed acquisition basis.
"""

from decimal import Decimal, ROUND_HALF_EVEN
import math
from typing import Literal, Union
import numpy as np
import pandas as pd

from src.config import FEE_CONFIG

Channel = Literal["direct", "spatial_ck", "buyer"]


def _round_half_even_div(num: np.ndarray, denom: int) -> np.ndarray:
    """Exact vectorized integer Banker's rounding of num / denom."""
    q = num // denom
    r = num % denom
    twice_r = 2 * r
    round_up = (twice_r > denom) | ((twice_r == denom) & ((q & 1) == 1))
    return q + round_up.astype(np.int64)


def calculate_direct_payout(
    price: float,
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    clamp_dead_zone: bool = True,
    is_pro: bool = False,
) -> float:
    """
    Exact Decimal (ROUND_HALF_EVEN) TCGplayer Direct seller net payout.
    - < $0.40: ineligible ($0.00)
    - $0.40 - $2.49: flat 50% fee (commission, Pro, and processing waived)
    - >= $2.50: $1.12 Direct + 8.95% commission (cap $75) + [2.5% Pro (cap $75)] + 2.5% gross processing
    """
    f_price = float(price)
    if not math.isfinite(f_price) or f_price <= 0.0:
        return 0.00

    d_price = Decimal(str(round(f_price, 4)))
    d_tax = Decimal(str(round(float(tax_rate), 4)))

    if d_price < Decimal(str(FEE_CONFIG["DIRECT_FLOOR_USD"])):
        return 0.00

    dead_min = Decimal(str(FEE_CONFIG["DIRECT_DEAD_ZONE_MIN"]))
    dead_max_key = "DIRECT_DEAD_ZONE_MAX_PRO" if is_pro else "DIRECT_DEAD_ZONE_MAX"
    dead_max = Decimal(str(FEE_CONFIG[dead_max_key]))
    if clamp_dead_zone and dead_min <= d_price <= dead_max:
        d_price = Decimal(str(FEE_CONFIG["DIRECT_TIER1_MAX_USD"]))

    if d_price < dead_min:
        tier1_rate = Decimal(str(FEE_CONFIG["DIRECT_TIER1_RATE"]))
        fee = (d_price * tier1_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        payout = max(Decimal("0.00"), d_price - fee)
        return float(payout.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))

    direct_fixed = Decimal(str(FEE_CONFIG["DIRECT_FIXED_USD"]))
    commission_cap = Decimal(str(FEE_CONFIG["COMMISSION_CAP_USD"]))
    commission_rate = Decimal(str(FEE_CONFIG["DIRECT_COMMISSION"]))
    commission = min(d_price * commission_rate, commission_cap)

    pro_fee = (
        min(d_price * Decimal(str(FEE_CONFIG["PRO_FEE"])), commission_cap)
        if is_pro
        else Decimal("0.00")
    )

    gross_total = d_price * (Decimal("1.00") + d_tax)
    processing_fee = gross_total * Decimal(str(FEE_CONFIG["PROCESSING_RATE"]))

    total_fee = (direct_fixed + commission + pro_fee + processing_fee).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )
    payout = max(Decimal("0.00"), d_price - total_fee)
    return float(payout.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def calculate_direct_payout_series(
    prices: Union[pd.Series, np.ndarray],
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    clamp_dead_zone: bool = True,
    is_pro: bool = False,
) -> Union[pd.Series, np.ndarray]:
    """
    Vectorized TCGplayer Direct payout matching calculate_direct_payout to the exact cent.
    """
    is_series = isinstance(prices, pd.Series)
    index = prices.index if is_series else None

    p_arr = (
        prices.to_numpy(dtype=np.float64, na_value=np.nan)
        if is_series
        else np.asarray(prices, dtype=np.float64)
    )
    p_clean = np.where(np.isfinite(p_arr) & (p_arr > 0.0), p_arr, 0.0)
    p_e4 = np.rint(p_clean * 10_000.0).astype(np.int64)

    floor_e4 = int(round(FEE_CONFIG["DIRECT_FLOOR_USD"] * 10_000))
    dead_min_e4 = int(round(FEE_CONFIG["DIRECT_DEAD_ZONE_MIN"] * 10_000))
    dead_max_key = "DIRECT_DEAD_ZONE_MAX_PRO" if is_pro else "DIRECT_DEAD_ZONE_MAX"
    dead_max_e4 = int(round(FEE_CONFIG[dead_max_key] * 10_000))
    tier1_max_e4 = int(round(FEE_CONFIG["DIRECT_TIER1_MAX_USD"] * 10_000))

    if clamp_dead_zone:
        in_dead_zone = (p_e4 >= dead_min_e4) & (p_e4 <= dead_max_e4)
        p_e4 = np.where(in_dead_zone, tier1_max_e4, p_e4)

    tier1_rate_e4 = int(round(FEE_CONFIG["DIRECT_TIER1_RATE"] * 10_000))
    tier1_fee_cents = _round_half_even_div(p_e4 * tier1_rate_e4, 1_000_000)

    direct_fixed_e12 = int(round(FEE_CONFIG["DIRECT_FIXED_USD"] * 100)) * (10**10)
    cap_e8 = int(round(FEE_CONFIG["COMMISSION_CAP_USD"] * 100)) * (10**6)
    comm_e4 = int(round(FEE_CONFIG["DIRECT_COMMISSION"] * 10_000))
    comm_e12 = np.minimum(p_e4 * comm_e4, cap_e8) * (10**4)

    if is_pro:
        pro_e4 = int(round(FEE_CONFIG["PRO_FEE"] * 10_000))
        pro_e12 = np.minimum(p_e4 * pro_e4, cap_e8) * (10**4)
    else:
        pro_e12 = 0

    tax_e4 = int(Decimal(str(round(float(tax_rate), 4))) * 10_000)
    proc_e4 = int(round(FEE_CONFIG["PROCESSING_RATE"] * 10_000))
    proc_e12 = p_e4 * (10_000 + tax_e4) * proc_e4

    tier2_fee_e12 = direct_fixed_e12 + comm_e12 + pro_e12 + proc_e12
    tier2_fee_cents = _round_half_even_div(tier2_fee_e12, 10**10)

    fee_cents = np.where(p_e4 < dead_min_e4, tier1_fee_cents, tier2_fee_cents)
    payout_e4 = np.maximum(0, p_e4 - fee_cents * 100)
    payout_cents = _round_half_even_div(payout_e4, 100)
    payout = np.where(p_e4 < floor_e4, 0.0, payout_cents / 100.0)

    if is_series:
        return pd.Series(payout, index=index, dtype=np.float64)
    return payout


def _channel_freight(channel: Channel) -> float:
    if channel == "direct":
        return FEE_CONFIG["HUB_FREIGHT_USD"]
    if channel == "spatial_ck":
        return FEE_CONFIG["OUTBOUND_BATCH_FREIGHT_USD"]
    if channel == "buyer":
        return 0.0
    raise ValueError(f"Unsupported channel '{channel}'")


def landed_basis(
    price: float,
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    channel: Channel = "direct",
) -> float:
    """Scalar landed acquisition cost including sales tax, inbound postage, and channel freight."""
    inbound = (
        FEE_CONFIG["INBOUND_POSTAGE_LOW_USD"]
        if price < FEE_CONFIG["INBOUND_POSTAGE_THRESHOLD_USD"]
        else FEE_CONFIG["INBOUND_POSTAGE_HIGH_USD"]
    )
    return float((price * (1.0 + tax_rate)) + inbound + _channel_freight(channel))


def landed_basis_series(
    prices: Union[pd.Series, np.ndarray],
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    channel: Channel = "direct",
) -> Union[pd.Series, np.ndarray]:
    """Vectorized landed acquisition cost matching landed_basis."""
    is_series = isinstance(prices, pd.Series)
    index = prices.index if is_series else None
    p = (
        prices.to_numpy(dtype=np.float64, na_value=np.nan)
        if is_series
        else np.asarray(prices, dtype=np.float64)
    )
    inbound = np.where(
        p < FEE_CONFIG["INBOUND_POSTAGE_THRESHOLD_USD"],
        FEE_CONFIG["INBOUND_POSTAGE_LOW_USD"],
        FEE_CONFIG["INBOUND_POSTAGE_HIGH_USD"],
    )
    basis = (p * (1.0 + tax_rate)) + inbound + _channel_freight(channel)
    if is_series:
        return pd.Series(basis, index=index, dtype=np.float64)
    return basis


def ck_credit_payout(ck_cash_price: Union[float, pd.Series, np.ndarray]):
    """Card Kingdom Store Credit payout (+30% bonus multiplier)."""
    return ck_cash_price * FEE_CONFIG["STORE_CREDIT_MULTIPLIER"]
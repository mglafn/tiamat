import numpy as np
import pandas as pd
import pytest

from src.pricing.fees import (
    calculate_direct_payout,
    calculate_direct_payout_series,
    ck_credit_payout,
    landed_basis,
    landed_basis_series,
)


TEST_PRICES = [0.10, 0.39, 0.40, 1.00, 2.47, 2.49, 2.50, 2.67, 2.68, 2.75, 2.76, 5.00, 19.99, 100.00, 1000.00]


@pytest.mark.parametrize("is_pro", [False, True])
@pytest.mark.parametrize("clamp", [False, True])
@pytest.mark.parametrize("tax_rate", [0.0, 0.075, 0.0825])
def test_scalar_vectorized_direct_payout_parity(is_pro: bool, clamp: bool, tax_rate: float):
    s = pd.Series(TEST_PRICES)
    vec_series = calculate_direct_payout_series(
        s, tax_rate=tax_rate, clamp_dead_zone=clamp, is_pro=is_pro
    )
    vec_array = calculate_direct_payout_series(
        np.array(TEST_PRICES), tax_rate=tax_rate, clamp_dead_zone=clamp, is_pro=is_pro
    )

    for idx, price in enumerate(TEST_PRICES):
        expected = calculate_direct_payout(
            price, tax_rate=tax_rate, clamp_dead_zone=clamp, is_pro=is_pro
        )
        assert vec_series.iloc[idx] == expected
        assert vec_array[idx] == expected


@pytest.mark.parametrize("channel", ["direct", "spatial_ck", "buyer"])
def test_landed_basis_scalar_vectorized_parity(channel: str):
    prices = [1.50, 4.99, 5.00, 25.00]
    vec = landed_basis_series(pd.Series(prices), tax_rate=0.075, channel=channel)
    for idx, price in enumerate(prices):
        assert vec.iloc[idx] == pytest.approx(
            landed_basis(price, tax_rate=0.075, channel=channel)
        )


def test_ck_credit_multiplier():
    assert ck_credit_payout(10.00) == pytest.approx(13.00)
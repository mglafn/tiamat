"""
test/test_api.py
----------------
Comprehensive Unit & Integration Test Suite for the REST API Microservice.
Validates HTTP endpoint contracts, feature sanitization, and Direct/SYP rate card math.
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import (
    app, 
    sanitize_features_for_inference, 
    calculate_direct_payout, 
    calculate_condition_risk_haircut,
    ALLOWED_FEATURE_COLS,
    FEATURE_SCHEMA
)

client = TestClient(app)


def test_health_endpoint():
    """Validates engine diagnostic health check."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "db_connected" in data
    assert "model_loaded" in data


def test_docs_redirect():
    """Confirms root path correctly redirects to Swagger documentation."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in [302, 307]
    assert response.headers["location"] == "/docs"


def test_search_validation():
    """Ensures queries with fewer than 2 characters trigger HTTP 422 Unprocessable Entity."""
    response = client.get("/api/v1/search?name=a")
    assert response.status_code == 422


def test_arbitrage_endpoint_contract():
    """Validates schema integrity on the cross-vendor arbitrage endpoint."""
    response = client.get("/api/v1/arbitrage?min_spread=0&limit=5")
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            item = data[0]
            assert "uuid" in item
            assert "tcg_price" in item
            assert "ck_price" in item
            assert "price_spread" in item
            assert "spread_pct" in item


def test_arbitrage_finish_filters():
    """Ensures finish filtering accepts 'normal', 'foil', and 'etched'."""
    for finish in ["normal", "foil", "etched"]:
        response = client.get(f"/api/v1/arbitrage?min_spread=0&finish={finish}&limit=2")
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


def test_direct_payout_schedule():
    """Validates piecewise calculations under the TCGplayer Direct Rate Card."""
    # 1. Sub-$0.40 floor rule
    assert calculate_direct_payout(0.35) == 0.00

    # 2. Sub-$2.50 50% flat fee tier
    assert calculate_direct_payout(1.00) == 0.50
    assert calculate_direct_payout(2.00) == 1.00
    assert calculate_direct_payout(2.49) == 1.25

    # 3. $5.00 Card Payout
    assert calculate_direct_payout(5.00, tax_rate=0.075, clamp_dead_zone=False) == 3.30

    # 4. $100.00 Card Payout
    assert calculate_direct_payout(100.00, tax_rate=0.075, clamp_dead_zone=False) == 87.24

    # 5. $1,000.00 High-Value Card Non-Pro (Commission Capped at $75.00)
    assert calculate_direct_payout(1000.00, tax_rate=0.075, clamp_dead_zone=False, is_pro=False) == 897.00

    # 6. $1,000.00 High-Value Card Pro Seller (Double Cap)
    assert calculate_direct_payout(1000.00, tax_rate=0.075, clamp_dead_zone=False, is_pro=True) == 872.00


def test_dead_zone_clamping():
    """Confirms [$2.50, $2.67] dead-zone prices are clamped to $2.49 to maximize net payout."""
    unclamped_payout = calculate_direct_payout(2.50, clamp_dead_zone=False)
    assert unclamped_payout < 1.15

    clamped_payout = calculate_direct_payout(2.50, clamp_dead_zone=True)
    assert clamped_payout == 1.25


def test_condition_risk_haircut():
    """Validates deterministic kappa_risk calculation."""
    # Standard Near Mint with low friction basis
    haircut = calculate_condition_risk_haircut(direct_price=10.00, acq_cost=8.00)
    assert 0.80 <= haircut <= 1.00
    assert round(haircut, 2) == 0.98

    # High downgrade risk edge
    haircut_high_loss = calculate_condition_risk_haircut(direct_price=20.00, acq_cost=2.00)
    assert haircut_high_loss < haircut


def test_feature_sanitization_types_and_defaults():
    """Verifies that sanitize_features_for_inference safely imputes NULL/NaN without crashes."""
    dummy_vals = (None,) * len(ALLOWED_FEATURE_COLS)
    df = sanitize_features_for_inference(list(ALLOWED_FEATURE_COLS), dummy_vals)

    assert len(df) == 1
    assert not df.isna().any().any()

    assert df['sma_ratio'].iloc[0] == 1.0
    assert df['bid_ask_spread_pct'].iloc[0] == 1.0
    assert df['volatility_14d'].iloc[0] == 0.0
    assert df['mana_value'].iloc[0] == 0.0

    assert df['is_foil'].dtype == int
    assert df['is_reserved'].dtype == int
    assert df['is_land'].dtype == int
    assert df['is_creature'].dtype == int
    assert df['rarity_score'].dtype == int
    assert df['rarity_score'].iloc[0] == 1
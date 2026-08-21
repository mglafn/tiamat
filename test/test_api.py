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
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "db_connected" in data
    assert "model_loaded" in data

def test_docs_redirect():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in [302, 307]
    assert response.headers["location"] == "/docs"

def test_search_validation():
    response = client.get("/api/v1/search?name=a")
    assert response.status_code in [422, 503]

def test_arbitrage_endpoint_contract():
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

def test_direct_payout_schedule():
    assert calculate_direct_payout(0.35) == 0.00
    assert calculate_direct_payout(1.00) == 0.50
    assert calculate_direct_payout(2.00) == 1.00
    assert calculate_direct_payout(2.49) == 1.25
    assert calculate_direct_payout(5.00, tax_rate=0.075, clamp_dead_zone=False) == 3.21
    assert calculate_direct_payout(100.00, tax_rate=0.075, clamp_dead_zone=False) == 85.44
    assert calculate_direct_payout(1000.00, tax_rate=0.075, clamp_dead_zone=False, is_pro=False) == 897.00

def test_dead_zone_clamping():
    unclamped_payout = calculate_direct_payout(2.50, clamp_dead_zone=False)
    assert unclamped_payout < 1.15
    clamped_payout = calculate_direct_payout(2.50, clamp_dead_zone=True)
    assert clamped_payout == 1.25

def test_condition_risk_haircut():
    haircut = calculate_condition_risk_haircut(direct_price=10.00, acq_cost=8.00)
    assert 0.80 <= haircut <= 1.00
    assert round(haircut, 2) == 0.98

def test_feature_sanitization_types_and_defaults():
    dummy_vals = (None,) * len(ALLOWED_FEATURE_COLS)
    df = sanitize_features_for_inference(list(ALLOWED_FEATURE_COLS), dummy_vals)
    assert len(df) == 1
    assert not df.isna().any().any()
    assert df['sma_ratio'].iloc[0] == 1.0
    assert df['bid_ask_spread_pct'].iloc[0] == 1.0
    assert df['volatility_14d'].iloc[0] == 0.0
    assert df['price_decay_velocity_3d'].iloc[0] == 0.0
    assert df['amihud_illiquidity_30d'].iloc[0] == 0.0
    assert df['is_foil'].dtype == int
    assert df['is_reserved'].dtype == int

def test_backtest_endpoint_contract():
    response = client.get("/api/v1/backtest?hurdle=8.0&sizing=kelly&filter_mode=cqr_veto")
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        data = response.json()
        assert "status" in data
        assert "params" in data
        assert "summary" in data
        assert "funnel" in data
        assert "top_trades" in data
        assert "worst_trades" in data
"""
test/test_characterization.py
-----------------------------
Deterministic fixture-DB characterization tests covering get_forecast,
scan_live_market, and run_arbitrage_backtest prior to refactoring.
"""

from pathlib import Path
import duckdb
import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.isotonic import IsotonicRegression
from sklearn.tree import DecisionTreeRegressor

import src.api.main as api_main
from src.analytics.backtest import run_arbitrage_backtest
from src.analytics.scan_market import scan_live_market
from src.config import FEATURE_COLS

FIXTURE_DATE = "2026-09-15"
SPLIT_DATE = "2026-09-10"
INT_FEATURES = ("is_foil", "is_reserved", "is_land", "is_creature", "rarity_score")

FIXTURE_CARDS = [
    # uuid, name, set_code, price, sma_ratio, decay_3d, q10, q50, q90, target_7d
    ("uuid-a", "Alpha Winner", "TST", 10.00, 1.15, 0.25, -5.0, 50.0, 60.0, 55.0),
    ("uuid-b", "Falling Knife", "TST", 10.00, 1.12, -2.50, -5.0, 60.0, 65.0, -20.0),
    ("uuid-c", "Floor Breach", "TST", 10.00, 0.90, 0.00, -22.0, 60.0, 65.0, 5.0),
    ("uuid-d", "Dead Zone", "TST", 2.00, 1.05, 0.00, -5.0, 28.0, 32.0, 10.0),
    ("uuid-e", "Capital Cap", "TST", 60.00, 1.25, 0.25, -5.0, 50.0, 60.0, 30.0),
]


def _fit_tree(X_fit: pd.DataFrame, targets: list[float]) -> DecisionTreeRegressor:
    model = DecisionTreeRegressor(max_depth=4, random_state=42)
    model.fit(X_fit, np.asarray(targets, dtype=np.float64))
    return model


@pytest.fixture()
def fixture_env(tmp_path: Path):
    db_path = tmp_path / "fixture.duckdb"
    model_path = tmp_path / "fixture_model.joblib"

    X_fit = pd.DataFrame(0.0, index=range(len(FIXTURE_CARDS)), columns=FEATURE_COLS)
    X_fit["sma_ratio"] = [c[4] for c in FIXTURE_CARDS]
    for int_col in INT_FEATURES:
        X_fit[int_col] = 1 if int_col == "rarity_score" else 0

    q_models = {
        0.10: _fit_tree(X_fit, [c[6] for c in FIXTURE_CARDS]),
        0.50: _fit_tree(X_fit, [c[7] for c in FIXTURE_CARDS]),
        0.90: _fit_tree(X_fit, [c[8] for c in FIXTURE_CARDS]),
    }
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(
        np.array([0.0, 15.0, 30.0, 60.0]),
        np.array([0.05, 0.25, 0.70, 0.90]),
    )

    joblib.dump(
        {
            "quantile_models": q_models,
            "isotonic_calibrator": calibrator,
            "optimal_tau_buyer": 0.40,
            "feature_cols": list(FEATURE_COLS),
            "metrics": {
                "mae_pct": 4.0,
                "prob_threshold": 0.40,
                "tau_buyer_radar": 0.40,
                "split_date": SPLIT_DATE,
            },
        },
        model_path,
    )

    conn = duckdb.connect(str(db_path))
    feature_cols_ddl = ", ".join(
        f"{col} {'INTEGER' if col in INT_FEATURES else 'DOUBLE'}" for col in FEATURE_COLS
    )
    conn.execute(
        f"""
        CREATE TABLE dim_cards (
            uuid VARCHAR,
            name VARCHAR,
            set_code VARCHAR,
            collector_number VARCHAR,
            edhrec_rank INTEGER,
            is_online_only BOOLEAN
        );
        CREATE TABLE fact_card_features (
            uuid VARCHAR,
            vendor VARCHAR,
            finish VARCHAR,
            price_date DATE,
            current_price DOUBLE,
            sma_7 DOUBLE,
            sma_30 DOUBLE,
            {feature_cols_ddl}
        );
        CREATE TABLE fact_training_dataset (
            uuid VARCHAR,
            vendor VARCHAR,
            finish VARCHAR,
            price_date DATE,
            current_price DOUBLE,
            target_return_7d_pct DOUBLE
        );
        CREATE TABLE fact_arbitrage_opportunities (
            uuid VARCHAR,
            price_date DATE,
            finish VARCHAR,
            tcg_price DOUBLE,
            ck_price DOUBLE,
            price_spread DOUBLE,
            spread_pct DOUBLE
        );
        """
    )

    for idx, (uuid, name, set_code, price, sma_ratio, decay_3d, _, _, _, tgt) in enumerate(
        FIXTURE_CARDS, start=1
    ):
        conn.execute(
            "INSERT INTO dim_cards VALUES (?, ?, ?, ?, ?, false)",
            [uuid, name, set_code, str(idx), 100 * idx],
        )
        feat_values = []
        for col in FEATURE_COLS:
            if col == "sma_ratio":
                feat_values.append(sma_ratio)
            elif col == "price_decay_velocity_3d":
                feat_values.append(decay_3d)
            elif col == "rarity_score":
                feat_values.append(1)
            elif col in INT_FEATURES:
                feat_values.append(0)
            else:
                feat_values.append(0.0)

        placeholders = ", ".join(["?"] * (7 + len(FEATURE_COLS)))
        conn.execute(
            f"INSERT INTO fact_card_features VALUES ({placeholders})",
            [uuid, "consensus", "normal", FIXTURE_DATE, price, price, price, *feat_values],
        )
        conn.execute(
            "INSERT INTO fact_training_dataset VALUES (?, 'consensus', 'normal', ?, ?, ?)",
            [uuid, FIXTURE_DATE, price, tgt],
        )

    conn.execute(
        """
        INSERT INTO fact_arbitrage_opportunities
        VALUES ('uuid-a', ?, 'normal', 10.00, 15.00, 8.59, 78.16)
        """,
        [FIXTURE_DATE],
    )
    conn.close()
    return db_path, model_path


def test_characterize_get_forecast_gates_and_pro_flag(fixture_env, monkeypatch):
    db_path, model_path = fixture_env
    monkeypatch.setattr(api_main, "DB_PATH", db_path)
    monkeypatch.setattr(api_main, "MODEL_PATH", model_path)
    monkeypatch.setattr(api_main, "model_artifact", None)

    with TestClient(api_main.app) as client:
        res_ok = client.get("/api/v1/forecast/uuid-a?finish=normal&is_pro=false")
        assert res_ok.status_code == 200
        ok = res_ok.json()
        assert ok["predicted_7d_price"] == 15.00
        assert ok["expected_net_payout"] == 11.95
        assert ok["net_expected_roi_pct"] == 9.49
        assert ok["allocated_kelly_units"] == 4
        assert ok["is_dead_zone_clamped"] is False
        assert ok["is_defensive_vetoed"] is False
        assert ok["veto_reasons"] == []

        res_pro = client.get("/api/v1/forecast/uuid-a?finish=normal&is_pro=true")
        assert res_pro.status_code == 200
        pro = res_pro.json()
        assert pro["expected_net_payout"] == 11.58
        assert pro["net_expected_roi_pct"] == 6.15
        assert pro["is_defensive_vetoed"] is True
        assert any("Net ROI Below Hurdle" in r for r in pro["veto_reasons"])

        knife = client.get("/api/v1/forecast/uuid-b").json()
        assert knife["is_defensive_vetoed"] is True
        assert any("Falling Knife" in r for r in knife["veto_reasons"])

        floor = client.get("/api/v1/forecast/uuid-c").json()
        assert floor["cqr_lpb"] == -22.0
        assert floor["allocated_kelly_units"] == 0
        assert floor["is_defensive_vetoed"] is True
        assert any("Downside Floor Breach" in r for r in floor["veto_reasons"])

        dead = client.get("/api/v1/forecast/uuid-d").json()
        assert dead["predicted_7d_price"] == 2.56
        assert dead["is_dead_zone_clamped"] is True
        assert dead["expected_net_payout"] == 1.23

        cap = client.get("/api/v1/forecast/uuid-e").json()
        assert cap["allocated_kelly_units"] == 0
        assert cap["is_defensive_vetoed"] is True
        assert any("Capital Ceiling" in r for r in cap["veto_reasons"])


def test_characterize_scan_live_market(fixture_env):
    db_path, model_path = fixture_env
    payload = scan_live_market(
        min_net_roi_pct=8.0,
        min_spread=0.0,
        sizing="kelly",
        is_pro=False,
        db_path=db_path,
        model_path=model_path,
        as_dict=True,
    )

    assert payload["status"] == "success"
    assert payload["funnel"] == {
        "Total Scanned Active SKUs": 5,
        "Stage 1 Spike Mover (τ)": 5,
        "q10 Downside Floor Passed": 4,
        "Set Decay Filter Passed": 3,
        "Net ROI Hurdle Cleared": 1,
    }
    assert [r["uuid"] for r in payload["directional_alpha"]] == ["uuid-a"]
    assert payload["directional_alpha"][0]["allocated_units"] == 4
    assert {r["uuid"] for r in payload["vetoed_traps"]} == {
        "uuid-b",
        "uuid-c",
        "uuid-d",
        "uuid-e",
    }
    assert len(payload["spatial_arbitrage"]) == 1
    assert payload["spatial_arbitrage"][0]["uuid"] == "uuid-a"


def test_characterize_backtest_holdout(fixture_env):
    db_path, model_path = fixture_env
    payload = run_arbitrage_backtest(
        min_net_roi_pct=8.0,
        sizing="kelly",
        is_pro=False,
        db_path=db_path,
        model_path=model_path,
        as_dict=True,
    )

    assert payload["status"] == "success"
    assert payload["summary"]["total_trades"] == 1
    assert payload["summary"]["win_trades"] == 1
    assert payload["summary"]["loss_trades"] == 0
    assert payload["summary"]["total_capital"] == 43.65
    assert payload["summary"]["total_net_profit"] == 5.92
    assert payload["summary"]["portfolio_roi"] == 13.56
    assert payload["top_trades"][0]["uuid"] == "uuid-a"
    assert payload["worst_trades"] == []
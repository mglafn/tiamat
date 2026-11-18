"""
test/test_build_features_characterization.py
--------------------------------------------
Deterministic fixture-DB characterization tests for build_analytical_features()
prior to SQL CTE cleanup and P0 feature engineering fixes.
"""

from datetime import date, timedelta
from pathlib import Path
import duckdb
import pytest

from src.analytics.build_features import build_analytical_features
from src.config import FEATURE_COLS
from src.etl.schema import PRICE_ENUM_DDL


def _insert_price_series(
    conn: duckdb.DuckDBPyConnection,
    uuid: str,
    prices: list[float],
    start: date,
    finish: str = "normal",
) -> None:
    rows = [
        (uuid, "paper", "tcgplayer", "retail", finish, start + timedelta(days=i), p)
        for i, p in enumerate(prices)
    ]
    conn.executemany("INSERT INTO fact_prices VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


@pytest.fixture()
def features_fixture_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "features_fixture.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(PRICE_ENUM_DDL)
    conn.execute(
        """
        CREATE TABLE fact_prices (
            uuid VARCHAR,
            format price_format,
            vendor price_vendor,
            list_type price_list_type,
            finish price_finish,
            price_date DATE,
            price FLOAT
        );
        CREATE TABLE dim_cards (
            uuid VARCHAR,
            name VARCHAR,
            set_code VARCHAR,
            collector_number VARCHAR,
            rarity VARCHAR,
            edhrec_rank INTEGER,
            is_online_only BOOLEAN,
            is_reserved BOOLEAN,
            mana_value DOUBLE,
            card_type VARCHAR,
            original_release_date DATE
        );
        """
    )

    dim_rows = [
        (
            "flat-card",
            "Flat Staple",
            "TST",
            "1",
            "rare",
            100,
            False,
            False,
            2.0,
            "Creature",
            date(2020, 1, 1),
        ),
        (
            "knife-card",
            "Knife Card",
            "TST",
            "2",
            "mythic",
            250,
            False,
            True,
            4.0,
            "Artifact",
            date(2018, 1, 1),
        ),
        (
            "bottom-card",
            "Bottom Card",
            "TST",
            "3",
            "uncommon",
            500,
            False,
            False,
            1.0,
            "Land",
            date(2022, 1, 1),
        ),
    ]
    conn.executemany("INSERT INTO dim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", dim_rows)

    start = date(2026, 9, 1)
    _insert_price_series(conn, "flat-card", [10.0] * 18, start)
    knife_prices = [20.0] * 12 + [19.5, 18.5, 17.0, 15.0, 12.0, 8.5]
    _insert_price_series(conn, "knife-card", knife_prices, start)
    bottom_prices = [20.0] * 12 + [19.0, 16.0, 12.0, 11.8, 11.6, 11.5]
    _insert_price_series(conn, "bottom-card", bottom_prices, start)

    conn.execute(
        "INSERT INTO fact_prices VALUES "
        "('flat-card', 'paper', 'cardkingdom', 'buylist', 'normal', ?, 15.00)",
        [start + timedelta(days=17)],
    )
    conn.close()
    return db_path


def test_characterize_build_analytical_features(features_fixture_db: Path):
    build_analytical_features(db_path=features_fixture_db)

    conn = duckdb.connect(str(features_fixture_db), read_only=True)
    try:
        cols = {row[0] for row in conn.execute("DESCRIBE fact_card_features").fetchall()}
        assert set(FEATURE_COLS).issubset(cols)

        latest_regimes = dict(
            conn.execute(
                """
                SELECT uuid, microstructure_regime
                FROM fact_card_features
                WHERE price_date = DATE '2026-09-18'
                """
            ).fetchall()
        )
        assert latest_regimes["flat-card"] == "NOISE_BOUND"
        assert latest_regimes["knife-card"] == "FALLING_KNIFE"
        assert latest_regimes["bottom-card"] == "CONFIRMED_LOCAL_BOTTOM"

        first_regime = conn.execute(
            """
            SELECT microstructure_regime
            FROM fact_card_features
            WHERE uuid = 'flat-card' AND price_date = DATE '2026-09-01'
            """
        ).fetchone()[0]
        assert first_regime == "INSUFFICIENT_HISTORY"

        flat_target = conn.execute(
            """
            SELECT target_return_7d_pct
            FROM fact_training_dataset
            WHERE uuid = 'flat-card' AND price_date = DATE '2026-09-01'
            """
        ).fetchone()[0]
        assert flat_target == pytest.approx(0.0)

        arb_rows = conn.execute(
            """
            SELECT uuid, tcg_price, ck_price, price_spread, spread_pct
            FROM fact_arbitrage_opportunities
            """
        ).fetchall()
        assert len(arb_rows) == 1
        uuid, tcg_p, ck_p, spread, spread_pct = arb_rows[0]
        assert uuid == "flat-card"
        assert tcg_p == pytest.approx(10.00)
        assert ck_p == pytest.approx(15.00)
        assert spread == pytest.approx(8.51)
        assert spread_pct == pytest.approx(77.43)
    finally:
        conn.close()
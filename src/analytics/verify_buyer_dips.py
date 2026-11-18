"""
src/analytics/verify_buyer_dips.py
-----------------------------------
Holdout & Microstructure Regime Evaluator for Generalist Buyers.
PLACEHOLDER: Evaluates static holdout predictions and SQL regime slices
(does not retrain quantile models across CPCV folds).
"""

import itertools
from pathlib import Path
import sys
import duckdb
import numpy as np
import pandas as pd

from src.analytics.inference import predict_buyer_breakout, try_load_forecast_bundle
from src.cli.reports import render_cpcv_scorecard
from src.config import DB_PATH, EVAL_CONFIG, FEATURE_COLS, MODEL_CONFIG, MODEL_PATH


class PurgedGroupTimeSeriesSplitter:
    """
    Combinatorial Purged Cross-Validation (CPCV) Splitter with Purging & Embargo.
    Generates train/test integer index positions with zero target overlap.
    """

    def __init__(
        self,
        n_groups: int = EVAL_CONFIG["CPCV_N_GROUPS"],
        k_test_groups: int = EVAL_CONFIG["CPCV_K_TEST"],
        purge_horizon: int = EVAL_CONFIG["PURGE_HORIZON_DAYS"],
        embargo_pct: float = 0.02,
    ):
        self.n_groups = n_groups
        self.k_test_groups = k_test_groups
        self.purge_horizon = purge_horizon
        self.embargo_pct = embargo_pct

    def split(self, df: pd.DataFrame, date_column: str = "price_date"):
        dates = pd.to_datetime(df[date_column]).sort_values().unique()
        T = len(dates)
        embargo_length = max(self.purge_horizon, int(np.floor(self.embargo_pct * T)))

        group_bounds = np.array_split(dates, self.n_groups)
        group_indices = list(range(self.n_groups))
        test_combinations = list(itertools.combinations(group_indices, self.k_test_groups))

        for test_groups in test_combinations:
            test_dates_set = set()
            for g in test_groups:
                test_dates_set.update(group_bounds[g])

            test_dates = sorted(list(test_dates_set))
            test_start, test_end = test_dates[0], test_dates[-1]

            purge_start = test_start - pd.Timedelta(days=self.purge_horizon)
            embargo_end = test_end + pd.Timedelta(days=embargo_length)

            train_mask = (df[date_column] < purge_start) | (df[date_column] > embargo_end)
            test_mask = df[date_column].isin(test_dates)

            yield np.where(train_mask)[0], np.where(test_mask)[0]


def run_cpcv_buyer_verification(db_path: Path = DB_PATH, model_path: Path = MODEL_PATH):
    if not db_path.exists():
        print(f"Database not found at {db_path}", file=sys.stderr)
        return

    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])

    conn = duckdb.connect(str(db_path), read_only=True)
    query = f"""
        SELECT
            t.uuid, t.finish, t.price_date, t.current_price, t.target_return_7d_pct,
            f.sma_30, f.microstructure_regime,
            {feature_select_sql},
            COALESCE(d.name, t.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code
        FROM fact_training_dataset t
        JOIN fact_card_features f 
            ON t.uuid = f.uuid AND t.finish = f.finish AND t.price_date = f.price_date
        LEFT JOIN dim_cards d ON t.uuid = d.uuid
        WHERE t.current_price >= 1.00
          AND f.sma_30 IS NOT NULL AND f.sma_30 > 0
        ORDER BY t.price_date ASC
    """
    try:
        df = conn.execute(query).fetchdf()
    except Exception as e:
        conn.close()
        print(f"\n[Database Query Error]: {e}")
        print("Please ensure `python -m src.analytics.build_features` has finished executing.\n")
        return

    conn.close()

    if len(df) == 0:
        print("No records available for backtesting.", file=sys.stderr)
        return

    df["price_date"] = pd.to_datetime(df["price_date"])
    cfg = EVAL_CONFIG

    bundle = try_load_forecast_bundle(model_path)
    buyer_radar_available = bundle is not None and bundle.has_buyer_radar
    oos_cutoff = pd.to_datetime(bundle.split_date) if (bundle and bundle.split_date) else None

    splitter = PurgedGroupTimeSeriesSplitter(
        n_groups=cfg["CPCV_N_GROUPS"],
        k_test_groups=cfg["CPCV_K_TEST"],
        purge_horizon=cfg["PURGE_HORIZON_DAYS"],
    )

    total_floor_entries, floor_held, floor_returns = 0, 0, []
    total_knife_vetoes, knife_bleed, knife_returns = 0, 0, []
    total_radar_alerts, radar_spikes, radar_returns = 0, 0, []
    seen_dates = set()

    for _, test_idx in splitter.split(df, "price_date"):
        test_df = df.iloc[test_idx].copy()
        if len(test_df) == 0:
            continue

        # Deduplicate dates across combinations when CPCV_K_TEST > 1
        test_df = test_df[~test_df["price_date"].isin(seen_dates)]
        if len(test_df) == 0:
            continue
        seen_dates.update(test_df["price_date"].unique())

        # Signal 1: Confirmed Floor (Scale-Invariant Deceleration)
        floor_mask = test_df["microstructure_regime"] == "CONFIRMED_LOCAL_BOTTOM"
        floors = test_df[floor_mask]
        total_floor_entries += len(floors)
        floor_held += int((floors["target_return_7d_pct"] >= cfg["SUPPORT_CUSHION_PCT"]).sum())
        floor_returns.extend(floors["target_return_7d_pct"].tolist())

        # Signal 2: True Falling Knife (Scale-Invariant Downward Acceleration)
        knife_mask = test_df["microstructure_regime"] == "FALLING_KNIFE"
        knives = test_df[knife_mask]
        total_knife_vetoes += len(knives)
        knife_bleed += int((knives["target_return_7d_pct"] < 0.0).sum())
        knife_returns.extend(knives["target_return_7d_pct"].tolist())

        # Signal 3: Buyer Radar Pre-Spike Breakout (strictly OOS >= split_date to prevent training/calib leakage)
        if buyer_radar_available and bundle is not None:
            oos_df = (
                test_df[test_df["price_date"] >= oos_cutoff] if oos_cutoff is not None else test_df
            )
            if len(oos_df) > 0:
                X_test_sub = oos_df[list(bundle.feature_cols)].fillna(0.0)
                calibrated_p, _ = predict_buyer_breakout(bundle, X_test_sub)
                spike_alerts = oos_df[calibrated_p >= bundle.tau_buyer_radar]
                total_radar_alerts += len(spike_alerts)
                radar_spikes += int(
                    (
                        spike_alerts["target_return_7d_pct"] >= MODEL_CONFIG["SPIKE_THRESHOLD_PCT"]
                    ).sum()
                )
                radar_returns.extend(spike_alerts["target_return_7d_pct"].tolist())
    floor_acc = (floor_held / max(1, total_floor_entries)) * 100.0
    floor_avg = np.mean(floor_returns) if floor_returns else 0.0
    knife_acc = (knife_bleed / max(1, total_knife_vetoes)) * 100.0
    knife_avg = np.mean(knife_returns) if knife_returns else 0.0
    radar_acc = (
        (radar_spikes / max(1, total_radar_alerts)) * 100.0 if total_radar_alerts > 0 else 0.0
    )
    radar_avg = np.mean(radar_returns) if radar_returns else 0.0

    floor_df_all = df[df["microstructure_regime"] == "CONFIRMED_LOCAL_BOTTOM"]
    buyer_alpha = (
        (
            (
                (floor_df_all["sma_30"] - floor_df_all["current_price"]) / floor_df_all["sma_30"]
            ).mean()
            * 100.0
        )
        if len(floor_df_all) > 0
        else 0.0
    )
    dar = (
        (np.array(floor_returns) > cfg["DRAWDOWN_TOLERANCE_PCT"]).mean() * 100.0
        if floor_returns
        else 0.0
    )
    fir = (
        (np.array(floor_returns) >= cfg["SUPPORT_CUSHION_PCT"]).mean() * 100.0
        if floor_returns
        else 0.0
    )

    render_cpcv_scorecard(
        total_instances=len(df),
        total_floor_entries=total_floor_entries,
        floor_acc=floor_acc,
        floor_avg=floor_avg,
        total_knife_vetoes=total_knife_vetoes,
        knife_acc=knife_acc,
        knife_avg=knife_avg,
        total_radar_alerts=total_radar_alerts,
        radar_acc=radar_acc,
        radar_avg=radar_avg,
        buyer_alpha=buyer_alpha,
        dar=dar,
        fir=fir,
        cfg=cfg,
    )


if __name__ == "__main__":
    run_cpcv_buyer_verification(DB_PATH, MODEL_PATH)

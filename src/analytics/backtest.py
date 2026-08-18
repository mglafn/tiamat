"""
Out-of-time backtesting engine for TCGplayer Direct / SYP arbitrage strategies.

Simulates execution across held-out historical partitions against our two-stage
XGBoost model. Accounts for real marketplace friction:
  - Piecewise fee tiers and dead-zone price clamping ($2.50 - $2.67)
  - Louisville hub grading downgrade risk (kappa_risk)
  - Inbound postage tiers and amortized freight
"""

import sys
import argparse
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"


def calculate_direct_payout_series(
    prices: pd.Series, 
    tax_rate: float = 0.075, 
    clamp_dead_zone: bool = True,
    is_pro: bool = False
) -> pd.Series:
    """
    Computes net seller payout under TCGplayer Direct rate rules.

    Fee structure:
      - P < $0.40: Ineligible ($0.00)
      - $0.40 <= P <= $2.49: 50% flat fee (commissions and processing waived)
      - $2.50 <= P <= $2.67: Dead zone where higher gross yields lower net.
        If clamp_dead_zone=True, peg exit to $2.49 to avoid the fee cliff.
      - P >= $2.50: $1.12 flat + 8.95% commission (capped at $75) + 2.5% processing on gross with tax.
    """
    p = prices.copy().astype(float)

    if clamp_dead_zone:
        # In [$2.50, $2.67], net payout is lower than selling at $2.49 due to the $1.12 fixed fee.
        p = np.where((p >= 2.50) & (p <= 2.67), 2.49, p)

    # Sub-$2.50 Tier (50% flat fee, Banker's rounding)
    sub_tier_fee = np.round(p * 0.50, 2)
    sub_tier_payout = p - sub_tier_fee

    # $2.50+ Tier ($1.12 fixed + 8.95% commission + 2.5% processing on gross total)
    commission = np.minimum(p * 0.0895, 75.00)
    pro_fee = np.minimum(p * 0.025, 75.00) if is_pro else 0.0
    
    gross_total = p * (1.0 + tax_rate)
    processing = gross_total * 0.025
    
    standard_fee = np.round(1.12 + commission + pro_fee + processing, 2)
    standard_payout = p - standard_fee

    payout = np.where(
        p < 0.40, 
        0.0, 
        np.where(p < 2.50, sub_tier_payout, standard_payout)
    )
    return np.maximum(0.0, payout)


def calculate_condition_risk_haircut(
    direct_price: pd.Series,
    acq_cost: pd.Series,
    downgrade_rate: float = 0.035,
    reject_rate: float = 0.005,
    salvage_factor: float = 0.75
) -> pd.Series:
    """
    Computes kappa_risk haircut factor to adjust expected payouts for grading downgrades.
    
    Models historical failure rates during Louisville intake:
      - 3.5% NM -> LP/MP downgrade (replacement fee debited, downgraded card salvaged to SEI)
      - 0.5% outright rejection / damaged / counter-pick
    """
    safe_direct = np.maximum(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = safe_direct / safe_direct
    
    kappa_risk = 1.0 - (downgrade_rate * np.maximum(0.0, downgrade_penalty) + reject_rate * reject_penalty)
    return np.clip(kappa_risk, 0.80, 1.00)


def run_arbitrage_backtest(min_net_roi_pct: float = 10.0, db_path: Path = DB_PATH, model_path: Path = MODEL_PATH):
    print(f"Running backtest (Target Net ROI >= {min_net_roi_pct:.1f}%)...")

    if not model_path.exists() or not db_path.exists():
        print(f"Error: Missing database ({db_path}) or model artifact ({model_path}). Run pipeline first.")
        return

    artifact = joblib.load(model_path)
    classifier = artifact["classifier"]
    regressor = artifact["regressor"]
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    prob_threshold = metrics.get("prob_threshold", 0.87)
    persisted_split_date = metrics.get("split_date", None)

    # 1. Pull labeled historical features
    conn = duckdb.connect(str(db_path), read_only=True)
    query = """
        SELECT 
            t.uuid,
            t.price_date,
            t.current_price,
            t.target_return_7d_pct,
            t.sma_ratio,
            t.volatility_14d,
            t.daily_return_pct,
            t.velocity_7d_pct,
            t.bid_ask_spread_pct,
            t.spread_velocity_7d,
            t.vendor_delta_7d,
            t.is_foil,
            t.is_reserved,
            t.mana_value,
            t.popularity_score,
            t.is_land,
            t.is_creature,
            t.asset_age_years,
            t.rarity_score,
            d.name,
            d.set_code
        FROM fact_training_dataset t
        LEFT JOIN dim_cards d ON t.uuid = d.uuid
        WHERE t.current_price >= 0.40
        ORDER BY t.price_date ASC
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    df['price_date'] = pd.to_datetime(df['price_date'])

    # 2. Isolate out-of-time test partition (honoring 14-day anti-leakage embargo)
    if persisted_split_date:
        test_start_date = pd.to_datetime(persisted_split_date)
    else:
        val_idx = int(len(df) * 0.85)
        test_start_date = df.loc[val_idx, 'price_date'] + pd.Timedelta(days=14)

    test_df = df[df['price_date'] >= test_start_date].copy().reset_index(drop=True)
    print(f"Test window: {test_start_date.date()} to {test_df['price_date'].max().date()} ({len(test_df):,} rows)")

    # 3. Model inference on test partition
    X_test = test_df[feature_cols].fillna(0.0)
    move_probs = classifier.predict_proba(X_test)[:, 1]
    predicted_magnitudes = regressor.predict(X_test)

    test_df['move_prob'] = move_probs
    test_df['pred_return_7d'] = np.where(move_probs >= prob_threshold, predicted_magnitudes, 0.0)
    test_df['actual_future_price'] = test_df['current_price'] * (1.0 + test_df['target_return_7d_pct'] / 100.0)

    # 4. Landed unit economics & friction modeling
    inbound_postage = np.where(test_df['current_price'] < 5.00, 0.99, 0.15)
    hub_freight = 0.012  # Amortized bulk freight per card to Louisville hub

    test_df['acquisition_cost'] = (test_df['current_price'] * 1.075) + inbound_postage + hub_freight
    test_df['expected_future_price'] = test_df['current_price'] * (1.0 + test_df['pred_return_7d'] / 100.0)

    raw_expected_payout = calculate_direct_payout_series(test_df['expected_future_price'], clamp_dead_zone=True)
    kappa_risk = calculate_condition_risk_haircut(test_df['expected_future_price'], test_df['acquisition_cost'])
    
    test_df['expected_net_payout'] = raw_expected_payout * kappa_risk
    test_df['expected_net_roi_pct'] = (
        (test_df['expected_net_payout'] - test_df['acquisition_cost']) / test_df['acquisition_cost']
    ) * 100.0

    # 5. Filter signals that clear hurdle
    buy_signals = test_df[
        (test_df['expected_net_roi_pct'] >= min_net_roi_pct) & 
        (test_df['pred_return_7d'] > 0.0)
    ].copy()

    if len(buy_signals) == 0:
        print(f"No trade signals met the net expected ROI hurdle of {min_net_roi_pct:.1f}%.")
        return

    # Compute realized returns
    raw_realized_payout = calculate_direct_payout_series(buy_signals['actual_future_price'], clamp_dead_zone=True)
    realized_kappa = calculate_condition_risk_haircut(buy_signals['actual_future_price'], buy_signals['acquisition_cost'])
    
    buy_signals['realized_exit_payout'] = raw_realized_payout * realized_kappa
    buy_signals['net_profit'] = buy_signals['realized_exit_payout'] - buy_signals['acquisition_cost']
    buy_signals['net_roi_pct'] = (buy_signals['net_profit'] / buy_signals['acquisition_cost']) * 100.0
    buy_signals['is_win'] = buy_signals['net_profit'] > 0

    # 6. Aggregate summary metrics
    total_trades = len(buy_signals)
    win_trades = int(buy_signals['is_win'].sum())
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0
    total_capital = buy_signals['acquisition_cost'].sum()
    total_net_profit = buy_signals['net_profit'].sum()
    portfolio_roi = (total_net_profit / total_capital) * 100.0
    avg_trade_roi = buy_signals['net_roi_pct'].mean()

    gross_gains = buy_signals[buy_signals['net_profit'] > 0]['net_profit'].sum()
    gross_losses = abs(buy_signals[buy_signals['net_profit'] < 0]['net_profit'].sum())
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else float('inf')

    print("\n--- Backtest Summary (Direct / SYP) ---")
    print(f"Target ROI Hurdle        : >= {min_net_roi_pct:.1f}%")
    print(f"Model Confidence Cutoff  : {prob_threshold:.2f}")
    print(f"Triggered Trades         : {total_trades:,} ({total_trades / len(test_df) * 100:.3f}% of test universe)")
    print(f"Win / Loss Count         : {win_trades} wins ({win_rate:.1f}%) / {loss_trades} losses")
    print(f"Capital Deployed         : ${total_capital:,.2f}")
    print(f"Net Realized Profit      : ${total_net_profit:,.2f}")
    print(f"Portfolio Net ROI        : {portfolio_roi:+.2f}%")
    print(f"Average ROI per Trade    : {avg_trade_roi:+.2f}%")
    print(f"Profit Factor            : {profit_factor:.2f}")

    top_trades = buy_signals.sort_values(by='net_profit', ascending=False).head(5)
    print("\nTop 5 Realized Trades:")
    for _, trade in top_trades.iterrows():
        name = trade['name'] or trade['uuid']
        set_code = trade['set_code'] or "OTC"
        print(f"  + {name} ({set_code}): basis ${trade['acquisition_cost']:.2f} -> payout ${trade['realized_exit_payout']:.2f} | net: +${trade['net_profit']:.2f} ({trade['net_roi_pct']:+.1f}%)")

    worst_trades = buy_signals.sort_values(by='net_profit', ascending=True).head(3)
    if len(worst_trades) > 0 and worst_trades.iloc[0]['net_profit'] < 0:
        print("\nLargest Drawdown Trades:")
        for _, trade in worst_trades.iterrows():
            if trade['net_profit'] >= 0:
                continue
            name = trade['name'] or trade['uuid']
            set_code = trade['set_code'] or "OTC"
            print(f"  - {name} ({set_code}): basis ${trade['acquisition_cost']:.2f} -> payout ${trade['realized_exit_payout']:.2f} | net: -${abs(trade['net_profit']):.2f} ({trade['net_roi_pct']:+.1f}%)")
    print("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run out-of-time backtest on Direct/SYP arbitrage")
    parser.add_argument("--hurdle", type=float, default=10.0, help="Minimum expected net ROI %% hurdle (default: 10.0)")
    args = parser.parse_args()

    run_arbitrage_backtest(min_net_roi_pct=args.hurdle)
"""
src/config.py
-------------
Centralized Configuration and Single Source of Truth for Tiamat Quant Terminal.
Houses system paths, microstructural thresholds, model hyperparameters, and fee rate cards.
"""

import os
from pathlib import Path
from typing import NamedTuple, Union

# =====================================================================
# 1. CORE SYSTEM PATHS
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
MODELS_DIR = BASE_DIR / "models"

DB_PATH = DATA_DIR / "mtg_prices.duckdb"
PRUNE_TEMP_DB_PATH = DATA_DIR / "mtg_prices_unpruned_tmp.duckdb"
LEGACY_FULL_DB_PATH = DATA_DIR / "mtg_prices_full.duckdb"
MODEL_PATH = MODELS_DIR / "xgboost_forecast.joblib"

ALL_PRICES_XZ_PATH = RAW_DATA_DIR / "AllPrices.json.xz"
ALL_PRICES_JSON_PATH = RAW_DATA_DIR / "AllPrices.json"
CARDS_CSV_PATH = RAW_DATA_DIR / "cards.csv"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
# 2. FEATURE ENGINEERING & SCALE-INVARIANT MICROSTRUCTURE
# =====================================================================
MICROSTRUCTURE_CONFIG = {
    # Discrete minimum listing increment in USD (prevents zero-MAD denominator collapse)
    "MIN_TICK_USD": float(os.getenv("MIN_TICK_USD", 0.01)),
    # Statistical Z-score thresholds for Downside Z
    "KNIFE_Z_SCORE_THRESH": float(os.getenv("KNIFE_Z_SCORE_THRESH", -1.96)),
    "BOTTOM_Z_SCORE_THRESH": float(os.getenv("BOTTOM_Z_SCORE_THRESH", -1.28)),
    "NOISE_Z_SCORE_BOUND": float(os.getenv("NOISE_Z_SCORE_BOUND", 1.00)),
    # Exhaustion ratio cutoff (eta = a_t / (|v_t| + eps))
    "MIN_EXHAUSTION_RATIO": float(os.getenv("MIN_EXHAUSTION_RATIO", 0.25)),
}


# =====================================================================
# 3. DUAL-PERSONA PREDICTIVE ENGINE HYPERPARAMETERS
# =====================================================================
MODEL_CONFIG = {
    "QUANTILES": [0.10, 0.50, 0.90],
    # PLACEHOLDER: Unified right-tail spike target across training, scanning, and evaluation
    "SPIKE_THRESHOLD_PCT": float(os.getenv("SPIKE_THRESHOLD_PCT", 12.0)),
    "FLIPPER_FEE_HURDLE_PCT": float(os.getenv("FLIPPER_FEE_HURDLE_PCT", 15.0)),
    "Q10_FLOOR_PCT": float(os.getenv("Q10_FLOOR_PCT", -15.0)),
    "DECAY_VELOCITY_FLOOR_PCT": float(os.getenv("DECAY_VELOCITY_FLOOR_PCT", -0.5)),
    "DEFAULT_ROI_HURDLE_PCT": float(os.getenv("DEFAULT_ROI_HURDLE_PCT", 8.0)),
    "F_BETA_RECALL_WEIGHT": float(os.getenv("F_BETA_RECALL_WEIGHT", 2.0)),
    "EMBARGO_DAYS": int(os.getenv("EMBARGO_DAYS", 14)),
}


class FeatureSpec(NamedTuple):
    name: str
    dtype: type
    default: Union[float, int]


# Single source of truth for model features, inference types, and NaN defaults
FEATURE_SPECS = (
    FeatureSpec("sma_ratio", float, 1.0),
    FeatureSpec("volatility_14d", float, 0.0),
    FeatureSpec("daily_return_pct", float, 0.0),
    FeatureSpec("velocity_7d_pct", float, 0.0),
    FeatureSpec("bid_ask_spread_pct", float, 1.0),
    FeatureSpec("spread_velocity_7d", float, 0.0),
    FeatureSpec("vendor_delta_7d", float, 0.0),
    FeatureSpec("price_decay_velocity_3d", float, 0.0),
    FeatureSpec("amihud_illiquidity_30d", float, 0.0),
    FeatureSpec("z_downside_3d", float, 0.0),
    FeatureSpec("velocity_3d", float, 0.0),
    FeatureSpec("accel_3d", float, 0.0),
    FeatureSpec("exhaustion_ratio", float, 0.0),
    FeatureSpec("is_foil", int, 0),
    FeatureSpec("is_reserved", int, 0),
    FeatureSpec("mana_value", float, 0.0),
    FeatureSpec("popularity_score", float, 0.0),
    FeatureSpec("is_land", int, 0),
    FeatureSpec("is_creature", int, 0),
    FeatureSpec("asset_age_years", float, 0.0),
    FeatureSpec("rarity_score", int, 1),
)

FEATURE_COLS = [spec.name for spec in FEATURE_SPECS]
FEATURE_SCHEMA = {spec.name: (spec.dtype, spec.default) for spec in FEATURE_SPECS}

# PLACEHOLDER (HQ-02): Fixed capital/unit caps pending real volume/depth liquidity policy
SIZING_CONFIG = {
    "PORTFOLIO_EQUITY_USD": float(os.getenv("PORTFOLIO_EQUITY_USD", 10000.0)),
    "MAX_POSITION_DOLLARS": float(os.getenv("MAX_POSITION_DOLLARS", 50.0)),
    "MAX_UNITS_PER_ASSET": int(os.getenv("MAX_UNITS_PER_ASSET", 4)),
}


# =====================================================================
# 4. BUYER STRATEGY & CPCV SCORECARD TOLERANCES
# =====================================================================
EVAL_CONFIG = {
    "CPCV_N_GROUPS": int(os.getenv("CPCV_N_GROUPS", 5)),
    "CPCV_K_TEST": int(os.getenv("CPCV_K_TEST", 1)),
    "PURGE_HORIZON_DAYS": int(os.getenv("PURGE_HORIZON_DAYS", MODEL_CONFIG["EMBARGO_DAYS"])),
    "SUPPORT_CUSHION_PCT": float(os.getenv("SUPPORT_CUSHION_PCT", -2.5)),
    "DRAWDOWN_TOLERANCE_PCT": float(os.getenv("DRAWDOWN_TOLERANCE_PCT", -5.0)),
}


# =====================================================================
# 5. MARKETPLACE RATE CARDS & PHYSICAL FRICTIONS
# =====================================================================
FEE_CONFIG = {
    "STANDARD_COMMISSION": 0.1075,
    "DIRECT_COMMISSION": 0.0895,
    "PRO_FEE": 0.025,
    "COMMISSION_CAP_USD": 75.00,
    "PROCESSING_RATE": 0.025,
    "PROCESSING_FIXED_USD": 0.30,
    "DIRECT_FIXED_USD": 1.12,
    "DIRECT_FLOOR_USD": 0.40,
    "DIRECT_TIER1_MAX_USD": 2.49,
    "DIRECT_TIER1_RATE": 0.50,
    "DIRECT_DEAD_ZONE_MIN": 2.50,
    "DIRECT_DEAD_ZONE_MAX": 2.67,
    "DIRECT_DEAD_ZONE_MAX_PRO": 2.75,
    "INBOUND_POSTAGE_LOW_USD": 0.99,
    "INBOUND_POSTAGE_HIGH_USD": 0.15,
    "INBOUND_POSTAGE_THRESHOLD_USD": 5.00,
    "HUB_FREIGHT_USD": 0.012,
    "OUTBOUND_BATCH_FREIGHT_USD": 0.09,
    "DEFAULT_TAX_RATE": 0.075,
    "STORE_CREDIT_MULTIPLIER": 1.30,
}

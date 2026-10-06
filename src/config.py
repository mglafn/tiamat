"""
src/config.py
-------------
Centralized Configuration and Single Source of Truth for Tiamat Quant Terminal.
Houses system paths, microstructural thresholds, model hyperparameters, and fee rate cards.
"""

import os
from pathlib import Path

# =====================================================================
# 1. CORE SYSTEM PATHS
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
MODELS_DIR = BASE_DIR / "models"

DB_PATH = DATA_DIR / "mtg_prices.duckdb"
MODEL_PATH = MODELS_DIR / "xgboost_forecast.joblib"

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
    "SPIKE_THRESHOLD_PCT": float(os.getenv("SPIKE_THRESHOLD_PCT", 12.0)),
    "FLIPPER_FEE_HURDLE_PCT": float(os.getenv("FLIPPER_FEE_HURDLE_PCT", 15.0)),
    "F_BETA_RECALL_WEIGHT": float(os.getenv("F_BETA_RECALL_WEIGHT", 2.0)),
    "EMBARGO_DAYS": int(os.getenv("EMBARGO_DAYS", 14)),
}

# Core feature schema used across training, API inference, and scanning
FEATURE_COLS = [
    'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
    'bid_ask_spread_pct', 'spread_velocity_7d', 'vendor_delta_7d',
    'price_decay_velocity_3d', 'amihud_illiquidity_30d',
    'z_downside_3d', 'velocity_3d', 'accel_3d', 'exhaustion_ratio',
    'is_foil', 'is_reserved', 'mana_value', 'popularity_score',
    'is_land', 'is_creature', 'asset_age_years', 'rarity_score'
]


# =====================================================================
# 4. BUYER STRATEGY & CPCV SCORECARD TOLERANCES
# =====================================================================
EVAL_CONFIG = {
    "CPCV_N_GROUPS": int(os.getenv("CPCV_N_GROUPS", 5)),
    "CPCV_K_TEST": int(os.getenv("CPCV_K_TEST", 1)),
    "PURGE_HORIZON_DAYS": int(os.getenv("PURGE_HORIZON_DAYS", 14)),
    "SUPPORT_CUSHION_PCT": float(os.getenv("SUPPORT_CUSHION_PCT", -2.5)),
    "DRAWDOWN_TOLERANCE_PCT": float(os.getenv("DRAWDOWN_TOLERANCE_PCT", -5.0)),
    "SPIKE_TARGET_PCT": float(os.getenv("SPIKE_TARGET_PCT", 8.0)),
}


# =====================================================================
# 5. MARKETPLACE RATE CARDS & PHYSICAL FRICTIONS
# =====================================================================
FEE_CONFIG = {
    "STANDARD_COMMISSION": 0.1075,
    "PRO_COMMISSION": 0.0895,
    "COMMISSION_CAP_USD": 75.00,
    "PROCESSING_RATE": 0.025,
    "PROCESSING_FIXED_USD": 0.30,
    "DIRECT_FIXED_USD": 1.12,
    "DEFAULT_TAX_RATE": 0.075,
    "STORE_CREDIT_MULTIPLIER": 1.30,
    "INTAKE_DOWNGRADE_RATE": 0.035,
    "INTAKE_REJECT_RATE": 0.005,
    "SALVAGE_FACTOR": 0.75,
}
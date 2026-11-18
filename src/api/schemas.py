"""
src/api/schemas.py
------------------
Pydantic response schemas for the Tiamat FastAPI microservice.
"""

from typing import List, Optional
from pydantic import BaseModel


class HealthCheck(BaseModel):
    status: str
    db_connected: bool
    model_loaded: bool


class CatalogCard(BaseModel):
    uuid: str
    name: str
    set_code: str
    collector_number: Optional[str] = None


class CardVariant(BaseModel):
    uuid: str
    set_code: str
    collector_number: Optional[str] = None
    floor_price: Optional[float] = None
    edhrec_rank: Optional[int] = None


class PriceHistoryPoint(BaseModel):
    price_date: str
    price: float
    sma_7: Optional[float] = None
    sma_30: Optional[float] = None
    daily_return_pct: Optional[float] = None


class ArbitrageOpportunity(BaseModel):
    uuid: str
    name: Optional[str] = "Unknown Asset"
    set_code: Optional[str] = "OTC"
    collector_number: Optional[str] = None
    price_date: str
    finish: str
    tcg_price: float
    ck_price: float
    price_spread: float
    spread_pct: float


class PredictionResponse(BaseModel):
    uuid: str
    vendor: str
    finish: str
    current_price: float
    predicted_7d_price: float
    predicted_gain_pct: float
    model_mae: float
    move_prob: float
    cqr_lpb: float
    price_decay_velocity_3d: float
    amihud_illiquidity_30d: float
    directional_accuracy_pct: Optional[float] = None
    expected_net_payout: Optional[float] = None
    net_expected_roi_pct: Optional[float] = None
    is_dead_zone_clamped: Optional[bool] = None
    kappa_risk: Optional[float] = None
    allocated_kelly_units: int = 1
    is_defensive_vetoed: bool = False
    veto_reasons: List[str] = []


class CardMarketSummary(BaseModel):
    uuid: str
    name: str = "Unknown Asset"
    set_code: str = "OTC"
    collector_number: Optional[str] = None
    edhrec_rank: Optional[int] = None
    latest_price_date: Optional[str] = None
    total_market_variants: int = 1
    floor_price: Optional[float] = None
    avg_price: Optional[float] = None
    ceiling_price: Optional[float] = None
    primary_vendor: Optional[str] = None
    primary_finish: Optional[str] = None
    predicted_7d_price: Optional[float] = None
    predicted_gain_pct: Optional[float] = None


class CardSearchResult(BaseModel):
    uuid: str
    name: str
    set_code: str
    collector_number: Optional[str] = None
    finish: str
    floor_price: float
    avg_price: float
    vendor_count: int

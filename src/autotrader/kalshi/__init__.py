"""Disabled-by-default Kalshi event-intelligence foundation.

This package is deliberately not imported by the paper runtime. It provides
read-only research primitives for Kalshi calibration, cross-market attribution,
and a future Demo integration. Nothing exported here grants broker control.
"""

from .config import KalshiConfig
from .features import probability_features
from .learning_bridge import KalshiLearningFeature, learning_features_from_observation
from .learning_tree import (
    CalibrationPoint,
    CrossMarketLearningNode,
    LeadLagPoint,
    build_learning_node,
    calibration_summary,
    candidate_feature_weight,
    cross_pillar_targets,
    lead_lag_summary,
)
from .models import KalshiEvent, KalshiMarket

__all__ = [
    "CalibrationPoint",
    "CrossMarketLearningNode",
    "KalshiConfig",
    "KalshiEvent",
    "KalshiLearningFeature",
    "KalshiMarket",
    "LeadLagPoint",
    "build_learning_node",
    "calibration_summary",
    "candidate_feature_weight",
    "cross_pillar_targets",
    "lead_lag_summary",
    "learning_features_from_observation",
    "probability_features",
]

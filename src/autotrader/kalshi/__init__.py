"""Disabled-by-default Kalshi event-intelligence foundation.

This package is deliberately not imported by the paper runtime.  It provides
read-only research primitives for a future Demo integration.
"""

from .config import KalshiConfig
from .features import probability_features
from .models import KalshiEvent, KalshiMarket

__all__ = ["KalshiConfig", "KalshiEvent", "KalshiMarket", "probability_features"]

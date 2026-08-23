from __future__ import annotations

from dataclasses import dataclass

from .config import KalshiConfig


@dataclass(frozen=True)
class KalshiPaperStrategy:
    """Future execution contract.  Submission is intentionally impossible."""

    config: KalshiConfig

    def candidates(self): return ()
    def submit(self, *args, **kwargs):
        raise RuntimeError("Kalshi execution is disabled; this foundation is research-only")

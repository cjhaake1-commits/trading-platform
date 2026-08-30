"""Continuous research-only intelligence lifecycle with no execution dependency."""
from __future__ import annotations

from datetime import UTC, datetime

from .corporate_features import derive_features
from .intelligence_fusion import CorporateFeatureSnapshot, IntelligenceFusionEngine, MarketConfirmationSnapshot
from .intelligence_persistence import IntelligencePersistence
from .research_universe import ResearchUniverse
from .sec_edgar import normalize_filing
from .social_market_intelligence import SocialMarketSnapshot


class IntelligenceOrchestrator:
    VERSION = "intelligence-tree-v1"
    def __init__(self, store, *, universe: ResearchUniverse | None = None):
        self.persistence = IntelligencePersistence(store)
        self.universe = universe or ResearchUniverse.configured()
        self.fusion = IntelligenceFusionEngine()

    def ingest_filing(self, payload, *, raw: bytes | str = b"", retrieved_at: str | None = None) -> dict[str, object]:
        filing = normalize_filing(payload, raw=raw)
        record = filing.record(retrieved_at=retrieved_at)
        self.persistence.observation(record)
        features = derive_features(filing.facts, effective_at=filing.filed_at)
        for name, value in features.items():
            if isinstance(value, (int, float)):
                self.persistence.feature(symbol=filing.cik, name=f"corporate.{name}", value=float(value), experiment_id=record["research_id"])
        return record

    def run_once(self, *, now: datetime | None = None) -> dict[str, object]:
        observed = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        for security in self.universe.records():
            symbol = str(security["symbol"])
            social = SocialMarketSnapshot(symbol=symbol, observed_at=datetime.fromisoformat(observed),
                                          mention_count=0, unique_authors=0, platforms=0, sentiment=0.0,
                                          attention_score=0.0, velocity_score=0.0, influencer_score=0.0,
                                          cross_platform_score=0.0, manipulation_risk=0.0, research_signal=0.0)
            fusion = self.fusion.fuse(social, CorporateFeatureSnapshot(symbol=symbol, observed_at=datetime.fromisoformat(observed)),
                                      MarketConfirmationSnapshot(symbol=symbol, observed_at=datetime.fromisoformat(observed)))
            self.persistence.observation({"research_id": f"fusion:{symbol}:{observed}", "lane": "intelligence_fusion",
                "source": "INTELLIGENCE_FUSION", "source_type": "DERIVED", "as_of_date": observed,
                "retrieved_at": observed, "freshness": "FRESH", "instrument": symbol,
                "signal_type": "FUSION", "signal_value": fusion.anomaly_priority, "confidence": 0.0,
                "metadata_json": {"fusion": fusion.__dict__, "universe": security, "feature_version": self.VERSION,
                                  "execution_authorized": False}, "paper_shadow_status": "RESEARCH_ONLY",
                "promotion_status": "OBSERVING", "model_weight": 0.0, "broker_control": 0})
        return {"observed_at": observed, "universe_size": len(self.universe.securities),
                "fusion_observations": len(self.universe.securities), "execution_authorized": False,
                "research_only": True}

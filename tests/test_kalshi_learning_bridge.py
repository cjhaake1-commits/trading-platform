from autotrader.kalshi.learning_bridge import (
    KalshiLearningFeature,
    learning_features_from_observation,
    persist_learning_features,
)


class Sink:
    def __init__(self):
        self.features = []
        self.attributions = []

    def put_feature(self, **kwargs):
        self.features.append(kwargs)

    def put_attribution(self, **kwargs):
        self.attributions.append(kwargs)


def test_only_namespaced_numeric_kalshi_features_are_admitted():
    features = learning_features_from_observation(
        {
            "family": "predictions",
            "quality": "FRESH",
            "market_ticker": "FED-TEST",
            "payload": {
                "kalshi.implied_probability": 0.62,
                "kalshi.probability_change": 0.07,
                "not_kalshi": 100,
                "kalshi.invalid": "not-a-number",
            },
        }
    )
    assert [item.name for item in features] == [
        "kalshi.implied_probability",
        "kalshi.probability_change",
    ]
    assert all(item.family == "predictions" for item in features)


def test_unknown_family_is_rejected():
    assert learning_features_from_observation({"family": "live_execution", "kalshi.edge": 1}) == []


def test_persisted_kalshi_features_are_zero_weight_research_only():
    sink = Sink()
    count = persist_learning_features(
        sink,
        observation_id="obs-1",
        experiment_id="five_pillar_paper_v2",
        symbol="SPY",
        pillar="Stocks",
        regime="risk_off",
        confidence=0.8,
        features=[
            KalshiLearningFeature(
                name="kalshi.implied_probability",
                value=0.61,
                freshness="FRESH",
                family="predictions",
            )
        ],
    )
    assert count == 1
    assert sink.features[0]["source"] == "kalshi"
    attribution = sink.attributions[0]
    assert attribution["feature_weight"] == 0.0
    assert attribution["decision"] == "research_only"
    assert attribution["model"] == "kalshi_research_candidate_v1"
    assert attribution["outcome"] is None
    assert attribution["realized_contribution"] is None

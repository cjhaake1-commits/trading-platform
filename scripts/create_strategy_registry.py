#!/usr/bin/env python3
"""Materialize the initial multi-pillar paper strategy registry."""
from __future__ import annotations

import json

from autotrader.strategy_registry import StrategyRegistry, default_strategy_definitions


def main() -> None:
    registry = StrategyRegistry()
    for definition in default_strategy_definitions():
        registry.register(definition)
    print(json.dumps({"registry_id": "STRATEGY_REGISTRY_V1", "strategies": len(registry.definitions), "path": str(registry.path)}))


if __name__ == "__main__":
    main()

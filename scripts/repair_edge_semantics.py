#!/usr/bin/env python3
"""Relabel legacy candidate-score economics as research proxies, fail closed."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def repair(db_path: str = "var/autotrader/paper_experiment.db") -> int:
    path = Path(db_path)
    if not path.exists():
        return 0
    changed = 0
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT event_id, strategy, estimated_edge, expected_value, features_json FROM activity_observations "
            "WHERE estimated_edge IS NOT NULL OR expected_value IS NOT NULL"
        ).fetchall()
        for event_id, strategy, edge, ev, raw_features in rows:
            try:
                features = json.loads(raw_features or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(features, dict) or not str(strategy).startswith("crypto."):
                continue
            features["edge_proxy"] = edge
            features["ev_proxy"] = ev
            features["edge_semantics"] = "EDGE_PROXY"
            features["ev_semantics"] = "EV_PROXY"
            connection.execute(
                "UPDATE activity_observations SET estimated_edge=NULL, expected_value=NULL, features_json=? WHERE event_id=?",
                (json.dumps(features, sort_keys=True), event_id),
            )
            changed += 1
        connection.commit()
    return changed


if __name__ == "__main__":
    print(repair())

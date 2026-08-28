"""Freeze the current verified Crypto cohort before research changes."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    source = Path("var/autotrader/learning/crypto-loss-attribution.json")
    report = json.loads(source.read_text(encoding="utf-8"))
    benchmark = json.loads(Path("var/autotrader/learning/crypto-btc-benchmark.json").read_text(encoding="utf-8"))
    report["cohort"] = "BASELINE_COHORT_V1"
    report["btc_benchmark_coverage"] = benchmark.get("coverage", 0.0)
    report["btc_mean_excess_return"] = sum(r.get("excess_return", 0.0) or 0.0 for r in benchmark.get("rows", [])) / len(benchmark.get("rows", [])) if benchmark.get("rows") else None
    output = Path("var/autotrader/learning/crypto-baseline-cohort-v1.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sample_size": report.get("sample_size"), "btc_coverage": report.get("btc_benchmark_coverage")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

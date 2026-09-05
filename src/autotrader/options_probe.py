"""Evidence-based options capability probe for existing adapters."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json


@dataclass(frozen=True)
class OptionCapability:
    provider: str
    capability: str
    state: str
    evidence: str


def probe_adapter(provider: str, adapter: object, *, output: str | Path = "var/autotrader/options-capabilities.json") -> list[dict[str, str]]:
    names = {"OPTION_CHAIN": ("option_chain", "get_option_chain"), "OPTION_QUOTES": ("option_quote", "get_option_quote"), "OPTION_GREEKS": ("option_greeks", "get_option_greeks"), "OPTION_PAPER_EXECUTION": ("submit_option_order", "submit_options_order"), "MULTILEG_OPTIONS": ("submit_multileg_order", "submit_option_spread")}
    rows = []
    for capability, methods in names.items():
        found = next((method for method in methods if callable(getattr(adapter, method, None))), None)
        rows.append(asdict(OptionCapability(provider, capability, "SUPPORTED" if found else "UNSUPPORTED", f"existing adapter method: {found}" if found else "no existing adapter method")))
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
    return rows

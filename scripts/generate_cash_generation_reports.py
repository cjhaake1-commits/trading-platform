"""Generate Phase 7 realized-cash reports from forward evidence only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autotrader.cash_generation import write_cash_generation_reports

if __name__ == "__main__":
    daily, weekly = write_cash_generation_reports()
    print(f"wrote {daily} and {weekly}")

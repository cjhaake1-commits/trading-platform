#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "== repository =="
pwd
git fetch origin bootstrap-paper-trading-core
git checkout bootstrap-paper-trading-core
git pull --ff-only origin bootstrap-paper-trading-core
test "$(git branch --show-current)" = bootstrap-paper-trading-core

if [[ "${LIVE_TRADING_ENABLED:-false}" != "false" ]]; then
  echo "LIVE_TRADING_ENABLED must be false" >&2; exit 20
fi
export LIVE_TRADING_ENABLED=false
export AUTONOMOUS_TRADING_ENABLED=true

if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi
python -m pytest -q
ruff check src tests scripts streamlit_app.py
python -m compileall src tests
python -m py_compile streamlit_app.py
git diff --check

PYTHONPATH=src python scripts/publish_dashboard_snapshot.py
systemctl --user daemon-reload
systemctl --user restart trading-platform-paper-runtime.service
systemctl --user restart trading-platform-streamlit.service
sleep 5

python - <<'PY'
import json
from pathlib import Path
s=json.loads(Path("var/autotrader/status.json").read_text())
assert s.get("healthy") is True
assert s.get("autonomous_enabled") is True
assert s.get("execution_state") == "armed_paper"
assert s.get("live_trading_enabled") is False
required=("autonomous-paper-trading","oanda-fx-paper-trading","alpaca-metals-paper-trading","saxo-international-paper-trading","daily-learning","research-refresh","daily-report","health")
missing=[name for name in required if name not in s.get("jobs",{})]
if missing: raise SystemExit(f"missing runtime jobs: {missing}")
for name in required:
    job=s["jobs"][name]
    if job.get("last_error"): raise SystemExit(f"{name}: {job['last_error']}")
print("paper runtime safety and job presence verified")
PY

systemctl --user is-active trading-platform-paper-runtime.service
systemctl --user is-active trading-platform-streamlit.service
systemctl --user show trading-platform-streamlit.service -p MainPID -p ActiveState -p SubState
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8501

echo "== recent service evidence =="
journalctl --user -u trading-platform-paper-runtime.service -u trading-platform-streamlit.service -n 120 --no-pager
echo "== current commit =="
git rev-parse HEAD

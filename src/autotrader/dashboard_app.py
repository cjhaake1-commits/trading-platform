from __future__ import annotations

import argparse
import html
import json
import sqlite3
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_portfolio(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"portfolio": None, "positions": [], "fills": 0, "brokers": []}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        state = conn.execute("SELECT * FROM portfolio_state WHERE id = 1").fetchone()
        positions = [dict(row) for row in conn.execute("SELECT * FROM positions ORDER BY symbol")]
        fills = conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"]
        brokers = [dict(row) for row in conn.execute("SELECT * FROM broker_state ORDER BY broker")]
    return {
        "portfolio": None if state is None else dict(state),
        "positions": positions,
        "fills": fills,
        "brokers": brokers,
    }


def _read_audit(path: Path, limit: int = 30) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            try:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            except sqlite3.Error:
                return []
    return [dict(row) for row in rows]


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "—"


def _fmt_pct(value) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "—"


def render_dashboard(status_path: Path, ledger_path: Path, audit_path: Path) -> str:
    status = _read_json(status_path)
    ledger = _read_portfolio(ledger_path)
    audit = _read_audit(audit_path)
    portfolio = ledger.get("portfolio") or {}
    positions = ledger.get("positions") or []
    jobs = status.get("jobs") if isinstance(status.get("jobs"), dict) else {}
    paper_job = jobs.get("autonomous-paper-trading") if isinstance(jobs, dict) else None
    health_job = jobs.get("health") if isinstance(jobs, dict) else None

    equity = portfolio.get("equity")
    peak = portfolio.get("peak_equity")
    daily_pnl = portfolio.get("daily_pnl")
    weekly_pnl = portfolio.get("weekly_pnl")
    drawdown = None
    try:
        if peak and float(peak) > 0 and equity is not None:
            drawdown = max((float(peak) - float(equity)) / float(peak), 0.0)
    except Exception:
        pass

    runtime_live = bool(status.get("last_heartbeat_at")) and bool(paper_job) and not bool((paper_job or {}).get("disabled"))
    runtime_label = "RUNNING" if runtime_live else "NOT CONFIRMED"
    runtime_class = "good" if runtime_live else "warn"

    position_rows = "".join(
        f"<tr><td>{html.escape(str(p.get('symbol','')))}</td>"
        f"<td>{html.escape(str(p.get('asset_class','')))}</td>"
        f"<td>{float(p.get('quantity',0)):,.6f}</td>"
        f"<td>{_fmt_money(p.get('average_price'))}</td>"
        f"<td>{_fmt_money(p.get('stop_price'))}</td></tr>"
        for p in positions
    ) or "<tr><td colspan='5'>No open positions</td></tr>"

    audit_rows = ""
    for row in audit:
        event_type = row.get("event_type", "")
        message = row.get("message", "")
        created = row.get("created_at", row.get("timestamp", ""))
        audit_rows += (
            f"<tr><td>{html.escape(str(created))}</td>"
            f"<td>{html.escape(str(event_type))}</td>"
            f"<td>{html.escape(str(message))}</td></tr>"
        )
    if not audit_rows:
        audit_rows = "<tr><td colspan='3'>No audit events yet</td></tr>"

    last_heartbeat = html.escape(str(status.get("last_heartbeat_at") or "—"))
    started_at = html.escape(str(status.get("started_at") or "—"))
    paper_error = html.escape(str((paper_job or {}).get("last_error") or "None"))

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta http-equiv='refresh' content='10'>
<title>Autotrader Paper Dashboard</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8edf7;margin:0;padding:24px}}
.wrap{{max-width:1200px;margin:auto}} h1{{margin:0 0 6px}} .sub{{color:#9aa7bd;margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}}
.card{{background:#151c31;border:1px solid #26314f;border-radius:14px;padding:16px}}
.k{{font-size:12px;color:#9aa7bd;text-transform:uppercase;letter-spacing:.08em}} .v{{font-size:26px;font-weight:700;margin-top:5px}}
.good{{color:#59d185}} .warn{{color:#ffcc66}} .bad{{color:#ff7272}}
table{{width:100%;border-collapse:collapse;background:#151c31;border-radius:12px;overflow:hidden;margin-top:10px}}
th,td{{padding:10px 12px;border-bottom:1px solid #26314f;text-align:left;font-size:14px}} th{{color:#9aa7bd}}
section{{margin-top:24px}} code{{color:#b8c7ff}} .meta{{font-size:13px;color:#9aa7bd;line-height:1.6}}
</style></head><body><div class='wrap'>
<h1>Autonomous Paper Trading</h1><div class='sub'>Combined Alpaca Paper + OANDA Practice • refreshes every 10 seconds</div>
<div class='grid'>
<div class='card'><div class='k'>Runtime</div><div class='v {runtime_class}'>{runtime_label}</div></div>
<div class='card'><div class='k'>Portfolio Equity</div><div class='v'>{_fmt_money(equity)}</div></div>
<div class='card'><div class='k'>Daily P&L</div><div class='v'>{_fmt_money(daily_pnl)}</div></div>
<div class='card'><div class='k'>Weekly P&L</div><div class='v'>{_fmt_money(weekly_pnl)}</div></div>
<div class='card'><div class='k'>Peak Drawdown</div><div class='v'>{_fmt_pct(drawdown)}</div></div>
<div class='card'><div class='k'>Open Positions</div><div class='v'>{len(positions)}</div></div>
<div class='card'><div class='k'>Recorded Fills</div><div class='v'>{ledger.get('fills',0)}</div></div>
</div>
<section><h2>Runtime health</h2><div class='card meta'>
Started: <code>{started_at}</code><br>Last heartbeat: <code>{last_heartbeat}</code><br>
Autonomous job disabled: <code>{html.escape(str((paper_job or {}).get('disabled','—')))}</code><br>
Consecutive failures: <code>{html.escape(str((paper_job or {}).get('consecutive_failures','—')))}</code><br>
Last error: <code>{paper_error}</code><br>
Health job disabled: <code>{html.escape(str((health_job or {}).get('disabled','—')))}</code>
</div></section>
<section><h2>Open positions</h2><table><thead><tr><th>Symbol</th><th>Asset</th><th>Quantity</th><th>Avg price</th><th>Stop</th></tr></thead><tbody>{position_rows}</tbody></table></section>
<section><h2>Recent autonomous activity</h2><table><thead><tr><th>Time</th><th>Event</th><th>Message</th></tr></thead><tbody>{audit_rows}</tbody></table></section>
</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Local browser dashboard for autonomous paper trading")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--status", default="var/autotrader/status.json")
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    args = parser.parse_args()

    status_path = Path(args.status)
    ledger_path = Path(args.ledger)
    audit_path = Path(args.audit_db)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in {"/", "/index.html"}:
                self.send_response(404); self.end_headers(); return
            body = render_dashboard(status_path, ledger_path, audit_path).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dashboard listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

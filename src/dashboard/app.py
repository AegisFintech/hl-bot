import time
import json
import logging
from pathlib import Path

from flask import Flask, render_template, jsonify, send_from_directory

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

_bot_ref = None


def set_bot_reference(bot):
    global _bot_ref
    _bot_ref = bot


def _status() -> dict:
    if not _bot_ref:
        return {"status": "not_connected"}
    risk = _bot_ref.risk_manager.get_state_dict() if _bot_ref.risk_manager else {}
    price = None
    try:
        bbo = _bot_ref.client.get_cached_bbo(_bot_ref.coin)
        if bbo:
            bid = float(bbo["bid"]["px"]) if "bid" in bbo else None
            ask = float(bbo["ask"]["px"]) if "ask" in bbo else None
            if bid and ask:
                price = round((bid + ask) / 2, 2)
    except Exception:
        pass
    strategy = getattr(_bot_ref, "strategy", None)
    settings = getattr(_bot_ref, "settings", None)
    return {
        "status": "running" if _bot_ref.running else "stopped",
        "uptime_s": round(time.time() - _bot_ref.start_time, 0) if _bot_ref.start_time else 0,
        "coin": _bot_ref.coin,
        "coins": list(getattr(_bot_ref, "coins", [_bot_ref.coin])),
        "network": "testnet" if _bot_ref.client.testnet else "MAINNET",
        "price": price,
        "risk": risk,
        "startup": getattr(_bot_ref, "startup_status", "Ready"),
        "strategy": strategy.label if strategy else None,
        "interval": settings.interval if settings else None,
        "halt_cleanup": getattr(_bot_ref, "halt_cleanup_status", "Not required"),
    }


def _snapshot():
    """Positions/orders the trading loop last read; the dashboard never calls the exchange."""
    snap = getattr(_bot_ref, "exchange_snapshot", None) or {}
    return snap.get("positions", []), snap.get("orders", []), snap.get("time", 0)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(_status())


@app.route("/api/positions")
def api_positions():
    if not _bot_ref:
        return jsonify([])
    return jsonify(_snapshot()[0])


@app.route("/api/orders")
def api_orders():
    if not _bot_ref:
        return jsonify([])
    return jsonify(_snapshot()[1])


@app.route("/api/trades")
def api_trades():
    if not _bot_ref or not _bot_ref.evaluator:
        return jsonify([])
    return jsonify(_bot_ref.evaluator.get_recent_trades(50))


@app.route("/api/performance")
def api_performance():
    if not _bot_ref or not _bot_ref.evaluator:
        return jsonify({})
    return jsonify(_bot_ref.evaluator.get_performance())


@app.route("/api/fills")
def api_fills():
    if not _bot_ref or not getattr(_bot_ref, "ledger", None):
        return jsonify([])
    try:
        fills = _bot_ref.ledger.fills(500)  # Local ledger: no exchange request weight per view.
        out = []
        for f in fills:
            out.append({
                "time": int(f.get("time", 0)),
                "coin": f.get("coin"),
                "side": f.get("side"),
                "sz": f.get("sz"),
                "px": f.get("px"),
                "closed_pnl": float(f.get("closedPnl", 0) or 0),
                "fee": float(f.get("fee", 0) or 0),
                "is_entry": float(f.get("closedPnl", 0) or 0) == 0,
            })
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades/all")
def api_trades_all():
    if not _bot_ref or not _bot_ref.evaluator:
        return jsonify([])
    return jsonify([t.to_dict() for t in _bot_ref.evaluator.trades])


@app.route("/api/pnl_chart")
def api_pnl_chart():
    if not _bot_ref or not _bot_ref.evaluator:
        return jsonify([])
    trades = [t.to_dict() for t in _bot_ref.evaluator.trades]
    cumulative = 0.0
    points = [{"trade": 0, "pnl": 0.0, "time": None}]
    for i, t in enumerate(trades):
        cumulative += t.get("pnl", 0)
        points.append({
            "trade": i + 1,
            "pnl": round(cumulative, 4),
            "time": t.get("exit_time"),
            "coin": t.get("coin"),
            "side": t.get("side"),
        })
    return jsonify(points)


@app.route("/api/sr_levels")
def api_sr_levels():
    if not _bot_ref or not hasattr(_bot_ref, "chart_levels"):
        return jsonify({"levels": [], "order_blocks": []})
    return jsonify({"levels": _bot_ref.chart_levels(), "order_blocks": []})


@app.route("/api/strategy")
def api_strategy():
    if not _bot_ref or not hasattr(_bot_ref, "strategy_status"):
        return jsonify({"status": "not_connected"}), 503
    return jsonify(_bot_ref.strategy_status())


@app.route("/api/account")
def api_account():
    if not _bot_ref or not _bot_ref.client:
        return jsonify({})
    account = getattr(_bot_ref, "account_snapshot", {}) or {}
    return jsonify({
        "available_to_trade": account.get("available"),
        "spot_usdc": account.get("spot_usdc"),
        "perps_account_value": account.get("perps_account_value"),
        "network": "testnet" if _bot_ref.client.testnet else "mainnet",
        "master_account": _bot_ref.client.master_account,
        "agent_address": _bot_ref.client.wallet.address,
        "sampled_at": account.get("timestamp"),
    })


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


# One shared cache prevents every connected browser from multiplying exchange reads.
import csv
import io
import threading
from flask import Response

_terminal_lock = threading.Lock()
_terminal_cache = {}
_terminal_at = 0.0
_slow_cache = {}
SLOW_TTL = 60.0  # Whole-history summaries are rebuilt at most once a minute.


def _section(out, errors, key, builder, slow=False):
    if slow:
        cached = _slow_cache.get(key)
        if cached and time.time() - cached[0] < SLOW_TTL:
            out[key] = cached[1]
            return
    try:
        out[key] = builder()
        if slow:
            _slow_cache[key] = (time.time(), out[key])
    except Exception:
        log.exception('%s unavailable', key)
        out[key] = _slow_cache.get(key, (0, {'status': 'unavailable'}))[1] if slow else {'status': 'unavailable'}
        errors.append(key.replace('_', ' ') + ' unavailable')


@app.route('/api/terminal')
def api_terminal():
    global _terminal_cache, _terminal_at
    if not _bot_ref:
        return jsonify({'status': _status(), 'errors': ['Bot is not connected'], 'timestamp': time.time()})
    if time.time() - _terminal_at < 5 and _terminal_cache:
        return jsonify(_terminal_cache)
    if not _terminal_lock.acquire(blocking=False):
        # Another request is rebuilding; serve the last view instead of queueing.
        return jsonify(_terminal_cache or {'status': _status(), 'errors': ['Terminal warming up'],
                                           'timestamp': time.time()})
    try:
        bot = _bot_ref
        errors = []
        out = dict(_terminal_cache)
        out.update(status=_status(), timestamp=time.time())
        positions, orders, snapshot_at = _snapshot()
        out['positions'], out['orders'] = positions, orders
        if time.time() - snapshot_at > 60:
            errors.append('Positions/orders snapshot is stale; last successful values shown')
        out['account'] = bot.account_snapshot
        if time.time() - (bot.account_snapshot or {}).get('timestamp', 0) > 30:
            errors.append('Account equity is stale; new entries blocked')
        _section(out, errors, 'performance', bot.ledger.performance)
        _section(out, errors, 'quality', lambda: bot.quality.summary(bot.ledger.fills(1000000), bot.execution.links()),
                 slow=True)
        out['development'] = development_registry()
        _section(out, errors, 'execution_audit', bot.execution.summary)
        _section(out, errors, 'equity_bridge', bot.account_audit.summary, slow=True)
        _section(out, errors, 'operations', bot.operations.summary)
        _section(out, errors, 'market_data', lambda: bot.client.candle_health(bot.coin))
        _section(out, errors, 'equity', bot.ledger.equity)
        _section(out, errors, 'fills', lambda: bot.ledger.fills(200))
        candles = bot.client.get_cached_candles(bot.coin)
        out['candles'] = sorted({int(c['t']): c for c in candles}.values(), key=lambda c: int(c['t']))[-500:]
        if len(out['candles']) < 50:
            errors.append('Chart candle history is still loading')
        out['book'] = bot.client.get_cached_orderbook(bot.coin) or {}
        out['tape'] = bot.client.get_cached_trades(bot.coin)[-40:]
        out['bbo_age_s'] = bot.client.bbo_age(bot.coin)
        _section(out, errors, 'strategy', bot.strategy_status)
        _section(out, errors, 'levels', bot.chart_levels)
        _section(out, errors, 'research', bot.research.snapshot, slow=True)
        out['errors'] = errors
        _terminal_cache, _terminal_at = out, time.time()
        return jsonify(out)
    finally:
        _terminal_lock.release()

@app.route('/api/research')
def api_research():
    if not _bot_ref or not getattr(_bot_ref, 'research', None):
        return jsonify({'status':'not_connected','mode':'Observation only'}), 503
    return jsonify(_bot_ref.research.snapshot())

@app.route('/api/export/fills.csv')
def export_fills():
    output = io.StringIO()
    fields = ['time', 'coin', 'dir', 'side', 'px', 'sz', 'closedPnl', 'fee', 'tid']
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for fill in _bot_ref.ledger.fills(1000000) if _bot_ref else []:
        writer.writerow({k: ("'"+str(fill.get(k,'')) if str(fill.get(k,'')).startswith(('=', '+', '-', '@')) and k in ('coin','dir','tid') else fill.get(k,'')) for k in fields})
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition':'attachment; filename=hl-bot-fills.csv'})

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Cache-Control'] = 'no-store'
    return response



def development_registry():
    try:
        path = Path(__file__).resolve().parents[2] / 'docs/RESEARCH_REGISTRY.json'
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {'automatic_promotion': False, 'milestones': [], 'hypotheses': [], 'status': 'unavailable'}


@app.route('/api/development', methods=['GET'])
def api_development():
    return jsonify(development_registry())


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from config import DASHBOARD_PORT
    run_dashboard(port=DASHBOARD_PORT)


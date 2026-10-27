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
    return {
        "status": "running" if _bot_ref.running else "stopped",
        "uptime_s": round(time.time() - _bot_ref.start_time, 0) if _bot_ref.start_time else 0,
        "coin": _bot_ref.coin,
        "network": "testnet" if _bot_ref.client.testnet else "MAINNET",
        "price": price,
        "risk": risk,
        "halt_cleanup": getattr(_bot_ref, "halt_cleanup_status", "Not required"),
    }


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
    if not _bot_ref or not _bot_ref.client:
        return jsonify([])
    try:
        return jsonify(_bot_ref.client.get_positions())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders")
def api_orders():
    if not _bot_ref or not _bot_ref.client:
        return jsonify([])
    try:
        return jsonify(_bot_ref.client.get_open_orders())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    if not _bot_ref or not _bot_ref.client:
        return jsonify([])
    try:
        fills = _bot_ref.client.info.user_fills(_bot_ref.client.address)
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
    if not _bot_ref or not _bot_ref.scalper:
        return jsonify({"levels": [], "order_blocks": []})
    sr = _bot_ref.scalper.sr
    levels = [{"price": l.price, "kind": l.kind, "strength": l.strength,
               "touches": l.touches, "score": round(l.score, 3)} for l in sr._levels]
    obs = [{"high": ob.price_high, "low": ob.price_low, "kind": ob.kind}
           for ob in sr._order_blocks]
    return jsonify({"levels": levels, "order_blocks": obs})


@app.route("/api/account")
def api_account():
    if not _bot_ref or not _bot_ref.client:
        return jsonify({})
    try:
        return jsonify({
            "available_to_trade": _bot_ref.client.get_available_to_trade(),
            "spot_usdc": _bot_ref.client.get_spot_usdc_balance(),
            "perps_account_value": _bot_ref.client.get_perps_account_value(),
            "network": "testnet" if _bot_ref.client.testnet else "mainnet",
            "master_account": _bot_ref.client.master_account,
            "agent_address": _bot_ref.client.wallet.address,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


# One shared cache prevents every connected browser from multiplying exchange reads.
import csv
import io
import threading
from flask import Response, request

_terminal_lock = threading.Lock()
_terminal_cache = {}
_terminal_at = 0.0

@app.route('/api/terminal')
def api_terminal():
    global _terminal_cache, _terminal_at
    if not _bot_ref:
        return jsonify({'status': _status(), 'errors': ['Bot is not connected'], 'timestamp': time.time()})
    with _terminal_lock:
        if time.time() - _terminal_at < 5 and _terminal_cache:
            return jsonify(_terminal_cache)
        bot = _bot_ref
        errors = []
        out = dict(_terminal_cache)
        out.update(status=_status(), timestamp=time.time())
        for key, getter in [('positions', bot.client.get_positions), ('orders', bot.client.get_open_orders)]:
            try:
                out[key] = getter()
            except Exception:
                errors.append(key + ' unavailable; last successful values retained')
        out['account'] = bot.account_snapshot
        if time.time() - bot.account_snapshot.get('timestamp', 0) > 30:
            errors.append('Account equity is stale; new entries blocked')
        out['performance'] = bot.ledger.performance()
        try:
            out['quality'] = bot.quality.summary(bot.ledger.fills(1000000), bot.execution.links())
        except Exception:
            log.exception('Quality audit unavailable')
            out['quality'] = {'status': 'unavailable'}
        out['development'] = development_registry()
        out['execution_audit'] = bot.execution.summary()
        try:
            out['equity_bridge'] = bot.account_audit.summary()
        except Exception:
            log.exception('Equity reconciliation unavailable')
            out['equity_bridge'] = {'status':'unavailable'}
        out['operations'] = bot.operations.summary()
        out['market_data'] = bot.client.candle_health(bot.coin)
        out['equity'] = bot.ledger.equity()
        out['fills'] = bot.ledger.fills(200)
        candles = bot.client.get_cached_candles(bot.coin)
        if len(candles) < 50:
            try:
                candles = bot.client.get_candles(bot.coin, '1m', 500*60000)
            except Exception:
                errors.append('Candle history unavailable')
        out['candles'] = sorted({int(c['t']): c for c in candles}.values(), key=lambda c: int(c['t']))[-500:]
        out['book'] = bot.client.get_cached_orderbook(bot.coin) or {}
        out['tape'] = bot.client.get_cached_trades(bot.coin)[-40:]
        out['bbo_age_s'] = bot.client.bbo_age(bot.coin)
        out['strategy'] = dict(bot.scalper.diagnostics, maker_fee_bps=bot.scalper.fee_entry*10000,
                               taker_fee_bps=bot.scalper.fee_exit*10000, target_daily_pct=10,
                               target_status='Unverified research target', mode='Forward demo evaluation',
                               pending_signals=len(bot._pending_signals))
        out['levels'] = [{'price': l.price, 'kind': l.kind, 'score': l.score} for l in bot.sr_detector._levels]
        try:
            out['research'] = bot.research.snapshot()
        except Exception:
            log.exception('Research snapshot unavailable')
            out['research'] = {'status':'unavailable','mode':'Observation only'}
        out['errors'] = errors
        _terminal_cache, _terminal_at = out, time.time()
        return jsonify(out)

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


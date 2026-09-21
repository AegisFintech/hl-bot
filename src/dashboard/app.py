import time
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
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from config import DASHBOARD_PORT
    run_dashboard(port=DASHBOARD_PORT)

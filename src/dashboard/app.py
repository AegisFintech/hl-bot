import json
import time
import threading
import logging
from pathlib import Path

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "hl-bot-dashboard"
socketio = SocketIO(app, cors_allowed_origins="*")

_bot_ref = None


def set_bot_reference(bot):
    global _bot_ref
    _bot_ref = bot


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    if not _bot_ref:
        return jsonify({"status": "not_connected"})

    return jsonify({
        "status": "running" if _bot_ref.running else "stopped",
        "uptime": round(time.time() - _bot_ref.start_time, 1) if _bot_ref.start_time else 0,
        "coin": _bot_ref.coin,
        "risk": _bot_ref.risk_manager.get_state_dict() if _bot_ref.risk_manager else {},
    })


@app.route("/api/positions")
def api_positions():
    if not _bot_ref or not _bot_ref.client:
        return jsonify([])
    try:
        positions = _bot_ref.client.get_positions()
        return jsonify(positions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders")
def api_orders():
    if not _bot_ref or not _bot_ref.client:
        return jsonify([])
    try:
        orders = _bot_ref.client.get_open_orders()
        return jsonify(orders)
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


@app.route("/api/pnl")
def api_pnl():
    if not _bot_ref or not _bot_ref.evaluator:
        return jsonify([])
    return jsonify(_bot_ref.evaluator.get_cumulative_pnl())


@app.route("/api/sr_levels")
def api_sr_levels():
    if not _bot_ref or not _bot_ref.scalper:
        return jsonify({"supports": [], "resistances": [], "order_blocks": []})

    sr = _bot_ref.scalper.sr
    levels = [{"price": l.price, "kind": l.kind, "strength": l.strength,
               "touches": l.touches, "score": round(l.score, 3)} for l in sr._levels]
    obs = [{"high": ob.price_high, "low": ob.price_low, "kind": ob.kind,
            "volume": ob.volume} for ob in sr._order_blocks]

    return jsonify({"levels": levels, "order_blocks": obs})


@app.route("/api/price")
def api_price():
    if not _bot_ref or not _bot_ref.client:
        return jsonify({})
    try:
        bbo = _bot_ref.client.get_cached_bbo(_bot_ref.coin)
        mid = _bot_ref.client.get_mid_price(_bot_ref.coin)
        return jsonify({"mid": mid, "bbo": bbo})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _emit_loop():
    while True:
        if _bot_ref:
            try:
                data = {
                    "status": "running" if _bot_ref.running else "stopped",
                    "risk": _bot_ref.risk_manager.get_state_dict() if _bot_ref.risk_manager else {},
                }
                if _bot_ref.client:
                    try:
                        bbo = _bot_ref.client.get_cached_bbo(_bot_ref.coin)
                        if bbo:
                            data["price"] = bbo
                    except Exception:
                        pass
                socketio.emit("update", data)
            except Exception:
                pass
        socketio.sleep(2)


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    socketio.start_background_task(_emit_loop)
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from config import DASHBOARD_PORT
    run_dashboard(port=DASHBOARD_PORT)

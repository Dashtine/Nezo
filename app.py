import threading
import logging
import time
import requests
import string
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, Response
from signalrcore.hub_connection_builder import HubConnectionBuilder
from collections import deque
from threading import Lock
from trades_db import init_db, calculate_analytics, create_trade


from preset_manager import (
    save_preset,
    load_preset,
    delete_preset,
    list_presets
)

from topstepx_api import (
    place_order,
    get_account,
    get_contract,
    generate_token,
    cancel_order,
    modify_order,
    get_latest_position
)
from levels import retrieve_bars, detect_swings, detect_fvg, get_levels, get_3sec_bar

# ======================================================
# CONFIGURATION
# ======================================================

app = Flask(__name__)

settings = {
    "contracts": 0,
    "takeProfit": 0,
    "stopLoss": 0,
    "tpslMethod": "",
    "contracts_tp1": 0,
    "contracts_tp2": 0,
    "backup_tp1": 0,
    "backup_tp2": 0,
    "backup_sl": 0,
    "beMethod": "",
    "useMacro": False,
    "sessions": [ 
        {"enabled": False, "start": "06:29", "end": "12:41"},
        {"enabled": False, "start": "16:59", "end": "21:01"},
        {"enabled": False, "start": "11:59", "end": "02:01"}
    ],
    "propUsername": "",
    "apiKey": "",
    "token": "",
    "token_expiry": "",
    "account": "",
    "accountId": "",
    "contractName": "",
    "contractId": "",
    "contractDesc": ""
}

trade_state = {
    "active": False,             # True while a position is open
    "direction": None,           # 'bullish' or 'bearish'
    "entry_price": None,         # Filled entry price
    "entry_size": 0,             # Size of the entry position
    "account_id": None,          # Account reference
    "tp_orders": [],             # [tp1_order_id, tp2_order_id]
    "sl_order": None,            # stop-loss order id
    "be_price": None,            # break-even price (future dynamic use)
    "opened_at": None,           # ISO timestamp of trade open
    "closed_at": None,           # ISO timestamp of trade close
    "brackets_set": False        # True once TP/SL orders are placed
}

AUTHORIZED_USER = ""
running = False
trade_lock = False
log_messages = []
hub_connection = None
running_breakeven = False
macro_time_active = False
in_ny_session = False
stop_event = threading.Event()
threads = {}  # store all active background threads
log_lock = Lock()
log_messages = deque(maxlen=200)

# ======================================================
# PRESET PROFILE ROUTES
# ======================================================
@app.route("/preset/list", methods=["GET"])
def preset_list():
    presets = list_presets()
    return jsonify({"presets": presets})

@app.route("/preset/save", methods=["POST"])
def preset_save():
    data = request.get_json()
    name = data.get("name")
    settings_data = data.get("settings")

    if not name or not settings_data:
        return jsonify({"error": "Missing preset name or settings"}), 400

    try:
        save_preset(name, settings_data)
        log_message(f"[Preset] Profile {name} saved successfully.")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/preset/load", methods=["POST"])
def preset_load():
    data = request.get_json()
    name = data.get("name")

    if not name:
        return jsonify({"error": "Missing preset name"}), 400

    preset = load_preset(name)
    if preset is None:
        return jsonify({"error": "Preset not found"}), 404
    
    log_message(f"[Preset] Profile {name} loaded successfully.")

    return jsonify({"status": "ok", "settings": preset})

@app.route("/preset/delete", methods=["POST"])
def preset_delete():
    data = request.get_json()
    name = data.get("name")

    if not name:
        return jsonify({"error": "Missing preset name"}), 400

    delete_preset(name)
    log_message(f"[Preset] Profile {name} deleted.")
    return jsonify({"status": "ok"})

# ======================================================
# Calculate Trades
# ======================================================
@app.route("/analytics/calc", methods=["POST"])
def analytics_calc():
    data = request.json
    results = calculate_analytics(data)   # lives in trades_db.py
    return jsonify(results)

# ======================================================
# LOGGING HELPERS
# ======================================================

def log_message(message):
    pst_now = datetime.now(ZoneInfo("America/Los_Angeles"))
    ts = pst_now.strftime("%m-%d-%y %I:%M:%S %p PST")
    entry = f"[{ts}] {message}"
    print(entry)

    with log_lock:
        log_messages.append(entry)

def generate_logs():
    idx = 0
    
    while True:
        with log_lock:
            if idx < len(log_messages):
                entry = log_messages[idx]
                idx += 1
                out = f"data: {entry}\n\n"
            else:
                out = ": keepalive\n\n"

        yield out

        time.sleep(0.1)

# ======================================================
# USERHUB CONNECTION
# ======================================================

def start_userhub():
    global hub_connection, trade_state
    hub_closed = False
    token = settings.get("token")
    account_id = settings.get("accountId")
    if not token or not account_id:
        log_message("[Bot] Cannot start: Missing token or account ID.")
        return

    hub_url = f"https://rtc.topstepx.com/hubs/user?access_token={token}"

    try:
        log_message("[Bot] Connecting to TopstepX Live Feed")

        connection = (
            HubConnectionBuilder()
            .with_url(hub_url)
            .with_automatic_reconnect({
                "type": "raw",
                "keep_alive_interval": 10,
                "reconnect_interval": 5,
                "max_attempts": 9999
            })
            .build()
        )

        def on_open():
            log_message("[Topstep] Connected.")
            connection.send("SubscribeAccounts", [])
            connection.send("SubscribeOrders", [account_id])
            connection.send("SubscribePositions", [account_id])
            connection.send("SubscribeTrades", [account_id])
            print(f"[Topstep] Subscribed to account {account_id}")

        def on_close():
            nonlocal hub_closed
            hub_closed = True
            log_message("[Topstep] Connection closed.")


        def on_error(err):
            log_message(f"[Topstep] Error: {err}")

        def on_position_update(args):
            """Handles position updates from TopstepX UserHub (GatewayUserPosition)."""

            global trade_state
            payload = args[0] if isinstance(args, list) and args else args
            if not isinstance(payload, dict):
                return

            pos = payload.get("data", {}) or {}
            action = payload.get("action")
            account_id = pos.get("accountId")
            contract_id = pos.get("contractId")
            size = pos.get("size", 0)
            avg_price = pos.get("averagePrice")
            ttype = pos.get("type", -1)

            side = "Long" if ttype == 1 else "Short" if ttype == 2 else "Flat"

            # Update hasPosition flag
            settings["hasPosition"] = size != 0

            # === POSITION CLOSED ===
            if action == 2 or size == 0 or ttype == 0:
                if trade_state.get("active"):
                    log_message(f"[Topstep] Position CLOSED @ {avg_price} | Contract={contract_id}")

                    if settings["tpslMethod"] == "ticks":
                        return
                    
                    # Cancel any remaining TP/SL orders
                    for oid in (trade_state.get("tp_orders") or []):
                        if oid:
                            cancel_order(oid, settings["token"], settings["accountId"])
                    if trade_state.get("sl_order"):
                        cancel_order(trade_state["sl_order"], settings["token"], settings["accountId"])
                    log_message("[Topstep] All open orders canceled after close.")

                    # Reset trade state
                    trade_state.update({
                        "active": False,
                        "direction": None,
                        "entry_price": None,
                        "entry_size": 0,
                        "tp_orders": [],
                        "sl_order": None,
                        "be_price": None,
                        "opened_at": None,
                        "closed_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
                        "brackets_set": False
                    })
                else:
                    print("[Topstep] Position close event received, but no active trade tracked.")
                return

            # === POSITION OPENED / ADJUSTED ===
            if action == 1:
                if settings["tpslMethod"] == "ticks":
                        log_message(f"[Topstep] {side} position OPENED @ {avg_price} (size={size})")
                        return
                
                if not trade_state.get("active"):
                    # New position opened
                    trade_state.update({
                        "active": True,
                        "direction": side.lower(),
                        "entry_price": avg_price,
                        "entry_size": size,
                        "account_id": account_id,
                        "opened_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
                        "brackets_set": False
                    })
                    log_message(f"[Topstep] {side} position OPENED @ {avg_price} (size={size})")

                else:
                    # Existing position adjusted (scaled in or partial reduction)
                    prev_size = trade_state.get("entry_size", 0)
                    if size != prev_size or avg_price != trade_state.get("entry_price"):
                        trade_state["entry_size"] = size
                        trade_state["entry_price"] = avg_price
                        log_message(f"[Topstep] Position UPDATED | Side={side}, Size={size}, Avg={avg_price}")

            # === LOG RAW EVENT ===
            log_message(f"[Topstep] Event received → Action={action}, Type={ttype}, Side={side}, Size={size}, Price={avg_price}")
        
        def on_order_update(args):
            """Handles order updates from TopstepX (GatewayUserOrder)."""
            global trade_state

            if settings["tpslMethod"] == "ticks":
                return
            
            payload = args[0] if isinstance(args, list) and args else args
            if not isinstance(payload, dict):
                return

            data = payload.get("data", {}) or {}
            order_id = data.get("id")
            account_id = data.get("accountId")
            status = data.get("status")            # 2 = filled
            fill_volume = data.get("fillVolume", 0)
            order_type = data.get("type")          # 1 = Limit, 2 = Market, 4 = Stop
            side = data.get("side")                # 0 = Buy, 1 = Sell

            # Only react to fills
            if status != 2 or fill_volume <= 0:
                return

            log_message(f"[Topstep] Order filled update received → ID={order_id}, Side={side}, Size={fill_volume}")

            tp_orders = trade_state.get("tp_orders") or []
            sl_order = trade_state.get("sl_order")

            # --- CASE 1: TP1 filled ---
            if len(tp_orders) >= 1 and order_id == tp_orders[0]:
                if settings["beMethod"] == "tp1":
                    log_message(f"[Topstep] TP1 filled (order {order_id}). Adjusting SL size and moving to breakeven.")
                else:
                    log_message(f"[Topstep] TP1 filled (order {order_id}). Adjusting SL size.")

                try:
                    total_size = trade_state.get("entry_size", 0)
                    tp1_size = fill_volume                     # size of TP1 order
                    remaining_size = max(total_size - tp1_size, 1)

                    # Update trade_state size
                    trade_state["entry_size"] = remaining_size

                    # Modify SL order size and/or move to breakeven
                    if settings["beMethod"] == "tp1":
                        modify_resp = modify_order(
                            account_id=account_id,
                            order_id=sl_order,
                            new_size=remaining_size,
                            token=settings["token"],
                            stop_price=trade_state["entry_price"]
                        )
                        if modify_resp.get("success"):
                            log_message(f"[Topstep] SL size updated → {remaining_size} contracts and moved to breakeven after TP1 fill.")
                        else:
                            log_message(f"[Topstep] Failed to modify SL size or move stoploss to breakeven: {modify_resp}")
                    elif settings["beMethod"] == "":
                        modify_resp = modify_order(
                            account_id=account_id,
                            order_id=trade_state["sl_order"],
                            new_size=remaining_size,
                            token=settings["token"],
                        )
                        if modify_resp.get("success"):
                           log_message(f"[Topstep] SL size updated → {remaining_size} contracts after TP1 fill.")
                        else:
                           log_message(f"[Topstep] Failed to modify SL size: {modify_resp}")

                    trade_state["be_price"] = None


                except Exception as e:
                    log_message(f"[UserHub] Error modifying SL after TP1 fill: {e}")

        connection.on_open(on_open)
        connection.on_close(on_close)
        connection.on_error(on_error)
        connection.on("GatewayUserPosition", on_position_update)
        connection.on("GatewayUserOrder", on_order_update)
        
        connection.start()
        log_message("[Topstep] Connection thread started, waiting for events...")
        while not stop_event.is_set() and not hub_closed:
            if stop_event.wait(5):
                break


    except Exception as e:
        log_message(f"[Topstep] Failed to start: {e}")

    finally:
        try:
            connection.stop()
        except:
            pass

# ======================================================
# ROUTES
# ======================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/validate_user", methods=["POST"])
def validate_user():
    data = request.get_json()
    username = data.get("username", "").strip()
    if username != AUTHORIZED_USER:
        return jsonify({"valid": False}), 403
    return jsonify({"valid": True})

@app.route("/get_settings", methods=["GET"])
def get_settings():
    return jsonify(settings)

@app.route("/save_settings", methods=["POST"])
def save_settings():
    data = request.get_json()

    settings["contracts"] = int(data.get("contracts", 0))
    settings["tpslMethod"] = str(data.get("tpslMethod", ""))

    if settings["tpslMethod"] == "ticks":
        settings["takeProfit"] = int(data.get("takeProfit", 0))
        settings["stopLoss"] = int(data.get("stopLoss", 0))
        # Reset level-based fields when using ticks
        settings["contracts_tp1"] = 0
        settings["contracts_tp2"] = 0
        settings["beMethod"] = ""
        settings["backup_tp1"] = 0
        settings["backup_tp2"] = 0
        settings["backup_sl"] = 0
    else:
        # Levels mode
        settings["takeProfit"] = 0
        settings["stopLoss"] = 0
        settings["contracts_tp1"] = int(data.get("contractsTP1", 0))
        settings["contracts_tp2"] = int(data.get("contractsTP2", 0))
        settings["beMethod"] = str(data.get("beMethod", ""))
        # Backup levels (used if auto levels fail)
        settings["backup_tp1"] = int(data.get("backupTP1", 0))
        settings["backup_tp2"] = int(data.get("backupTP2", 0))
        settings["backup_sl"] = int(data.get("backupSL", 0))

    # Macro time filter toggle
    settings["useMacro"] = bool(data.get("useMacro", False))

    # --- Custom Sessions ---
    sessions = data.get("sessions", [])
    parsed_sessions = []

    for i, s in enumerate(sessions, start=1):
        try:
            parsed_sessions.append({
                "enabled": bool(s.get("enabled", False)),
                "start": str(s.get("start", "")),
                "end": str(s.get("end", ""))
            })
        except Exception as e:
            log_message(f"[Settings] Error parsing session {i}: {e}")
            parsed_sessions.append({
                "enabled": False,
                "start": "",
                "end": ""
            })

    settings["sessions"] = parsed_sessions

    log_message("[Bot] Settings updated.")
    return jsonify({"status": "ok", "settings": settings})


@app.route("/set_api_key", methods=["POST"])
def set_api_key():
    data = request.get_json()
    api_key = data.get("apiKey")
    prop_username = data.get("username")

    if not api_key or not prop_username:
        return jsonify({"error": "API key and prop username required"}), 400
    try:
        token_data = generate_token(api_key, prop_username)
        expiry_time = token_data["expiry"]
        token = token_data["token"]
        settings.update({
            "propUsername": prop_username,
            "apiKey": api_key,
            "token": token,
            "token_expiry": expiry_time.isoformat()
        })
        log_message(f"[Bot] API key authenticated for {prop_username}.")
        return jsonify({"status": "ok"})
    except Exception as e:
        log_message(f"[Bot] Error generating token: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/set_account", methods=["POST"])
def set_account():
    data = request.get_json()
    account_name = data.get("accountId")
    token = settings.get("token")
    if not token:
        return jsonify({"error": "No valid token. Please authenticate first."}), 400
    try:
        accounts_data = get_account(token)
        found = next(
            (a for a in accounts_data.get("accounts", [])
             if a.get("name", "").lower() == account_name.lower()), None)
        if not found:
            log_message(f"[Bot] Account not found for {account_name}")
            return jsonify({"status": "error", "error": "Account not found"}), 404
        settings["account"] = found["name"]
        settings["accountId"] = found["id"]
        log_message(f"[Bot] Account set: {found['name']}")
        return jsonify({"status": "ok"})
    except Exception as e:
        log_message(f"[Bot] Error fetching account: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/set_contract", methods=["POST"])
def set_contract():
    data = request.get_json()
    symbol = data.get("symbol", "").strip().upper()
    token = settings.get("token")
    if not token:
        return jsonify({"error": "No valid token."}), 400
    try:
        contract_data = get_contract(token)
        contracts = contract_data.get("contracts", [])
        alt_symbol = symbol
        if len(symbol) >= 3 and symbol[-2:].isdigit():
            alt_symbol = symbol[:-2] + symbol[-1]
        elif len(symbol) >= 2 and symbol[-1].isdigit():
            alt_symbol = symbol[:-1] + "2" + symbol[-1]
        found = next(
            (c for c in contracts
             if c.get("name", "").upper() in [symbol, alt_symbol]),
            None
        )
        if not found:
            log_message(f"[Bot] No contract match found for {symbol} or {alt_symbol}")
            return jsonify({
                "status": "error",
                "error": f"Contract '{symbol}' not found."
            }), 404
        settings["contractName"] = found["name"]
        settings["contractId"] = found["id"]
        settings["contractDesc"] = found.get("description", "")

        log_message(f"[Bot] Contract set: {found['name']} ({found['id']})")
        return jsonify({"status": "ok"})
    except Exception as e:
        log_message(f"[Bot] Error fetching contract: {e}")
        return jsonify({"error": str(e)}), 500

# ======================================================
# START / STOP
# ======================================================

@app.route("/start", methods=["POST"])
def start():
    global running
    running = True
    stop_event.clear()  # reset kill flag before starting threads

    if settings["tpslMethod"] == "ticks" and (settings["contracts"] <= 0 or settings["takeProfit"] <= 0 or settings["stopLoss"] <= 0):
        running = False
        log_message("[Bot] Error: You must set your contract size and TP/SL first to use ticks method.")
        return jsonify({"success": False}), 400
    
    # only start threads if they aren’t already alive
    start_thread("userhub", start_userhub)
    start_thread("heartbeat", heartbeat_monitor)
    start_thread("macro_time", macro_time_tracker)

    if settings["tpslMethod"] == "levels":
        start_thread("breakeven", breakeven_monitor)

    log_message(f"[Bot] Program ready — now taking in orders for {settings["contractName"]} | Mode: {settings["tpslMethod"].upper()} | BE Option: {settings["beMethod"].upper()}")
    return jsonify({"success": True})

@app.route("/stop", methods=["POST"])
def stop():
    global running, hub_connection
    running = False
    stop_event.set()  # broadcast shutdown

    log_message("[System] Stopping all threads...")

    try:
        if hub_connection:
            hub_connection.stop()
            log_message("[Topstep] Disconnected.")
    except Exception as e:
        log_message(f"[Topstep] Error closing connection: {e}")

    # Wait briefly for threads to exit
    for name, t in list(threads.items()):
        if t.is_alive():
            t.join(timeout=2)
            log_message(f"[System] Thread '{name}' stopped.")
    threads.clear()

    log_message("[Bot] Bot stopped successfully.")
    return jsonify({"success": True})

@app.route("/shutdown", methods=["POST"])
def shutdown():
    log_message("[System] Shutdown requested.")

    # 1. Stop bot logic first (threads, hub, running flag)
    global running, hub_connection

    running = False
    stop_event.set()

    try:
        if hub_connection:
            hub_connection.stop()
            log_message("[UserHub] Disconnected.")
    except Exception as e:
        log_message(f"[UserHub] Error closing connection: {e}")

    # Try to stop threads normally
    for name, t in list(threads.items()):
        if t.is_alive():
            t.join(timeout=2)
            if t.is_alive():
                log_message(f"[System] Thread '{name}' refused normal shutdown.")

    # 2. Hard exit if anything is still alive or if user wants full kill
    threads.clear()
    log_message("[System] Forcing full shutdown now.")
    os._exit(0)

    return jsonify({"success": True})

@app.route("/logs")
def logs():
    return Response(generate_logs(), mimetype="text/event-stream")

# ======================================================
# WEBHOOK
# ======================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    global running
    if not running:
        log_message("Alert ignored; bot not running.")
        return jsonify({"status": "ignored"})

    try:
        data = request.get_json() if request.is_json else {"message": request.data.decode("utf-8").strip()}
        log_message(f"Alert received: {data}")
        
        if settings.get("hasPosition"):
            log_message("Order skipped: already in position.")
            return jsonify({"status": "ignored", "reason": "position open"})

        msg = data.get("message", "").lower()
        side = 0 if "bullish" in msg else 1
        tp = settings["takeProfit"] * (1 if side == 0 else -1)
        sl = settings["stopLoss"] * (-1 if side == 0 else 1)

        order_resp = place_order(
            settings["accountId"],
            settings["contractId"],
            side,
            settings["contracts"],
            tp,
            sl,
            settings.get("token")
        )

        if order_resp.get("success"):
            return jsonify({"status": "ok", "order": order_resp})
        log_message("Failed to create order.")
        return jsonify({"status": "error", "order": order_resp})

    except Exception as e:
        log_message(f"Error in webhook: {e}")
        return jsonify({"error": str(e)}), 400

# ======================================================
# WEBHOOK_IFVG : Uses IFVG strategy (market + limit orders)
# ======================================================
@app.route("/webhook_ifvg", methods=["POST"])
def webhook_ifvg():
    global running,trade_lock, trade_state, in_ny_session

    if not running:
        log_message("[Trade] Alert ignored; bot not running.")
        return jsonify({"status": "ignored"})
    
    if trade_lock:
        log_message("[Trade] ⚠️ Trade lock active — another order is being processed.")
        return jsonify({"status": "ignored", "reason": "trade lock active"})
    
    if settings.get("hasPosition"):
            log_message("[Trade] Order skipped: already in position.")
            return jsonify({"status": "ignored", "reason": "position open"})
    
    # Only take trades when macro_time_active is True
    if not macro_time_active:
        log_message("[Trade] Ignored alert — outside allowed time window.")
        return jsonify({"status": "ignored"})

    
    trade_lock = True

    try:
        if request.is_json:
            data = request.get_json()
            message = data.get("message", "").lower().strip()
        else:
            raw = request.data.decode("utf-8").strip()
            message = raw.lower()
            data = {"message": message}

        if "test" in message:
            log_message(f"[Test] Alert received: {message}")
        else:
            log_message(f"[Trade] Alert received: {message}")

        # Direction
        if "bullish" in message:
            direction = "bullish"
            side = 0  # Buy
        elif "bearish" in message:
            direction = "bearish"
            side = 1  # Sell
        else:
            log_message("[Trade] No direction keyword found. Aborting.")
            trade_lock = False
            return jsonify({"error": "Missing 'bullish' or 'bearish' keyword"}), 400

        # If using ticks, place order here and exit
        if settings["tpslMethod"] == "ticks":
            tp = settings["takeProfit"] * (1 if side == 0 else -1)
            sl = settings["stopLoss"] * (-1 if side == 0 else 1)

            order_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                side,
                settings["contracts"],
                tp,
                sl,
                settings.get("token")
            )

            trade_lock = False
            if order_resp.get("success"):
                log_message(f"[Trade] {direction.upper()} market order placed successfully.")
                return jsonify({"status": "ok", "order": order_resp})
            
            log_message("[Trade] Failed to create order.")
            return jsonify({"status": "error", "order": order_resp})

        # Timeframe detection
        timeframe_tokens = [
            t for t in message.split()
            if t.endswith(("min", "m", "sec", "s"))
        ]

        if not timeframe_tokens:
            log_message("[Trade] No valid timeframe found. Aborting.")
            trade_lock = False
            return jsonify({"error": "Missing timeframe (e.g. '3min', '5m', '30sec')"}), 400

        try:
            # Extract numeric portion
            unit_number = int(''.join(ch for ch in timeframe_tokens[0] if ch.isdigit()))
            is_seconds = "sec" in timeframe_tokens[0] or timeframe_tokens[0].endswith("s")
            # Set appropriate unit code for your API (assuming 2 = minutes, 1 = seconds)
            unit_type = 1 if is_seconds else 2


        except ValueError:
            log_message("[Trade] Invalid timeframe format. Aborting.")
            trade_lock = False
            return jsonify({"error": "Invalid timeframe format"}), 400

        
        log_message(f"[Trade] Using timeframe: {unit_number} {'seconds' if is_seconds else 'minute'}")

        tp1_contracts = settings["contracts_tp1"]
        tp2_contracts = settings["contracts_tp2"]
        total_contracts = tp1_contracts + tp2_contracts
        settings["contracts"] = total_contracts

        # === 1. MARKET ENTRY ===
        order_resp = place_order(
            settings["accountId"],
            settings["contractId"],
            side,
            settings["contracts"],
            0,  # TP placeholder
            0,  # SL placeholder
            settings["token"],
            order_type=2  # MARKET
        )
        
        if not order_resp.get("success"):
            log_message(f"[Trade] {direction.upper()} market order failed: {order_resp}")
            trade_lock = False
            return jsonify({"error": "Market order failed"}), 500

        log_message(f"[Trade] {direction.upper()} market order placed successfully.")

        # === 1.5 FETCH REAL ENTRY PRICE ===
        pos_data = get_latest_position(settings["accountId"], settings["token"])
        if not pos_data:
            log_message("[Trade] Position not found after order placement; using fallback candle close.")
            entry_bar = retrieve_bars(settings["contractId"], settings["token"], unit=unit_type, unit_number=unit_number, limit=1)[-1]
            entry_price = entry_bar["c"]
        else:
            entry_price = pos_data.get("averagePrice")
            entry_bar = retrieve_bars(settings["contractId"], settings["token"], unit=unit_type, unit_number=unit_number, limit=1)[-1]
            entry_low = entry_bar["l"]
            entry_high = entry_bar["h"]

            log_message(f"[Trade] Entry price set from position data: {entry_price}")

        # === 2. RETRIEVE LEVELS ===
        if unit_type == 2:
            bars = retrieve_bars(settings["contractId"], settings["token"], unit=unit_type, unit_number=unit_number, limit=10000)
        elif unit_type == 1:
            bars = retrieve_bars(settings["contractId"], settings["token"], unit=unit_type, unit_number=unit_number, limit=5000)

        if not bars:
            log_message("[Trade] ❌ No bars retrieved. Aborting.")
            trade_lock = False
            return jsonify({"error": "Failed to retrieve bars"}), 500

        highs, lows = detect_swings(bars)
        bullish_fvgs, bearish_fvgs = detect_fvg(bars)
        # === Sort and Display Recent Swing Points (Newest → Oldest) ===
        # highs_sorted = sorted(highs, key=lambda x: x["time"], reverse=True)
        # lows_sorted = sorted(lows, key=lambda x: x["time"], reverse=True)
        # print('entry_high', entry_high)
        # print("\n=== Recent Swing Highs (Newest → Oldest) ===")
        # for h in highs_sorted[:15]:
        #     if h['price'] > entry_high:
        #         print(f"HIGH | {h['time']} | Price = {h['price']}")

        # print("\n=== Recent Swing Lows (Newest → Oldest) ===")
        # for l in lows_sorted[:15]:
        #     print(f"LOW  | {l['time']} | Price = {l['price']}")

        # Sort oldest → newest
        # highs_sorted = sorted(highs, key=lambda x: x["time"])
        # lows_sorted = sorted(lows, key=lambda x: x["time"])

        # print("\n=== Oldest Swing Highs (Oldest → Newest) ===")
        # for h in highs_sorted[:15]:
        #     print(f"HIGH | {h['time']} | Price = {h['price']}")

        # print("\n=== Oldest Swing Lows (Oldest → Newest) ===")
        # for l in lows_sorted[:15]:
        #     print(f"LOW  | {l['time']} | Price = {l['price']}")

        if direction == "bullish":
            levels = get_levels(direction, entry_high, highs, lows, bullish_fvgs, bearish_fvgs)
        elif direction == "bearish":
            levels = get_levels(direction, entry_low, highs, lows, bullish_fvgs, bearish_fvgs)
        
        sl_price = levels.get("sl")
        tp1_price = levels.get("tp1")
        tp2_price = levels.get("tp2")
        be_price = levels.get("be")

        # ----- Use back ups / ticks if levels were not found -----
        if not tp1_price or not tp2_price or not sl_price:
            contract = settings.get("contractName", "")
            direction = direction.lower()
            entry_price = float(entry_price)

            # If both TP1 and TP2 levels were not found then use backup ticks.    
            if not tp1_price or not tp2_price:
                backup_tp1 = settings["backup_tp1"]
                backup_tp2 = settings["backup_tp2"]

                # Tick size detection
                if "NQ" in contract:
                    tick_size = 0.25
                elif "GC" in contract:
                    tick_size = 0.1
                else:
                    tick_size = 0.25  # fallback

                # Direction-based math
                if direction == "bullish":
                    tp1_price = entry_price + (backup_tp1 * tick_size)
                    tp2_price = entry_price + (backup_tp2 * tick_size)
                elif direction == "bearish":
                    tp1_price = entry_price - (backup_tp1 * tick_size)
                    tp2_price = entry_price - (backup_tp2 * tick_size)
                else:
                    tp1_price, tp2_price = None, None

                log_message(f"[Trade] Backup TPs applied for {backup_tp1} & {backup_tp2} ticks")


            if not sl_price:
                backup_sl = settings["backup_sl"]

                # Define tick sizes per product type
                if "NQ" in contract:
                    tick_size = 0.25
                elif "GC" in contract:
                    tick_size = 0.1
                else:
                    tick_size = 0.25  # fallback

                # Calculate stop loss based on direction
                if direction == "bullish":
                    sl_price = entry_price - (backup_sl * tick_size)
                elif direction == "bearish":
                    sl_price = entry_price + (backup_sl * tick_size)
                else:
                    sl_price = None  # unrecognized direction

                log_message(f"[Trade] Backup SL applied for {backup_sl}")

        if not sl_price or not tp1_price or not tp2_price:
            log_message("[Trade] Missing one or more TP/SL levels.")
            trade_lock = False
            return jsonify({"error": "Invalid SL/TP values"}), 400

        if settings["beMethod"] == "first":
            log_message(f"[Trade] Levels → SL={sl_price} | BE={be_price} | {tp1_price} | TP2={tp2_price}")
        elif settings["beMethod"] == "tp1":
            log_message(f"[Trade] Levels → SL={sl_price} | BE/TP1: {tp1_price} | TP2={tp2_price}")
        else:
            log_message(f"[Trade] Levels → SL={sl_price} | BE=None | {tp1_price} | TP2={tp2_price}")
            
        # === 3. PLACE LIMIT ORDERS ===
        log_message("[Trade] Placing TP1, TP2, and SL orders...")

        if settings["beMethod"] == "first":
            trade_state['be_price'] = be_price
        elif settings["beMethod"] == "tp1":
            trade_state["be_price"] = tp1_price

        # --- LONG (bullish) setup ---
        if direction == "bullish":
            # TP1 (Sell Limit)
            tp1_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                1,  # Sell
                tp1_contracts,
                0, 0,
                settings["token"],
                price=tp1_price,
                order_type=1  # LIMIT
            )

            # TP2 (Sell Limit)
            tp2_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                1,  # Sell
                tp2_contracts,
                0, 0,
                settings["token"],
                price=tp2_price,
                order_type=1  # LIMIT
            )

            # SL (Sell Stop)
            sl_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                1,  # Sell
                total_contracts,
                0, 0,
                settings["token"],
                price=sl_price,
                order_type=4  # STOP
            )

        # --- SHORT (bearish) setup ---
        else:
            # TP1 (Buy Limit)
            tp1_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                0,  # Buy
                tp1_contracts,
                0, 0,
                settings["token"],
                price=tp1_price,
                order_type=1  # LIMIT
            )

            # TP2 (Buy Limit)
            tp2_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                0,  # Buy
                tp2_contracts,
                0, 0,
                settings["token"],
                price=tp2_price,
                order_type=1  # LIMIT
            )

            # SL (Buy Stop)
            sl_resp = place_order(
                settings["accountId"],
                settings["contractId"],
                0,  # Buy
                total_contracts,
                0, 0,
                settings["token"],
                price=sl_price,
                order_type=4  # STOP
            )

        # --- Record bracket orders in trade_state ---
        trade_state["tp_orders"] = [
            tp1_resp.get("orderId"),
            tp2_resp.get("orderId")
        ]
        trade_state["sl_order"] = sl_resp.get("orderId")
        trade_state["brackets_set"] = True

        # --- Log and return results ---
        # log_message(f"[Trade] TP1 order response: {tp1_resp} | TP2 order response: {tp2_resp} | SL order response: {sl_resp}")

        trade_lock = False

        return jsonify({
            "status": "ok",
            "direction": direction,
            "timeframe": unit_number,
            "levels": {"sl": sl_price, "tp1": tp1_price, "tp2": tp2_price},
            "tp1_response": tp1_resp,
            "tp2_response": tp2_resp,
            "sl_response": sl_resp
        })
    
    except Exception as e:
        log_message(f"[Trade] Error: {e}")
        return jsonify({"error": str(e)}), 500

# ======================================================
# Threads
# ======================================================
def start_thread(name, target):
    """Start a thread if it's not already alive."""
    if name in threads and threads[name].is_alive():
        log_message(f"[System] Thread '{name}' already running, skipping.")
        return
    t = threading.Thread(target=target, daemon=True, name=name)
    threads[name] = t
    t.start()
    log_message(f"[System] Thread '{name}' started.")

def heartbeat_monitor():
    """Periodically ping TopstepX to confirm connectivity (silent unless failure)."""
    url = "https://api.topstepx.com/api/Status/ping"
    failure_count = 0

    while not stop_event.is_set():
        try:
            resp = requests.get(url, timeout=5)
            text = resp.text.strip().lower()

            if resp.ok and text in ("pong", "ok", "healthy", "success"):
                failure_count = 0  # success — stay quiet
            else:
                failure_count += 1
                log_message(f"[Heartbeat] Unexpected ping response ({text or resp.status_code}) [{failure_count}x]")

        except Exception as e:
            failure_count += 1
            log_message(f"[Heartbeat] Ping error: {e} [{failure_count}x]")

        stop_event.wait(5)  # replaces time.sleep, allows instant stop
    log_message("[Heartbeat] exited.")

def breakeven_monitor():
    global trade_state

    while not stop_event.is_set():
        if not trade_state.get("active"):
            if stop_event.wait(3):
                break
            continue
        be_price = trade_state.get("be_price") 
        if not be_price:
            if stop_event.wait(3):
                break
            continue
    
        sl_order = trade_state.get("sl_order")
        if not sl_order:
            print("[BE] SL order not yet available, skipping this cycle.")
            if stop_event.wait(3):
                break
            continue
        bar = get_3sec_bar(settings["contractId"], settings["token"])

        if not bar:
            if stop_event.wait(3):
                break
            continue
        high = float(bar.get("high", 0))
        low = float(bar.get("low", 0))

        # --- LONG ---
        if trade_state["direction"] == "long" and high >= be_price:
            log_message(f"[BE] Breakeven hit @ {bar['high']}. Moving SL to BE.")
            modify_order(
                settings["accountId"],
                sl_order,
                new_size=trade_state["entry_size"],
                token=settings["token"],
                stop_price=trade_state["entry_price"]
            )
            trade_state["be_price"] = None

        # --- SHORT ---
        elif trade_state["direction"] == "short" and low <= be_price:
            log_message(f"[BE] Breakeven hit @ {bar['low']}. Moving SL to BE.")
            modify_order(
                settings["accountId"],
                sl_order,
                new_size=trade_state["entry_size"],
                token=settings["token"],
                stop_price=trade_state["entry_price"]
            )
            trade_state["be_price"] = None

        stop_event.wait(5)
    log_message("[BE Monitor] exited.")

def macro_time_tracker():
    global macro_time_active, running
    tz = ZoneInfo("America/Los_Angeles")

    while not stop_event.is_set():
        now = datetime.now(tz)
        hour, minute = now.hour, now.minute
        current_minutes = hour * 60 + minute

        use_macro = settings.get("useMacro", False)
        sessions = settings.get("sessions", [])

        # Tracks whether ANY session is enabled
        any_enabled = False
        in_session = False

        # ----------------------------------------
        # Custom Session Detection
        # ----------------------------------------
        for idx, s in enumerate(sessions, start=1):
            if not s.get("enabled"):
                continue

            any_enabled = True

            try:
                start_h, start_m = map(int, s.get("start", "00:00").split(":"))
                end_h, end_m = map(int, s.get("end", "00:00").split(":"))
                start_total = start_h * 60 + start_m
                end_total = end_h * 60 + end_m

                # Normal case (start < end)
                if start_total <= end_total:
                    active = start_total <= current_minutes < end_total
                else:
                    # Overnight session (e.g. 23:59 -> 02:01)
                    active = (
                        current_minutes >= start_total or
                        current_minutes < end_total
                    )

                if active:
                    in_session = True
                    break

            except Exception as e:
                log_message(f"[Macro] Invalid session format: {e}")

        # ----------------------------------------
        # If NO sessions are enabled, allow full-time trading
        # ----------------------------------------
        if not any_enabled:
            in_session = True

        # ----------------------------------------
        # Macro Windows (NY Only)
        # ----------------------------------------
        ny_start = 6 * 60 + 20
        ny_end = 13 * 60 + 10
        in_ny = ny_start <= current_minutes < ny_end

        if use_macro and in_ny:
            # Macro windows:
            # XX:50 - YY:10
            # XX:20 - XX:40
            macro_window = (
                minute >= 50 or              # 50 -> 59
                minute <= 10 or              # 00 -> 10
                (20 <= minute <= 40)         # 20 -> 40
            )
        else:
            # No macro enforcement
            macro_window = True

        # ----------------------------------------
        # Final Decision
        # ----------------------------------------
        macro_time_active = in_session and macro_window

        if stop_event.wait(1):
            break

# ======================================================
# RUN
# ======================================================
if __name__ == "__main__":
    # app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)



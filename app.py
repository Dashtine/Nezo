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
from trades_db import init_db, calculate_analytics, create_trade, update_trade


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
from levels import retrieve_bars, detect_swings, detect_fvg, get_levels, get_2sec_bar
from market_cache import init_timeframe_cache, get_cached_structures, start_cache_refresher, quick_refresh

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
    "active": False,
    "direction": None,
    "entry_price": None,
    "entry_size": 0,
    "account_id": None,
    "tp_orders": [],
    "sl_order": None,
    "be_price": None,
    "opened_at": None,
    "closed_at": None,
    "brackets_set": False,
    "pending_direction": None,   # 🔹 used for Strategy A (levels mode)
    "pending_timeframe": None,
    "pending_symbol": None,
    "pending_sl": 0,
    "tp1_filled": False,
    "be_active": False
}


AUTHORIZED_USER = "jkpqismuggle"
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
                        "account_id": None,
                        "tp_orders": [],
                        "sl_order": None,
                        "be_price": None,
                        "be_active": False,
                        "opened_at": None,
                        "closed_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
                        "brackets_set": False,
                        "pending_direction": None,
                        "pending_timeframe": None,
                        "pending_symbol": None,
                        "pending_sl": 0,
                        "tp1_filled": False
                    })
                else:
                    print("[Topstep] Position close event received, but no active trade tracked.")
                return

            # === POSITION OPENED / ADJUSTED ===
            if action == 1:
                if settings["tpslMethod"] == "ticks":
                        log_message(f"[Topstep] {side} position OPENED @ {avg_price} (size={size})")
                        return
                

                side_label = "long" if ttype == 1 else "short"
                entry_price = avg_price

                # Brand new position JUST opened
                if not trade_state.get("active"):

                    trade_state.update({
                        "active": True,
                        "direction": side_label,
                        "entry_price": entry_price,
                        "entry_size": size,
                        "account_id": account_id,
                        "opened_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
                        "brackets_set": False
                    })
                    log_message(f"[Topstep] {side} position OPENED @ {avg_price} (size={size})")

                    # ============================================================
                    # STRATEGY A: PLACE BRACKETS HERE
                    # ============================================================

                    pending_dir = trade_state.get("pending_direction")

                    if not pending_dir:
                        log_message("[Trade] No pending direction stored. Skipping bracket placement.")
                        return

                    # Load cached structure (fast, no API calls)
                    # quick_refresh(settings["contractId"], settings["token"], "1m")
                    cache = get_cached_structures("1m")
                    if not cache:
                        log_message("[Trade] Cache unavailable. Cannot compute FVG/TP/SL levels.")
                        return
 
                    highs = cache["highs"]
                    lows = cache["lows"]
                    bullish_fvgs = cache["bullish_fvgs"]
                    bearish_fvgs = cache["bearish_fvgs"]

                    bars = cache["bars"]
                    last_bar = bars[-1]
                    entry_high = last_bar["h"]
                    entry_low = last_bar["l"]

                    # Determine correct entry reference
                    if pending_dir == "bullish":
                        levels = get_levels("bullish", entry_high, highs, lows, bullish_fvgs, bearish_fvgs)
                    else:
                        levels = get_levels("bearish", entry_low, highs, lows, bullish_fvgs, bearish_fvgs)

                    sl_price = levels.get("sl")
                    tp1_price = levels.get("tp1")
                    tp2_price = levels.get("tp2")
                    be_price = levels.get("be")

                    if not sl_price or not tp1_price or not tp2_price:
                        log_message("[Trade] Missing TP/SL levels. Aborting bracket placement.")
                        return

                    # Assign BE level
                    if settings["beMethod"] == "first":
                        trade_state["be_price"] = be_price
                    elif settings["beMethod"] == "tp1":
                        trade_state["be_price"] = tp1_price
                    else:
                        trade_state["be_price"] = None

                    # Get contracts
                    tp1_contracts = settings["contracts_tp1"]
                    tp2_contracts = settings["contracts_tp2"]
                    total_contracts = tp1_contracts + tp2_contracts

                    token = settings["token"]
                    contract_id = settings["contractId"]
                    account_id = settings["accountId"]

                    # ============================================================
                    # Place TP/SL bracket orders
                    # ============================================================
                    if pending_dir == "bullish":
                        # TP1 Sell Limit
                        tp1_resp = place_order(account_id, contract_id, 1, tp1_contracts,
                                            0, 0, token, price=tp1_price, order_type=1)

                        # TP2 Sell Limit
                        tp2_resp = place_order(account_id, contract_id, 1, tp2_contracts,
                                            0, 0, token, price=tp2_price, order_type=1)

                        # SL Sell Stop
                        sl_resp = place_order(account_id, contract_id, 1, total_contracts,
                                            0, 0, token, price=sl_price, order_type=4)

                    else:  # bearish
                        # TP1 Buy Limit
                        tp1_resp = place_order(account_id, contract_id, 0, tp1_contracts,
                                            0, 0, token, price=tp1_price, order_type=1)

                        # TP2 Buy Limit
                        tp2_resp = place_order(account_id, contract_id, 0, tp2_contracts,
                                            0, 0, token, price=tp2_price, order_type=1)

                        # SL Buy Stop
                        sl_resp = place_order(account_id, contract_id, 0, total_contracts,
                                            0, 0, token, price=sl_price, order_type=4)

                    # Save order IDs
                    trade_state["tp_orders"] = [tp1_resp.get("orderId"), tp2_resp.get("orderId")]
                    trade_state["sl_order"] = sl_resp.get("orderId")
                    trade_state["brackets_set"] = True

                    # Clear pending
                    trade_state["pending_direction"] = None
                    
                    log_message(f"[Trade] Brackets placed → SL={sl_price} | BE={trade_state["be_price"]} | TP1={tp1_price} | TP2={tp2_price}")
                    placed_at = datetime.now(ZoneInfo("America/Los_Angeles")).isoformat()

                    trade_id = create_trade(
                        placed_at=placed_at,
                        account=settings.get("account", settings.get("accountId", "")),
                        symbol=settings["contractName"],
                        timeframe=trade_state.get("timeframe", "1m"),
                        entry_price=entry_price,
                        stoploss_price=sl_price
                    )

                    trade_state["trade_id"] = trade_id

                    log_message(f"[Trade] Database record created → trade_id={trade_id}")
                    return
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

                    remaining_size = total_size - tp1_size
                    if remaining_size <= 0:
                        remaining_size = 0
                        
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
                        trade_state["be_active"] = True
                        if modify_resp.get("success"):
                            log_message(f"[Topstep] SL size updated → {remaining_size} contracts and moved to breakeven after TP1 fill.")
                        else:
                            log_message(f"[Topstep] Failed to modify SL size or move stoploss to breakeven: {modify_resp}")
                    else:
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
                    # --- DB UPDATE: TP1 HIT ---
                    trade_state["tp1_filled"] = True
                    trade_id = trade_state.get("trade_id")
                    if trade_id:
                        update_trade(
                            trade_id,
                            tp1_filled_price=data.get("averagePrice"),
                            tp1_hit=1,
                            result="win"
                        )
                        log_message(f"[Trade] TP1 update saved → trade_id={trade_id}")

                    trade_state["be_price"] = None
                    return


                except Exception as e:
                    log_message(f"[UserHub] Error modifying SL after TP1 fill: {e}")

            # --- CASE 2: TP2 filled (full take profit = WIN) ---
            if len(tp_orders) >= 2 and order_id == tp_orders[1]:
                log_message(f"[Topstep] TP2 filled (order {order_id}). Full take profit reached.")

                trade_id = trade_state.get("trade_id")
                if trade_id:
                    update_trade(
                        trade_id,
                        tp2_filled_price=data.get("averagePrice"),
                        tp2_hit=1,
                        result="win"
                    )
                    log_message(f"[Trade] WIN recorded → trade_id={trade_id}")
                trade_state["be_active"] = False
                # Do NOT modify SL here. TP2 means trade is DONE.
                return
            
            # --- CASE 3: Stoploss filled ---
            if order_id == sl_order:

                trade_id = trade_state.get("trade_id")
                be_active = trade_state.get("be_active", False)

                # BE METHOD = FIRST
                if settings["beMethod"] == "first":
                    if trade_state.get("tp1_filled"):
                        # TP1 guarantees a win even if SL later hits at BE
                        result = "win"
                    elif be_active:
                        # BE triggered before TP1 → breakeven result
                        result = "be"
                    else:
                        # Stoploss hit with no BE and no TP1 → full loss
                        result = "lose"


                # BE METHOD = TP1
                elif settings["beMethod"] == "tp1":
                    if trade_state.get("tp1_filled"):
                        result = "win"
                    else:
                        result = "lose"

                # Update DB
                if trade_id:
                    update_trade(trade_id, result=result)
                    log_message(f"[Trade] Result recorded → {result} | trade_id={trade_id}")
                    
                trade_state["be_active"] = False
                log_message(f"[Trade] SL fill → result={result} → trade_id={trade_id}")

                return

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

        # 🔹 NEW: Preload 1m swings/FVGs cache
        contract_id = settings.get("contractId")
        token = settings.get("token")

        if contract_id and token:
            try:
                log_message("[LevelsCache] Preloading 1m swings/FVGs cache...")
                ok = init_timeframe_cache(contract_id, token, tf_key="1m")
                if ok:
                    log_message("[LevelsCache] 1m cache warmed successfully.")
                else:
                    log_message("[LevelsCache] Failed to warm 1m cache (no bars).")
                    
                # 🔹 Start background refresher
                start_cache_refresher(contract_id, token, stop_event)
                log_message("[LevelsCache] Background refresher started")

            except Exception as e:
                log_message(f"[LevelsCache] Error preloading 1m cache: {e}")
        else:
            log_message("[LevelsCache] Skipped cache warm-up — missing contractId or token.")

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
# WEBHOOK_IFVG : Uses IFVG strategy
#   - ticks mode: market + brackets here
#   - levels mode: MARKET ONLY, brackets handled in on_position_update
# ======================================================
@app.route("/webhook_ifvg", methods=["POST"])
def webhook_ifvg():
    global running, trade_lock, trade_state, in_ny_session

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
        # ---------------------------
        # Parse incoming alert
        # ---------------------------
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
            unit_number = int(''.join(ch for ch in timeframe_tokens[0] if ch.isdigit()))
            is_seconds = "sec" in timeframe_tokens[0] or timeframe_tokens[0].endswith("s")
            unit_type = 1 if is_seconds else 2  # 1 = seconds, 2 = minutes (for future use if needed)
        except ValueError:
            log_message("[Trade] Invalid timeframe format. Aborting.")
            trade_lock = False
            return jsonify({"error": "Invalid timeframe format"}), 400

        log_message(f"[Trade] Using timeframe: {unit_number} {'seconds' if is_seconds else 'minute'}")

        # ======================================================
        # TICKS MODE: TP & SL are placed here. That's it.
        # ======================================================
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
                log_message(f"[Trade] {direction.upper()} market order placed with TP/SL brackets.")
                return jsonify({"status": "ok", "order": order_resp})
            
            log_message(f"[Trade] Failed to create market order: {order_resp}")
            return jsonify({"status": "error", "order": order_resp}), 500

        # ======================================================
        # LEVELS MODE: MARKET ENTRY ONLY
        #   Brackets will be placed inside on_position_update
        # ======================================================
        tp1_contracts = settings["contracts_tp1"]
        tp2_contracts = settings["contracts_tp2"]
        total_contracts = tp1_contracts + tp2_contracts
        settings["contracts"] = total_contracts

        # Save intended direction BEFORE placing the market order
        trade_state["pending_direction"] = direction
        trade_state["brackets_set"] = False
        trade_state["entry_size"] = total_contracts
        print(settings["contracts"])

        order_resp = place_order(
            settings["accountId"],
            settings["contractId"],
            side,
            settings["contracts"],
            0,  # no TP ticks here
            0,  # no SL ticks here
            settings["token"],
            order_type=2  # MARKET
        )

        if not order_resp.get("success"):
            log_message(f"[Trade] Market order failed (levels mode): {order_resp}")
            trade_lock = False
            return jsonify({"error": "Market order failed", "order": order_resp}), 500

        log_message(f"[Trade] {direction.upper()} market order placed successfully.")

        trade_lock = False

        return jsonify({
            "status": "ok",
            "mode": "levels",
            "message": "Market order placed. Brackets will be set on position fill.",
            "direction": direction,
            "timeframe": {
                "unit_type": unit_type,
                "unit_number": unit_number,
                "is_seconds": is_seconds
            }
        })

    except Exception as e:
        trade_lock = False
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
        # Only check when a trade is active AND brackets exist
        if not trade_state.get("active"):
            if stop_event.wait(2):
                break
            continue

        be_price = trade_state.get("be_price")
        if not be_price:
            if stop_event.wait(2):
                break
            continue
    
        sl_order = trade_state.get("sl_order")
        if not sl_order:
            print("[BE] SL order not yet available, skipping this cycle.")
            if stop_event.wait(2):
                break
            continue
        bar = get_2sec_bar(settings["contractId"], settings["token"])
        if not bar:
            if stop_event.wait(2):
                break
            continue
        high = float(bar["high"])
        low = float(bar["low"])

        direction = trade_state.get("direction")
        entry_price = trade_state.get("entry_price")
        entry_size = trade_state.get("entry_size")

        # === LONG BE Trigger ===
        if trade_state["direction"] == "long" and high >= be_price:
            log_message(f"[BE] Breakeven hit @ {bar['high']}. Moving SL to BE.")
            modify_order(
                settings["accountId"],
                sl_order,
                new_size=entry_size,
                token=settings["token"],
                stop_price=entry_price
            )

            trade_state["be_price"] = None
            trade_state["be_active"] = True
            continue

        # --- SHORT ---
        elif trade_state["direction"] == "short" and low <= be_price:
            log_message(f"[BE] Breakeven hit @ {bar['high']}. Moving SL to BE.")
            modify_order(
                settings["accountId"],
                sl_order,
                new_size=entry_size,
                token=settings["token"],
                stop_price=entry_price
            )

            trade_state["be_price"] = None
            trade_state["be_active"] = True
            continue

        time.sleep(1)


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



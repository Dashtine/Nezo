import pytz
import threading
import logging
import time
from signalrcore.hub_connection_builder import HubConnectionBuilder
from flask import Flask, request, jsonify, render_template, Response
from datetime import datetime, timezone
from topstepx_api import place_order, get_account, get_contract, has_open_position, generate_token

app = Flask(__name__)

# ======================================================
# CONFIGURATION
# ======================================================

# All settings live only in memory
settings = {
    "contracts": 0,
    "takeProfit": 0,
    "stopLoss": 0,
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

AUTHORIZED_USER = "jkpqismuggle"  # your only valid username
running = False
log_messages = []
hub_connection = None

# ======================================================
# TOPSTEPX LIVE FEED
# ======================================================
from signalrcore.hub_connection_builder import HubConnectionBuilder
import threading
import logging


def start_userhub():
    global hub_connection
    token = settings.get("token")
    account_id = settings.get("accountId")
    hub_url = f"https://rtc.topstepx.com/hubs/user?access_token={token}"
    if not token or not account_id:
        log_message("[UserHub] Cannot start: Missing token or account ID.")
        return

    try:
        # ======================================================
        # 1. Build connection
        # ======================================================
        log_message("[UserHub] Attempting to connect to TopstepX Live Feed")

        # Uncomment line below to show debug messages of the SignalR
        # logging.basicConfig(level=logging.DEBUG)

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
        # ======================================================
        # 2. Event handlers
        # ======================================================
        def on_open():
            log_message("[UserHub] Connected successfully.")
            # These method names are per the TopstepX docs
            connection.send("SubscribeAccounts", [])
            connection.send("SubscribeOrders", [account_id])
            connection.send("SubscribePositions", [account_id])
            connection.send("SubscribeTrades", [account_id])
            log_message(f"[UserHub] Subscribed to account {account_id}")

        def on_close():
            log_message("[UserHub] Connection closed.")

        def on_error(err):
            log_message(f"[UserHub] Error: {err}")

        def on_generic(args):
            log_message(f"[UserHub] Raw event: {args}")

        def on_account_update(args):
            print("[UserHub] Account update:", args)

        def on_order_update(args):
            print("[UserHub] Order update:", args)

        def on_position_update(args):
            # Normalize payload
            payload = args[0] if isinstance(args, list) and args else args
            if not isinstance(payload, dict):
                return

            action = payload.get("action")
            pos = payload.get("data", {})

            if not isinstance(pos, dict):
                return

            size = pos.get("size", 0)
            avg_price = pos.get("averagePrice")
            trade_type = pos.get("type")        # 1 = long, 2 = short
            side = "Long" if trade_type == 1 else "Short" if trade_type == 2 else "?"

            # Update position flag
            settings["hasPosition"] = size != 0

            # Log simplified info
            if action == 1:  # opened or updated
                log_message(f"{side} placed at {avg_price}")
            elif action == 2:  # closed
                log_message(f"Position closed at {avg_price}")

            # Optional state confirmation
            # log_message(f"[UserHub] hasPosition={settings['hasPosition']} (size={size})")




        def on_trade_update(args):
            print("[UserHub] Trade update:", args)
        # ======================================================
        # 3. Register handlers
        # ======================================================
        connection.on_open(on_open)
        connection.on_close(on_close)
        connection.on_error(on_error)

        # Debug catch-all (shows all traffic)
        # connection.on("GatewayUserAccount", on_account_update)
        # connection.on("GatewayUserOrder", on_order_update)
        # connection.on("GatewayUserTrade", on_trade_update)
        connection.on("GatewayUserPosition", on_position_update)
        # ======================================================
        # 4. Start connection in background thread
        # ======================================================
        # threading.Thread(target=connection.start, daemon=True).start()
        connection.start()

        while True:
            time.sleep(5)

    except Exception as e:
        log_message(f"[UserHub] Failed to start: {e}")
# ======================================================
# HELPER FUNCTIONS
# ======================================================
def log_message(message):
    timestamp = datetime.now().strftime('%m-%d-%y %H:%M:%S')
    entry = f"[{timestamp}] {message}"
    print(entry)
    log_messages.append(entry)
    if len(log_messages) > 100:
        log_messages.pop(0)


def generate_logs():
    while True:
        if log_messages:
            yield f"data: {log_messages.pop(0)}\n\n"


# ======================================================
# ROUTES
# ======================================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/validate_user', methods=['POST'])
def validate_user():
    data = request.get_json()
    username = data.get("username", "").strip()
    if username != AUTHORIZED_USER:
        return jsonify({"valid": False}), 403
    return jsonify({"valid": True})


@app.route('/get_settings', methods=['GET'])
def get_settings():
    return jsonify(settings)


@app.route('/save_settings', methods=['POST'])
def save_settings():
    data = request.get_json()
    settings["contracts"] = int(data.get("contracts", 0))
    settings["takeProfit"] = int(data.get("takeProfit", 0))
    settings["stopLoss"] = int(data.get("stopLoss", 0))
    log_message("Settings updated in memory.")
    return jsonify({"status": "ok", "settings": settings})


@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    data = request.get_json()
    api_key = data.get("apiKey")
    prop_username = data.get("propUsername")

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

        # pst = pytz.timezone("America/Los_Angeles")
        # expiry_pst = expiry_time.replace(tzinfo=timezone.utc).astimezone(pst)
        # expiry_str = expiry_pst.strftime("%Y-%m-%d %I:%M %p %Z")

        log_message(f"API key authenticated for {prop_username}! Next, set account and symbol!")

        return jsonify("status" "ok", "expiry")

    except Exception as e:
        log_message(f"Error generating token: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/set_account', methods=['POST'])
def set_account():
    data = request.get_json()
    account_name = data.get("account")

    token = settings.get("token")
    if not token:
        return jsonify({"error": "No valid token. Please validate your API key first."}), 400

    try:
        accounts_data = get_account(token)
        accounts = accounts_data.get("accounts", [])
        found = next((a for a in accounts if a.get("name", "").lower() == account_name.lower()), None)

        if found:
            settings["account"] = found.get("name")
            settings["accountId"] = found.get("id")
            log_message(f"Account set: {found.get('name')} ({found.get('id')})")

            return jsonify({
                "status": "ok",
                "account": found.get("name"),
                "accountId": found.get("id")
            })

        else:
            return jsonify({"status": "error", "error": "Account not found"}), 404

    except Exception as e:
        log_message(f"Error fetching account: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/set_contract', methods=['POST'])
def set_contract():
    data = request.get_json()
    symbol = data.get("symbol", "").strip().upper()
    token = settings.get("token")

    if not token:
        return jsonify({"error": "No valid token. Please validate your API key first."}), 400

    try:
        contract_data = get_contract(token)
        contracts = contract_data.get("contracts", [])

        # Normalize user input and build alternate possibilities
        # Example: user enters MNQZ25 -> alt is MNQZ5
        #          or user enters MNQZ5  -> alt is MNQZ25
        alt_symbol = symbol
        if len(symbol) >= 3 and symbol[-2:].isdigit():
            # Ends with two digits (e.g. MNQZ25)
            alt_symbol = symbol[:-2] + symbol[-1]
        elif len(symbol) >= 2 and symbol[-1].isdigit():
            # Ends with one digit (e.g. MNQZ5)
            alt_symbol = symbol[:-1] + "2" + symbol[-1]
        # Try matching either version
        found = next(
            (c for c in contracts if c.get("name", "").upper() in [symbol, alt_symbol]),
            None
        )

        if found:
            settings["contractName"] = found.get("name")
            settings["contractId"] = found.get("id")
            settings["contractDesc"] = found.get("description", "")

            log_message(
                f"Contract set: {found.get('name')} ({found.get('id')}) - {found.get('description', '')}"
            )

            return jsonify({
                "status": "ok",
                "contractName": found.get("name"),
                "contractId": found.get("id"),
                "description": found.get("description", "")
            })
        else:
            log_message(f"No contract match found for {symbol} or {alt_symbol}")
            return jsonify({
                "status": "error",
                "error": f"Contract '{symbol}' not found. Tried '{alt_symbol}' too."
            }), 404

    except Exception as e:
        log_message(f"Error fetching contract: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/start', methods=['POST'])
def start():
    global running
    running = True

    if settings["contracts"] <= 0 or settings["takeProfit"] <= 0 or settings["stopLoss"] <= 0:
        running = False
        log_message("Error: You must set your contract size and TP/SL first.")
        return jsonify({"success": False}), 400

    log_message("Program started! Connecting to TopstepX live feed...")
    threading.Thread(target=start_userhub, daemon=True).start()

    log_message("Program ready — now taking in orders!")
    return jsonify({"success": True})


@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    log_message("Bot stopped")

    if hub_connection:
        try:
            hub_connection.stop()
            log_message("[UserHub] Disconnected from live feed.")
        except Exception as e:
            log_message(f"[UserHub] Error closing connection: {e}")
        
    return jsonify({"success": True})


@app.route('/logs')
def logs():
    return Response(generate_logs(), mimetype='text/event-stream')


@app.route('/webhook', methods=['POST'])
def webhook():
    global running
    if not running:
        log_message("Alert ignored because bot is not running")
        return jsonify({"status": "ignored"})

    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = {"message": request.data.decode("utf-8").strip()}

        log_message(f"Alert received: {data}")

        if settings.get("hasPosition"):
            log_message("Order skipped: already in a position")
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
        elif order_resp.get("success") and not settings.get("hasPosition"):
            log_message("Failed to create order.")
            return jsonify({"status": "error", "order": order_resp})

    except Exception as e:
        log_message(f"Error in webhook: {e}")
        return jsonify({"error": str(e)}), 400


# ======================================================
# TEST ROUTES (manual trigger buttons)
# ======================================================
@app.route('/test_long', methods=['POST'])
def test_long():
    """Simulate a bullish TradingView alert"""
    log_message("TEST: Placing long market order!")

    # Create fake alert payload identical to a real webhook
    fake_alert = {"message": "1m-15m MNQZ2025: Potential Bullish Candle"}

    with app.test_request_context(
        '/webhook',
        method='POST',
        json=fake_alert
    ):
        response = webhook()
        print("Webhook response from /test_long:", response)
    return jsonify({"status": "ok"})


@app.route('/test_short', methods=['POST'])
def test_short():
    """Simulate a bearish TradingView alert"""
    log_message("TEST: Placing short market order!")

    fake_alert = {"message": "1m-15m MNQZ2025: Potential Bearish Candle"}

    with app.test_request_context(
        '/webhook',
        method='POST',
        json=fake_alert
    ):
        response = webhook()
        print("Webhook response from /test_short:", response)
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
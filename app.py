import json
import os
import pytz
from flask import Flask, request, jsonify, render_template, Response, send_from_directory
from datetime import datetime, timezone, timedelta
from topstepx_api import ACC_ID, CONTRACT_ID, place_order, get_account, get_account, get_contract, has_open_position, generate_token

app = Flask(__name__)

config_file = "user_configs.json"
settings = {
    "contracts": 0,
    "takeProfit": 0,
    "stopLoss": 0
}

running = False
log_messages = []

@app.route('/')
def index():
    return render_template('index.html')

def load_config():
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    return {"users": {}}

def save_config(config):
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

def reload_config():
    global config
    config = load_config()

config = load_config()

# Saves the on screen parameters to the users configuration
@app.route('/save_settings', methods=['POST'])
def save_settings():
    data = request.get_json()
    username = data.get("username")
    reload_config()
    if username not in config["users"]:
        return jsonify({"error": "unauthorized"}), 403

    config["users"][username] = {
        "contracts": int(data.get("contracts", 1)),
        "takeProfit": int(data.get("takeProfit", 0)),
        "stopLoss": int(data.get("stopLoss", 0))
    }
    save_config(config)
    return jsonify({"status": "ok", "settings": config["users"][username]})

# Get user's settings
@app.route('/get_settings', methods=['GET'])
def get_settings():
    username = request.args.get("username")
    reload_config()
    if username not in config["users"]:
        return jsonify({"error": "unauthorized"}), 403
    return jsonify(config["users"][username])

# Places a market long order
@app.route('/test_long', methods=['POST'])
def test_long():
    log_message("TEST: Placed long market order!")
    test_plain_text = '{"message": "1m-15m MNQZ2025: Potential Bullish Candle 2"}'
    
    with app.test_request_context(
        '/webhook',
        method='POST',
        data=test_plain_text,
        content_type='text/plain'
    ):
        response = webhook()
        print("Webhook response from /start:", response)

    return ''
  
@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    data = request.get_json()
    # username = 'j<kpqismuggle'

    username = data.get("username")          # dashboard username
    prop_username = data.get("propUsername") # prop-firm username
    api_key = data.get("apiKey")
    print(username)
    print(api_key)
    print(prop_username)
    if not username or not api_key or not prop_username:
        return jsonify({"error": "Username, prop-firm username, and API key required"}), 400

    reload_config()
    if username not in config["users"]:
        return jsonify({"error": "Unauthorized user"}), 403

    try:
        token_data = generate_token(api_key, prop_username)
        expiry_time = token_data["expiry"]
        token = token_data["token"]

        config["users"][username]["propUsername"] = prop_username
        config["users"][username]["apiKey"] = api_key
        config["users"][username]["token"] = token
        config["users"][username]["token_expiry"] = expiry_time.isoformat()
        save_config(config)

        # convert UTC to PST for display
        pst = pytz.timezone("America/Los_Angeles")
        expiry_pst = expiry_time.replace(tzinfo=timezone.utc).astimezone(pst)
        expiry_str = expiry_pst.strftime("%Y-%m-%d %I:%M %p %Z")

        log_message(f"Token generated for {username} ({prop_username}), expires {expiry_str}")

        return jsonify({
            "status": "ok",
            "expiry": expiry_str
        })

    except Exception as e:
        log_message(f"Error generating token for {username}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/check_token', methods=['GET'])
def check_token():
    # username = 'j<kpqismuggle'
    username = request.args.get("username")
    reload_config()

    if username not in config["users"]:
        return jsonify({"error": "Unauthorized user"}), 403

    user = config["users"][username]
    token = user.get("token")
    expiry_str = user.get("token_expiry")

    if not token or not expiry_str:
        return jsonify({"valid": False, "message": "No token found"}), 200

    try:
        expiry_time = datetime.fromisoformat(expiry_str)
    except ValueError:
        return jsonify({"valid": False, "message": "Invalid expiry format"}), 200
    
    if expiry_time.tzinfo is None:
        expiry_time = expiry_time.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)

    if now > expiry_time:
        return jsonify({
            "valid": False,
            "message": "Token expired. Please validate key again."
        }), 200

    # Convert to PST for nice display
    pst = pytz.timezone("America/Los_Angeles")
    expiry_pst = expiry_time.astimezone(pst)
    expiry_display = expiry_pst.strftime("%Y-%m-%d %I:%M %p %Z")

    return jsonify({
        "valid": True,
        "expiry": expiry_display,
        "message": f"Session is good for 24 hours. You must validate again before {expiry_display}."
    }), 200


@app.route('/set_account', methods=['POST'])
def set_account():
    data = request.get_json()
    username = data.get("username")
    account_name = data.get("account")
    print("set_account", account_name)
    if not username or not account_name:
        return jsonify({"error": "Username and account name required"}), 400

    reload_config()
    if username not in config["users"]:
        return jsonify({"error": "Unauthorized user"}), 403

    user_data = config["users"][username]
    token = user_data.get("token")

    if not token:
        return jsonify({"error": "No valid token. Please validate your API key first."}), 400

    try:
        accounts_data = get_account(token)
        # Expecting something like {"accounts": [{"name": "Demo Account", "id": "1234"}, ...]}
        accounts = accounts_data.get("accounts", [])
        found = next((a for a in accounts if a.get("name", "").lower() == account_name.lower()), None)

        if found:
            account_id = found.get("id") or found.get("accountId") or found.get("account_id")
            user_data["account"] = account_name
            user_data["accountId"] = account_id
            save_config(config)
            log_message(f"Account set for {username}: {account_name} ({account_id})")
            return jsonify({
                "status": "ok",
                "account": account_name,
                "accountId": account_id
            })
        else:
            user_data["account"] = account_name
            user_data["accountId"] = "Invalid"
            save_config(config)
            log_message(f"Invalid account for {username}: {account_name}")
            return jsonify({
                "status": "error",
                "error": f"Account '{account_name}' not found",
                "accountId": "Invalid"
            })

    except Exception as e:
        user_data["account"] = account_name
        user_data["accountId"] = "Invalid"
        save_config(config)
        log_message(f"Error fetching account for {username}: {e}")
        return jsonify({"error": str(e), "accountId": "Invalid"}), 500


@app.route('/set_contract', methods=['POST'])
def set_contract():
    data = request.get_json()
    username = data.get("username")
    user_input = data.get("symbol", "").strip().upper()

    if not username or not user_input:
        return jsonify({"error": "Username and contract name required"}), 400

    reload_config()
    if username not in config["users"]:
        return jsonify({"error": "Unauthorized user"}), 403

    user_data = config["users"][username]
    token = user_data.get("token")

    if not token:
        return jsonify({"error": "No valid token. Please validate your API key first."}), 400

    try:
        contract_data = get_contract(token)
        contracts = contract_data.get("contracts", [])

        # --- Normalize search ---
        # Example: if user types MNQZ25, alt is MNQZ5; if they type MNQZ5, alt is MNQZ25
        alt_input = user_input
        if len(user_input) >= 3 and user_input[-2:].isdigit():
            # ends with two digits (e.g. MNQZ25)
            alt_input = user_input[:-2] + user_input[-1]
        elif len(user_input) >= 2 and user_input[-1].isdigit():
            # ends with one digit (e.g. MNQZ5)
            alt_input = user_input[:-1] + "2" + user_input[-1]  # append likely decade marker (guess 2020s)

        # --- Match either version ---
        found = next(
            (c for c in contracts if c.get("name", "").upper() in [user_input, alt_input]),
            None
        )

        if found:
            contract_id = found.get("id")
            contract_desc = found.get("description", "")
            actual_name = found.get("name")

            user_data["contractName"] = actual_name
            user_data["contractId"] = contract_id
            user_data["contractDesc"] = contract_desc
            save_config(config)

            log_message(f"Contract set for {username}: {actual_name} ({contract_id}) - {contract_desc}")

            return jsonify({
                "status": "ok",
                "contractName": actual_name,
                "contractId": contract_id,
                "description": contract_desc
            })
        else:
            user_data["contractName"] = user_input
            user_data["contractId"] = "Invalid"
            user_data["contractDesc"] = ""
            save_config(config)
            log_message(f"Invalid contract for {username}: {user_input}")

            return jsonify({
                "status": "error",
                "error": f"Contract '{user_input}' not found",
                "contractId": "Invalid"
            })

    except Exception as e:
        user_data["contractName"] = user_input
        user_data["contractId"] = "Invalid"
        user_data["contractDesc"] = ""
        save_config(config)
        log_message(f"Error fetching contract for {username}: {e}")
        return jsonify({"error": str(e), "contractId": "Invalid"}), 500
    

# Places a market short order
@app.route('/test_short', methods=['POST'])
def test_short():
    log_message("TEST: Placing short market order!")
    test_plain_text = '{"message": "1m-15m MNQZ2025: Potential Bearish Candle 2"}'
    
    with app.test_request_context(
        '/webhook',
        method='POST',
        data=test_plain_text,
        content_type='text/plain'
    ):
        response = webhook()
        print("Webhook response from /start:", response)

    return ''

# Outputs a message on to the screen
def log_message(message):
    timestamp = datetime.now().strftime('%m-%d-%y %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    log_messages.append(log_entry)
    if len(log_messages) > 100:
        log_messages.pop(0)

# generates logs
def generate_logs():
    while True:
        if log_messages:
            yield f"data: {log_messages.pop(0)}\n\n"





# Enables taking in orders only if contract size, tp, and sl are set
@app.route('/start', methods=['POST'])
def start():
    global running
    running = True

    contracts = int(settings.get("contracts", 0))
    takeProfit_ticks = int(settings.get("takeProfit", 0))
    stopLoss_ticks = int(settings.get("stopLoss", 0))

    if contracts <= 1 or takeProfit_ticks <= 1 or stopLoss_ticks <= 1:
        running = False
        log_message("Error: You must set your contract size and number of ticks for TP / SL")
        return jsonify({"success": False}), 400

    log_message("Program started! Now taking in orders!")

    return ''

# Disables placing orders
@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    log_message("Bot stopped")
    return ''

@app.route('/logs')
def logs():
    return Response(generate_logs(), mimetype='text/event-stream')

# Alerts from TradingView and test functions enter here to parses data to prepare for order placement
@app.route('/webhook', methods=['POST'])
def webhook():
    global running
    if not running:
        log_message("Alert ignored because bot is not running")
        return jsonify({"status": "ignored", "reason": "bot not running"})

    try:
        if request.is_json:
            data = request.get_json()
        else:
            raw_data = request.data.decode("utf-8").strip()
            data = {"message": raw_data}

        log_message(f"Alert received: {data}")

        if has_open_position(ACC_ID):
            log_message("Order skipped: already in a position")
            return jsonify({"status": "ignored", "reason": "position open"})
        
        contracts = int(settings.get("contracts", 0))
        takeProfit_ticks = int(settings.get("takeProfit", 0))
        stopLoss_ticks = int(settings.get("stopLoss", 0))

        if "message" in data:
            msg = data["message"].lower()

            if "bullish" in msg:
                signal = 0
                stopLoss_ticks = stopLoss_ticks * -1
            elif "bearish" in msg:
                signal = 1
                takeProfit_ticks = takeProfit_ticks * -1

            order_resp = place_order(ACC_ID, CONTRACT_ID, signal, contracts, takeProfit_ticks, stopLoss_ticks)
            print("Order response:", order_resp)

                    
        if order_resp.get("success"):
            log_message("Order Created!")
            return jsonify({"status": "order executed", "order": order_resp})
        else:
            log_message("Failed to create order!")
            return jsonify({"status": "order failed", "order": order_resp})

    except Exception as e:
        log_message(f"Error in webhook: {e}")
        return jsonify({"error": "Invalid data"}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
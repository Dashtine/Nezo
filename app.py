import json
import os
from flask import Flask, request, jsonify, render_template, Response, send_from_directory
from datetime import datetime
from topstepx_api import ACC_ID, CONTRACT_ID, place_order, get_accounts, get_contracts, has_open_position

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
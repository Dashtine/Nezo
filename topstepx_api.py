import requests
from datetime import datetime, timedelta

BASE_URL = "https://api.topstepx.com"   # or demo gateway if you're testing
API_TOKEN = ""
CONTRACT_ID = "CON.F.US.MNQ.Z25"
ACC_ID = "9216410"


def _headers():
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }

# Places a market based on alert and parameters
def place_order(account_id, contract_id, side, size, tp_ticks, sl_ticks):
    url = f"{BASE_URL}/api/Order/place"

    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,   # 2 = Market order
        "side": side,
        "size": size,
        "takeProfitBracket": {
          "ticks": tp_ticks,
          "type": 1
        },
        "stopLossBracket": {
        "ticks": sl_ticks, 
        "type": 4
        }
    }

    resp = requests.post(url, headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()

# checks if there are any open positions
# returns true if there are
def has_open_position(account_id):
    url = f"{BASE_URL}/api/Position/searchOpen"

    payload = {"accountId": account_id}

    resp = requests.post(url, headers=_headers(), json=payload)
    resp.raise_for_status()
    data = resp.json()

    positions = data.get("positions", [])
    return len(positions) > 0


# Verify and grab the account id
def get_account(token):
    """Return list of accounts for the authenticated user."""
    url = f"{BASE_URL}/api/Account/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {"onlyActiveAccounts": True}

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

# Verify and get contract id
def get_contract(token):
    """Return all available contracts for the user."""
    url = f"{BASE_URL}/api/Contract/available"
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {"live": False}

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def generate_token(api_key, username=None):
    """Use the user's API key to request a new access token from TopstepX."""
    url = f"{BASE_URL}/api/Auth/loginKey"
    headers = {
        "accept": "text/plain",
        "Content-Type": "application/json"
    }

    payload = {
        "userName": username,
        "apiKey": api_key}
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    token_data = resp.json()

    # Extract fields based on actual response structure
    token = token_data.get("token")
    success = token_data.get("success", False)
    error_message = token_data.get("errorMessage")

    if not success or not token:
        raise Exception(f"TopstepX authentication failed: {error_message or 'Unknown error'}")

    # TopstepX doesn’t provide expiry, so we assume 1 hour validity
    expiry_time = datetime.utcnow() + timedelta(hours=24)

    if username:
        print(f"[TopstepX] Token generated for {username}, assumed expiry {expiry_time.isoformat()}")

    return {
        "token": token,
        "expiry": expiry_time
    }



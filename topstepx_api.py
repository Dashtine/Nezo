import requests
from datetime import datetime, timedelta

BASE_URL = "https://api.topstepx.com"  # main TopstepX API endpoint


# Builds the authorization headers dynamically
def _headers(token=None):
    return {
        "Authorization": f"Bearer {token or ''}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }


# ======================================================
# Order Placement
# ======================================================
def place_order(account_id, contract_id, side, size, tp_ticks, sl_ticks, token):
    """
    Places a market order with TP and SL brackets.
    side: 0 = Buy, 1 = Sell
    """
    url = f"{BASE_URL}/api/Order/place"

    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,  # 2 = Market
        "side": side,
        "size": size,
        "takeProfitBracket": {"ticks": tp_ticks, "type": 1},
        "stopLossBracket": {"ticks": sl_ticks, "type": 4}
    }

    resp = requests.post(url, headers=_headers(token), json=payload)
    resp.raise_for_status()
    return resp.json()



# ======================================================
# Position Checking
# ======================================================
def has_open_position(account_id, token=None):
    """
    Checks if there are any open positions for the given account.
    Returns True if open positions exist.
    """
    url = f"{BASE_URL}/api/Position/searchOpen"
    payload = {"accountId": account_id}

    resp = requests.post(url, headers=_headers(token), json=payload)
    resp.raise_for_status()
    data = resp.json()
    return len(data.get("positions", [])) > 0


# ======================================================
# Account and Contract Management
# ======================================================
def get_account(token):
    """
    Returns list of active accounts for the authenticated user.
    """
    url = f"{BASE_URL}/api/Account/search"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"onlyActiveAccounts": True}
    )
    resp.raise_for_status()
    return resp.json()


def get_contract(token):
    """
    Returns list of available contracts for the authenticated user.
    """
    url = f"{BASE_URL}/api/Contract/available"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"live": False}
    )
    resp.raise_for_status()
    return resp.json()


# ======================================================
# Authentication
# ======================================================
def generate_token(api_key, username=None):
    """
    Exchanges an API key for a temporary session token.
    Returns dict with token and expiry datetime.
    """
    url = f"{BASE_URL}/api/Auth/loginKey"
    payload = {"userName": username, "apiKey": api_key}
    headers = {"accept": "text/plain", "Content-Type": "application/json"}

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    token_data = resp.json()

    token = token_data.get("token")
    success = token_data.get("success", False)
    error_message = token_data.get("errorMessage")

    if not success or not token:
        raise Exception(f"TopstepX authentication failed: {error_message or 'Unknown error'}")

    expiry_time = datetime.utcnow() + timedelta(hours=24)
    print(f"[TopstepX] Token generated for {username or 'N/A'}, expires {expiry_time.isoformat()}")

    return {"token": token, "expiry": expiry_time}



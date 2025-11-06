import requests
import json
import time
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
def place_order(account_id, contract_id, side, size, tp_ticks, sl_ticks, token, price=None, order_type=2):
    """
    Places an order on TopstepX.
    side: 0 = Buy, 1 = Sell
    order_type:
        1 = Limit
        2 = Market
        3 = StopLimit
        4 = Stop
    price: required for limit and stop orders
    """
    url = f"{BASE_URL}/api/Order/place"

    if tp_ticks != 0 and sl_ticks != 0:
        payload = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": 2,  # 2 = Market
            "side": side,
            "size": size,
            "takeProfitBracket": {"ticks": tp_ticks, "type": 1},
            "stopLossBracket": {"ticks": sl_ticks, "type": 4}
        }
    else:
        payload = {
            "accountId": account_id,
            "contractId": contract_id,
            "side": side,
            "size": size,
            "type": order_type
        }

        # Assign correct price field based on order type
        if order_type == 1 and price:  # Limit
            payload["limitPrice"] = price
        elif order_type in (3, 4) and price:  # Stop or StopLimit
            payload["stopPrice"] = price

    headers = _headers(token)

    # Debug log
    # print(f"[place_order] Payload: {payload}")

    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ======================================================
# Cancel Orders
# ======================================================
def cancel_order(order_id, token, account_id=None):
    print("order_id", order_id)
    print("account_id",account_id)
    """
    Cancels a specific order by ID.
    Requires both accountId and orderId in payload.
    """
    url = f"{BASE_URL}/api/Order/cancel"
    headers = _headers(token)

    payload = {
        "accountId": account_id,
        "orderId": int(order_id)
    }

    print(f"[cancel_order] Payload: {payload}")

    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        print(f"[cancel_order] Response: {data}")
        return data
    except Exception as e:
        print(f"[cancel_order] Error canceling order {order_id}: {e}")
        return {"success": False, "error": str(e)}

# ======================================================
# Modify Orders
# ======================================================
def modify_order(account_id, order_id, new_size=None, token=None, stop_price=None, limit_price=None, trail_price=None):
    """
    Modifies an existing order's size and/or price (stop, limit, trail).
    Fields left as None will not be sent to the API.
    """
    url = f"{BASE_URL}/api/Order/modify"
    headers = _headers(token)

    # Base payload
    payload = {
        "accountId": int(account_id),
        "orderId": int(order_id)
    }

    # Include optional params only if specified
    if new_size is not None:
        payload["size"] = int(new_size)
    if limit_price is not None:
        payload["limitPrice"] = float(limit_price)
    if stop_price is not None:
        payload["stopPrice"] = float(stop_price)
    if trail_price is not None:
        payload["trailPrice"] = float(trail_price)

    print(f"[modify_order] Payload: {payload}")

    try:
        resp = requests.post(url, headers=headers, json=payload)
        text = resp.text.strip()
        if not text:
            print(f"[modify_order] ⚠️ Empty response body (status={resp.status_code})")
            return {"success": False, "error": "Empty response"}
        data = resp.json()
        print(f"[modify_order] Response: {data}")
        return data
    except Exception as e:
        print(f"[modify_order] Error modifying order {order_id}: {e}")
        return {"success": False, "error": str(e)}





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
# Get Latest Position
# ======================================================
def get_latest_position(account_id, token):
    """Polls TopstepX until a new position appears (returns its data)."""
    url = f"{BASE_URL}/api/Position/searchOpen"
    payload = {"accountId": account_id}

    for _ in range(10):  # up to 10 tries (~1s)
        resp = requests.post(url, headers=_headers(token), json=payload)
        if not resp.ok:
            time.sleep(0.1)
            continue

        data = resp.json()
        positions = data.get("positions", [])
        if positions:
            # Assuming only one active instrument
            return positions[0]

        time.sleep(0.1)

    return None


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



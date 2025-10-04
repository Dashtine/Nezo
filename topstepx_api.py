import requests

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


# Return list of accounts available for this user
def get_accounts():
    url = f"{BASE_URL}/api/Account/search"
    resp = requests.post(url, headers=_headers(), json={"onlyActiveAccounts": True})
    resp.raise_for_status()
    return resp.json()

# Return all available contracts
def get_contracts():
    url = f"{BASE_URL}/api/Contract/available"
    resp = requests.post(url, headers=_headers(), json={"live": True})
    resp.raise_for_status()
    return resp.json()
import requests, time
from datetime import datetime, timedelta, timezone

API_URL = "https://api.topstepx.com/api/History/retrieveBars"
EPS = 1e-3
_last_no_bar_log = 0

# ======================================================
# DEBUG PRINTERS
# ======================================================
def fmt_swing_list(swings, label):
    """Pretty-print the last 10 swings (raw UTC timestamps)."""
    print(f"\n=== Last 10 {label} ===")
    for s in reversed(swings[-10:]):  # newest → oldest
        print(f"{s['time']} | {label[:-1]} Price = {s['price']}")
    print("=========================================\n")


# ======================================================
# BAR FETCHER
# ======================================================
def retrieve_bars(contract_id, token, unit=2, unit_number=3, limit=10000, inc_partial=False):
    """Fetch recent bars from TopstepX API (supports seconds or minutes, all UTC)."""
    # print(f"[Bars] limit={limit} | unit_number={unit_number}")

    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        now_utc = datetime.now(timezone.utc)

        # === Determine correct time range ===
        if unit == 1:  # seconds (e.g., 30sec)
            # Use current time for freshest bars; don't floor to a previous bucket
            end_utc = now_utc.replace(microsecond=0)
            start_utc = end_utc - timedelta(seconds=43200 * unit_number)
        else:  # minutes (e.g., 1m, 3m, 5m)
            if unit_number <= 1:
                end_utc = now_utc.replace(microsecond=0)
            else:
                floored_minute = (now_utc.minute // unit_number) * unit_number
                end_utc = now_utc.replace(minute=floored_minute, second=0, microsecond=0)
            start_utc = end_utc - timedelta(minutes=5000 * unit_number)

        # print(f"Start UTC: {start_utc.isoformat()} | End UTC: {end_utc.isoformat()}")

        payload = {
            "contractId": contract_id,
            "live": False,                  
            "startTime": start_utc.isoformat(),
            "endTime": end_utc.isoformat(),
            "unit": unit,                   # 1 = seconds, 2 = minutes
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": inc_partial       
        }

        resp = requests.post(API_URL, headers=headers, json=payload)
        data = resp.json()

        if not data.get("success"):
            print(f"[Bars] API Error: {data.get('errorMessage')}")
            return []

        bars = data.get("bars", [])
        if not bars:
            print("[Bars] No bars returned.")
            return []

        bars_sorted = sorted(bars, key=lambda b: b["t"])

        # Debug print for last 10 candles
        # recent_10 = list(reversed(bars_sorted[-10:]))
        # print("\n=== Most Recent 10 Candles ===")
        # for bar in recent_10:
        #     print(f"{bar['t']} | O={bar['o']} H={bar['h']} L={bar['l']} C={bar['c']}")
        # print("=========================================\n")

        return bars_sorted

    except Exception as e:
        print(f"[Bars] Failed to retrieve bars: {e}")
        return []


def get_2sec_bar(contract_id, token):
    """Fetch the most recent 3-second bar from TopstepX API (UTC)."""
    global _last_no_bar_log
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        now_utc = datetime.now(timezone.utc)
        end_utc = now_utc.replace(microsecond=0)
        start_utc = end_utc - timedelta(seconds=15)  # small window around now

        payload = {
            "contractId": contract_id,
            "live": False,            # historical service
            "startTime": start_utc.isoformat(),
            "endTime": end_utc.isoformat(),
            "unit": 1,                # 1 = seconds
            "unitNumber": 2,          # 2-second bars
            "limit": 1,               # only the latest bar
            "includePartialBar": True # allow the current forming bar
        }

        resp = requests.post(API_URL, headers=headers, json=payload)
        data = resp.json()

        if not data.get("success"):
            print(f"[Levels] API Error: {data.get('errorMessage')}")
            return None

        bars = data.get("bars", [])
        if not bars:
            now = time.time()
            # log this message only every 15 seconds
            if now - _last_no_bar_log >= 300:
                print("[Levels] No 2-second bars returned.")
                _last_no_bar_log = now
            return None

        bar = bars[-1]
        # Example structure: {'t': '2025-10-29T01:43:53.000Z', 'o': 3978.2, 'h': 3978.8, 'l': 3977.9, 'c': 3978.3}
        return {
            "time": bar["t"],
            "open": float(bar["o"]),
            "high": float(bar["h"]),
            "low": float(bar["l"]),
            "close": float(bar["c"])
        }

    except Exception as e:
        print(f"[Levels] Failed to retrieve 2-second bar: {e}")
        return None
    
# ======================================================
# SWING DETECTION
# ======================================================
def detect_swings(bars):
    """Detect swing highs/lows (uses raw UTC timestamps)."""
    highs, lows = [], []
    if len(bars) < 3:
        return highs, lows

    last_bar = bars[-1]
    last_low, last_high = float(last_bar["l"]), float(last_bar["h"])
    # print(f"last_low={last_low}, last_high={last_high}")

    for i in range(1, len(bars) - 1):
        prev_bar, bar, next_bar = bars[i-1], bars[i], bars[i+1]

        # swing high
        if bar["h"] >= prev_bar["h"] and bar["h"] >= next_bar["h"]:
            if abs(bar["h"] - last_high) < 0.01:
                continue
            highs.append({"price": bar["h"], "time": bar["t"]})

        # swing low
        if bar["l"] <= prev_bar["l"] and bar["l"] <= next_bar["l"]:
            if abs(bar["l"] - last_low) < 0.01:
                continue
            lows.append({"price": bar["l"], "time": bar["t"]})

    return highs, lows


# ======================================================
# FAIR VALUE GAP DETECTOR
# ======================================================
def detect_fvg(bars):
    """Detect bullish/bearish FVGs (UTC timestamps)."""
    bullish_fvgs, bearish_fvgs = [], []
    for i in range(2, len(bars)):
        c1, _, c3 = bars[i-2], bars[i-1], bars[i]

        # Bullish FVG (gap below price)
        if c1["h"] < c3["l"]:
            bullish_fvgs.append({
                "type": "bullish",
                "start_time": c1["t"],
                "end_time": c3["t"],
                "gap_top": float(c3["l"]),
                "gap_bottom": float(c1["h"])
            })
        # Bearish FVG (gap above price)
        elif c1["l"] > c3["h"]:
            bearish_fvgs.append({
                "type": "bearish",
                "start_time": c1["t"],
                "end_time": c3["t"],
                "gap_top": float(c1["l"]),
                "gap_bottom": float(c3["h"])
            })

    # print(f"[Levels] Detected {len(bullish_fvgs)} bullish and {len(bearish_fvgs)} bearish FVGs.")
    return bullish_fvgs, bearish_fvgs


# ======================================================
# LEVEL GENERATOR
# ======================================================
def _parse_any(ts: str) -> datetime:
    """Parse ISO UTC timestamps from Topstep."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def get_levels(direction, entry_price, highs, lows, bullish_fvgs, bearish_fvgs):
    """Compute stop loss and take profit levels using swings + FVGs."""
    sl = be = tp1 = tp2 = None
    d = direction.lower()

    if d == "bullish":
        # sort by time ascending (oldest→newest)
        sorted_lows = sorted(lows, key=lambda x: x["time"])

        # find most recent swing low below entry
        for low in reversed(sorted_lows):
            if low["price"] < entry_price - EPS:
                sl = low["price"]
                sl_time = low["time"]
                print(f"[Levels] SL chosen from swing low → Time: {sl_time} | Price: {sl}")
                break

    else:
        sorted_highs = sorted(highs, key=lambda x: x["time"])

        # find most recent swing high above entry
        for high in reversed(sorted_highs):
            if high["price"] > entry_price + EPS:
                sl = high["price"]
                sl_time = high["time"]
                print(f"[Levels] SL chosen from swing high → Time: {sl_time} | Price: {sl}")
                break


    # --- BUILD CHRONOLOGICAL LIST ---
    candidates = []

    if d == "bullish":
        for h in highs:
            candidates.append((_parse_any(h["time"]), float(h["price"]), "swing_high"))
        for fvg in bearish_fvgs:
            candidates.append((_parse_any(fvg["end_time"]), float(fvg["gap_bottom"]), "bear_fvg_bottom"))
        side_check = lambda px: px > entry_price + EPS
        move_check = lambda px, prev: px > prev + EPS

    else:  # bearish
        for l in lows:
            candidates.append((_parse_any(l["time"]), float(l["price"]), "swing_low"))
        for fvg in bullish_fvgs:
            candidates.append((_parse_any(fvg["end_time"]), float(fvg["gap_top"]), "bull_fvg_top"))
        side_check = lambda px: px < entry_price - EPS
        move_check = lambda px, prev: px < prev - EPS

    # Sort newest → oldest
    candidates.sort(key=lambda x: x[0], reverse=True)

    # print("\n=== Candidate Timeline (Newest → Oldest) ===")
    # for t_utc, price, kind in candidates:
    #     print(f"{t_utc.isoformat()} | {price:<8.2f} | {kind}")
    # print("===========================================\n")

    # --- BUILD SEQUENTIAL LEVELS ---
    ladder = []
    for _, price, _ in candidates:
        if not side_check(price):
            continue
        if not ladder:
            ladder.append(price)
        elif move_check(price, ladder[-1]):
            ladder.append(price)
        if len(ladder) == 3:
            break

    if len(ladder) >= 1:
        be = ladder[0]
    if len(ladder) >= 2:
        tp1 = ladder[1]
    if len(ladder) >= 3:
        tp2 = ladder[2]

    print(f"[Levels] Direction={direction} | Entry={entry_price} | "
          f"SL={sl} | BE={be} | TP1={tp1} | TP2={tp2}")
    return {"sl": sl, "be": be, "tp1": tp1, "tp2": tp2}


# ======================================================
# QUICK TEST
# ======================================================
if __name__ == "__main__":
    TOKEN = "<your_token_here>"
    CONTRACT_ID = "CON.F.US.MNQ.Z25"

    bars = retrieve_bars(CONTRACT_ID, TOKEN, unit_number=3, limit=200, inc_partial=False)
    if not bars:
        print("[Levels] No bars retrieved — exiting.")
    else:
        highs, lows = detect_swings(bars)
        fmt_swing_list(highs, "Swing Highs")
        fmt_swing_list(lows, "Swing Lows")

        bullish_fvgs, bearish_fvgs = detect_fvg(bars)
        entry_price = bars[-1]["c"]

        levels = get_levels("bearish", entry_price, highs, lows, bullish_fvgs, bearish_fvgs)
        print(levels)

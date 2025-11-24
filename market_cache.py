# market_cache.py

import threading
import time
from datetime import datetime, timezone, timedelta

from levels import retrieve_bars, detect_swings, detect_fvg

# Timeframe config (we'll extend this later: 15s, 30s, 2m, 3m, 5m, etc.)
TIMEFRAMES = {
    "1m": {
        "unit": 2,              # 2 = minutes
        "unit_number": 1,
        "limit": 10000,         # increased from 2500 → 10000 for deeper history
        "max_cache": 10000      # rolling window size (will use in incremental refresh)
    },
}

_cache_lock = threading.Lock()

# Structure:
# {
#   "1m": {
#       "bars": [...],
#       "highs": [...],
#       "lows": [...],
#       "bullish_fvgs": [...],
#       "bearish_fvgs": [...],
#       "meta": {...},
#       "last_update": datetime
#   }
# }
_market_cache = {}

def normalize_ts(ts: str):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def _build_timeframe_cache(contract_id, token, tf_key: str) -> bool:
    """Fetch full bars & compute swings/FVGs for a single timeframe."""
    cfg = TIMEFRAMES.get(tf_key)
    if not cfg:
        return False

    # Fetch historical bars (large initial load)
    bars = retrieve_bars(
        contract_id=contract_id,
        token=token,
        unit=cfg["unit"],
        unit_number=cfg["unit_number"],
        limit=cfg["limit"],
        inc_partial=False
    )

    if not bars:
        print(f"[LevelsCache] No bars returned for timeframe {tf_key}")
        return False

    highs, lows = detect_swings(bars)
    bullish_fvgs, bearish_fvgs = detect_fvg(bars)

    with _cache_lock:
        _market_cache[tf_key] = {
            "bars": bars,
            "highs": highs,
            "lows": lows,
            "bullish_fvgs": bullish_fvgs,
            "bearish_fvgs": bearish_fvgs,
            "meta": {
                "unit": cfg["unit"],
                "unit_number": cfg["unit_number"],
                "limit": cfg["limit"],
                "max_cache": cfg["max_cache"]
            },
            "last_update": datetime.now(timezone.utc)
        }

    print("Warmup bars:", len(bars))

    return True



def init_timeframe_cache(contract_id, token, tf_key: str = "1m") -> bool:
    """
    Public entry to build cache for a specific timeframe.
    Called at bot startup.
    """
    return _build_timeframe_cache(contract_id, token, tf_key)





def get_cached_structures(tf_key: str = "1m"):
    with _cache_lock:
        data = _market_cache.get(tf_key)
        if not data:
            return None

        return {
            "bars": list(data["bars"]),          # 🔥 ADD THIS
            "highs": list(data["highs"]),
            "lows": list(data["lows"]),
            "bullish_fvgs": list(data["bullish_fvgs"]),
            "bearish_fvgs": list(data["bearish_fvgs"]),
            "meta": dict(data["meta"]),
            "last_update": data["last_update"],
        }

def same_minute(ts1, ts2):
    dt1 = normalize_ts(ts1)
    dt2 = normalize_ts(ts2)
    return dt1.year == dt2.year and dt1.month == dt2.month and dt1.day == dt2.day \
           and dt1.hour == dt2.hour and dt1.minute == dt2.minute

# ======================================================
# BACKGROUND REFRESHER FOR TIMEFRAME CACHE
# ======================================================
def _incremental_refresh(contract_id, token, tf_key: str):
    """Incrementally update the cache by fetching only the newest bars."""

    cfg = TIMEFRAMES.get(tf_key)
    if not cfg:
        return False

    max_cache = cfg["max_cache"]

    # Step 1: Load existing cache
    with _cache_lock:
        existing = _market_cache.get(tf_key)

    if not existing:
        # No cache yet → fallback to full build
        return _build_timeframe_cache(contract_id, token, tf_key)

    old_bars = existing["bars"]
    if not old_bars:
        return _build_timeframe_cache(contract_id, token, tf_key)

    last_cached_time = normalize_ts(old_bars[-1]["t"])

    # Step 2: Fetch only a few recent bars (small incremental pull)
    recent_bars = retrieve_bars(
        contract_id=contract_id,
        token=token,
        unit=cfg["unit"],
        unit_number=cfg["unit_number"],
        limit=15,
        inc_partial=True
    )

    if not recent_bars:
        print("[LevelsCache] Incremental: No new bars received.")
        return False

    # Step 3: Find bars newer than our last cached bar
    new_bars = [
        b for b in recent_bars
        if normalize_ts(b["t"]) > last_cached_time
    ]

    if not new_bars:
        return True
    
    # Filter out bars from the same minute (duplicate partial bars)
    filtered_new_bars = []
    
    for nb in new_bars:
        if not same_minute(nb["t"], old_bars[-1]["t"]):
            print(f"nb: {nb['t']} || old_bars: {old_bars[-1]['t']}")
            filtered_new_bars.append(nb)

    # If after filtering we have nothing new, exit early
    if not filtered_new_bars:
        return True

    # Step 4: Combine old + new
    combined = old_bars + filtered_new_bars

    # Step 5: Trim cache to rolling window
    if len(combined) > max_cache:
        combined = combined[-max_cache:]

    # Step 6: Detect swings/gaps around the update region
    # We only need to re-check a few bars before the new ones
    recheck_start = max(0, len(combined) - len(filtered_new_bars) - 15)
    window = combined[recheck_start:]
    first_recheck_time = normalize_ts(combined[recheck_start]["t"])


    # Local detection
    local_highs, local_lows = detect_swings(window)
    local_bull_fvg, local_bear_fvg = detect_fvg(window)

    # Step 7: Remove structure that falls within the recalculation window
    frt = first_recheck_time

    updated_highs = [
        h for h in existing["highs"]
        if normalize_ts(h["time"]) < frt
    ]

    updated_lows = [
        l for l in existing["lows"]
        if normalize_ts(l["time"]) < frt
    ]

    updated_bull_fvg = [
        f for f in existing["bullish_fvgs"]
        if normalize_ts(f["start_time"]) < frt
    ]

    updated_bear_fvg = [
        f for f in existing["bearish_fvgs"]
        if normalize_ts(f["start_time"]) < frt
    ]


    # Deduplicate local swings within the window
    unique_local_highs = []
    seen = set()

    for h in local_highs:
        key = (h["time"], h["price"])
        if key not in seen:
            seen.add(key)
            unique_local_highs.append(h)

    unique_local_lows = []
    seen = set()

    for l in local_lows:
        key = (l["time"], l["price"])
        if key not in seen:
            seen.add(key)
            unique_local_lows.append(l)

    # Deduplicate FVGs inside window
    unique_bull_fvg = []
    seen_bull = set()
    for f in local_bull_fvg:
        key = (f["start_time"], f["end_time"])
        if key not in seen_bull:
            seen_bull.add(key)
            unique_bull_fvg.append(f)

    unique_bear_fvg = []
    seen_bear = set()
    for f in local_bear_fvg:
        key = (f["start_time"], f["end_time"])
        if key not in seen_bear:
            seen_bear.add(key)
            unique_bear_fvg.append(f)

    # Step 8: Add ONLY the newly detected swings/FVGs from window
    updated_highs.extend(unique_local_highs)
    updated_lows.extend(unique_local_lows)
    updated_bull_fvg.extend(unique_bull_fvg)
    updated_bear_fvg.extend(unique_bear_fvg)


    # Step 9: Save updated cache
    with _cache_lock:
        _market_cache[tf_key] = {
            "bars": combined,
            "highs": updated_highs,
            "lows": updated_lows,
            "bullish_fvgs": updated_bull_fvg,
            "bearish_fvgs": updated_bear_fvg,
            "meta": existing["meta"],
            "last_update": datetime.now(timezone.utc)
        }
    # print("Incremental new bars:", len(new_bars))
    # print("Total swing highs:", len(updated_highs))
    # print("Total swing lows:", len(updated_lows))
    # Debug: print last 5 swing highs and lows
    print("Last 5 swing highs:")
    for h in updated_highs[-5:]:
        print(f"  {h['time']} | {h['price']}")

    print("Last 5 swing lows:")
    for l in updated_lows[-5:]:
        print(f"  {l['time']} | {l['price']}")

    return True

def quick_refresh(contract_id, token, tf_key="1m"):
    """Super-light refresh: only checks for a new fully formed bar."""
    cfg = TIMEFRAMES.get(tf_key)
    if not cfg:
        return False

    with _cache_lock:
        existing = _market_cache.get(tf_key)
    if not existing:
        return False

    old_bars = existing["bars"]
    last_ts = normalize_ts(old_bars[-1]["t"])

    # fetch only newest bar
    recent = retrieve_bars(
        contract_id,
        token,
        unit=cfg["unit"],
        unit_number=cfg["unit_number"],
        limit=2
    )

    if not recent:
        return False

    newest = recent[-1]
    newest_ts = normalize_ts(newest["t"])

    # Only add if the minute changed
    if newest_ts.minute == last_ts.minute:
        return True

    # append the new bar
    combined = old_bars + [newest]
    if len(combined) > cfg["max_cache"]:
        combined = combined[-cfg["max_cache"]:]

    # detect swings only inside last 3–5 bars
    window = combined[-10:]
    local_highs, local_lows = detect_swings(window)
    local_bull, local_bear = detect_fvg(window)

    # merge
    updated_highs = existing["highs"] + local_highs
    updated_lows = existing["lows"] + local_lows
    updated_bull = existing["bullish_fvgs"] + local_bull
    updated_bear = existing["bearish_fvgs"] + local_bear

    with _cache_lock:
        _market_cache[tf_key] = {
            "bars": combined,
            "highs": updated_highs,
            "lows": updated_lows,
            "bullish_fvgs": updated_bull,
            "bearish_fvgs": updated_bear,
            "meta": existing["meta"],
            "last_update": datetime.now(timezone.utc)
        }

    return True


def start_cache_refresher(contract_id, token, stop_event):
    TARGET_OFFSET = 59.8

    def _refresh_loop():
        print("[LevelsCache] Background Refresher started.")

        while not stop_event.is_set():
            now = datetime.now(timezone.utc)

            # Target time inside THIS minute
            current_minute = now.replace(second=0, microsecond=0)
            target_time = current_minute + timedelta(seconds=TARGET_OFFSET)

            # If it's already passed, move to NEXT minute
            if target_time <= now:
                target_time = current_minute + timedelta(minutes=1, seconds=TARGET_OFFSET)

            sleep_secs = (target_time - now).total_seconds()

            # print(f"[LevelsCache] Next tick scheduled in {sleep_secs:.3f}s → target={target_time.isoformat()}")

            if stop_event.wait(sleep_secs):
                break

            # print(f"[LevelsCache] Refresh tick at {datetime.now(timezone.utc).isoformat()} (offset={TARGET_OFFSET}s)")

            try:
                ok = _incremental_refresh(contract_id, token, "1m")
                if not ok:
                    print("[LevelsCache] Incremental failed → full rebuild")
                    _build_timeframe_cache(contract_id, token, "1m")
            except Exception as e:
                print(f"[LevelsCache] Refresher error: {e}")
                try:
                    _build_timeframe_cache(contract_id, token, "1m")
                except:
                    pass

    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    return t






# Nezo

Nezo is a full-stack automated futures trading platform built with Python and Flask. It receives TradingView-style signals, validates trading state, integrates with TopstepX for order execution, manages bracket orders and break-even behavior, caches market structure for faster decisions, and records trade history for analytics.

This project was built as an end-to-end engineering project focused on real-time integrations, reliability, state management, and production-style backend workflows.

## Engineering Highlights

- **Python + Flask backend** for webhook ingestion, application state, settings, analytics, and trading controls
- **TopstepX REST API integration** for authentication, contracts, accounts, historical bars, order placement, cancellation, and position data
- **SignalR real-time updates** for positions, orders, and trade events
- **Duplicate-order and position guards** to reduce race conditions around rapid incoming signals
- **Market-structure engine** for swing highs/lows and fair value gaps used in dynamic stop-loss and take-profit selection
- **Incremental market-data cache** with locking and localized recalculation to reduce repeated API work
- **SQLite persistence** for trade history, analytics, and non-sensitive presets
- **Threaded background processes** for connection health, cache refreshes, and trade management
- **Web dashboard** for connection settings, strategy configuration, presets, logs, session controls, and analytics

## Architecture

```text
TradingView / Signal Source
          |
          v
   Flask Webhook API
          |
          +--> Validation + trade-state guards
          |
          +--> Market structure / cached levels
          |
          +--> TopstepX REST API ------> Orders / account data
          |
          +--> SignalR User Hub ------> Live position/order updates
          |
          +--> SQLite ---------------> Trade history / analytics
          |
          v
      Web Dashboard
```

## Main Modules

- `app.py` - Flask application, webhook flow, real-time event handling, trade state, and UI routes
- `topstepx_api.py` - TopstepX REST integration and order operations
- `levels.py` - market-bar retrieval, swing detection, FVG detection, and level selection
- `market_cache.py` - rolling market-data cache and incremental structure refresh
- `trades_db.py` - SQLite trade storage and analytics queries
- `preset_manager.py` - preset persistence with authentication secrets removed before storage
- `templates/` and `static/` - browser dashboard

## Reliability and Safety Controls

Nezo includes several controls intended to make automated execution safer and more deterministic:

- blocks new entries when an existing position is detected
- serializes trade-entry handling to reduce duplicate orders from near-simultaneous alerts
- tracks open take-profit and stop-loss orders
- cancels remaining exits after a position closes or an exit fills
- supports session-time filters and configurable trade-management modes
- keeps API credentials out of committed source files

## Local Data and Credentials

Local databases, environment files, Python cache files, and operating-system metadata are intentionally excluded from Git.

API credentials should be supplied at runtime and should never be committed to this repository. Preset storage strips authentication material before writing settings to SQLite.

## Tech Stack

**Backend:** Python, Flask, Requests, SignalR client, SQLite  
**Frontend:** JavaScript, HTML, CSS  
**Integrations:** TopstepX REST API, TopstepX SignalR user hub, TradingView-style webhooks

## Project Status

This repository represents an independently built trading automation project and is primarily presented as a software engineering portfolio project. It is not financial advice and should not be treated as a production trading service without independent validation, security review, and testing.

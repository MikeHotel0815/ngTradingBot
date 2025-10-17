# ngTradingBot API Documentation

**Version:** 1.0
**Base URL:** `http://your-server:PORT`
**Last Updated:** 2025-10-14

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Multi-Port Architecture](#multi-port-architecture)
4. [Data Models](#data-models)
5. [API Endpoints](#api-endpoints)
   - [Port 9900 - Commands & Control](#port-9900---commands--control)
   - [Port 9901 - Tick Streaming](#port-9901---tick-streaming)
   - [Port 9902 - Trade Updates](#port-9902---trade-updates)
   - [Port 9903 - Logging](#port-9903---logging)
   - [Port 9905 - WebUI & Dashboard](#port-9905---webui--dashboard)
6. [WebSocket Events](#websocket-events)
7. [Error Handling](#error-handling)
8. [Rate Limits](#rate-limits)
9. [Code Examples](#code-examples)

---

## Overview

The ngTradingBot API is a RESTful API for automated forex/crypto trading with MetaTrader 5 (MT5). It provides:

- **Real-time tick streaming** from MT5
- **Automated signal generation** using technical indicators and pattern recognition
- **Trade execution and management** with TP/SL/Trailing Stop
- **Backtesting engine** for strategy validation
- **Auto-optimization** with shadow trading for disabled symbols
- **Risk management** with circuit breakers, daily drawdown limits, and position limits
- **WebSocket support** for real-time dashboard updates

### Key Features

✅ **Multi-Layer Risk Protection** (Circuit Breaker, Daily Drawdown, SL-Hit Protection)
✅ **AI Decision Logging** (Full transparency of all trading decisions)
✅ **Auto-Optimization** (14-day rolling backtests with auto-enable/disable)
✅ **Symbol-Specific Dynamic Config** (Each symbol learns independently)
✅ **News Filter** (Pause trading during high-impact news)
✅ **Shadow Trading** (Monitor disabled symbols for recovery)
✅ **Spread Validation** (Reject trades at abnormal spreads)

---

## Authentication

### API Key Authentication

All endpoints (except `/api/status` and `/api/connect`) require API key authentication.

**Two methods:**

#### Method 1: Request Body
```json
{
  "account": 123456,
  "api_key": "your-api-key-here",
  ...
}
```

#### Method 2: HTTP Header
```http
X-API-Key: your-api-key-here
```

### Getting an API Key

API keys are automatically generated when an MT5 EA connects for the first time:

```http
POST /api/connect
Content-Type: application/json

{
  "account": 123456,
  "broker": "IC Markets",
  "platform": "MT5"
}
```

**Response:**
```json
{
  "status": "success",
  "api_key": "generated-api-key-48-chars",
  "is_new": true,
  "subscribed_symbols": [],
  "server_time": "2025-10-14T12:34:56Z"
}
```

⚠️ **Security Note:** Store the API key securely. It cannot be recovered if lost.

---

## Multi-Port Architecture

The server uses **5 separate ports** for different data types:

| Port | Purpose | Protocol | Authentication |
|------|---------|----------|----------------|
| **9900** | Commands & Control | HTTP REST | ✅ Required |
| **9901** | Tick Streaming | HTTP REST | ✅ Required |
| **9902** | Trade Updates | HTTP REST | ✅ Required |
| **9903** | Logging | HTTP REST | ✅ Required |
| **9905** | WebUI & Dashboard | HTTP/WebSocket | ⚠️ Mixed |

### Why Multi-Port?

- **Performance:** Separate I/O threads for tick streaming vs. commands
- **Scalability:** Independent load balancing per data type
- **Isolation:** Tick floods don't block trade execution
- **Monitoring:** Per-port traffic analysis

---

## Data Models

### Core Models

#### Account
```typescript
{
  id: number;
  mt5_account_number: number;
  api_key: string;
  broker: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit_today: number;
  profit_week: number;
  profit_month: number;
  profit_year: number;
  created_at: string; // ISO 8601
  last_heartbeat: string; // ISO 8601
}
```

#### Trade
```typescript
{
  id: number;
  account_id: number;
  ticket: number; // MT5 ticket
  symbol: string;
  type: string; // "market_buy", "market_sell", "limit", "stop"
  direction: string; // "BUY", "SELL"
  volume: number;
  open_price: number;
  open_time: string; // ISO 8601
  close_price: number | null;
  close_time: string | null; // ISO 8601
  sl: number;
  tp: number;
  profit: number;
  commission: number;
  swap: number;
  source: string; // "ea_command", "mt5_manual", "autotrade"
  command_id: string | null; // UUID
  signal_id: number | null;
  timeframe: string | null; // "M5", "M15", "H1", "H4", "D1"
  entry_reason: string | null;
  entry_confidence: number | null;
  close_reason: string | null; // "TP_HIT", "SL_HIT", "TRAILING_STOP", "MANUAL"
  status: string; // "open", "closed"
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

#### TradingSignal
```typescript
{
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string; // "M5", "M15", "H1", "H4", "D1"
  signal_type: string; // "BUY", "SELL", "HOLD"
  confidence: number; // 0-100%
  entry_price: number;
  sl_price: number;
  tp_price: number;
  indicators_used: object; // {"RSI": 32, "MACD": {...}}
  patterns_detected: string[]; // ["Bullish Engulfing", ...]
  reasons: string[]; // ["RSI Oversold Bounce", ...]
  status: string; // "active", "expired", "executed", "ignored"
  created_at: string; // ISO 8601
  expires_at: string | null; // ISO 8601
  executed_at: string | null; // ISO 8601
}
```

#### Command
```typescript
{
  id: string; // UUID
  account_id: number;
  command_type: string; // "OPEN_TRADE", "CLOSE_TRADE", "MODIFY_TRADE", etc.
  payload: object; // Command-specific data
  status: string; // "pending", "sent", "completed", "failed"
  response: object | null;
  created_at: string; // ISO 8601
  executed_at: string | null; // ISO 8601
}
```

#### Tick
```typescript
{
  id: number;
  account_id: number;
  symbol: string;
  bid: number;
  ask: number;
  spread: number; // Ask - Bid
  volume: number;
  timestamp: string; // ISO 8601
  tradeable: boolean; // Market hours status
}
```

#### BacktestRun
```typescript
{
  id: number;
  account_id: number;
  name: string;
  description: string | null;
  symbols: string; // Comma-separated
  timeframes: string; // Comma-separated
  start_date: string; // ISO 8601
  end_date: string; // ISO 8601
  initial_balance: number;
  final_balance: number | null;
  total_trades: number | null;
  winning_trades: number | null;
  losing_trades: number | null;
  win_rate: number | null; // 0-1
  profit_factor: number | null;
  total_profit: number | null;
  total_loss: number | null;
  max_drawdown: number | null;
  max_drawdown_percent: number | null;
  sharpe_ratio: number | null;
  status: string; // "pending", "running", "completed", "failed"
  progress_percent: number; // 0-100
  current_status: string | null;
  started_at: string | null; // ISO 8601
  completed_at: string | null; // ISO 8601
  error_message: string | null;
}
```

---

## API Endpoints

## Port 9900 - Commands & Control

### Account & Connection

#### POST `/api/connect`
**Description:** Initial MT5 EA connection. Creates account if new, returns API key.

**Request:**
```json
{
  "account": 123456,
  "broker": "IC Markets",
  "platform": "MT5",
  "available_symbols": ["EURUSD", "GBPUSD", "XAUUSD"]
}
```

**Response:**
```json
{
  "status": "success",
  "api_key": "generated-api-key-48-characters-long",
  "is_new": true,
  "subscribed_symbols": [
    {"symbol": "EURUSD", "mode": "default"}
  ],
  "server_time": "2025-10-14T12:34:56Z"
}
```

---

#### POST `/api/heartbeat`
**Description:** Regular heartbeat from EA with account status (every 30s).

**Request:**
```json
{
  "api_key": "your-api-key",
  "account": 123456,
  "balance": 10000.00,
  "equity": 10150.00,
  "margin": 200.00,
  "free_margin": 9950.00,
  "profit_today": 150.00,
  "profit_week": 300.00,
  "profit_month": 800.00,
  "profit_year": 2500.00
}
```

**Response:**
```json
{
  "status": "success"
}
```

**Notes:**
- Automatically corrects profit values by subtracting deposits/withdrawals
- Updates account balance and last_heartbeat timestamp

---

#### GET `/api/status`
**Description:** Get server status (no authentication required).

**Response:**
```json
{
  "status": "running",
  "server_time": "2025-10-14T12:34:56Z",
  "accounts": 3,
  "active_symbols": 12
}
```

---

### Commands

#### POST `/api/get_commands`
**Description:** Get pending commands for EA (Redis-based instant delivery).

**Request:**
```json
{
  "api_key": "your-api-key",
  "account": 123456
}
```

**Response:**
```json
{
  "status": "success",
  "commands": [
    {
      "id": "auto_a1b2c3d4",
      "type": "OPEN_TRADE",
      "symbol": "EURUSD",
      "order_type": "BUY",
      "volume": 0.01,
      "sl": 1.08500,
      "tp": 1.09000,
      "comment": "Auto-Trade Signal #123"
    }
  ]
}
```

**Notes:**
- Checks PostgreSQL for pending commands
- Pushes to Redis queue for instant delivery
- Returns up to 10 commands per request

---

#### POST `/api/create_command`
**Description:** Create a new command with instant Redis delivery.

**Request:**
```json
{
  "api_key": "your-api-key",
  "command_type": "OPEN_TRADE",
  "payload": {
    "symbol": "EURUSD",
    "order_type": "BUY",
    "volume": 0.01,
    "sl": 1.08500,
    "tp": 1.09000,
    "comment": "Manual trade from dashboard"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "command_id": "auto_a1b2c3d4",
  "message": "Command created and queued for instant execution"
}
```

**Command Types:**
- `OPEN_TRADE` - Open new position
- `CLOSE_TRADE` - Close position by ticket
- `MODIFY_TRADE` - Modify SL/TP/Trailing Stop
- `REQUEST_OHLC` - Request OHLC data
- `REQUEST_HISTORICAL_DATA` - Request historical data for backtesting

---

#### POST `/api/command_response`
**Description:** Receive command execution result from EA.

**Request:**
```json
{
  "api_key": "your-api-key",
  "command_id": "auto_a1b2c3d4",
  "status": "completed",
  "response": {
    "ticket": 987654321,
    "open_price": 1.08650,
    "open_time": "2025-10-14T12:35:00Z"
  }
}
```

**Response:**
```json
{
  "status": "success"
}
```

**Notes:**
- Publishes to Redis Pub/Sub for WebSocket notification
- Updates command status in database

---

### Symbol Management

#### POST `/api/symbols`
**Description:** Get subscribed symbols for this account (filtered by broker availability).

**Request:**
```json
{
  "api_key": "your-api-key",
  "account": 123456
}
```

**Response:**
```json
{
  "status": "success",
  "symbols": ["EURUSD", "GBPUSD", "XAUUSD"],
  "count": 3
}
```

---

#### POST `/api/subscribe`
**Description:** Subscribe to symbols for monitoring.

**Request:**
```json
{
  "api_key": "your-api-key",
  "symbols": ["EURUSD", "GBPUSD", "BTCUSD"],
  "mode": "default"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Subscribed to 2 symbols",
  "added": ["EURUSD", "GBPUSD"],
  "invalid": ["BTCUSD"]
}
```

**Notes:**
- `mode` options: `"default"`, `"scalping"`, `"swing"`
- Validates symbols against broker availability
- Returns list of invalid symbols

---

#### POST `/api/symbol_specs`
**Description:** Update symbol specifications from EA.

**Request:**
```json
{
  "api_key": "your-api-key",
  "symbols": [
    {
      "symbol": "EURUSD",
      "volume_min": 0.01,
      "volume_max": 100.00,
      "volume_step": 0.01,
      "stops_level": 10,
      "freeze_level": 5,
      "trade_mode": 7,
      "digits": 5,
      "point_value": 0.00001
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "updated": 1
}
```

---

### Auto-Trading

#### POST `/api/auto-trade/enable`
**Description:** Enable auto-trading with optional min confidence.

**Request:**
```json
{
  "min_confidence": 60.0
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Auto-Trading ENABLED (min confidence: 60%)"
}
```

**Validation:**
- `min_confidence`: 0-100 (default: 60)

---

#### POST `/api/auto-trade/disable`
**Description:** Disable auto-trading (kill-switch).

**Response:**
```json
{
  "status": "success",
  "message": "Auto-Trading DISABLED"
}
```

---

#### GET `/api/auto-trade/status`
**Description:** Get auto-trading status.

**Response:**
```json
{
  "enabled": true,
  "min_confidence": 60.0,
  "circuit_breaker_enabled": true,
  "circuit_breaker_tripped": false,
  "circuit_breaker_reason": null,
  "max_daily_loss_percent": 5.0,
  "max_total_drawdown_percent": 20.0,
  "processed_signals": 1523
}
```

---

### Backtesting

#### POST `/api/backtest/create`
**Description:** Create a new backtest run.

**Request:**
```json
{
  "account_id": 1,
  "name": "EURUSD H1 Strategy Test",
  "description": "Testing trend-following strategy",
  "symbols": "EURUSD,GBPUSD",
  "timeframes": "H1,H4",
  "start_date": "2025-09-01",
  "end_date": "2025-10-01",
  "initial_balance": 10000.00,
  "min_confidence": 0.60,
  "position_size_percent": 0.01,
  "max_positions": 5
}
```

**Response:**
```json
{
  "status": "success",
  "backtest_id": 42,
  "message": "Backtest created successfully"
}
```

**Validation:**
- `symbols`: Comma-separated, validated against broker symbols
- `timeframes`: Must include H1, H4, or D1
- `start_date`/`end_date`: Max 2 years range
- `initial_balance`: 100-1,000,000
- `min_confidence`: 0-1
- `position_size_percent`: 0.001-0.1
- `max_positions`: 1-50

**Timeframe Requirements:**
- H4: Minimum 9 days
- D1: Minimum 30 days

---

#### POST `/api/backtest/<backtest_id>/start`
**Description:** Start a backtest run in background.

**Response:**
```json
{
  "status": "success",
  "message": "Backtest 42 started. Requesting historical OHLC data from EA..."
}
```

**Notes:**
- Creates `REQUEST_OHLC` commands for EA
- Runs in background thread
- Updates progress via WebSocket

---

#### GET `/api/backtest/list`
**Description:** Get list of all backtest runs.

**Query Parameters:**
- `account_id` (optional, default: 1)

**Response:**
```json
{
  "backtests": [
    {
      "id": 42,
      "name": "EURUSD H1 Strategy Test",
      "status": "completed",
      "progress_percent": 100.0,
      "current_status": "Backtest completed successfully",
      "symbols": "EURUSD,GBPUSD",
      "timeframes": "H1,H4",
      "start_date": "2025-09-01T00:00:00Z",
      "end_date": "2025-10-01T00:00:00Z",
      "total_trades": 87,
      "win_rate": 0.6321,
      "profit_factor": 1.85,
      "net_profit": 542.30
    }
  ]
}
```

---

#### GET `/api/backtest/<backtest_id>`
**Description:** Get backtest run details and results.

**Response:**
```json
{
  "id": 42,
  "name": "EURUSD H1 Strategy Test",
  "status": "completed",
  "symbols": "EURUSD,GBPUSD",
  "timeframes": "H1,H4",
  "start_date": "2025-09-01T00:00:00Z",
  "end_date": "2025-10-01T00:00:00Z",
  "initial_balance": 10000.00,
  "final_balance": 10542.30,
  "total_trades": 87,
  "winning_trades": 55,
  "losing_trades": 32,
  "win_rate": 0.6321,
  "profit_factor": 1.85,
  "total_profit": 1250.00,
  "total_loss": -707.70,
  "max_drawdown": -230.50,
  "max_drawdown_percent": -0.023,
  "sharpe_ratio": 1.42,
  "progress_percent": 100.0,
  "processed_candles": 720,
  "total_candles": 720
}
```

---

#### GET `/api/backtest/<backtest_id>/trades`
**Description:** Get all trades from a backtest run.

**Response:**
```json
{
  "trades": [
    {
      "id": 1,
      "direction": "BUY",
      "symbol": "EURUSD",
      "timeframe": "H1",
      "volume": 0.01,
      "entry_time": "2025-09-01T08:00:00Z",
      "entry_price": 1.08500,
      "entry_reason": "RSI Oversold + MACD Bullish Crossover",
      "exit_time": "2025-09-01T12:00:00Z",
      "exit_price": 1.08750,
      "exit_reason": "TP_HIT",
      "profit": 25.00,
      "profit_percent": 0.23,
      "duration_minutes": 240,
      "signal_confidence": 75.5,
      "trailing_stop_used": false
    }
  ]
}
```

---

#### DELETE `/api/backtest/<backtest_id>`
**Description:** Delete a backtest run and all associated data.

**Response:**
```json
{
  "status": "success",
  "message": "Backtest deleted"
}
```

---

### Settings

#### GET `/api/settings`
**Description:** Get global settings.

**Response:**
```json
{
  "max_positions": 5,
  "max_positions_per_symbol_timeframe": 1,
  "risk_per_trade_percent": 0.01,
  "position_size_percent": 0.01,
  "max_drawdown_percent": 0.10,
  "min_signal_confidence": 0.60,
  "signal_max_age_minutes": 60,
  "sl_cooldown_minutes": 60,
  "min_bars_required": 50,
  "min_bars_d1": 30,
  "realistic_profit_factor": 0.60,
  "autotrade_enabled": true,
  "autotrade_min_confidence": 60.0,
  "updated_at": "2025-10-14T12:00:00Z"
}
```

---

#### POST `/api/settings`
**Description:** Update global settings.

**Request:**
```json
{
  "max_positions": 10,
  "risk_per_trade_percent": 0.015,
  "min_signal_confidence": 0.65
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Settings updated"
}
```

**Validation:**
- `position_size_percent`: 0.001-100.0
- `max_drawdown_percent`: 1.0-100.0
- `min_signal_confidence`: 0-100
- `signal_max_age_minutes`: 1-1440
- `sl_cooldown_minutes`: 0-1440
- `min_bars_required`: 10-500
- `min_bars_d1`: 10-500
- `realistic_profit_factor`: 0.1-10.0

---

## Port 9901 - Tick Streaming

#### POST `/api/ticks`
**Description:** Receive batched tick data from EA (every 100ms).

**Request:**
```json
{
  "api_key": "your-api-key",
  "account": 123456,
  "ticks": [
    {
      "symbol": "EURUSD",
      "bid": 1.08500,
      "ask": 1.08520,
      "spread": 0.00020,
      "volume": 1000,
      "timestamp": 1697281234,
      "tradeable": true
    }
  ],
  "positions": [
    {
      "ticket": 987654321,
      "profit": 25.50,
      "swap": -0.50
    }
  ],
  "balance": 10000.00,
  "equity": 10025.00,
  "margin": 200.00,
  "free_margin": 9825.00,
  "profit_today": 150.00,
  "profit_week": 300.00,
  "profit_month": 800.00,
  "profit_year": 2500.00
}
```

**Response:**
```json
{
  "status": "success",
  "received": 1
}
```

**Notes:**
- Buffers ticks in Redis for batch writing
- Updates shadow trades with current prices
- Emits WebSocket events: `price_update`, `account_update`, `positions_update`

---

#### POST `/api/ohlc/historical`
**Description:** Receive historical OHLC data from EA.

**Request:**
```json
{
  "api_key": "your-api-key",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "candles": [
    {
      "timestamp": 1697277600,
      "open": 1.08500,
      "high": 1.08650,
      "low": 1.08450,
      "close": 1.08600,
      "volume": 50000
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "imported": 720,
  "skipped": 5,
  "total": 725
}
```

**Notes:**
- Converts MT5 timestamps (broker time) to UTC
- Skips duplicate candles (unique index on symbol+timeframe+timestamp)

---

## Port 9902 - Trade Updates

#### POST `/api/trades/sync`
**Description:** Sync all trades from MT5 EA (open positions and closed trades).

**Request:**
```json
{
  "api_key": "your-api-key",
  "trades": [
    {
      "ticket": 987654321,
      "symbol": "EURUSD",
      "type": "MARKET",
      "direction": "BUY",
      "volume": 0.01,
      "open_price": 1.08500,
      "open_time": "2025-10-14T12:00:00Z",
      "close_price": 1.08750,
      "close_time": "2025-10-14T14:00:00Z",
      "sl": 1.08300,
      "tp": 1.09000,
      "profit": 25.00,
      "commission": -0.50,
      "swap": -0.20,
      "status": "closed",
      "command_id": "auto_a1b2c3d4",
      "source": "autotrade"
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "synced": 15,
  "updated": 3
}
```

**Notes:**
- Links trades to commands by ticket match
- Extracts signal metadata from command payloads
- Updates existing trades if status changed

---

#### POST `/api/trades/update`
**Description:** Update single trade (called on OnTrade event in EA).

**Request:**
```json
{
  "api_key": "your-api-key",
  "ticket": 987654321,
  "close_price": 1.08750,
  "close_time": "2025-10-14T14:00:00Z",
  "profit": 25.00,
  "status": "closed",
  "close_reason": "TP_HIT"
}
```

**Response:**
```json
{
  "status": "success"
}
```

**Notes:**
- Updates indicator scores when trade closes
- Sets SL cooldown if `close_reason` = `"SL_HIT"`
- Links trades to commands by ticket match
- Emits WebSocket `position_update` event

---

## Port 9903 - Logging

#### POST `/api/log`
**Description:** Receive logs from EA.

**Request:**
```json
{
  "api_key": "your-api-key",
  "level": "INFO",
  "message": "Trade opened successfully",
  "details": {
    "ticket": 987654321,
    "symbol": "EURUSD",
    "volume": 0.01
  }
}
```

**Response:**
```json
{
  "status": "success"
}
```

**Log Levels:** `INFO`, `WARNING`, `ERROR`, `CRITICAL`

---

## Port 9905 - WebUI & Dashboard

### Dashboard Views

#### GET `/`
**Description:** Main dashboard view (HTML template).

**Response:** Renders `dashboard.html`

---

#### GET `/api/dashboard/status`
**Description:** Get account status for dashboard.

**Response:**
```json
{
  "status": "success",
  "account": {
    "id": 1,
    "number": 123456,
    "broker": "IC Markets",
    "balance": 10000.00,
    "equity": 10150.00,
    "margin": 200.00,
    "free_margin": 9950.00,
    "profit_today": 150.00,
    "profit_week": 300.00,
    "profit_month": 800.00,
    "profit_year": 2500.00,
    "last_heartbeat": "2025-10-14T12:34:56Z"
  }
}
```

**Notes:** Returns most recently active account (latest heartbeat)

---

#### GET `/api/dashboard/symbols`
**Description:** Get subscribed symbols with latest tick data.

**Response:**
```json
{
  "status": "success",
  "symbols": [
    {
      "symbol": "EURUSD",
      "bid": 1.08500,
      "ask": 1.08520,
      "tick_count": 15234,
      "last_tick": "2025-10-14T12:34:56Z",
      "trends": {
        "M5": "up",
        "M15": "up",
        "H1": "neutral",
        "H4": "down"
      },
      "tradeable": true
    }
  ],
  "account": {
    "number": 123456,
    "balance": 10000.00,
    "equity": 10150.00,
    "margin": 200.00,
    "free_margin": 9950.00,
    "profit_today": 150.00,
    "profit_week": 300.00,
    "profit_month": 800.00,
    "profit_year": 2500.00
  }
}
```

---

### Trading Signals

#### GET `/api/signals`
**Description:** Get active trading signals with filters.

**Query Parameters:**
- `symbol` (optional) - Filter by symbol
- `timeframe` (optional) - M1, M5, M15, H1, H4, D1
- `confidence` (optional, default: 0) - Min confidence (0-100)
- `type` (optional) - BUY or SELL

**Response:**
```json
{
  "status": "success",
  "signals": [
    {
      "id": 123,
      "symbol": "EURUSD",
      "timeframe": "H1",
      "signal_type": "BUY",
      "confidence": 75.5,
      "entry_price": 1.08500,
      "sl_price": 1.08300,
      "tp_price": 1.09000,
      "indicators_used": {
        "RSI": 32.5,
        "MACD": {"signal": 0.0012, "histogram": 0.0005},
        "EMA_20": 1.08450
      },
      "patterns_detected": ["Bullish Engulfing", "Above 200 EMA"],
      "reasons": ["RSI Oversold Bounce", "MACD Bullish Crossover"],
      "status": "active",
      "tradeable": true,
      "created_at": "2025-10-14T12:30:00Z",
      "expires_at": "2025-10-14T13:30:00Z"
    }
  ],
  "count": 1,
  "volatility": "normal",
  "interval": 10
}
```

**Notes:**
- Expires old signals before querying
- Server-side market hours filtering
- Returns tradeable status based on current time

---

#### POST `/api/open_trade`
**Description:** Open trade from dashboard (one-click trading).

**Request:**
```json
{
  "symbol": "EURUSD",
  "order_type": "BUY",
  "volume": 0.01,
  "sl": 1.08300,
  "tp": 1.09000,
  "comment": "Dashboard Trade",
  "trailing_stop": 50.0,
  "signal_id": 123,
  "timeframe": "H1"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Trade command created",
  "command_id": "auto_a1b2c3d4",
  "normalized_volume": 0.01
}
```

**Validation:**
- `order_type`: BUY or SELL
- `volume`: Normalized to broker's volume_step
- `sl`/`tp`: Required, must be valid prices
- `trailing_stop`: Optional, in pips

---

#### POST `/api/close_trade/<ticket>`
**Description:** Close a specific trade by ticket number.

**Response:**
```json
{
  "status": "success",
  "message": "Close command sent for trade #987654321",
  "command_id": "auto_e5f6g7h8"
}
```

---

#### POST `/api/close_all_profitable`
**Description:** Close all trades that are currently in profit.

**Response:**
```json
{
  "status": "success",
  "message": "Close commands sent for 5 profitable trades",
  "tickets": [987654321, 987654322, 987654323, 987654324, 987654325],
  "commands": ["auto_e5f6g7h8", "auto_i9j0k1l2", ...]
}
```

**Notes:** Gets P&L from Redis monitoring data

---

#### POST `/api/close_all_trades`
**Description:** Close ALL open trades (requires confirmation from frontend).

**Response:**
```json
{
  "status": "success",
  "message": "Close commands sent for 8 trades",
  "tickets": [987654321, 987654322, ...],
  "commands": ["auto_e5f6g7h8", ...]
}
```

⚠️ **WARNING:** Closes ALL trades!

---

### Trade History & Analytics

#### GET `/api/trades/history`
**Description:** Get trade history with advanced filters and pagination.

**Query Parameters:**
- `status` (optional) - closed, open, all
- `symbol` (optional) - Filter by symbol
- `direction` (optional) - BUY, SELL
- `profit_status` (optional) - profit, loss
- `period` (optional) - all, today, week, month, year, custom
- `start_date` (optional, for custom) - YYYY-MM-DD
- `end_date` (optional, for custom) - YYYY-MM-DD
- `page` (optional, default: 1)
- `per_page` (optional, default: 20, max: 100)

**Response:**
```json
{
  "status": "success",
  "trades": [
    {
      "id": 1,
      "ticket": 987654321,
      "symbol": "EURUSD",
      "type": "MARKET",
      "direction": "BUY",
      "volume": 0.01,
      "open_price": 1.08500,
      "open_time": "2025-10-14T12:00:00Z",
      "close_price": 1.08750,
      "close_time": "2025-10-14T14:00:00Z",
      "sl": 1.08300,
      "tp": 1.09000,
      "profit": 25.00,
      "commission": -0.50,
      "swap": -0.20,
      "source": "autotrade",
      "timeframe": "H1",
      "confidence": 75.5,
      "entry_reason": "RSI Oversold + MACD Bullish Crossover",
      "close_reason": "TP_HIT",
      "signal_id": 123,
      "status": "closed",
      "duration_hours": 2.0
    }
  ],
  "pagination": {
    "total": 320,
    "page": 1,
    "per_page": 20,
    "total_pages": 16,
    "has_next": true,
    "has_prev": false
  }
}
```

**Notes:** All inputs validated to prevent SQL injection

---

#### GET `/api/trades/analytics`
**Description:** Get comprehensive trade analytics including error analysis.

**Response:**
```json
{
  "status": "success",
  "analytics": {
    "trades": {
      "total": 320,
      "open": 1,
      "closed": 319,
      "winning": 233,
      "losing": 86,
      "win_rate": 73.04
    },
    "profit": {
      "total": 83.88,
      "average_win": 5.25,
      "average_loss": -3.80
    },
    "commands": {
      "successful": 315,
      "failed": 5,
      "success_rate": 98.44
    },
    "errors": {
      "Invalid stops": 3,
      "Not enough money": 2
    },
    "sources": {
      "autotrade": 280,
      "ea_command": 35,
      "mt5_manual": 5
    },
    "timeframe_performance": {
      "H1": {
        "count": 150,
        "total_profit": 45.30,
        "wins": 110,
        "losses": 40
      },
      "H4": {
        "count": 120,
        "total_profit": 38.58,
        "wins": 88,
        "losses": 32
      }
    },
    "close_reasons": {
      "TP_HIT": 180,
      "SL_HIT": 86,
      "TRAILING_STOP": 45,
      "MANUAL": 8
    }
  }
}
```

---

### Safety Monitoring

#### GET `/api/safety-monitor/status`
**Description:** Get comprehensive safety monitoring status for live dashboard.

**Query Parameters:**
- `account_id` (optional, default: 1)

**Response:**
```json
{
  "status": "success",
  "timestamp": "2025-10-14T12:34:56Z",
  "account_id": 1,
  "safety_status": {
    "circuit_breaker": {
      "enabled": true,
      "tripped": false,
      "reason": null,
      "failed_command_count": 0,
      "max_daily_loss_percent": 5.0,
      "max_total_drawdown_percent": 20.0
    },
    "daily_drawdown": {
      "limit_reached": false,
      "current_loss": -15.50,
      "max_daily_loss_eur": 200.00,
      "max_daily_loss_percent": 2.0,
      "remaining_eur": 184.50
    },
    "sl_hit_cooldowns": [
      {
        "symbol": "EURUSD",
        "cooldown_until": "2025-10-14T16:00:00Z",
        "remaining_seconds": 3600
      }
    ],
    "news_filter": {
      "upcoming_events": [
        {
          "time": "2025-10-14T14:30:00Z",
          "currency": "USD",
          "impact": "HIGH",
          "event_name": "Non-Farm Payrolls"
        }
      ],
      "total_upcoming": 3
    },
    "position_limits": {
      "open_positions": 5,
      "max_positions": 10,
      "max_positions_per_symbol_timeframe": 1,
      "positions_by_symbol": {
        "EURUSD": 2,
        "GBPUSD": 1,
        "XAUUSD": 2
      },
      "utilization_percent": 50.0
    },
    "multi_timeframe_conflicts": [
      {
        "symbol": "EURUSD",
        "conflicts": ["M15 says BUY, H1 says SELL"],
        "signals": [
          {
            "timeframe": "M15",
            "signal_type": "BUY",
            "confidence": 65.0
          },
          {
            "timeframe": "H1",
            "signal_type": "SELL",
            "confidence": 70.0
          }
        ]
      }
    ],
    "auto_trading": {
      "enabled": true,
      "min_confidence": 60.0
    }
  },
  "overall_health": "WARNING",
  "health_messages": {
    "errors": [],
    "warnings": [
      "News event in 2 hours: USD Non-Farm Payrolls",
      "EURUSD has conflicting signals across timeframes"
    ],
    "info": [
      "Circuit breaker: Active",
      "Daily drawdown: 184.50 EUR remaining"
    ]
  }
}
```

**Health Status:**
- `HEALTHY` - All systems normal
- `WARNING` - Minor issues detected
- `ERROR` - Critical issues, auto-trading may be disabled
- `UNKNOWN` - Unable to determine status

---

### AI Decision Logging

#### GET `/api/ai-decisions`
**Description:** Get recent AI decisions for transparency.

**Query Parameters:**
- `limit` (optional, default: 50)
- `type` (optional) - Filter by decision type
- `minutes` (optional) - Time window in minutes

**Response:**
```json
{
  "status": "success",
  "decisions": [
    {
      "id": 1,
      "timestamp": "2025-10-14T12:30:00Z",
      "decision_type": "TRADE_OPEN",
      "decision": "APPROVED",
      "symbol": "EURUSD",
      "timeframe": "H1",
      "primary_reason": "Signal #123 approved for trading",
      "detailed_reasoning": {
        "signal_id": 123,
        "confidence": 75.5,
        "entry_price": 1.08500,
        "volume": 0.01,
        "sl": 1.08300,
        "tp": 1.09000
      },
      "impact_level": "HIGH",
      "user_action_required": false,
      "confidence_score": 75.5,
      "risk_score": 0.01,
      "account_balance": 10000.00,
      "open_positions": 4
    }
  ]
}
```

**Decision Types:**
- `TRADE_OPEN` - Trade execution decision
- `TRADE_CLOSE` - Trade closure decision
- `SIGNAL_SKIP` - Signal rejected
- `TRADE_REPLACEMENT` - Opportunity cost management
- `SPREAD_REJECTION` - Spread too high
- `CIRCUIT_BREAKER` - Circuit breaker activated
- `RISK_LIMIT` - Risk limit reached

---

### Auto-Optimization

#### GET `/api/auto-optimization/status`
**Description:** Get current auto-optimization status for all symbols.

**Query Parameters:**
- `account_id` (optional, default: 1)

**Response:**
```json
{
  "status": "success",
  "symbols": [
    {
      "symbol": "EURUSD",
      "status": "active",
      "evaluation_date": "2025-10-14T00:00:00Z",
      "backtest_total_trades": 45,
      "backtest_win_rate": 55.56,
      "backtest_profit": 125.50,
      "backtest_profit_percent": 1.26,
      "consecutive_loss_days": 0,
      "consecutive_profit_days": 3,
      "shadow_trades": 0,
      "shadow_profit": 0.00,
      "auto_disabled_reason": null
    },
    {
      "symbol": "GBPUSD",
      "status": "disabled",
      "evaluation_date": "2025-10-14T00:00:00Z",
      "backtest_total_trades": 38,
      "backtest_win_rate": 31.58,
      "backtest_profit": -85.30,
      "backtest_profit_percent": -0.85,
      "consecutive_loss_days": 5,
      "consecutive_profit_days": 0,
      "shadow_trades": 12,
      "shadow_profit": 45.20,
      "auto_disabled_reason": "3 consecutive loss days (Win Rate: 31.58%)"
    }
  ],
  "status_counts": {
    "active": 4,
    "watch": 1,
    "disabled": 1
  },
  "total_symbols": 6
}
```

---

#### POST `/api/auto-optimization/trigger`
**Description:** Manually trigger a daily backtest run.

**Response:**
```json
{
  "status": "success",
  "message": "Backtest triggered successfully"
}
```

**Notes:** Runs in background thread

---

## WebSocket Events

**Connection URL:** `ws://your-server:9905/socket.io/`

### Emitted by Server

#### `connected`
```json
{
  "status": "connected"
}
```

#### `tick_update` / `price_update`
```json
{
  "symbol": "EURUSD",
  "bid": 1.08500,
  "ask": 1.08520,
  "timestamp": "2025-10-14T12:34:56Z"
}
```

#### `account_update`
```json
{
  "number": 123456,
  "balance": 10000.00,
  "equity": 10150.00,
  "margin": 200.00,
  "free_margin": 9950.00
}
```

#### `profit_update`
```json
{
  "today": 150.00,
  "week": 300.00,
  "month": 800.00,
  "year": 2500.00
}
```

#### `positions_update`
```json
{
  "account_id": 1,
  "position_count": 5,
  "positions": [
    {
      "ticket": 987654321,
      "symbol": "EURUSD",
      "direction": "BUY",
      "volume": 0.01,
      "pnl": 25.50,
      "open_price": 1.08500,
      "sl": 1.08300,
      "tp": 1.09000
    }
  ],
  "total_pnl": 125.50,
  "timestamp": "2025-10-14T12:34:56Z"
}
```

#### `transaction_update`
```json
{
  "account": 123456,
  "type": "BALANCE",
  "amount": 1000.00,
  "balance": 11000.00,
  "timestamp": "2025-10-14T12:34:56Z",
  "comment": "Deposit"
}
```

#### `command_update`
```json
{
  "command_id": "auto_a1b2c3d4",
  "status": "completed",
  "response": {
    "ticket": 987654321,
    "open_price": 1.08650
  }
}
```

### Handlers

#### `connect`
Triggered when client connects to WebSocket.

#### `disconnect`
Triggered when client disconnects from WebSocket.

---

## Error Handling

### Standard Error Response

```json
{
  "status": "error",
  "message": "Error description here",
  "code": "ERROR_CODE"
}
```

### HTTP Status Codes

| Code | Meaning | Usage |
|------|---------|-------|
| 200 | OK | Successful request |
| 400 | Bad Request | Invalid parameters |
| 401 | Unauthorized | Missing API key |
| 403 | Forbidden | Invalid API key |
| 404 | Not Found | Resource not found |
| 500 | Internal Server Error | Server error |

### Common Error Codes

| Code | Description |
|------|-------------|
| `MISSING_API_KEY` | API key not provided |
| `INVALID_API_KEY` | API key is invalid |
| `INVALID_PARAMETERS` | Request parameters are invalid |
| `SYMBOL_NOT_AVAILABLE` | Symbol not available at broker |
| `INSUFFICIENT_MARGIN` | Not enough margin for trade |
| `SPREAD_TOO_HIGH` | Spread exceeds maximum allowed |
| `MARKET_CLOSED` | Market is closed for this symbol |
| `POSITION_LIMIT_REACHED` | Max positions limit reached |
| `DAILY_DRAWDOWN_LIMIT` | Daily loss limit exceeded |
| `CIRCUIT_BREAKER_TRIPPED` | Circuit breaker activated |

---

## Rate Limits

### Per-Port Limits

| Port | Endpoint | Limit |
|------|----------|-------|
| 9900 | All | 100 req/min |
| 9901 | `/api/ticks` | 600 req/min (10/sec) |
| 9902 | `/api/trades/update` | 300 req/min |
| 9903 | `/api/log` | 300 req/min |
| 9905 | All | 200 req/min |

### Headers

Response headers include rate limit information:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1697281800
```

---

## Code Examples

### Python - Connect & Subscribe

```python
import requests

BASE_URL = "http://localhost:9900"

# Connect and get API key
response = requests.post(f"{BASE_URL}/api/connect", json={
    "account": 123456,
    "broker": "IC Markets",
    "platform": "MT5",
    "available_symbols": ["EURUSD", "GBPUSD", "XAUUSD"]
})

api_key = response.json()["api_key"]
print(f"API Key: {api_key}")

# Subscribe to symbols
response = requests.post(f"{BASE_URL}/api/subscribe", json={
    "api_key": api_key,
    "symbols": ["EURUSD", "GBPUSD"],
    "mode": "default"
})

print(response.json())
```

### Python - Send Ticks

```python
import requests
import time

TICK_URL = "http://localhost:9901/api/ticks"

while True:
    ticks_data = {
        "api_key": api_key,
        "account": 123456,
        "ticks": [
            {
                "symbol": "EURUSD",
                "bid": 1.08500,
                "ask": 1.08520,
                "spread": 0.00020,
                "volume": 1000,
                "timestamp": int(time.time()),
                "tradeable": True
            }
        ],
        "balance": 10000.00,
        "equity": 10150.00,
        "margin": 200.00,
        "free_margin": 9950.00,
        "profit_today": 150.00,
        "profit_week": 300.00,
        "profit_month": 800.00,
        "profit_year": 2500.00
    }

    response = requests.post(TICK_URL, json=ticks_data)
    print(response.json())

    time.sleep(0.1)  # 100ms interval
```

### Python - Get Signals & Open Trade

```python
import requests

DASHBOARD_URL = "http://localhost:9905"

# Get active signals
response = requests.get(f"{DASHBOARD_URL}/api/signals", params={
    "symbol": "EURUSD",
    "confidence": 70,
    "type": "BUY"
})

signals = response.json()["signals"]

if signals:
    signal = signals[0]

    # Open trade from signal
    response = requests.post(f"{DASHBOARD_URL}/api/open_trade", json={
        "symbol": signal["symbol"],
        "order_type": signal["signal_type"],
        "volume": 0.01,
        "sl": signal["sl_price"],
        "tp": signal["tp_price"],
        "comment": f"Auto-Trade Signal #{signal['id']}",
        "signal_id": signal["id"],
        "timeframe": signal["timeframe"]
    })

    print(response.json())
```

### JavaScript - WebSocket Connection

```javascript
const socket = io('http://localhost:9905');

socket.on('connected', (data) => {
    console.log('Connected:', data);
});

socket.on('price_update', (data) => {
    console.log(`${data.symbol}: Bid=${data.bid}, Ask=${data.ask}`);
    updateChart(data);
});

socket.on('positions_update', (data) => {
    console.log(`Open Positions: ${data.position_count}, Total P&L: ${data.total_pnl}`);
    updatePositionsTable(data.positions);
});

socket.on('account_update', (data) => {
    console.log(`Balance: ${data.balance}, Equity: ${data.equity}`);
    updateAccountInfo(data);
});

socket.on('command_update', (data) => {
    console.log(`Command ${data.command_id}: ${data.status}`);
    if (data.status === 'completed') {
        showNotification('Trade executed successfully!');
    }
});
```

### MQL5 - Send Command Response

```mql5
void SendCommandResponse(string command_id, bool success, long ticket) {
    string url = "http://localhost:9900/api/command_response";
    string headers = "Content-Type: application/json\r\n";

    string json = StringFormat(
        "{\"api_key\":\"%s\",\"command_id\":\"%s\",\"status\":\"%s\",\"response\":{\"ticket\":%d,\"open_price\":%.5f,\"open_time\":\"%s\"}}",
        API_KEY,
        command_id,
        success ? "completed" : "failed",
        ticket,
        SymbolInfoDouble(_Symbol, SYMBOL_BID),
        TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES)
    );

    char post[], result[];
    StringToCharArray(json, post, 0, StringLen(json));

    int res = WebRequest("POST", url, headers, 5000, post, result, headers);

    if(res == 200) {
        Print("Command response sent: ", command_id);
    }
}
```

### Python - Create Backtest

```python
import requests
from datetime import datetime, timedelta

BACKTEST_URL = "http://localhost:9900"

# Create backtest
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

response = requests.post(f"{BACKTEST_URL}/api/backtest/create", json={
    "account_id": 1,
    "name": "EURUSD H1 Strategy Test",
    "description": "Testing trend-following strategy on EURUSD",
    "symbols": "EURUSD",
    "timeframes": "H1,H4",
    "start_date": start_date.strftime("%Y-%m-%d"),
    "end_date": end_date.strftime("%Y-%m-%d"),
    "initial_balance": 10000.00,
    "min_confidence": 0.60,
    "position_size_percent": 0.01,
    "max_positions": 5
})

backtest_id = response.json()["backtest_id"]
print(f"Backtest created: {backtest_id}")

# Start backtest
response = requests.post(f"{BACKTEST_URL}/api/backtest/{backtest_id}/start")
print(response.json())

# Poll for results
import time
while True:
    response = requests.get(f"{BACKTEST_URL}/api/backtest/{backtest_id}")
    backtest = response.json()

    if backtest["status"] == "completed":
        print(f"Backtest completed!")
        print(f"Win Rate: {backtest['win_rate']*100:.2f}%")
        print(f"Profit Factor: {backtest['profit_factor']:.2f}")
        print(f"Net Profit: ${backtest['total_profit'] + backtest['total_loss']:.2f}")
        break
    elif backtest["status"] == "failed":
        print(f"Backtest failed: {backtest['error_message']}")
        break

    print(f"Progress: {backtest['progress_percent']:.1f}% - {backtest['current_status']}")
    time.sleep(5)
```

---

## Appendix

### Timeframe Values

| Value | Description |
|-------|-------------|
| `M1` | 1 Minute |
| `M5` | 5 Minutes |
| `M15` | 15 Minutes |
| `M30` | 30 Minutes |
| `H1` | 1 Hour |
| `H4` | 4 Hours |
| `D1` | Daily |

### Signal Types

| Type | Description |
|------|-------------|
| `BUY` | Long position |
| `SELL` | Short position |
| `HOLD` | No action |

### Trade Sources

| Source | Description |
|--------|-------------|
| `autotrade` | Auto-trader execution |
| `ea_command` | Dashboard/API command |
| `mt5_manual` | Manual MT5 trade |

### Close Reasons

| Reason | Description |
|--------|-------------|
| `TP_HIT` | Take Profit hit |
| `SL_HIT` | Stop Loss hit |
| `TRAILING_STOP` | Trailing Stop triggered |
| `MANUAL` | Manual closure |
| `TIMEOUT` | Max hold time exceeded |
| `OPPORTUNITY_COST` | Replaced by better signal |

---

**End of Documentation**

For support or questions, please visit: [GitHub Issues](https://github.com/your-repo/ngTradingBot/issues)

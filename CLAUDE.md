# ngTradingBot - Claude AI Context

## Project Overview

Advanced Multi-Port Trading System combining:
- **Python Backend** - Multi-port Flask server on Tailscale (100.97.100.50)
- **MT5 Expert Advisor** - Runs on Windows VPS, connects to Python server
- **PostgreSQL Database** - Stores ticks, trades, signals, logs
- **Redis Cache** - Real-time data caching
- **Web Dashboard** - Real-time monitoring and control

## Recent Major Updates (2025-10-04)

### ✅ Signal Market Hours Filtering
- **Server-side validation** for trading hours ([app.py:44-78](app.py#L44-78))
- Forex pairs (GBPUSD, EURUSD) hidden on weekends
- Crypto pairs (BTCUSD) always tradeable (24/7)
- Automatic signal filtering in dashboard

### ✅ Comprehensive EA Logging System
- **Connection events**: Connected, reconnected, disconnected
- **Trade events**: Opened, closed, modified with full details
- **Command events**: Received, executed, failed
- **Error events**: Heartbeat failures, authentication errors
- **Symbol events**: New symbols subscribed
- All events stored in `logs` table with level, message, details, timestamp

### ✅ Enhanced EA Features
- **Trading hours detection** in EA ([ServerConnector.mq5:1883-1954](ServerConnector.mq5#L1883-1954))
- Weekend detection for Forex pairs
- Improved `IsSymbolTradeable()` function
- OnTimer() based tick collection (100ms intervals)

## Network Configuration

- **Server IP**: 100.97.100.50 (Tailscale)
- **Port 9900**: Command & Control API
- **Port 9901**: High-frequency tick streaming
- **Port 9902**: Trade updates and position sync
- **Port 9903**: Centralized logging system
- **Port 9905**: Web Dashboard & WebSocket
- **PostgreSQL**: Port 5432 (internal Docker network)
- **Redis**: Port 6379 (internal Docker network)

## Architecture

### Multi-Port Server Design

```
┌─────────────────────────────────────────────────────────────┐
│                    ngTradingBot Server                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Port 9900 (Command)    ← EA Connection, Heartbeat          │
│  Port 9901 (Ticks)      ← Real-time tick batches (100ms)    │
│  Port 9902 (Trades)     ← Position updates, sync            │
│  Port 9903 (Logs)       ← EA event logging                  │
│  Port 9905 (Dashboard)  ← WebUI + WebSocket                 │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (5432)      ← Persistent storage                │
│  Redis (6379)           ← Caching layer                     │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
/projects/ngTradingBot/
├── app.py                    # Multi-port Flask application
├── database.py               # SQLAlchemy setup & session management
├── models.py                 # ORM models (accounts, ticks, trades, signals, logs)
├── auth.py                   # API key authentication
├── signal_generator.py       # Technical analysis engine
├── signal_worker.py          # Background signal generation
├── tick_batch_writer.py      # High-performance tick storage
├── backup_scheduler.py       # Automated DB backups to GitHub
├── redis_client.py           # Redis connection management
├── command_helper.py         # Trade command creation utilities
├── requirements.txt          # Python dependencies
├── Dockerfile                # Server container definition
├── docker-compose.yml        # Multi-container orchestration
├── README.md                 # User documentation
├── CLAUDE.md                 # This file - AI context
├── templates/
│   └── dashboard.html        # Web dashboard UI
└── mt5_EA/
    ├── README.md             # MT5 EA documentation
    └── Experts/
        └── ServerConnector.mq5  # Main EA (2606 lines)
```

## Database Schema

### Core Tables

**accounts**: MT5 account information
```sql
id, account_number, broker, platform, api_key, created_at, last_seen
```

**subscribed_symbols**: User symbol subscriptions
```sql
id, account_id, symbol, created_at
```

**ticks**: Real-time tick data (7-day retention)
```sql
id, account_id, symbol, bid, ask, volume, timestamp, tradeable
```

**ohlc_data**: Historical candle data
```sql
id, account_id, symbol, timeframe, timestamp, open, high, low, close, volume
```

**trades**: Position history with close reasons
```sql
id, account_id, ticket, symbol, direction, volume, open_price, open_time,
close_price, close_time, sl, tp, profit, commission, swap, status,
source, close_reason, created_at
```

**trading_signals**: Generated signals
```sql
id, account_id, symbol, timeframe, signal_type, confidence, entry_price,
sl_price, tp_price, indicators_used, patterns_detected, reasons, status,
created_at, expires_at
```

**logs**: EA and server event logs
```sql
id, account_id, level, message, details (JSONB), timestamp
```

**commands**: Pending trade commands
```sql
id, account_id, command_type, symbol, payload (JSONB), status, created_at,
executed_at, response (JSONB)
```

**account_transactions**: Deposits, withdrawals, balance changes
```sql
id, account_id, ticket, transaction_type, amount, timestamp, comment, balance
```

**broker_symbols**: Available symbols from broker
```sql
id, account_id, symbol, created_at
```

## API Endpoints

### Port 9900 - Command & Control

**POST /api/connect**
- EA initial connection
- Returns: `{api_key, symbols: []}`

**POST /api/heartbeat**
- Periodic status updates (every 30s)
- Body: `{account, api_key, timestamp, balance, equity, margin, free_margin, profit_*}`
- Returns: `{status, symbols: [], commands: []}`

**POST /api/symbols**
- Get subscribed symbols
- Returns: `{symbols: []}`

**POST /api/symbol_specs**
- Upload symbol specifications
- Body: `{account, api_key, symbols: [{symbol, volume_min, ...}]}`

**POST /api/ohlc/historical**
- Upload historical candles
- Body: `{account, symbol, timeframe, candles: []}`

**POST /api/get_commands**
- Poll for pending commands
- Returns: `{commands: [{id, type, ...}]}`

**POST /api/command_response**
- Report command execution result
- Body: `{account, api_key, command_id, status, response}`

**POST /api/transaction**
- Report account transactions
- Body: `{account, api_key, ticket, transaction_type, amount, timestamp, comment, balance}`

**POST /api/profit_update**
- Send profit metrics
- Body: `{account, api_key, balance, equity, profit_today, profit_week, profit_month, profit_year}`

### Port 9901 - Tick Streaming

**POST /api/ticks**
- Batch tick ingestion (100ms batches)
- Body: `{account, api_key, ticks: [{symbol, bid, ask, volume, timestamp, tradeable}], balance, equity, ...}`
- High-frequency updates every 100ms

### Port 9902 - Trade Updates

**POST /api/trades/update**
- Position updates (open/close/modify)
- Body: `{account, api_key, ticket, symbol, direction, volume, open_price, open_time, close_price, close_time, sl, tp, profit, commission, swap, status, source, close_reason}`

### Port 9903 - Logging

**POST /api/log**
- EA log messages
- Body: `{account, api_key, level, message, details: {info: "..."}}`
- Levels: INFO, WARNING, ERROR

### Port 9905 - Dashboard

**GET /**
- Web dashboard UI

**GET /api/dashboard/info**
- Account information
- Returns: `{account_number, balance, equity, margin, free_margin, profit_*, open_positions}`

**GET /api/dashboard/symbols**
- Subscribed symbols with latest ticks
- Returns: `{symbols: [{symbol, bid, ask, timestamp, tradeable}]}`

**GET /api/signals**
- Active trading signals
- Query: `?confidence=<min_confidence>`
- Returns: `{signals: [], count, volatility, interval}`

**POST /api/command/create**
- Create trade command
- Body: `{account, api_key, command_type, symbol, order_type, volume, sl, tp, comment}`

**WebSocket /socket.io**
- Real-time updates for dashboard

## MT5 Expert Advisor

### Key Features

1. **OnTimer() Based Tick Collection**
   - 100ms interval timer
   - Collects ticks for ALL subscribed symbols
   - Independent from chart symbol

2. **Trading Hours Detection**
   - Crypto: Always tradeable (24/7)
   - Forex: Weekend detection (Sat/Sun closed)
   - Friday 22:00 UTC → Weekend starts
   - Sunday before 22:00 UTC → Weekend continues

3. **Close Reason Detection**
   - SL_HIT: Stop Loss triggered
   - TP_HIT: Take Profit triggered
   - TRAILING_STOP: SL moved in profit direction
   - MANUAL: User-initiated close

4. **Comprehensive Logging**
   - Connection/Reconnection/Disconnect
   - Trade opened/closed/modified
   - Command execution (success/failure)
   - Errors and warnings
   - Symbol subscription changes

5. **Automatic Reconnection**
   - Detects connection loss
   - Automatic reconnection on heartbeat failure
   - Preserves API key across restarts

### Configuration

```mql5
input string ServerURL = "http://100.97.100.50:9900";
input int ConnectionTimeout = 5000;
input int HeartbeatInterval = 30;        // seconds
input int TickBatchInterval = 100;       // milliseconds
```

### Logging Events

All EA events are sent to server Port 9903 and stored in `logs` table:

**INFO Level:**
- EA connected to server
- EA reconnected to server
- Trade opened (with ticket, symbol, direction, volume)
- Trade closed (with profit, close reason)
- Trade modified (with new SL/TP)
- Command received (with type, ID)
- Command executed successfully
- Symbol subscribed
- EA disconnecting (normal shutdown)

**WARNING Level:**
- Unknown command type
- Heartbeat failed (HTTP errors)

**ERROR Level:**
- Failed to connect to server
- Heartbeat failed (WebRequest error)
- Authentication failed (invalid API key)
- Command failed (execution errors)

### Key Functions

**IsSymbolTradeable(symbol)**: Market hours detection
- Returns true for crypto (BTC, ETH, XRP, LTC)
- Returns false for Forex on weekends
- Checks SymbolInfoSessionTrade() for other instruments

**DetectCloseReason(positionTicket, dealTicket)**: Close reason analysis
- Compares close price with SL/TP
- Detects if SL moved in profit direction
- Returns: TP_HIT, SL_HIT, TRAILING_STOP, MANUAL, UNKNOWN

**SendLog(level, message, details)**: Event logging
- Sends logs to server Port 9903
- Only logs when connected and has API key
- JSON format with details object

## Signal Generation

### Technical Indicators

**RSI (Relative Strength Index)**
- Period: 14
- Overbought: >70 (SELL signal)
- Oversold: <30 (BUY signal)

**MACD (Moving Average Convergence Divergence)**
- Fast: 12, Slow: 26, Signal: 9
- Bullish crossover: MACD crosses above signal (BUY)
- Bearish crossover: MACD crosses below signal (SELL)

**Stochastic Oscillator**
- K: 5, D: 3, Slowing: 3
- Overbought: >80 (SELL signal)
- Oversold: <20 (BUY signal)

**Bollinger Bands**
- Period: 20, Deviation: 2
- Upper breakout: SELL signal
- Lower breakout: BUY signal

**EMA Crossover**
- Fast: 9, Slow: 21
- Golden cross: Fast > Slow (BUY)
- Death cross: Fast < Slow (SELL)

### Signal Confidence

```python
confidence = (matching_indicators / total_indicators) * 100
```

Example: If 3 out of 5 indicators agree → 60% confidence

### Market Volatility Detection

**Low Volatility** (signal interval: 20s)
- ATR < mean - std_dev

**Normal Volatility** (signal interval: 10s)
- mean - std_dev ≤ ATR ≤ mean + std_dev

**High Volatility** (signal interval: 5s)
- ATR > mean + std_dev

### Market Hours Filtering

Implemented in **app.py** ([is_symbol_tradeable_now](app.py#L44-78)):

**Crypto (BTC, ETH, XRP, LTC, etc.)**
- Always tradeable: `return True`

**Forex (USD, EUR, GBP, JPY, etc.)**
- Saturday (weekday 5): `return False`
- Sunday (weekday 6): `return False`
- Friday after 22:00 UTC: `return False`
- Sunday before 22:00 UTC: `return False`

**Other Instruments**
- Default: `return True`

Signals with `tradeable: false` are automatically hidden in dashboard.

## Docker Services

```yaml
services:
  db:
    image: postgres:15
    container_name: ngtradingbot_db
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    container_name: ngtradingbot_redis
    ports: ["6379:6379"]

  server:
    build: .
    container_name: ngtradingbot_server
    ports: ["9900-9905:9900-9905"]
    depends_on: [db, redis]
```

## Common Commands

### Docker Management

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Rebuild after code changes
docker compose build server
docker compose restart server

# View logs
docker logs ngtradingbot_server -f
docker logs ngtradingbot_db -f
docker logs ngtradingbot_redis -f

# View specific port logs
docker logs ngtradingbot_server -f | grep "9901"
```

### Database Operations

```bash
# Connect to database
docker exec -it ngtradingbot_db psql -U trader -d ngtradingbot

# View tables
\dt

# View logs
SELECT level, message, details, timestamp
FROM logs
ORDER BY timestamp DESC
LIMIT 20;

# View latest ticks
SELECT symbol, bid, ask, tradeable, timestamp
FROM ticks
WHERE symbol = 'BTCUSD'
ORDER BY timestamp DESC
LIMIT 10;

# View active signals
SELECT symbol, signal_type, confidence, entry_price, sl_price, tp_price, created_at
FROM trading_signals
WHERE status = 'active'
ORDER BY confidence DESC;

# View open trades
SELECT ticket, symbol, direction, volume, open_price, sl, tp, profit
FROM trades
WHERE status = 'open'
ORDER BY open_time DESC;
```

### Redis Operations

```bash
# Connect to Redis
docker exec -it ngtradingbot_redis redis-cli

# View all keys
KEYS *

# View market volatility
GET market_volatility

# View signal interval
GET signal_interval

# View latest tick for symbol
GET tick:BTCUSD
```

### Backup Operations

```bash
# Manual backup
docker exec ngtradingbot_server python backup_scheduler.py

# View backup status
docker logs ngtradingbot_server | grep backup

# List backups
ls -lh /projects/ngTradingBot/backups/
```

## Development Workflow

### Code Changes

1. **Modify Python code**
   ```bash
   # Edit files in /projects/ngTradingBot/
   nano app.py
   ```

2. **Rebuild and restart**
   ```bash
   docker compose build server
   docker compose restart server
   ```

3. **Verify changes**
   ```bash
   docker logs ngtradingbot_server -f
   ```

### EA Changes

1. **Modify MQL5 code**
   - Edit in MetaEditor on Windows VPS
   - File: `ServerConnector.mq5`

2. **Update modification date**
   ```mql5
   #define CODE_LAST_MODIFIED "2025-10-04 09:20:00"
   ```

3. **Compile in MetaEditor**
   - F7 or Tools > Compile

4. **Restart EA**
   - Remove from chart
   - Re-add to chart
   - Check Experts tab for connection log

### Database Schema Changes

1. **Modify models.py**
   ```python
   # Add new column
   class Trade(Base):
       new_field = Column(String(100))
   ```

2. **Update database**
   ```bash
   docker exec -it ngtradingbot_db psql -U trader -d ngtradingbot
   ALTER TABLE trades ADD COLUMN new_field VARCHAR(100);
   ```

## Troubleshooting

### EA Not Connecting

1. **Check server status**
   ```bash
   docker ps
   docker logs ngtradingbot_server
   ```

2. **Verify WebRequest allowed**
   - MT5 > Tools > Options > Expert Advisors
   - Enable "Allow WebRequest for listed URLs"
   - Add: `http://100.97.100.50:9900`

3. **Check EA logs**
   - MT5 > Toolbox > Experts tab
   - Look for connection messages

### No Ticks Received

1. **Check symbol subscription**
   ```sql
   SELECT * FROM subscribed_symbols WHERE account_id = 1;
   ```

2. **Verify EA timer**
   - Should see "OnTimer()" logs every 100ms
   - Check MT5 Experts tab

3. **Monitor tick endpoint**
   ```bash
   docker logs ngtradingbot_server -f | grep "POST /api/ticks"
   ```

### Signals Not Generated

1. **Check signal worker**
   ```bash
   docker logs ngtradingbot_server | grep signal_worker
   ```

2. **Verify market hours**
   - Forex signals hidden on weekends
   - Check `tradeable` field in signals

3. **Check Redis connection**
   ```bash
   docker exec ngtradingbot_redis redis-cli PING
   ```

### Dashboard Not Updating

1. **Check WebSocket connection**
   - Browser console: Look for socket.io errors

2. **Verify server ports**
   ```bash
   docker ps | grep 9905
   ```

3. **Clear browser cache**
   - Hard refresh: Ctrl+Shift+R

## Performance Optimization

### Tick Batch Writing

- Buffer size: 1000 ticks
- Write interval: 5 seconds
- Prevents database overload

### Signal Generation

- Interval based on volatility
- Low: 20s, Normal: 10s, High: 5s
- Old signals auto-expired after 24h

### Database Cleanup

- Tick retention: 7 days
- Automatic cleanup on server startup
- Prevents database bloat

## Security Considerations

1. **API Key Authentication**
   - Generated on first connection
   - Stored in EA config file
   - Required for all endpoints (except /connect)

2. **Rate Limiting**
   - Heartbeat: Every 30s
   - Ticks: Every 100ms (batched)
   - Commands: Polled every 1s

3. **Input Validation**
   - All trade commands validated
   - SL/TP required (no zero values)
   - Volume normalized to symbol specs

## Future Enhancements

- [ ] Web-based EA configuration
- [ ] Multi-account support in dashboard
- [ ] Advanced pattern recognition
- [ ] Machine learning signal scoring
- [ ] Risk management system
- [ ] Performance analytics
- [ ] Alert notifications
- [ ] Mobile app

## Known Issues

None currently reported.

## Version History

**2025-10-04**: Enhanced logging system, market hours filtering
**2025-10-03**: Signal generation, dashboard improvements
**2025-10-02**: Multi-port architecture, WebSocket integration
**2025-10-01**: Initial implementation

## Contact

For technical support, consult this file and project documentation.

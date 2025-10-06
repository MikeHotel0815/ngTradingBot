# ngTradingBot

Advanced Multi-Port Trading System with MetaTrader 5 Integration, Real-time Signal Generation, and Web Dashboard.

## Features

### 🔌 Multi-Port Server Architecture
- **Port 9900**: Command & Control API (EA connection, heartbeat, commands)
- **Port 9901**: High-frequency tick streaming (100ms batches)
- **Port 9902**: Trade updates and position synchronization
- **Port 9903**: Centralized logging system
- **Port 9905**: Web Dashboard & WebSocket real-time updates

### 📊 Real-time Trading Signals
- **Technical Analysis**: RSI, MACD, Stochastic, Bollinger Bands, EMA crossovers
- **Pattern Detection**: Support/Resistance, Trend channels
- **Multi-timeframe**: M1, M5, M15, H1, H4, D1
- **Confidence Scoring**: Weighted multi-indicator signals
- **Market Hours Detection**: Automatic filtering of non-tradeable symbols

### 🤖 MT5 Expert Advisor (EA)
- **WebSocket-based Communication**: Reliable binary protocol
- **Tick Streaming**: Real-time market data with 100ms batches
- **Trade Execution**: Open, modify, close positions via REST API
- **Close Reason Detection**: SL_HIT, TP_HIT, TRAILING_STOP, MANUAL
- **Comprehensive Logging**: All EA events logged to server
- **Auto-reconnection**: Automatic recovery from disconnections

### 📈 Web Dashboard
- **Real-time Updates**: WebSocket-based live data
- **Signal Management**: Filter by confidence, view active signals
- **Position Monitoring**: Track open trades with P&L
- **Symbol Price Display**: Live bid/ask with pulsing updates
- **Performance Metrics**: Today, Week, Month, Year profits
- **AutoTrade Control**: Automated signal execution

### 🗄️ Database & Storage
- **PostgreSQL**: Account data, trades, signals, ticks, logs
- **Redis**: Market volatility caching, signal intervals
- **Automated Cleanup**: Old tick data retention (7 days)
- **Backup System**: Daily database backups to GitHub

## Setup

### Prerequisites
```bash
# Docker & Docker Compose installed
# MetaTrader 5 installed (for EA)
```

### Installation

1. **Clone Repository**
```bash
git clone <repository>
cd ngTradingBot
```

2. **Start Services**
```bash
docker compose up -d
```

3. **Configure MT5 EA**
- Copy `mt5_EA/Experts/ServerConnector.mq5` to MT5 Experts folder
- Compile in MetaEditor
- Add to chart
- Configure WebRequest URL: `http://<server-ip>:9900`

### Environment Variables

Create `.env` file:
```env
POSTGRES_USER=trader
POSTGRES_PASSWORD=<your-password>
POSTGRES_DB=ngtradingbot
REDIS_URL=redis://redis:6379/0
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
```

## Architecture

### Server Components

**app.py**: Main Flask application with multi-port routing
- Command & Control endpoints
- Tick batch processing
- Trade synchronization
- Logging aggregation
- WebUI & dashboard

**signal_generator.py**: Technical analysis engine
- Multi-indicator analysis
- Pattern detection
- Confidence scoring
- Signal expiration management

**signal_worker.py**: Background signal generation
- Periodic signal updates
- Market volatility detection
- Dynamic signal intervals

**tick_batch_writer.py**: High-performance tick storage
- Batched PostgreSQL inserts
- Redis caching for latest ticks
- Memory-efficient buffering

**backup_scheduler.py**: Automated backup system
- Daily database dumps
- GitHub integration
- Retention management

### Database Schema

**accounts**: MT5 account information
**subscribed_symbols**: User symbol subscriptions
**ticks**: Real-time tick data (7-day retention)
**ohlc_data**: Historical candle data
**trades**: Position history with close reasons
**trading_signals**: Generated signals with indicators
**logs**: EA and server event logs
**commands**: Pending trade commands

## API Endpoints

### Command & Control (9900)
- `POST /api/connect` - EA initial connection
- `POST /api/heartbeat` - Account status updates
- `POST /api/symbols` - Get subscribed symbols
- `POST /api/get_commands` - Poll pending commands
- `POST /api/command_response` - Command execution result

### Tick Streaming (9901)
- `POST /api/ticks` - Batch tick ingestion

### Trade Updates (9902)
- `POST /api/trades/update` - Position updates

### Logging (9903)
- `POST /api/log` - EA log messages

### Dashboard (9905)
- `GET /` - Web dashboard
- `GET /api/dashboard/info` - Account information
- `GET /api/signals` - Active trading signals
- `POST /api/command/create` - Manual trade commands
- WebSocket `/socket.io` - Real-time updates

## MT5 Expert Advisor

### Features
- OnTimer() based tick collection (100ms intervals)
- Independent from chart symbol ticks
- Trading hours detection (Forex weekends, Crypto 24/7)
- Close reason detection (SL/TP/Trailing/Manual)
- Comprehensive event logging
- Automatic reconnection on disconnect

### Logging Events
- Connection/Reconnection/Disconnect
- Trade opened/closed/modified
- Command execution (success/failure)
- Errors and warnings
- Symbol subscription changes

### Configuration
```mql5
input string ServerURL = "http://100.97.100.50:9900";
input int ConnectionTimeout = 5000;
input int HeartbeatInterval = 30;
input int TickBatchInterval = 100;
```

## Signal Generation

### Technical Indicators
- **RSI**: Overbought (>70), Oversold (<30)
- **MACD**: Bullish/Bearish crossovers
- **Stochastic**: Overbought (>80), Oversold (<20)
- **Bollinger Bands**: Breakout detection
- **EMA Crossover**: Fast(9)/Slow(21) crossovers

### Confidence Calculation
```python
confidence = (matching_indicators / total_indicators) * 100
```

### Market Hours Filtering
- **Crypto (BTC, ETH, etc.)**: 24/7 tradeable
- **Forex (GBPUSD, EURUSD, etc.)**: Closed weekends (Sat/Sun)
- **Metals (XAU, XAG)**: Session-based trading

## Monitoring

### View Logs
```bash
# Server logs
docker logs ngtradingbot_server -f

# Database logs
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c \
  "SELECT level, message, details, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20;"

# Redis cache
docker exec ngtradingbot_redis redis-cli KEYS "*"
```

### Health Checks
- Server startup logs show all 5 ports active
- EA heartbeat every 30 seconds
- Signal generation logs show interval and volatility
- Tick batch writer logs show storage rate

## Development

### Database Migrations
```bash
# Connect to DB
docker exec -it ngtradingbot_db psql -U trader -d ngtradingbot

# View schema
\dt
\d+ trades
```

### Manual Backup
```bash
docker exec ngtradingbot_server python backup_scheduler.py
```

### Signal Generation Testing
```python
from signal_generator import generate_signal

signal = generate_signal(
    symbol="BTCUSD",
    timeframe="H4",
    account_id=1
)
```

## Troubleshooting

### EA Not Connecting
1. Check WebRequest is enabled in MT5 Tools > Options
2. Add server URL to allowed URLs list
3. Verify server is running: `docker ps`
4. Check EA logs in MT5 Experts tab

### No Signals Generated
1. Check signal worker is running: `docker logs ngtradingbot_server | grep signal_worker`
2. Verify symbols are subscribed: Check dashboard
3. Check market hours for Forex symbols
4. Review signal generation logs

### Dashboard Not Updating
1. Check WebSocket connection in browser console
2. Verify tick streaming is active
3. Restart server: `docker compose restart server`

## License

Proprietary - All rights reserved

## Support

For issues and questions, contact the development team.

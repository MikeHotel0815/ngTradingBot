# ngTradingBot - Automated MT5 Trading System

🤖 **Vollautomatisches Trading-System** mit MT5-Integration, Machine Learning und dynamischem Risk Management

## 🎯 Features

- ✅ **Timezone-aware Trading**: UTC + Broker Zeit (EET/EEST) mit automatischer Konvertierung
- ✅ **3-Tier Risk Profiles**: MODERATE | NORMAL | AGGRESSIVE mit dynamischer Confidence-Berechnung
- ✅ **Session-based Trading**: ASIAN | LONDON | OVERLAP | US mit Volatilitäts-Anpassungen
- ✅ **Dynamic Position Limits**: Confidence-basiert (50-100% → 1-5 Trades)
- ✅ **10 Background Workers**: Auto-Trader, Market Conditions, Time Exit, TP/SL Monitor, etc.
- ✅ **Real-time Dashboard**: WebSocket-Updates, sortierte Positionen nach Profit
- ✅ **MT5 Binary Protocol**: 2s Heartbeat, 250ms Command Polling für maximale Performance

## 📁 Projektstruktur

```
ngTradingBot/
├── app.py                          # Flask API Server (Multi-Port: 9900-9905)
├── auto_trader.py                  # Automatischer Trading-Engine
├── unified_workers.py              # 10 Background Workers
├── timezone_manager.py             # 🆕 Timezone Management (UTC ↔ EET/EEST)
├── dynamic_confidence_calculator.py # 🆕 Context-aware Confidence
├── session_volatility_analyzer.py  # Session & Volatility Analysis
├── models.py                       # SQLAlchemy ORM Models
├── database.py                     # Database Connection
├── redis_client.py                 # Redis Queue & Metrics
├── core_communication.py           # MT5 Binary Protocol Handler
├── core_api.py                     # Core API Endpoints
├── templates/                      # Dashboard HTML/CSS/JS
├── workers/                        # Individual Worker Modules
├── mt5_EA/                         # MetaTrader 5 Expert Advisors
├── migrations/                     # SQL Database Migrations
├── docs/                           # 📚 Documentation (46 MD files)
├── tests/                          # 🧪 Test Files
├── scripts/                        # 🔧 Shell Scripts
└── archive/                        # 📦 Old Versions

Docker Services:
├── ngtradingbot_server             # Flask API Server
├── ngtradingbot_workers            # Unified Workers
├── ngtradingbot_db                 # PostgreSQL 15
└── ngtradingbot_redis              # Redis 7
```

## 🚀 Quick Start

### IMPORTANT: Docker Build Rules

**⚠️ On code changes ALWAYS rebuild container with --no-cache**

```bash
# After ANY Python code changes:
docker compose build --no-cache workers
docker compose build --no-cache server

# Then restart:
docker compose up -d
```

Docker caches layers aggressively. Without `--no-cache`, your code changes may not be included in the container!

### 1. Clone & Setup

```bash
git clone https://github.com/MikeHotel0815/ngTradingBot.git
cd ngTradingBot
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start System

```bash
# Build & Start
docker compose build --no-cache
docker compose up -d

# Check Status
docker compose ps
docker logs ngtradingbot_workers --tail 50
```

### 3. Access Dashboard

```
http://localhost:9900
```

## ⚙️ Configuration

### Environment Variables (.env)

```bash
# Database
DATABASE_URL=postgresql://user:pass@db:5432/trading

# Redis
REDIS_URL=redis://redis:6379/0

# MT5 Connection
MT5_ACCOUNT=12345678
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Server

# Auto-Trading
AUTO_TRADING_ENABLED=true
MIN_CONFIDENCE=50.0
RISK_PROFILE=normal  # moderate | normal | aggressive

# Workers
TIME_EXIT_ENABLED=true
TPSL_MONITOR_ENABLED=true
```

## 🕒 Timezone Management

Das System verwendet **timezone-aware timestamps** für präzises Trading:

- **Server/DB**: UTC (naive timestamps für SQLAlchemy)
- **Broker/MT5**: EET/EEST (Europe/Bucharest)
- **Logging**: Zeigt beide Zeitzonen: `[UTC: 10:30:00 | Broker: 13:30:00 EEST]`

### Usage:

```python
from timezone_manager import tz

# Current time
now_utc = tz.now_utc()
now_broker = tz.now_broker()

# Convert
broker_time = tz.utc_to_broker(utc_dt)
utc_time = tz.broker_to_utc(broker_dt)

# Database
db_dt = tz.to_db(aware_dt)      # Make naive UTC
aware_dt = tz.from_db(db_dt)    # Make aware

# Logging
log_msg = tz.format_for_log(dt, "Trade opened")
```

Siehe: `docs/TIMEZONE_IMPLEMENTATION.md`

## 🎯 Risk Profile System

### 3 Intelligente Profile:

| Profile    | Base Conf. | Symbol Adj. | Session Adj. | Volatility Adj. |
|------------|------------|-------------|--------------|-----------------|
| MODERATE   | 65%        | ±2-8%       | ±0-5%        | ±3-5%           |
| NORMAL     | 55%        | ±2-8%       | ±0-5%        | ±3-5%           |
| AGGRESSIVE | 50%        | ±2-8%       | ±0-5%        | ±3-5%           |

### Dynamic Position Limits:

- **50-59% Confidence** → 1 Trade
- **60-69% Confidence** → 2 Trades
- **70-79% Confidence** → 3 Trades
- **80-89% Confidence** → 4 Trades
- **90-100% Confidence** → 5 Trades (capped at 4)

Siehe: `docs/MAX_PERFORMANCE_CONFIG.md`

## 📊 Trading Sessions (UTC)

| Session    | UTC Time    | Volatility | Trailing Multiplier |
|------------|-------------|------------|---------------------|
| ASIAN      | 00:00-08:00 | Low (0.7x) | 0.7x                |
| LONDON     | 08:00-16:00 | High (1.2x)| 1.2x                |
| OVERLAP    | 13:00-16:00 | Max (1.5x) | 1.5x                |
| US         | 13:00-22:00 | High (1.3x)| 1.3x                |
| AFTER_HOURS| 22:00-00:00 | Low        | 0.9x                |

## 🔧 Workers (10 Total)

| Worker               | Interval | Function                          |
|----------------------|----------|-----------------------------------|
| decision_cleanup     | 1h       | Clean old trading decisions       |
| news_fetch           | 1h       | Fetch economic calendar           |
| trade_timeout        | 5min     | Timeout stale trades              |
| strategy_validation  | 5min     | Validate trading strategies       |
| drawdown_protection  | 1min     | Monitor account drawdown          |
| partial_close        | 1min     | Partial position closing          |
| **auto_trader**      | 1min     | Execute trading signals           |
| **market_conditions**| 5min     | 🆕 Log session + volatility       |
| **time_exit**        | 5min     | 🆕 Time-based exits               |
| **tpsl_monitor**     | 1min     | 🆕 TP/SL validation               |

## 📡 API Endpoints

### Trading Control

```bash
# Get Auto-Trade Status
GET http://localhost:9901/api/auto-trade/status

# Set Risk Profile
POST http://localhost:9901/api/auto-trade/set-risk-profile
{"risk_profile": "aggressive"}

# Get Confidence Requirements
GET http://localhost:9901/api/auto-trade/confidence-requirements
```

### Monitoring

```bash
# Worker Status
GET http://localhost:9901/api/workers/status

# Market Conditions
GET http://localhost:9901/api/market-conditions

# System Health
GET http://localhost:9900/health
```

Siehe: `docs/API_DOCUMENTATION.md`

## 🧪 Testing

```bash
# Timezone Verification
python3 verify_timezone.py

# Unit Tests
cd tests
python3 test_core_system.py
python3 test_tp_sl.py

# 72h Monitoring
cd scripts
./start_72h_test.sh
```

## 📚 Dokumentation

Alle Dokumente in `docs/`:

- `TIMEZONE_IMPLEMENTATION.md` - Timezone Management
- `MAX_PERFORMANCE_CONFIG.md` - Performance Tuning
- `API_DOCUMENTATION.md` - API Reference
- `CORE_SYSTEM_README.md` - Core System
- `MIGRATION_GUIDE.md` - Database Migrations
- `TESTING_CHECKLIST.md` - QA Checklist

## 🐛 Debugging

```bash
# Worker Logs
docker logs ngtradingbot_workers --tail 100 -f

# Server Logs
docker logs ngtradingbot_server --tail 100 -f

# Database
docker exec -it ngtradingbot_db psql -U trading_user -d trading

# Redis
docker exec -it ngtradingbot_redis redis-cli
```

## 🔒 Security

- ✅ Environment variables für sensible Daten
- ✅ PostgreSQL mit Passwort-Auth
- ✅ Redis mit Passwort (optional)
- ✅ Docker Network Isolation
- ✅ Input Validation auf allen Endpoints

## 📈 Performance

- **Heartbeat**: 2 Sekunden (optimal für 2 EAs)
- **Command Polling**: 250ms
- **Database**: Connection Pooling (20 connections)
- **Redis**: Pipelining für Batch Operations
- **WebSocket**: Smart Updates (nur bei Änderungen)

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open Pull Request

## 📄 License

MIT License - siehe LICENSE file

## 👤 Author

**MikeHotel0815**

- GitHub: [@MikeHotel0815](https://github.com/MikeHotel0815)

## 🎯 Status

✅ **PRODUCTION READY** - Timezone-aware, Risk Profiles, 10 Workers, Full Monitoring

---

**Last Updated**: 2025-10-17 | **Version**: 3.0.0 (Timezone Implementation)

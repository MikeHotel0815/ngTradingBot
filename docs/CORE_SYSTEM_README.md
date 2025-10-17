# ngTradingBot - Core Communication System
**Bulletproof EA ↔ Server Communication**

*Version 2.0 - "Rock Solid"*  
*Last Updated: 2025-10-17*

---

## 🎯 Vision

**Das Core-System ist KUGELSICHER.**

Die Kommunikation zwischen EA und Server ist absolut zuverlässig. Kommandos werden schnellstmöglich an den EA weitergegeben und Informationen vom EA werden schnellstmöglich vom Server verarbeitet.

**Der EA/MT5 ist die "Single Source of Truth"!**

Alle anderen Funktionen (Strategie, Kontrolle, Analyse) sind als separate Module integriert.

---

## 🏗️ Architektur

### Multi-Port Design

```
┌─────────────────────────────────────────────────────────────┐
│                    ngTradingBot Core Server                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Port 9900: Command & Control                                │
│  ├─ /api/connect          (EA Initial Connection)           │
│  ├─ /api/heartbeat        (Status Updates - 30s)            │
│  ├─ /api/get_commands     (Poll Commands - 1s)              │
│  ├─ /api/command_response (Execution Results)               │
│  ├─ /api/disconnect       (Clean Shutdown)                  │
│  └─ /api/status           (Server Status)                   │
│                                                               │
│  Port 9901: Tick Data Streaming                              │
│  └─ /api/ticks/batch      (Batch Tick Upload - 100ms)       │
│                                                               │
│  Port 9902: Trade Synchronization                            │
│  ├─ /api/trades/sync      (Full State Sync - 30s)           │
│  ├─ /api/trades/opened    (Trade Open Notification)         │
│  ├─ /api/trades/closed    (Trade Close Notification)        │
│  └─ /api/trades/modified  (SL/TP Modification)              │
│                                                               │
│  Port 9903: EA Logging                                       │
│  └─ /api/log              (EA Log Messages)                 │
│                                                               │
│  Port 9905: WebUI & Management API                           │
│  ├─ /health               (Health Check)                    │
│  ├─ /api/system/status    (System Status)                   │
│  └─ WebSocket             (Real-time Updates)               │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
MT5 EA (Windows VPS)
      │
      ├─ Every 100ms ──→ Tick Batch ──→ Port 9901 ──→ Batch Writer ──→ PostgreSQL
      │
      ├─ Every 1s ────→ Poll Commands ──→ Port 9900 ──→ Redis Queue
      │
      ├─ Every 30s ───→ Heartbeat ──→ Port 9900 ──→ Update Account State
      │                      │
      │                      └─→ Get Pending Commands
      │
      ├─ Every 30s ───→ Trade Sync ──→ Port 9902 ──→ Reconcile Positions
      │
      ├─ On Events ───→ Logs ──→ Port 9903 ──→ PostgreSQL
      │
      └─ On Events ───→ Trade Notifications ──→ Port 9902 ──→ Database
```

---

## 🔑 Key Principles

### 1. EA is Single Source of Truth

**Problem:** Dateninkonsistenzen zwischen EA und Server

**Lösung:**
- EA sendet jeden 30s ALLE offenen Trades
- Server reconciled automatisch (schließt Trades die nicht mehr im EA sind)
- Bei Konflikten gewinnt IMMER der EA-State
- Server darf NIEMALS Trades ohne EA-Bestätigung ändern

```python
# Beispiel: Trade Sync
ea_tickets = {16218652, 16218653, 16218654}
db_tickets = {16218652, 16218653, 16218655}

missing_in_ea = {16218655}  # → Server schließt automatisch
missing_in_db = {}           # → (keine neuen)
both = {16218652, 16218653}  # → Update SL/TP falls geändert
```

### 2. Zero Data Loss

**Problem:** Tick-Daten oder Commands gehen verloren

**Lösung:**
- Alle EA-Messages werden SOFORT persistiert (PostgreSQL)
- Batch Writer für Ticks (alle 1s ins DB)
- Redis Queue für Commands (instant delivery)
- Complete Audit Trail (jede Interaktion geloggt)

### 3. Fast Command Delivery

**Problem:** Commands erreichen EA zu langsam

**Lösung:**
- Redis In-Memory Queue (< 1ms latency)
- Command Priority System (CRITICAL > HIGH > NORMAL > LOW)
- EA pollt jeden 1s (kann auf 500ms reduziert werden)
- Heartbeat enthält auch Commands (redundant)

```python
# Command Priority
CRITICAL = 99   # Emergency close all
HIGH = 10       # SL/TP modifications, urgent closes
NORMAL = 5      # Regular trade operations
LOW = 1         # Symbol updates, settings
```

### 4. Reliable Response Tracking

**Problem:** Unklarer Command-Status

**Lösung:**
- Jeder Command hat Status: PENDING → EXECUTING → COMPLETED/FAILED/TIMEOUT
- Timeout Tracking (default 30s)
- Retry Logic (max 3 retries mit exponential backoff)
- Response Validation (EA muss Ticket/Error zurückgeben)
- Latency Tracking (Command Response Time in ms)

### 5. Connection Resilience

**Problem:** Verbindungsabbrüche

**Lösung:**
- Health Score (0-100) pro Connection
- Auto-Reconnect mit exponential backoff
- Failed Heartbeat Tracking
- Automatic Connection State Management
- Degradation: CONNECTED → RECONNECTING → FAILED

```python
# Health Score Calculation
health = 100
health -= 10 * consecutive_failures
health += 5  # on successful heartbeat
health = max(0, min(100, health))

is_healthy = (
    state == CONNECTED and
    last_heartbeat < 60s ago and
    consecutive_failures < 3 and
    health_score > 50
)
```

---

## 📊 Core Components

### 1. CoreCommunicationManager

**Hauptklasse für EA-Kommunikation**

```python
from core_communication import get_core_comm

comm = get_core_comm()

# Register EA Connection
conn = comm.register_connection(
    account_id=1,
    account_number=12345678,
    broker="Pepperstone"
)

# Process Heartbeat
result = comm.process_heartbeat(
    account_id=1,
    balance=10000.00,
    equity=10050.00,
    margin=100.00,
    free_margin=9950.00,
    latency_ms=45.3
)

# Create Command
cmd_id, cmd_exec = comm.create_command(
    account_id=1,
    command_type="OPEN_TRADE",
    payload={
        'symbol': 'EURUSD',
        'order_type': 'BUY',
        'volume': 0.1,
        'sl': 1.0850,
        'tp': 1.0950
    },
    priority=CommandPriority.NORMAL
)

# Process Command Response
comm.process_command_response(
    command_id=cmd_id,
    status='completed',
    response_data={'ticket': 16218652, 'open_price': 1.0900}
)

# Sync Trades (EA as Source of Truth)
result = comm.sync_trades_from_ea(
    account_id=1,
    ea_trades=[
        {
            'ticket': 16218652,
            'symbol': 'EURUSD',
            'direction': 'BUY',
            'volume': 0.1,
            'open_price': 1.0900,
            'sl': 1.0850,
            'tp': 1.0950
        }
    ]
)
```

### 2. EAConnection

**Repräsentiert eine aktive EA-Verbindung**

```python
@dataclass
class EAConnection:
    account_id: int
    account_number: int
    broker: str
    state: ConnectionState
    
    # Metrics
    connected_at: datetime
    last_heartbeat: datetime
    heartbeat_count: int
    tick_count: int
    command_count: int
    
    # Performance
    avg_heartbeat_latency: float     # in seconds
    avg_command_response_latency: float
    
    # Health
    consecutive_failures: int
    health_score: float              # 0-100
```

### 3. CommandExecution

**Tracked Command-Ausführung**

```python
@dataclass
class CommandExecution:
    command_id: str
    account_id: int
    command_type: str
    priority: CommandPriority
    
    status: CommandStatus
    created_at: datetime
    sent_at: datetime
    completed_at: datetime
    
    retry_count: int
    max_retries: int = 3
    timeout: int = 30  # seconds
    
    response_data: Dict
    error_message: str
```

---

## 🚀 Usage

### Starting the Core Server

```bash
# Direct Python
python app_core.py

# Via Docker Compose
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Sending Commands to EA

```python
from core_api import (
    send_open_trade_command,
    send_modify_trade_command,
    send_close_trade_command,
    send_close_all_command
)

# Open Trade
cmd_id = send_open_trade_command(
    account_id=1,
    symbol='EURUSD',
    order_type='BUY',
    volume=0.1,
    sl=1.0850,
    tp=1.0950,
    comment='Signal #123'
)

# Modify Trade
cmd_id = send_modify_trade_command(
    account_id=1,
    ticket=16218652,
    sl=1.0860,  # Trail stop
    tp=1.0950
)

# Close Trade
cmd_id = send_close_trade_command(
    account_id=1,
    ticket=16218652
)

# Emergency: Close All
cmd_id = send_close_all_command(
    account_id=1,
    symbol='EURUSD'  # optional: only EURUSD
)
```

### Checking EA Status

```python
from core_communication import get_ea_status, is_ea_connected

# Check if EA is connected and healthy
if is_ea_connected(account_id=1):
    print("EA is online and healthy")
else:
    print("EA is offline or unhealthy")

# Get detailed status
status = get_ea_status(account_id=1)
print(f"Heartbeat Age: {status['last_heartbeat_age_seconds']}s")
print(f"Health Score: {status['health_score']}")
print(f"Latency: {status['avg_heartbeat_latency_ms']}ms")
```

### System Status

```bash
# Via HTTP API
curl http://localhost:9905/api/system/status

# Response
{
  "connections": {
    "total": 1,
    "healthy": 1,
    "unhealthy": 0,
    "details": [...]
  },
  "commands": {
    "total_processed": 1523,
    "total_failed": 12,
    "success_rate": 99.21,
    "active": 3
  },
  "data": {
    "total_ticks_received": 458234,
    "total_heartbeats_received": 2890
  }
}
```

---

## 📈 Monitoring & Metrics

### Connection Metrics

```python
conn = comm.get_connection(account_id)

print(f"State: {conn.state.value}")
print(f"Health Score: {conn.health_score:.1f}%")
print(f"Heartbeats: {conn.heartbeat_count}")
print(f"Failed Heartbeats: {conn.failed_heartbeats}")
print(f"Reconnects: {conn.reconnect_count}")
print(f"Avg Heartbeat Latency: {conn.avg_heartbeat_latency * 1000:.1f}ms")
print(f"Avg Command Latency: {conn.avg_command_response_latency * 1000:.1f}ms")
```

### System-Wide Metrics

```python
status = comm.get_system_status()

print(f"Total Connections: {status['connections']['total']}")
print(f"Healthy: {status['connections']['healthy']}")
print(f"Commands Processed: {status['commands']['total_processed']}")
print(f"Success Rate: {status['commands']['success_rate']}%")
print(f"Ticks Received: {status['data']['total_ticks_received']}")
```

### Health Alerts

```python
# Example: Monitor unhealthy connections
for conn in comm.get_all_connections():
    if not conn.is_healthy():
        print(f"⚠️  ALERT: Account {conn.account_number} is unhealthy!")
        print(f"   Health Score: {conn.health_score:.1f}%")
        print(f"   Consecutive Failures: {conn.consecutive_failures}")
        print(f"   Last Heartbeat: {conn.last_heartbeat}")
        
        # Send Telegram notification
        telegram.send_alert(
            f"EA Connection Unhealthy\n"
            f"Account: {conn.account_number}\n"
            f"Health: {conn.health_score:.1f}%"
        )
```

---

## 🔧 Configuration

### Environment Variables

```bash
# Database
DATABASE_URL="postgresql://user:pass@localhost:5432/ngtrading"

# Redis
REDIS_HOST="localhost"
REDIS_PORT=6379
REDIS_DB=0

# Server Ports
PORT_COMMAND=9900
PORT_TICKS=9901
PORT_TRADES=9902
PORT_LOGS=9903
PORT_WEBUI=9905

# Performance
TICK_BATCH_SIZE=100
TICK_BATCH_INTERVAL_SEC=1
COMMAND_POLL_INTERVAL_SEC=1
HEARTBEAT_INTERVAL_SEC=30
TRADE_SYNC_INTERVAL_SEC=30

# Health Monitoring
MAX_HEARTBEAT_AGE_SEC=60
MAX_CONSECUTIVE_FAILURES=3
MIN_HEALTH_SCORE=50
```

### Tuning Parameters

```python
# core_communication.py

# Command Timeouts
DEFAULT_COMMAND_TIMEOUT = 30  # seconds
HIGH_PRIORITY_TIMEOUT = 10
CRITICAL_PRIORITY_TIMEOUT = 5

# Retry Logic
MAX_COMMAND_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # exponential: 2^retry_count seconds

# Connection Health
HEARTBEAT_TIMEOUT = 60  # seconds
MAX_CONSECUTIVE_FAILURES = 3
HEALTH_DEGRADATION_RATE = 10  # points per failure
HEALTH_RECOVERY_RATE = 5      # points per success

# Cleanup
COMMAND_TRACKER_MAX_AGE_HOURS = 24  # cleanup old trackers
```

---

## 🛡️ Error Handling

### Connection Failures

```python
# Auto-Recovery Pattern
try:
    conn = comm.register_connection(account_id, account_number, broker)
except Exception as e:
    logger.error(f"Failed to register connection: {e}")
    # System auto-retries via EA's reconnection logic
```

### Command Failures

```python
# Command mit Retry-Logic
cmd_id, cmd_exec = comm.create_command(...)

# Check status later
if cmd_exec.status == CommandStatus.FAILED:
    if cmd_exec.can_retry():
        # System automatically retries
        logger.info(f"Command will retry: {cmd_exec.retry_count}/{cmd_exec.max_retries}")
    else:
        # Max retries exceeded
        logger.error(f"Command failed permanently: {cmd_exec.error_message}")
        # Handle gracefully (alert user, log, etc.)
```

### Trade Sync Conflicts

```python
# EA State wins always
result = comm.sync_trades_from_ea(account_id, ea_trades)

if result['reconciliation']['closed_trades'] > 0:
    logger.warning(
        f"Closed {result['reconciliation']['closed_trades']} trades "
        f"that were not in EA (DB was out of sync)"
    )

if result['reconciliation']['new_trades'] > 0:
    logger.warning(
        f"Found {result['reconciliation']['new_trades']} trades in EA "
        f"that were missing in DB (added now)"
    )
```

---

## 📝 Best Practices

### 1. Always Check EA Connection Before Commands

```python
if not is_ea_connected(account_id):
    raise Exception("EA is not connected - cannot send command")

cmd_id = send_open_trade_command(...)
```

### 2. Use Appropriate Command Priorities

```python
# Normal trading
send_open_trade_command(...)  # Priority: NORMAL

# Urgent modifications
send_modify_trade_command(...)  # Priority: HIGH

# Emergency situations
send_close_all_command(...)  # Priority: CRITICAL
```

### 3. Monitor Health Regularly

```python
# Background task (every 60s)
def monitor_connections():
    for conn in comm.get_all_connections():
        if conn.health_score < 70:
            alert_admin(f"Connection health degrading: {conn.account_number}")
        
        if conn.consecutive_failures >= 3:
            alert_admin(f"Connection failing: {conn.account_number}")
```

### 4. Let EA Sync Handle State

```python
# ❌ Don't manually close trades in DB
# trade.status = 'closed'  # BAD!

# ✅ Wait for EA sync or send close command
send_close_trade_command(account_id, ticket)
# EA will confirm and sync will update DB
```

### 5. Log Everything

```python
# All operations are logged automatically
logger.info(f"Command sent: {command_type}")
logger.info(f"Response received: {status}")
logger.warning(f"Connection degraded: {health_score}")
logger.error(f"Command failed: {error_message}")
```

---

## 🔬 Testing

### Unit Tests

```bash
# Test core communication
pytest tests/test_core_communication.py -v

# Test API endpoints
pytest tests/test_core_api.py -v

# Test connection management
pytest tests/test_connection.py -v
```

### Integration Tests

```bash
# Test EA <-> Server communication
pytest tests/integration/test_ea_communication.py -v

# Test trade sync
pytest tests/integration/test_trade_sync.py -v
```

### Load Tests

```bash
# Simulate high-frequency trading
python tests/load/simulate_hft.py --accounts 5 --trades-per-sec 10

# Simulate tick flood
python tests/load/simulate_tick_flood.py --symbols 20 --ticks-per-sec 100
```

---

## 📊 Performance Benchmarks

### Expected Metrics

```
Heartbeat Processing:     < 5ms
Command Creation:         < 10ms
Command Delivery:         < 50ms (Redis queue)
Trade Sync:              < 100ms (10 trades)
Tick Batch Processing:   < 50ms (100 ticks)
```

### Throughput

```
Commands per second:     > 100
Ticks per second:       > 10,000
Trade syncs per hour:   > 100
Concurrent connections:  > 10
```

---

## 🐛 Troubleshooting

### EA Not Connecting

```
1. Check server is running: curl http://localhost:9900/api/status
2. Check EA logs in MT5 Experts tab
3. Check EA WebRequest permissions
4. Check Tailscale/VPN connection
5. Check firewall rules
```

### Commands Not Reaching EA

```
1. Check Redis: redis-cli PING
2. Check command queue: redis-cli LLEN command_queue_1
3. Check EA is polling: look for "CheckForCommands" in EA logs
4. Check command status: GET /api/command/{command_id}/status
```

### Trades Not Syncing

```
1. Check EA trade sync logs
2. Check /api/trades/sync endpoint
3. Manually trigger sync: POST /api/trades/sync/force
4. Check PostgreSQL connection
```

### High Latency

```
1. Check network latency: ping server
2. Check PostgreSQL performance: EXPLAIN ANALYZE queries
3. Check Redis performance: redis-cli --latency
4. Reduce tick batch size
5. Increase worker threads
```

---

## 🎓 Migration from Old System

### Changes from app.py to app_core.py

```python
# OLD (app.py)
@app.route('/api/connect', methods=['POST'])
def connect():
    # Complex logic mixed with business logic
    ...

# NEW (core_api.py)
def register_command_endpoints(app):
    @app.route('/api/connect', methods=['POST'])
    @require_api_key
    def connect(account: Account):
        # Clean, focused on EA communication
        comm = get_core_comm()
        conn = comm.register_connection(...)
        return jsonify({...})
```

### Running Both Systems Simultaneously

```bash
# Run old system (for strategy modules)
python app.py &

# Run new core system (for EA communication)
python app_core.py &

# Gradually migrate endpoints from app.py to modules
```

---

## 🚀 Future Enhancements

### Planned Features

- [ ] WebSocket push for commands (eliminate polling)
- [ ] Command batching for better throughput
- [ ] Multi-region server support
- [ ] Command replay/audit system
- [ ] Advanced health prediction (ML-based)
- [ ] Automatic failover to backup server
- [ ] GraphQL API for complex queries

---

## 📞 Support

**Issues:** https://github.com/MikeHotel0815/ngTradingBot/issues  
**Discord:** [Coming Soon]  
**Email:** [Coming Soon]

---

## 📄 License

Proprietary - All Rights Reserved

---

**Built with ❤️ for bulletproof trading**

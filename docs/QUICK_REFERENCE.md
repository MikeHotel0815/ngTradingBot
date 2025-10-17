# Core System Quick Reference 🚀

**Schnellreferenz für die tägliche Arbeit mit dem Core Communication System**

---

## 🏃 Quick Start Commands

```bash
# Start Core Server
python app_core.py

# Run Tests
python test_core_system.py

# Check System Status
curl http://localhost:9905/api/system/status | jq

# Check Logs
tail -f logs/core_system.log
```

---

## 📡 Common API Calls

### Check Connection Status

```bash
curl http://localhost:9905/api/system/status | jq '.connections'
```

### Send Command to EA

```python
from core_api import send_open_trade_command

cmd_id = send_open_trade_command(
    account_id=1,
    symbol='EURUSD',
    order_type='BUY',
    volume=0.1,
    sl=1.0850,
    tp=1.0950,
    comment='Manual trade'
)
print(f"Command sent: {cmd_id}")
```

### Check EA Health

```python
from core_communication import is_ea_connected, get_ea_status

if is_ea_connected(account_id=1):
    status = get_ea_status(account_id=1)
    print(f"Health Score: {status['health_score']}")
    print(f"Latency: {status['avg_heartbeat_latency_ms']}ms")
else:
    print("EA is offline!")
```

---

## 🔍 Monitoring

### Live System Status

```bash
watch -n 5 'curl -s http://localhost:9905/api/system/status | jq ".connections, .commands"'
```

### Check Redis Queue

```bash
# Check command queue length
redis-cli LLEN command_queue_1

# View pending commands
redis-cli LRANGE command_queue_1 0 -1
```

### Database Queries

```sql
-- Check open trades
SELECT mt5_ticket, symbol, direction, volume, open_price, status
FROM trades
WHERE account_id = 1 AND status = 'open';

-- Check recent commands
SELECT id, type, status, created_at
FROM commands
WHERE account_id = 1
ORDER BY created_at DESC
LIMIT 10;

-- Check connection logs
SELECT level, message, timestamp
FROM logs
WHERE account_id = 1
ORDER BY timestamp DESC
LIMIT 20;
```

---

## 🛠️ Troubleshooting

### EA Not Connecting

```bash
# 1. Check server is running
curl http://localhost:9900/api/status

# 2. Check EA ServerURL in MT5
# Should be: http://100.97.100.50:9900

# 3. Check firewall
sudo ufw status | grep 9900

# 4. Check Tailscale
ping 100.97.100.50
```

### Commands Not Executing

```bash
# 1. Check Redis
redis-cli PING

# 2. Check command queue
redis-cli LLEN command_queue_1

# 3. Check EA is polling
# Look for "CheckForCommands" in EA logs (MT5 Experts tab)

# 4. Clear stuck commands (CAREFUL!)
redis-cli DEL command_queue_1
```

### High Latency

```bash
# 1. Check network
ping 100.97.100.50

# 2. Check database performance
psql -U ngtrading -d ngtrading -c "
  SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
  FROM pg_tables
  WHERE schemaname = 'public'
  ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
  LIMIT 10;
"

# 3. Optimize database
psql -U ngtrading -d ngtrading -c "VACUUM ANALYZE;"

# 4. Check system resources
htop
```

---

## 📊 Key Metrics

### Healthy System

```
✅ Health Score:          > 90%
✅ Command Success Rate:  > 99%
✅ Heartbeat Latency:     < 100ms
✅ Command Latency:       < 300ms
✅ Consecutive Failures:  < 3
✅ Connection State:      CONNECTED
```

### Warning Signs

```
⚠️  Health Score:          70-90%
⚠️  Command Success Rate:  95-99%
⚠️  Heartbeat Latency:     100-500ms
⚠️  Consecutive Failures:  1-2
```

### Critical Issues

```
🔴 Health Score:          < 70%
🔴 Command Success Rate:  < 95%
🔴 Heartbeat Latency:     > 500ms
🔴 Consecutive Failures:  >= 3
🔴 Connection State:      DISCONNECTED/FAILED
```

---

## 🎯 Daily Checklist

### Morning

- [ ] Check system status: `curl http://localhost:9905/api/system/status`
- [ ] Review overnight logs: `grep ERROR logs/*.log | tail -50`
- [ ] Check all EAs connected: Verify `connections.total` matches expected
- [ ] Check health scores: All > 90%
- [ ] Verify trades synced: No reconciliation conflicts

### During Day

- [ ] Monitor health dashboard (if available)
- [ ] Check for error spikes
- [ ] Verify command execution times
- [ ] Monitor trade sync accuracy

### Evening

- [ ] Review daily metrics
- [ ] Check for any degraded connections
- [ ] Verify all commands executed successfully
- [ ] Backup if needed
- [ ] Plan any maintenance for night

---

## 🔧 Common Tasks

### Restart Core Server

```bash
# Stop
pkill -f "python app_core.py"

# Start
python app_core.py &

# Or with systemd
sudo systemctl restart ngtrading
```

### Clear Redis Queue (Emergency)

```bash
# ⚠️  WARNING: This deletes all pending commands!
redis-cli DEL command_queue_1
redis-cli DEL command_queue_2
# etc for all accounts
```

### Force Trade Sync

```python
from core_communication import get_core_comm

comm = get_core_comm()
result = comm.sync_trades_from_ea(
    account_id=1,
    ea_trades=[]  # Empty = close all open trades in DB
)
print(result)
```

### Manual Command Injection

```python
from core_communication import get_core_comm, CommandPriority

comm = get_core_comm()
cmd_id, cmd_exec = comm.create_command(
    account_id=1,
    command_type="CLOSE_ALL",
    payload={'symbol': 'EURUSD'},  # Optional: specific symbol
    priority=CommandPriority.CRITICAL
)
print(f"Emergency close command sent: {cmd_id}")
```

---

## 📱 Alert Triggers

### Setup Alerts For

```python
# Example: Connection Health Alert
for conn in comm.get_all_connections():
    if conn.health_score < 80:
        send_telegram_alert(
            f"⚠️  Connection Health Degraded\n"
            f"Account: {conn.account_number}\n"
            f"Health: {conn.health_score:.1f}%\n"
            f"Failures: {conn.consecutive_failures}"
        )
    
    if conn.consecutive_failures >= 3:
        send_telegram_alert(
            f"🔴 Connection Failing\n"
            f"Account: {conn.account_number}\n"
            f"Consecutive Failures: {conn.consecutive_failures}\n"
            f"Last Heartbeat: {conn.last_heartbeat}"
        )
```

---

## 🔐 Security Best Practices

- [ ] API keys stored in environment variables only
- [ ] No API keys in git
- [ ] Firewall rules restrict port access
- [ ] Regular security updates
- [ ] Monitor logs for suspicious activity
- [ ] Rotate API keys periodically
- [ ] Use VPN (Tailscale) for EA connections

---

## 📚 Quick Links

| Resource | Location |
|----------|----------|
| Full Documentation | `CORE_SYSTEM_README.md` |
| Migration Guide | `MIGRATION_GUIDE.md` |
| Test Suite | `python test_core_system.py` |
| Source Code | `core_communication.py`, `core_api.py` |

---

## 💡 Tips & Tricks

### Performance Optimization

```bash
# Reduce tick batch interval for lower latency
# In EA: TickBatchInterval = 50  (default 100)

# Increase command poll frequency
# In EA: Poll every 500ms instead of 1000ms
```

### Debug Mode

```python
# Enable debug logging
import logging
logging.getLogger('core_communication').setLevel(logging.DEBUG)
```

### Custom Monitoring Script

```python
#!/usr/bin/env python3
# monitor.py - Custom monitoring script

from core_communication import get_core_comm
import time

while True:
    comm = get_core_comm()
    status = comm.get_system_status()
    
    print(f"\n{'='*50}")
    print(f"Connections: {status['connections']['healthy']}/{status['connections']['total']}")
    print(f"Commands Success Rate: {status['commands']['success_rate']}%")
    print(f"Ticks Received: {status['data']['total_ticks_received']}")
    
    time.sleep(60)  # Check every minute
```

---

## 🆘 Emergency Procedures

### EA Completely Unresponsive

```bash
# 1. Check if EA is running in MT5
# 2. Remove EA from chart
# 3. Re-add EA to chart
# 4. Check connection: curl http://localhost:9905/api/system/status
# 5. If still failing, restart MT5
```

### Server Not Responding

```bash
# 1. Check if server is running
ps aux | grep app_core

# 2. Check system resources
htop
df -h

# 3. Check logs
tail -100 logs/core_system.log

# 4. Restart server
sudo systemctl restart ngtrading

# 5. Verify all services
curl http://localhost:9900/api/status
curl http://localhost:9905/api/system/status
```

### Database Issues

```bash
# 1. Check PostgreSQL is running
sudo systemctl status postgresql

# 2. Check connections
psql -U ngtrading -d ngtrading -c "SELECT count(*) FROM pg_stat_activity;"

# 3. Kill long-running queries (if needed)
psql -U ngtrading -d ngtrading -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'active' AND query_start < now() - interval '5 minutes';
"

# 4. Restart PostgreSQL (last resort)
sudo systemctl restart postgresql
```

---

## 📈 Performance Baselines

**Record these values for your system:**

```
My System Baselines:
--------------------
Heartbeat Latency:        ___ ms
Command Creation:         ___ ms
Command Execution:        ___ ms
Trade Sync:              ___ ms
Tick Batch Processing:   ___ ms
Database Query (trades): ___ ms
Redis Latency:           ___ ms

Recorded on: ___________
Under load:  ___ connections, ___ ticks/s, ___ commands/min
```

---

**Keep this reference handy for daily operations!** 📋

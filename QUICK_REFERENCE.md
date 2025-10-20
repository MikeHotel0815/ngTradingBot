# ngTradingBot Audit - Quick Reference Card

## 🚀 Quick Start

### View Current Performance
```bash
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT direction, COUNT(*) as trades,
  ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as win_rate,
  ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'30 days' AND status='closed'
GROUP BY direction;"
```

### Run Monitoring Dashboard
```bash
python audit_monitor.py --once
```

### Check System Health
```bash
docker logs ngtradingbot_server --tail 50
```

---

## 🎯 Current Settings

| Parameter | Value | Location |
|-----------|-------|----------|
| BUY Signal Advantage | 2 | signal_generator.py:205 |
| BUY Confidence Penalty | 3.0% | signal_generator.py:360 |
| Max Signal Age | 300s (5min) | auto_trader.py:511 |
| Position Size Cap | 1.0 lot | auto_trader.py:445 |
| Circuit Breaker Threshold | 5 | auto_trader.py:1455 |
| Circuit Breaker Cooldown | 5 min | auto_trader.py:1456 |

---

## 📊 Current Performance (Last 30 Days)

```
Overall:    261 trades, 78.5% WR, €165.66 profit
BUY:        128 trades, 71.1% WR, €-21.71 (PF: 0.85) ⚠️
SELL:       133 trades, 85.7% WR, €187.37 (PF: 4.00) ✅
Gap:        14.6% (SELL better) → Bias is JUSTIFIED ✅
```

---

## ⚡ Common Commands

### Daily Checks
```bash
# 1. Performance snapshot
docker logs ngtradingbot_server | grep "Position Size" | tail -10

# 2. Signal staleness
docker logs ngtradingbot_server | grep "Signal too old" | wc -l

# 3. Circuit breaker status
docker logs ngtradingbot_server | grep "Circuit Breaker" | tail -5
```

### Weekly Analysis
```bash
# BUY vs SELL last 7 days
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT direction, COUNT(*),
  ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as wr,
  ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'7 days' AND status='closed'
GROUP BY direction;"
```

### Emergency
```bash
# Stop trading immediately
docker exec ngtradingbot_server pkill -f auto_trader

# Restart system
docker compose restart server workers

# Check logs for errors
docker logs ngtradingbot_server --tail 100 | grep -i error
```

---

## 🔧 To Adjust Settings

1. **Edit file:** `vim /projects/ngTradingBot/signal_generator.py`
2. **Change line 205:** `BUY_SIGNAL_ADVANTAGE = X`
3. **Change line 360:** `BUY_CONFIDENCE_PENALTY = Y.Y`
4. **Rebuild:** `docker compose build --no-cache`
5. **Restart:** `docker compose up -d`

---

## 📁 Important Files

| File | Purpose |
|------|---------|
| `AUDIT_COMPLETE_SUMMARY.md` | 📖 Complete overview |
| `AUDIT_FIXES_SUMMARY.md` | 🔧 What was fixed |
| `CONFIGURATION_TUNING_GUIDE.md` | ⚙️ How to optimize |
| `audit_monitor.py` | 👀 Real-time monitoring |
| `analyze_current_performance.py` | 📊 Performance analysis |
| `run_audit_backtests.py` | 🧪 Backtest comparison |

---

## ⚠️ Warning Signs

| Sign | Action |
|------|--------|
| All trades 0.01 lot | Check position sizer logs |
| Many "Signal too old" | Increase MAX_SIGNAL_AGE_SECONDS |
| Circuit breaker tripping | Check MT5 connection |
| BUY profit factor < 0.5 | Increase BUY_SIGNAL_ADVANTAGE |
| No trades for 24h | Check auto-trading enabled |

---

## ✅ Success Indicators

| Indicator | Target | Current |
|-----------|--------|---------|
| Overall Win Rate | > 60% | 78.5% ✅ |
| Profit Factor | > 1.5 | 2.76 ✅ |
| BUY/SELL Gap | < 15% | 14.6% ✅ |
| Position Sizing | Varied | ✅ (if not all 0.01) |
| Signal Freshness | < 2 min avg | Monitor |

---

## 📞 Quick Help

**Problem:** Can't find a file
```bash
cd /projects/ngTradingBot && ls -la *.md
```

**Problem:** Docker not running
```bash
docker compose up -d
```

**Problem:** Need to see all settings
```bash
grep -n "BUY_SIGNAL\|BUY_CONFIDENCE\|MAX_SIGNAL\|CIRCUIT_BREAKER" signal_generator.py auto_trader.py
```

---

**Last Updated:** 2025-10-20
**For detailed info:** See `AUDIT_COMPLETE_SUMMARY.md`

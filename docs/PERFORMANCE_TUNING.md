# Performance Tuning Guide
**Optimize EA ↔ Server Communication for Your Trading Style**

*Created: 2025-10-17*

---

## 🎯 Trading Style → Optimal Settings

### **High-Frequency Trading (HFT)**

**Use Case:**
- Scalping (seconds to minutes)
- News trading
- Arbitrage
- Quick entry/exit

**Recommended Settings:**
```mql5
input int HeartbeatInterval = 10;      // 10 seconds
// In OnTimer(): Poll every 500ms
```

**Performance:**
```
Command Max Latency:      500ms ✅
Disconnect Detection:     10s ✅
Network Load:            ~126 requests/min
Bandwidth:               ~1 KB/s (negligible)
```

**File:** `ServerConnector_Optimized.mq5`

---

### **Day Trading (Default)**

**Use Case:**
- Intraday trades (minutes to hours)
- Standard trading
- Most use cases

**Recommended Settings:**
```mql5
input int HeartbeatInterval = 30;      // 30 seconds
// In OnTimer(): Poll every 1000ms
```

**Performance:**
```
Command Max Latency:      1000ms ✅
Disconnect Detection:     30s ✅
Network Load:            ~62 requests/min
Bandwidth:               ~0.5 KB/s (minimal)
```

**File:** `ServerConnector.mq5` (current)

---

### **Swing Trading (Conservative)**

**Use Case:**
- Position trading (days to weeks)
- Low-frequency trades
- Minimal server load

**Recommended Settings:**
```mql5
input int HeartbeatInterval = 60;      // 60 seconds
// In OnTimer(): Poll every 2000ms
```

**Performance:**
```
Command Max Latency:      2000ms ⚠️
Disconnect Detection:     60s ⚠️
Network Load:            ~32 requests/min
Bandwidth:               ~0.25 KB/s (minimal)
```

---

## 📊 Settings Comparison Table

| Setting | HFT | Day Trading | Swing Trading |
|---------|-----|-------------|---------------|
| **Heartbeat** | 10s | 30s | 60s |
| **Command Poll** | 500ms | 1000ms | 2000ms |
| **Max Command Latency** | 500ms | 1000ms | 2000ms |
| **Disconnect Detection** | 10s | 30s | 60s |
| **Requests/min** | ~126 | ~62 | ~32 |
| **Network Load** | High | Normal | Low |
| **Recommended For** | Scalpers | Most traders | Long-term |

---

## 🔧 How to Change Settings

### **Method 1: EA Input Parameters (Easy)**

1. In MT5, right-click EA on chart → "Expert properties"
2. Go to "Inputs" tab
3. Change `HeartbeatInterval`:
   - HFT: `10`
   - Day Trading: `30` (default)
   - Swing: `60`
4. Click OK

### **Method 2: Edit Source Code (Advanced)**

#### For Heartbeat:

```mql5
// In ServerConnector.mq5, line ~17
input int HeartbeatInterval = 10;  // Change this value
```

#### For Command Polling:

```mql5
// In ServerConnector.mq5, OnTimer() function, line ~213
if(timerCallCount >= 5 && serverConnected)  // 500ms polling
// OR
if(timerCallCount >= 10 && serverConnected)  // 1000ms polling (default)
// OR
if(timerCallCount >= 20 && serverConnected)  // 2000ms polling (conservative)
```

Recompile after changes (F7 in MetaEditor).

---

## 🧪 Testing Different Settings

### **A/B Testing Script**

```python
# test_performance.py
from datetime import datetime
import time
import statistics

# Test command execution latency
def test_latency(iterations=100):
    latencies = []
    
    for i in range(iterations):
        start = time.time()
        
        # Create command
        cmd_id = send_open_trade_command(
            account_id=1,
            symbol='EURUSD',
            order_type='BUY',
            volume=0.01,
            sl=1.0850,
            tp=1.0950
        )
        
        # Wait for execution
        # (in real test, wait for EA response)
        
        end = time.time()
        latencies.append((end - start) * 1000)  # ms
    
    print(f"Average Latency: {statistics.mean(latencies):.1f}ms")
    print(f"Median Latency:  {statistics.median(latencies):.1f}ms")
    print(f"Max Latency:     {max(latencies):.1f}ms")
    print(f"Min Latency:     {min(latencies):.1f}ms")

test_latency()
```

---

## 📈 Expected Performance by Setting

### **HFT (10s heartbeat, 500ms poll)**

```
✅ Pros:
- Fast command execution (avg 250ms)
- Quick disconnect detection (10s)
- Rapid position updates
- Ideal for scalping

⚠️ Cons:
- Higher server load (2x)
- More network traffic
- Slightly higher CPU usage
```

### **Day Trading (30s heartbeat, 1000ms poll) - DEFAULT**

```
✅ Pros:
- Good balance of speed and efficiency
- Acceptable latency (avg 500ms)
- Reasonable disconnect detection (30s)
- Suitable for most trading styles

✅ Recommended for:
- 95% of users
- Standard trading
- Production environments
```

### **Swing Trading (60s heartbeat, 2000ms poll)**

```
✅ Pros:
- Lowest server load
- Minimal network traffic
- Very efficient

⚠️ Cons:
- Slower command execution (avg 1000ms)
- Slower disconnect detection (60s)
- Not suitable for fast-paced trading
```

---

## 🎚️ Advanced: Dynamic Settings

### **Concept: Adjust Settings Based on Market Conditions**

```mql5
// Dynamic settings based on volatility
int GetOptimalHeartbeatInterval() {
    // Check market volatility
    double atr = iATR(_Symbol, PERIOD_M1, 14);
    double avgATR = 50.0; // pips
    
    if(atr > avgATR * 1.5) {
        // High volatility → faster updates
        return 10;
    } else if(atr < avgATR * 0.5) {
        // Low volatility → slower updates
        return 60;
    } else {
        // Normal volatility
        return 30;
    }
}

// In OnTick()
void OnTick() {
    static datetime lastCheck = 0;
    
    // Update interval every 5 minutes
    if(TimeCurrent() - lastCheck > 300) {
        HeartbeatInterval = GetOptimalHeartbeatInterval();
        lastCheck = TimeCurrent();
    }
    
    // ... rest of code
}
```

---

## 📊 Server-Side Performance Limits

### **Single Server Capacity (estimated)**

```
Hardware: 4 vCPU, 8GB RAM, SSD

Maximum Capacity:
- Connections:      100+ EAs simultaneously ✅
- Heartbeats:       200/sec (12,000/min) ✅
- Command polls:    500/sec (30,000/min) ✅
- Tick ingestion:   10,000 ticks/sec ✅

Bottlenecks:
1. PostgreSQL writes (ticks)
2. Redis queue operations
3. Network bandwidth

Scaling Options:
- Horizontal: Add more servers (load balancer)
- Vertical: Bigger server
- Optimize: Batch operations, caching
```

---

## 🔍 Monitoring Performance

### **Check Command Latency**

```python
from core_communication import get_core_comm

comm = get_core_comm()
status = comm.get_system_status()

print(f"Avg Command Latency: {status['avg_command_latency_ms']}ms")

# Alert if too slow
if status['avg_command_latency_ms'] > 1000:
    print("⚠️ WARNING: High latency detected!")
```

### **Monitor Network Load**

```bash
# Server-side
# Count requests per minute
watch -n 60 'tail -1000 logs/access.log | wc -l'

# Check bandwidth
iftop -i eth0
```

### **Database Performance**

```sql
-- Check slow queries
SELECT
    query,
    mean_exec_time,
    calls
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- queries > 100ms
ORDER BY mean_exec_time DESC
LIMIT 10;
```

---

## 🎯 Recommendations by Use Case

### **Scenario 1: News Trading**

```mql5
// FASTEST settings
input int HeartbeatInterval = 5;      // 5 seconds!
// Poll every 250ms in OnTimer()

// Only during news events, switch back to default after
```

### **Scenario 2: Automated Grid/Martingale**

```mql5
// FAST settings
input int HeartbeatInterval = 10;     // 10 seconds
// Poll every 500ms

// Need fast execution for grid orders
```

### **Scenario 3: Signal Copier**

```mql5
// DEFAULT settings
input int HeartbeatInterval = 30;     // 30 seconds
// Poll every 1000ms

// Balance between speed and efficiency
```

### **Scenario 4: Portfolio Management**

```mql5
// CONSERVATIVE settings
input int HeartbeatInterval = 60;     // 60 seconds
// Poll every 2000ms

// Long-term positions, no rush
```

---

## 💡 Best Practices

### **1. Start with Default Settings**

```mql5
// Begin with:
input int HeartbeatInterval = 30;
// Poll interval: 1000ms

// Then optimize based on actual needs
```

### **2. Monitor and Adjust**

```python
# Check metrics daily
status = comm.get_system_status()

if status['avg_command_latency_ms'] > 1000:
    # Consider faster polling
    pass

if status['connections']['unhealthy'] > 0:
    # Consider faster heartbeat
    pass
```

### **3. Consider Server Load**

```
Number of EAs × Requests/min = Total Load

Example:
- 5 EAs with HFT settings:
  5 × 126 = 630 requests/min ✅ OK

- 20 EAs with HFT settings:
  20 × 126 = 2,520 requests/min ⚠️ High

- 20 EAs with default settings:
  20 × 62 = 1,240 requests/min ✅ OK
```

### **4. Test Before Production**

```bash
# Run performance test
python test_core_system.py --verbose

# Monitor for 24 hours
watch -n 60 'curl -s http://localhost:9905/api/system/status | jq ".commands.success_rate"'
```

---

## 🚀 Quick Settings Guide

| Your Trading Style | Heartbeat | Poll Interval | File to Use |
|-------------------|-----------|---------------|-------------|
| 🏃 Scalping/HFT | 10s | 500ms | `ServerConnector_Optimized.mq5` |
| 📈 Day Trading | 30s | 1000ms | `ServerConnector.mq5` (default) |
| 📊 Swing Trading | 60s | 2000ms | Edit source + recompile |
| 🎯 News Trading | 5-10s | 250-500ms | Edit source + recompile |

---

## 📞 Support

**Questions?**
- Check: `DESIGN_DECISIONS.md` for technical details
- Check: `CORE_SYSTEM_README.md` for full documentation
- Test: `python test_core_system.py` for performance baseline

---

**Remember:** The best settings depend on YOUR trading style and server capacity. Start with defaults, then optimize! 🎯

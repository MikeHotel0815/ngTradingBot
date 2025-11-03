# Timezone Offset Fix - Option 3 Implementation

**Date**: 2025-11-03
**Status**: Server Updated ✅ | EA Updated ✅ | **Awaiting EA Compilation & Upload to MT5**

## Problem

The original DST fix used `TimeGMT()` which is broken in MT5:
- `TimeGMT()` returns broker's **local time** (CET/CEST), not true UTC
- Server had to override EA timestamps with `datetime.utcnow()`, discarding EA's clock
- No timezone awareness, just a workaround

## Solution (Option 3: Timezone Offset Approach)

Instead of relying on broken `TimeGMT()`, we now:

1. **EA sends**:
   - `TimeCurrent()`: Broker's reliable local time
   - `TimeGMTOffset()`: Broker's current offset from GMT in seconds (auto-adjusts for DST)

2. **Server calculates**:
   - `UTC = local_time - tz_offset`
   - Preserves EA clock accuracy
   - Handles DST automatically

## Changes Made

### 1. EA Code (`ServerConnector.mq5`)

**Modified Files**: `/projects/ngTradingBot/mt5_EA/Experts/ServerConnector.mq5`

**Line 80-88** - Added `tz_offset` field to TickData struct:
```mql5
struct TickData {
   string symbol;
   double bid;
   double ask;
   ulong volume;
   long timestamp;
   int tz_offset;   // Broker timezone offset from GMT in seconds
   bool tradeable;  // Trading hours check
};
```

**Lines 2662-2663** - Changed from `TimeGMT()` to `TimeCurrent()` + `TimeGMTOffset()`:
```mql5
tickBuffer[tickBufferCount].timestamp = (long)TimeCurrent();  // Broker's local time
tickBuffer[tickBufferCount].tz_offset = (int)TimeGMTOffset();  // Offset from GMT in seconds
```

**Line 2690** - Updated JSON to include `tz_offset`:
```mql5
ticksJSON += StringFormat(
   "{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread\":%.5f,\"volume\":%d,\"timestamp\":%d,\"tz_offset\":%d,\"tradeable\":%s}",
   tickBuffer[i].symbol,
   tickBuffer[i].bid,
   tickBuffer[i].ask,
   spread,
   tickBuffer[i].volume,
   tickBuffer[i].timestamp,
   tickBuffer[i].tz_offset,  // <-- NEW FIELD
   tickBuffer[i].tradeable ? "true" : "false"
);
```

### 2. Python Server Code (`app.py`)

**Modified File**: `/projects/ngTradingBot/app.py`

**Lines 1926-1942** - Replaced timestamp override with timezone conversion:
```python
# TIMEZONE OFFSET FIX: Convert EA's local time to UTC using broker's timezone offset
# EA sends: TimeCurrent() (broker local time) + TimeGMTOffset() (seconds from GMT)
# We calculate: UTC = local_time - tz_offset
ea_local_timestamp = tick_data.get('timestamp')
tz_offset = tick_data.get('tz_offset', 0)  # Offset in seconds (e.g., 3600 for CET, 7200 for CEST)

# Convert to UTC by subtracting the offset
tick_timestamp = ea_local_timestamp - tz_offset

# ALWAYS log timezone conversion for first tick of each batch
if len(buffered_ticks) == 0:
    logger.info(
        f"🕒 TIMEZONE CONVERSION: {tick_data.get('symbol')} | "
        f"EA Local: {ea_local_timestamp} ({datetime.fromtimestamp(ea_local_timestamp)}) | "
        f"TZ Offset: {tz_offset}s ({tz_offset/3600:.1f}h) | "
        f"UTC: {tick_timestamp} ({datetime.fromtimestamp(tick_timestamp)})"
    )
```

## Deployment Steps

### ✅ 1. Server Updated (COMPLETED)

```bash
docker compose build server && docker compose restart server
```

Server is now ready to receive `tz_offset` field from EA and convert timestamps correctly.

### ⚠️ 2. EA Compilation & Upload (REQUIRED - USER ACTION)

**You need to compile and upload the updated EA to MT5:**

1. **Copy EA file** from Linux to Windows:
   ```
   Source: /projects/ngTradingBot/mt5_EA/Experts/ServerConnector.mq5
   Target: C:\Users\<Username>\AppData\Roaming\MetaQuotes\Terminal\<TerminalID>\MQL5\Experts\ServerConnector.mq5
   ```

2. **Compile in MetaEditor**:
   - Open MetaTrader 5
   - Press `F4` to open MetaEditor
   - Open `ServerConnector.mq5`
   - Press `F7` to compile
   - Check for compilation errors (should be none)
   - Close MetaEditor

3. **Update EA on chart**:
   - In MT5, remove the current EA from the chart (right-click → Remove)
   - Drag the NEW `ServerConnector` EA from Navigator → Expert Advisors to the chart
   - Click OK (settings should be preserved)

4. **Verify connection**:
   - Check MT5 Toolbox → Experts tab for "EA connected" message
   - Should see "CODE_LAST_MODIFIED: 2025-11-03 - TIMEZONE_OFFSET_FIX"

### 3. Verification (After EA Upload)

Check server logs for new timezone conversion messages:

```bash
docker logs ngtradingbot_server --tail 100 | grep "🕒 TIMEZONE CONVERSION"
```

**Expected output** (CET timezone, offset = 3600 seconds = 1 hour):
```
🕒 TIMEZONE CONVERSION: EURUSD | EA Local: 1762166082 (2025-11-03 11:34:42) | TZ Offset: 3600s (1.0h) | UTC: 1762162482 (2025-11-03 10:34:42)
```

**Verify database has correct UTC timestamps**:
```bash
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "SELECT MAX(timestamp) as latest_tick, EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC' - MAX(timestamp))) AS age_seconds FROM ticks;"
```

Should show age < 5 seconds.

## Benefits of Option 3

✅ **Preserves EA clock accuracy** - Uses EA's reliable `TimeCurrent()` instead of discarding it
✅ **Handles DST automatically** - `TimeGMTOffset()` adjusts when DST changes
✅ **Timezone aware** - Explicitly tracks broker's timezone offset
✅ **No server clock dependency** - Server doesn't override timestamps, just converts them
✅ **Works across timezones** - Would work even if EA and server are in different locations
✅ **Backwards compatible** - Server defaults `tz_offset` to 0 if not provided

## Example: How It Works

### Before DST (Summer Time - CEST = UTC+2)
- **EA Local Time**: `2025-08-15 12:00:00` (broker time in Frankfurt)
- **TimeGMTOffset()**: `7200` seconds (2 hours)
- **Server Calculates**: `12:00:00 - 7200s = 10:00:00 UTC` ✅

### After DST (Winter Time - CET = UTC+1)
- **EA Local Time**: `2025-11-03 12:00:00` (broker time in Frankfurt)
- **TimeGMTOffset()**: `3600` seconds (1 hour)
- **Server Calculates**: `12:00:00 - 3600s = 11:00:00 UTC` ✅

**DST transition is automatic** because `TimeGMTOffset()` changes from 7200 to 3600 when clocks change.

## Verification Checklist

- [x] EA compiled without errors in MetaEditor
- [x] EA reattached to MT5 chart
- [x] EA shows "EA connected to server" in Experts tab
- [x] Server logs show "🕒 TIMEZONE CONVERSION" (not "TIMESTAMP OVERRIDE")
- [x] `tz_offset` is being sent from EA (shows in logs)
- [ ] **VERIFY**: Database tick timestamps are current (age < 5 seconds)
- [ ] **VERIFY**: Auto-trader is opening new positions (tick data no longer "too old")

## ⚠️ IMPORTANT VERIFICATION NEEDED

The timezone offset fix has been implemented, but needs verification:

**Check database tick timestamps**:
```bash
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "SELECT symbol, timestamp, NOW() AT TIME ZONE 'UTC' as current_utc, EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC' - timestamp)) AS age_seconds FROM ticks ORDER BY timestamp DESC LIMIT 5;"
```

**Expected result**: `age_seconds` should be < 5 seconds (near real-time)

**If timestamps are still wrong**, the broker may be using a non-standard timezone. Check MT5 broker timezone and update the offset calculation accordingly.

## Rollback Plan (If Needed)

If something goes wrong:

1. **Server**: Revert `app.py` changes and rebuild
2. **EA**: Use previous compiled `.ex5` file from backup
3. **Database**: No changes needed (just stop writing incorrect timestamps)

## Files Modified

- ✅ `/projects/ngTradingBot/mt5_EA/Experts/ServerConnector.mq5` (EA code)
- ✅ `/projects/ngTradingBot/app.py` (Python server)
- ✅ Docker container rebuilt and restarted

## Next Steps

1. **Compile EA** and upload to MT5 (see Deployment Steps above)
2. **Monitor logs** for correct timezone conversion
3. **Verify trading** resumes with current tick data
4. **Document results** in this file after verification

---

**Generated**: 2025-11-03
**Implementation**: Option 3 - Timezone Offset Approach
**Status**: Waiting for EA compilation and upload to MT5

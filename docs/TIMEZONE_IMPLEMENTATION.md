# Timezone Implementation Documentation
# =====================================

## Overview

The ngTradingBot system now has comprehensive timezone management to ensure all timestamps are handled correctly across different contexts:

- **Server/Database**: Always UTC
- **Broker/MT5**: EET/EEST (Europe/Bucharest timezone = UTC+2 or UTC+3 with DST)
- **Trading Sessions**: Defined in UTC
- **Logging**: Shows both UTC and Broker time for clarity

## Key Components

### 1. timezone_manager.py (NEW)

Central timezone management module with global instance `tz`:

```python
from timezone_manager import tz

# Get current time
now_utc = tz.now_utc()        # Timezone-aware UTC
now_broker = tz.now_broker()  # Timezone-aware EET/EEST

# Convert between timezones
broker_time = tz.utc_to_broker(utc_datetime)
utc_time = tz.broker_to_utc(broker_datetime)

# Database operations (naive UTC for SQLAlchemy)
db_timestamp = tz.to_db(aware_datetime)
aware_datetime = tz.from_db(db_timestamp)

# Parse MT5 timestamps (sent in broker time)
utc_dt = tz.parse_broker_timestamp(unix_timestamp)

# Format for logging (shows both timezones)
log_msg = tz.format_for_log(dt, "Trade opened")
# Output: "Trade opened [UTC: 2025-10-17 10:30:00 | Broker: 2025-10-17 12:30:00 EET]"

# Get current session with timezone info
session_info = tz.get_current_session_info()
# Returns: {'session': 'LONDON', 'utc_time': '10:30:00', 'broker_time': '12:30:00 EET', ...}
```

### 2. Trading Sessions (UTC-based)

All sessions are defined in UTC:

| Session      | UTC Time        | London Time     | New York Time   |
|--------------|-----------------|-----------------|-----------------|
| ASIAN        | 00:00 - 08:00   | 00:00 - 08:00   | 19:00 - 03:00   |
| LONDON       | 08:00 - 16:00   | 08:00 - 16:00   | 03:00 - 11:00   |
| OVERLAP      | 13:00 - 16:00   | 13:00 - 16:00   | 08:00 - 11:00   |
| US           | 13:00 - 22:00   | 13:00 - 22:00   | 08:00 - 17:00   |
| AFTER_HOURS  | 22:00 - 00:00   | 22:00 - 00:00   | 17:00 - 19:00   |

### 3. MT5/Broker Communication

**Critical**: MT5 sends timestamps in **broker timezone (EET/EEST)**, not UTC!

```python
# When receiving timestamp from MT5:
unix_ts = data['timestamp']  # This is in EET/EEST!
utc_dt = tz.parse_broker_timestamp(unix_ts)  # Convert to UTC

# When sending to database:
db_dt = tz.to_db(utc_dt)  # Make naive UTC for SQLAlchemy

# When reading from database:
aware_dt = tz.from_db(db_dt)  # Make timezone-aware UTC
```

### 4. Logging Best Practices

Always show both UTC and Broker time in logs for debugging:

```python
from timezone_manager import tz, log_with_timezone

# Simple logging with timezone
log_with_timezone("Trade executed", dt=trade_time, level='info')

# Manual formatting
logger.info(tz.format_for_log(dt, "Signal received"))

# Session info logging
session_info = tz.get_current_session_info()
logger.info(f"Trading in {session_info['session']} session "
            f"[UTC: {session_info['utc_time']} | Broker: {session_info['broker_time']}]")
```

## Updated Modules

### session_volatility_analyzer.py
- Uses `tz.now_utc()` instead of `datetime.utcnow()`
- Session detection uses `tz.get_current_session_info()`
- Logging shows both UTC and broker time

### auto_trader.py
- Added timezone documentation to header
- Imports `timezone_manager`
- Uses timezone-aware timestamps

### unified_workers.py
- Market conditions worker shows timezone context
- Logs display UTC and broker time

### core_communication.py
- Heartbeat uses timezone-aware timestamps
- Proper conversion of broker timestamps from MT5

## Database Considerations

**IMPORTANT**: PostgreSQL stores timestamps as naive UTC (TIMESTAMP WITHOUT TIME ZONE)

```sql
-- Database timezone setting
SELECT current_setting('TIMEZONE');  -- Usually 'UTC'

-- All datetime columns store UTC without timezone info
-- Python code must:
-- 1. Convert broker timestamps to UTC before storing
-- 2. Add UTC timezone when reading from DB
-- 3. Convert to broker timezone only for display/logging
```

## Verification

Run the verification script:

```bash
cd /projects/ngTradingBot
python verify_timezone.py
```

This checks:
- ✅ Timezone manager imports correctly
- ✅ Current time functions work
- ✅ UTC <-> Broker conversions are accurate
- ✅ Logging format includes both timezones
- ✅ Session detection works
- ✅ Database helpers (to_db/from_db) work
- ✅ Broker timestamp parsing works
- ✅ Modules import timezone_manager

## Common Pitfalls

### ❌ WRONG:
```python
# Don't use datetime.utcnow() anymore
now = datetime.utcnow()  # Naive UTC, no timezone info

# Don't assume timestamps are UTC
timestamp = data['time']  # Could be broker time!
```

### ✅ CORRECT:
```python
# Use timezone manager
from timezone_manager import tz

now = tz.now_utc()  # Timezone-aware UTC

# Parse broker timestamps correctly
timestamp = tz.parse_broker_timestamp(data['time'])
```

## Testing

When testing timezone handling:

1. **Check different sessions**: Test during ASIAN, LONDON, and US sessions
2. **Verify conversions**: Ensure UTC <-> Broker conversions are correct
3. **Check logs**: Look for `[UTC: ... | Broker: ... EET]` format
4. **Database queries**: Verify timestamps are stored as UTC
5. **MT5 communication**: Confirm broker timestamps are converted

## Migration Notes

**No database migration required** - timestamps were already stored as UTC (naive).

The changes are purely in the Python code to:
- Make timezone handling explicit
- Convert broker timestamps correctly
- Provide clear logging
- Prevent timezone-related bugs

## Support

For timezone-related issues:

1. Check `verify_timezone.py` output
2. Look for timezone context in logs
3. Verify MT5 EA sends correct timestamps
4. Check session detection matches UTC time
5. Confirm database stores naive UTC

## Summary

✅ **All timestamps internally in UTC** (timezone-aware in Python)  
✅ **Broker timestamps converted from EET to UTC**  
✅ **Database stores naive UTC** (for SQLAlchemy compatibility)  
✅ **Logs show both UTC and Broker time**  
✅ **Sessions defined in UTC**  
✅ **Global `tz` instance for easy access**  
✅ **Verification script available**  

The system now knows **where** and **when** it's trading with complete timezone clarity! 🌍🕒

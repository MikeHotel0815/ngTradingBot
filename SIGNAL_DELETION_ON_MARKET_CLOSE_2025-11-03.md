# Signal Deletion on Market Close - Implementation

**Date**: 2025-11-03
**Status**: ✅ Implemented and Active
**Version**: v1.0

## Problem

User requested: **"Wenn die Märkte schliessen, können alle bestehenden Signale gelöscht werden."**

Translation: "When markets close, all existing signals can be deleted."

Previously, signals were only marked as `expired` when markets closed, keeping them in the database. This was unnecessary since expired signals from closed markets have no trading value.

## Solution

Modified signal handling to **DELETE signals** (not just expire) when markets close.

## Changes Made

### 1. Modified `signal_generator.py` - Method `_expire_active_signals()`

**File**: `/projects/ngTradingBot/signal_generator.py`
**Lines**: 922-963

```python
def _expire_active_signals(self, reason: str):
    """
    Expire or delete active signals for this symbol/timeframe when conditions no longer apply

    Args:
        reason: Reason for expiration (for logging)
               If reason is "market closed", signals will be DELETED instead of expired
    """
    db = ScopedSession()
    try:
        # Find active signals for this symbol/timeframe (signals are now global)
        active_signals = db.query(TradingSignal).filter(
            TradingSignal.symbol == self.symbol,
            TradingSignal.timeframe == self.timeframe,
            TradingSignal.status == 'active'
        ).all()

        if active_signals:
            # DELETE signals when market closes (don't keep them as expired)
            if reason == "market closed":
                for sig in active_signals:
                    logger.info(
                        f"🗑️  Signal #{sig.id} ({sig.symbol} {sig.timeframe} {sig.signal_type}) "
                        f"DELETED: {reason}"
                    )
                    db.delete(sig)
            else:
                # EXPIRE signals for other reasons (keep in DB for analysis)
                for sig in active_signals:
                    sig.status = 'expired'
                    logger.info(
                        f"Signal #{sig.id} ({sig.symbol} {sig.timeframe} {sig.signal_type}) "
                        f"expired: {reason}"
                    )

        db.commit()

    except Exception as e:
        logger.error(f"Error expiring/deleting active signals: {e}")
        db.rollback()
    finally:
        db.close()
```

**Key Changes:**
- Added conditional logic: `if reason == "market closed"`
- Signals with "market closed" reason → **DELETED** (`db.delete(sig)`)
- Other reasons (low confidence, pattern changed, etc.) → **EXPIRED** (kept for analysis)
- Added 🗑️ emoji to deletion logs for visibility

### 2. Modified `signal_generator.py` - Static Method `expire_old_signals()`

**File**: `/projects/ngTradingBot/signal_generator.py`
**Lines**: 1011-1068

```python
@staticmethod
def expire_old_signals():
    """
    Expire old signals (run periodically)
    DELETE signals for symbols outside trading hours (market closed)
    """
    from models import Tick
    from market_hours import is_market_open
    db = ScopedSession()
    try:
        now = datetime.utcnow()

        # Expire signals that passed their expiry time (keep in DB for analysis)
        expired_count = db.query(TradingSignal).filter(
            TradingSignal.status == 'active',
            TradingSignal.expires_at <= now
        ).update({'status': 'expired'})

        # DELETE signals for symbols outside trading hours (market closed)
        active_signals = db.query(TradingSignal).filter(
            TradingSignal.status == 'active'
        ).all()

        deleted_market_closed = 0
        for signal in active_signals:
            # Check if market is open using market_hours configuration
            if not is_market_open(signal.symbol, now):
                logger.info(
                    f"🗑️  Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                    f"DELETED: market closed"
                )
                db.delete(signal)
                deleted_market_closed += 1
            else:
                # Fallback: Check if symbol is tradeable via tick data
                latest_tick = db.query(Tick).filter_by(
                    symbol=signal.symbol
                ).order_by(Tick.timestamp.desc()).first()

                if latest_tick and not latest_tick.tradeable:
                    logger.info(
                        f"🗑️  Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                        f"DELETED: not tradeable (tick flag)"
                    )
                    db.delete(signal)
                    deleted_market_closed += 1

        db.commit()

        if expired_count > 0:
            logger.info(f"Expired {expired_count} old signals")

        if deleted_market_closed > 0:
            logger.info(f"🗑️  Deleted {deleted_market_closed} signals (market closed)")

    except Exception as e:
        logger.error(f"Error expiring signals: {e}")
        db.rollback()
    finally:
        db.close()
```

**Key Changes:**
- Added `from market_hours import is_market_open` import
- Changed logic to **DELETE** signals when market is closed (instead of expiring)
- Uses two checks:
  1. **Primary**: `is_market_open()` from market_hours.py (static configuration)
  2. **Fallback**: `tick.tradeable` flag from MT5 EA (real-time data)
- Renamed variable: `non_tradeable_expired` → `deleted_market_closed`
- Updated log message to show deletion count

## Behavior

### When Market is OPEN ✅
- Signals are **generated** normally
- Signals remain **active** in database
- Auto-trader can **execute trades** based on signals

### When Market CLOSES 🗑️
- Signals are **DELETED** from database (not expired)
- Deletion happens automatically every 10 seconds (via `signal_worker.py`)
- Log shows: `🗑️ Signal #123 (EURUSD H1 BUY) DELETED: market closed`

### When Market RE-OPENS 🔄
- Fresh signals are **generated** based on new market conditions
- No old/stale signals from previous session
- Clean slate for new trading opportunities

## Trigger Points

Signal deletion happens in 3 places:

### 1. During Signal Generation (Real-time)
**File**: `signal_generator.py:79-84`

```python
# ✅ Check if market is open for this symbol
from market_hours import is_market_open
if not is_market_open(self.symbol):
    logger.debug(f"Market closed for {self.symbol}, skipping signal generation")
    self._expire_active_signals("market closed")  # ← Calls deletion
    return None
```

**When**: Every time a signal generation attempt is made (every 10s)
**Action**: Deletes signals for that specific symbol/timeframe

### 2. Periodic Cleanup (Background Worker)
**File**: `signal_worker.py:81`

```python
# Expire old signals
SignalGenerator.expire_old_signals()  # ← Calls deletion
```

**When**: Every 10 seconds (signal worker interval)
**Action**: Checks ALL active signals and deletes those for closed markets

### 3. Signal Worker Pre-Filter
**File**: `signal_worker.py:190-193`

```python
# Skip signal generation for non-tradeable symbols
if not tick_tradeable:
    logger.debug(f"Skipping signal generation for {symbol_name} (outside trading hours)")
    continue
```

**When**: Before signal generation starts
**Action**: Prevents signal creation for closed markets (no deletion needed)

## Market Hours Configuration

Deletion uses market hours from `market_hours.py`:

**Forex (EURUSD, GBPUSD, etc.)**:
- Open: Sunday 22:00 UTC → Friday 21:00 UTC
- Closed: Friday 21:00 UTC → Sunday 22:00 UTC

**Commodities (XAUUSD, XAGUSD)**:
- Same as Forex hours

**Indices (DE40.c, US500.c)**:
- Same as Forex hours

**Crypto (BTCUSD, ETHUSD)**:
- 24/7 (never closed)

## Verification

### Check Current Signals:
```bash
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c \
  "SELECT symbol, timeframe, signal_type, status, created_at FROM trading_signals ORDER BY created_at DESC LIMIT 10;"
```

### Monitor Deletion Logs (when market closes):
```bash
docker logs ngtradingbot_server -f | grep "🗑️.*DELETED"
```

**Expected output on Friday 21:00 UTC (Forex close)**:
```
🗑️  Signal #12345 (EURUSD H1 BUY) DELETED: market closed
🗑️  Signal #12346 (GBPUSD H4 SELL) DELETED: market closed
🗑️  Signal #12347 (XAUUSD H1 BUY) DELETED: market closed
🗑️  Deleted 15 signals (market closed)
```

### Test with Market Hours:
```python
from datetime import datetime
from market_hours import is_market_open

# Saturday (market closed)
saturday = datetime(2025, 11, 1, 14, 0)
print(f"EURUSD open on Saturday: {is_market_open('EURUSD', saturday)}")  # False
print(f"BTCUSD open on Saturday: {is_market_open('BTCUSD', saturday)}")  # True (24/7)
```

## Benefits

✅ **Database Cleanup**: No accumulation of stale signals
✅ **Clean Slate**: Fresh signals when market reopens
✅ **Performance**: Smaller signals table, faster queries
✅ **No Confusion**: Auto-trader never sees old signals from closed markets
✅ **Automatic**: No manual intervention needed

## Rollback Plan

If needed, revert to old behavior (expire instead of delete):

```python
# In signal_generator.py:922, change:
if reason == "market closed":
    db.delete(sig)  # DELETE
# Back to:
sig.status = 'expired'  # EXPIRE
```

Then restart server:
```bash
docker restart ngtradingbot_server
```

## Files Modified

- ✅ `/projects/ngTradingBot/signal_generator.py` (Lines 922-963, 1011-1068)
- ✅ Server restarted: `docker restart ngtradingbot_server` (2025-11-03 14:20:36 UTC)

## Status

**✅ ACTIVE** - Implementation complete, server restarted, changes live

**Next Market Close**: Friday 2025-11-07 21:00 UTC (Forex markets)
**Verification**: Monitor logs at that time for deletion messages

---

**Generated**: 2025-11-03 14:24 UTC
**Implementation**: Signal Deletion on Market Close
**Requestor**: User requirement - "Wenn die Märkte schliessen, können alle bestehenden Signale gelöscht werden."

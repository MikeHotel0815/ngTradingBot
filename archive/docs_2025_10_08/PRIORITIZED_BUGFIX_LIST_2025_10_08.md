# 🔧 Priorisierte Bugfix-Liste - ngTradingBot
**Datum:** 8. Oktober 2025  
**Basierend auf:** Complete System Audit

---

## 🔴 CRITICAL - Sofort beheben (Heute)

### BUG-001: Bare Except Statements (Silent Failures)
**Priority:** 🔴 CRITICAL  
**Effort:** 2 Stunden  
**Impact:** HIGH - Trades können unbemerkt scheitern

**Betroffene Files:**
- `app.py:2829`
- `signal_generator.py:357`
- `smart_tp_sl.py:114,127,318`
- `signal_worker.py:247`
- `pattern_recognition.py:268,281`

**Fix:**
```python
# Ersetze alle:
try:
    # operation
except:
    pass

# Mit:
try:
    # operation
except (SpecificException1, SpecificException2) as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    # Handle gracefully
```

**Test:**
- Trigger jede Exception-Path
- Verify Logging funktioniert
- Verify Graceful Degradation

---

### BUG-002: Fehlende Max Open Positions Limit
**Priority:** 🔴 CRITICAL  
**Effort:** 2 Stunden  
**Impact:** HIGH - Überexposition, Margin Call Risk

**File:** `auto_trader.py`

**Fix:**
```python
class AutoTrader:
    def __init__(self):
        # ...
        self.max_open_positions = 10  # Configurable
        
    def check_position_limits(self, db, account_id):
        """Check if max position limits are reached"""
        open_count = db.query(Trade).filter(
            Trade.account_id == account_id,
            Trade.status == 'open'
        ).count()
        
        if open_count >= self.max_open_positions:
            logger.warning(f"⚠️ Max positions reached: {open_count}/{self.max_open_positions}")
            return {
                'allowed': False,
                'reason': f'Max open positions limit ({self.max_open_positions})'
            }
        
        return {'allowed': True}
    
    def should_execute_signal(self, signal, db):
        # ... existing checks ...
        
        # NEW: Check position limits
        position_check = self.check_position_limits(db, signal.account_id)
        if not position_check['allowed']:
            return position_check
```

**Integration:**
- Add check in `should_execute_signal()`
- Add to AI Decision Log
- Add config option in Settings

**Test:**
- Open 10 positions
- Verify 11th is rejected
- Verify log entry created

---

### BUG-003: SQL Injection Risiko
**Priority:** 🔴 CRITICAL  
**Effort:** 6 Stunden  
**Impact:** CRITICAL - Security Breach möglich

**File:** `app.py` (mehrere Endpoints)

**Betroffene Endpoints:**
```python
# Beispiel unsicherer Code:
@app.route('/api/trades')
def get_trades():
    symbol = request.args.get('symbol')
    query = f"SELECT * FROM trades WHERE symbol = '{symbol}'"  # UNSAFE!
```

**Fix - Alle Queries parametrisieren:**
```python
# VORHER (Unsicher):
query = f"SELECT * FROM trades WHERE symbol = '{symbol}'"
result = db.execute(query)

# NACHHER (Sicher):
query = "SELECT * FROM trades WHERE symbol = :symbol"
result = db.execute(query, {'symbol': symbol})

# Oder mit SQLAlchemy ORM (bevorzugt):
trades = db.query(Trade).filter(Trade.symbol == symbol).all()
```

**Files zu prüfen:**
- `app.py` - alle API Endpoints
- Filter/Sort Parameters
- Search Queries

**Test:**
- SQL Injection Tests:
  - `symbol='; DROP TABLE trades; --`
  - `symbol=' OR '1'='1`
  - `symbol=UNION SELECT * FROM accounts`
- Verify alle blockiert werden

---

### BUG-004: Trade Execution Confirmation fehlt
**Priority:** 🔴 CRITICAL  
**Effort:** 4 Stunden  
**Impact:** HIGH - Trades scheitern unbemerkt

**File:** `auto_trader.py`

**Problem:**
```python
# Command wird in Redis Queue gepusht
self.redis.push_command(account_id, command_data)
# Aber: Keine Bestätigung dass MT5 ausgeführt hat!
```

**Fix - Execution Verification:**
```python
def check_pending_commands(self, db):
    """
    Verify pending commands were executed by MT5
    Retry failed commands, alert on persistent failures
    """
    now = datetime.utcnow()
    expired_commands = []
    
    for cmd_id, cmd_info in list(self.pending_commands.items()):
        # Check if command timed out (5 min)
        if now > cmd_info['timeout_at']:
            expired_commands.append(cmd_id)
            
            # Check if trade was actually created
            trade = db.query(Trade).filter(
                Trade.signal_id == cmd_info['signal_id']
            ).first()
            
            if not trade:
                # Command failed - retry or alert
                logger.error(f"❌ Command {cmd_id} failed - no trade created!")
                
                # Log to AI Decision Log
                from ai_decision_log import log_circuit_breaker
                self.failed_command_count += 1
                
                if self.failed_command_count >= 3:
                    # Circuit breaker!
                    self.enabled = False
                    log_circuit_breaker(
                        account_id=cmd_info['account_id'],
                        failed_count=self.failed_command_count,
                        reason="3 consecutive command failures",
                        details={'failed_commands': expired_commands}
                    )
            else:
                logger.info(f"✅ Command {cmd_id} executed successfully")
                self.failed_command_count = 0  # Reset on success
            
            # Remove from pending
            del self.pending_commands[cmd_id]
```

**Test:**
- Simuliere MT5 Disconnect
- Verify Commands timeout
- Verify Circuit Breaker triggers
- Verify Alert erstellt wird

---

## 🟠 HIGH - Bald beheben (Diese Woche)

### BUG-005: Race Conditions in Singleton Creation
**Priority:** 🟠 HIGH  
**Effort:** 1 Stunde  
**Impact:** MEDIUM - Kann zu State-Inkonsistenzen führen

**Files:**
- `auto_trader.py:1109`
- `shadow_trading_engine.py`
- `trailing_stop_manager.py`

**Fix:**
```python
import threading

_auto_trader = None
_lock = threading.Lock()

def get_auto_trader():
    """Thread-safe singleton creation"""
    global _auto_trader
    if _auto_trader is None:
        with _lock:
            # Double-check locking pattern
            if _auto_trader is None:
                _auto_trader = AutoTrader()
    return _auto_trader
```

**Apply to all Singletons:**
- AutoTrader
- ShadowTradingEngine
- TrailingStopManager
- RedisClient
- Decision Logger

---

### BUG-006: Indicator Cache Synchronisation
**Priority:** 🟠 HIGH  
**Effort:** 4 Stunden  
**Impact:** MEDIUM - Inkonsistente Signals möglich

**File:** `technical_indicators.py`

**Problem:**
```python
# Different indicators have different cache TTLs
rsi = self.calculate_rsi()  # Cache: 15s
macd = self.calculate_macd()  # Cache: 300s
# RSI ist frischer als MACD - Conflict!
```

**Fix - Synchronized Calculation:**
```python
class TechnicalIndicators:
    def calculate_all_indicators(self) -> Dict:
        """
        Calculate all indicators from same OHLC snapshot
        Ensures consistency across all indicators
        """
        # Get OHLC once
        df = self._get_ohlc_data(limit=200)
        if df is None:
            return None
        
        timestamp = datetime.utcnow().isoformat()
        indicators = {}
        
        # Calculate all from same DataFrame
        indicators['rsi'] = self._calc_rsi_from_df(df)
        indicators['macd'] = self._calc_macd_from_df(df)
        indicators['ema'] = self._calc_ema_from_df(df)
        indicators['bb'] = self._calc_bb_from_df(df)
        indicators['atr'] = self._calc_atr_from_df(df)
        # ... etc
        
        # Add consistent timestamp to all
        for name, data in indicators.items():
            data['calculated_at'] = timestamp
            self._set_cache(name, data)
        
        return indicators
    
    def _calc_rsi_from_df(self, df: pd.DataFrame) -> Dict:
        """Calculate RSI from existing DataFrame"""
        close = df['close'].values
        rsi = talib.RSI(close, timeperiod=14)
        # ... rest of calculation
```

**Update Signal Generator:**
```python
# In signal_generator.py
indicators_data = self.indicators.calculate_all_indicators()
# Use pre-calculated indicators instead of individual calls
```

---

### BUG-007: News Filter nicht integriert
**Priority:** 🟠 HIGH  
**Effort:** 2 Stunden  
**Impact:** MEDIUM - Trading während High-Impact News

**Files:**
- `news_filter.py` (existiert)
- `auto_trader.py` (Integration fehlt)

**Fix:**
```python
# In auto_trader.py
def should_execute_signal(self, signal, db):
    # ... existing checks ...
    
    # NEW: News filter check
    from news_filter import get_news_filter
    news_filter = get_news_filter()
    
    news_check = news_filter.check_upcoming_news(
        signal.symbol,
        minutes_ahead=15
    )
    
    if not news_check['safe_to_trade']:
        logger.warning(f"📰 News pause: {news_check['reason']}")
        
        # Log to AI Decision Log
        from ai_decision_log import log_news_pause
        log_news_pause(
            account_id=signal.account_id,
            reason=news_check['reason'],
            details={
                'symbol': signal.symbol,
                'news_events': news_check.get('events', []),
                'resume_at': news_check.get('resume_at')
            }
        )
        
        return {
            'execute': False,
            'reason': news_check['reason']
        }
```

---

### BUG-008: Missing Unit Tests
**Priority:** 🟠 HIGH  
**Effort:** 20 Stunden (initial setup)  
**Impact:** HIGH - Undetected Regressions

**Test Structure:**
```
tests/
├── unit/
│   ├── test_auto_trader.py
│   ├── test_technical_indicators.py
│   ├── test_pattern_recognition.py
│   ├── test_signal_generator.py
│   ├── test_risk_management.py
│   └── test_indicator_scorer.py
├── integration/
│   ├── test_signal_to_trade_flow.py
│   ├── test_circuit_breakers.py
│   └── test_shadow_trading.py
└── fixtures/
    ├── mock_ohlc_data.py
    └── mock_mt5_connection.py
```

**Priority Tests:**
1. Circuit Breaker Activation
2. TP/SL Validation
3. Position Size Calculation
4. Spread Validation
5. Signal Confidence Calculation

**Example Test:**
```python
# tests/unit/test_auto_trader.py
import pytest
from auto_trader import AutoTrader

def test_circuit_breaker_daily_loss():
    """Test circuit breaker triggers on 5% daily loss"""
    trader = AutoTrader()
    
    # Mock account with 5% loss
    mock_account = MockAccount(
        balance=10000,
        profit_today=-500  # -5%
    )
    
    # Circuit breaker should trip
    result = trader.check_circuit_breaker(db, mock_account.id)
    assert result == False
    assert trader.circuit_breaker_tripped == True
    assert "5%" in trader.circuit_breaker_reason
```

---

## 🟡 MEDIUM - Nächste Woche

### BUG-009: Data Validation fehlt
**Priority:** 🟡 MEDIUM  
**Effort:** 6 Stunden  
**Impact:** MEDIUM - Bad Data → Bad Trades

**Files:**
- `technical_indicators.py`
- `pattern_recognition.py`
- `signal_generator.py`

**Fix - OHLC Validation:**
```python
def _validate_ohlc_data(self, df: pd.DataFrame) -> bool:
    """
    Validate OHLC data quality
    Returns True if data is valid
    """
    if df is None or len(df) == 0:
        logger.error("OHLC data is empty")
        return False
    
    # Check for required columns
    required = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required):
        logger.error(f"Missing OHLC columns: {set(required) - set(df.columns)}")
        return False
    
    # Check for NaN/Inf
    if df[['open', 'high', 'low', 'close']].isnull().any().any():
        logger.error("OHLC data contains NaN values")
        return False
    
    if np.isinf(df[['open', 'high', 'low', 'close']]).any().any():
        logger.error("OHLC data contains Inf values")
        return False
    
    # Check OHLC relationship: high >= low, high >= open/close, low <= open/close
    invalid = (
        (df['high'] < df['low']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close']) |
        (df['low'] > df['open']) |
        (df['low'] > df['close'])
    )
    
    if invalid.any():
        logger.error(f"OHLC data has invalid relationships: {invalid.sum()} candles")
        return False
    
    # Check for zero prices
    if (df[['open', 'high', 'low', 'close']] <= 0).any().any():
        logger.error("OHLC data contains zero or negative prices")
        return False
    
    return True

def _get_ohlc_data(self, limit: int = 200) -> Optional[pd.DataFrame]:
    """Get and validate OHLC data"""
    # ... existing code ...
    
    # NEW: Validate before returning
    if not self._validate_ohlc_data(df):
        return None
    
    return df
```

---

### BUG-010: Pattern Redundancy
**Priority:** 🟡 MEDIUM  
**Effort:** 4 Stunden  
**Impact:** MEDIUM - False High Confidence

**File:** `pattern_recognition.py`

**Fix - Pattern Clustering:**
```python
class PatternRecognizer:
    # Define pattern groups (similar patterns)
    PATTERN_GROUPS = {
        'bullish_continuation': [
            'Three White Soldiers',
            'Advance Block',
            'Rising Three Methods'
        ],
        'bearish_continuation': [
            'Three Black Crows',
            'Falling Three Methods'
        ],
        'bullish_reversal': [
            'Hammer',
            'Inverted Hammer',
            'Bullish Engulfing',
            'Morning Star'
        ],
        # ... etc
    }
    
    def _deduplicate_patterns(self, patterns: List[Dict]) -> List[Dict]:
        """
        Remove redundant patterns from same group
        Keep only the highest reliability pattern per group
        """
        grouped = {}
        
        for pattern in patterns:
            # Find which group this pattern belongs to
            group = self._find_pattern_group(pattern['name'])
            
            if group not in grouped:
                grouped[group] = pattern
            else:
                # Keep pattern with higher reliability
                if pattern['reliability'] > grouped[group]['reliability']:
                    grouped[group] = pattern
        
        return list(grouped.values())
```

---

### BUG-011: Indicator Scorer Overfitting
**Priority:** 🟡 MEDIUM  
**Effort:** 3 Stunden  
**Impact:** MEDIUM - Unstable Performance

**File:** `indicator_scorer.py`

**Fix - Minimum Sample Size:**
```python
class IndicatorScorer:
    MINIMUM_SAMPLE_SIZE = 20  # Require 20 trades before adjusting weight
    
    def get_indicator_weight(self, indicator_name: str) -> float:
        """
        Get weight with minimum sample size requirement
        """
        db = ScopedSession()
        try:
            score_obj = IndicatorScore.get_or_create(
                db, self.account_id, self.symbol, self.timeframe, indicator_name
            )
            
            # NEW: Check sample size
            if score_obj.total_signals < self.MINIMUM_SAMPLE_SIZE:
                # Not enough data - use neutral weight
                logger.debug(
                    f"Indicator {indicator_name}: Insufficient data "
                    f"({score_obj.total_signals}/{self.MINIMUM_SAMPLE_SIZE}) - "
                    f"using neutral weight 0.65"
                )
                return 0.65  # Slightly above minimum
            
            # Enough data - use adaptive weight
            weight = 0.3 + (float(score_obj.score) / 100) * 0.7
            
            return weight
            
        finally:
            db.close()
    
    def update_score(self, indicator_name: str, was_profitable: bool, profit: float):
        """
        Update score with outlier protection
        """
        db = ScopedSession()
        try:
            score_obj = IndicatorScore.get_or_create(...)
            
            # NEW: Cap impact of single trade
            MAX_SINGLE_IMPACT = 5.0  # Max 5% score change per trade
            
            old_score = score_obj.score
            score_obj.update_score(was_profitable, profit)
            
            # Limit score change
            score_change = abs(score_obj.score - old_score)
            if score_change > MAX_SINGLE_IMPACT:
                # Clamp change
                if score_obj.score > old_score:
                    score_obj.score = old_score + MAX_SINGLE_IMPACT
                else:
                    score_obj.score = old_score - MAX_SINGLE_IMPACT
                
                logger.warning(
                    f"Score change capped: {indicator_name} "
                    f"change limited to {MAX_SINGLE_IMPACT}%"
                )
            
            db.commit()
            
        finally:
            db.close()
```

---

### BUG-012: Code Duplication - OHLC Loading
**Priority:** 🟡 MEDIUM  
**Effort:** 4 Stunden  
**Impact:** LOW - Maintenance Overhead

**Create:** `data_utils.py`

**Fix - Zentrale Utility:**
```python
# data_utils.py
"""
Centralized data loading and caching utilities
"""

import pandas as pd
from typing import Optional
from database import ScopedSession
from models import OHLCData
import logging

logger = logging.getLogger(__name__)

class DataLoader:
    """Centralized OHLC data loader with caching"""
    
    _cache = {}  # In-memory cache
    
    @classmethod
    def get_ohlc_data(
        cls,
        account_id: int,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        use_cache: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLC data with optional caching
        Validates data quality before returning
        """
        cache_key = f"{account_id}_{symbol}_{timeframe}_{limit}"
        
        # Check cache
        if use_cache and cache_key in cls._cache:
            cached = cls._cache[cache_key]
            # Check if cache is fresh (< 30 seconds old)
            if (datetime.utcnow() - cached['timestamp']).seconds < 30:
                return cached['data']
        
        # Load from database
        db = ScopedSession()
        try:
            ohlc = db.query(OHLCData).filter_by(
                account_id=account_id,
                symbol=symbol,
                timeframe=timeframe
            ).order_by(OHLCData.timestamp.desc()).limit(limit).all()
            
            if not ohlc:
                logger.warning(f"No OHLC data: {symbol} {timeframe}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame([{
                'timestamp': o.timestamp,
                'open': float(o.open),
                'high': float(o.high),
                'low': float(o.low),
                'close': float(o.close),
                'volume': float(o.volume) if o.volume else 0
            } for o in reversed(ohlc)])
            
            # Validate
            if not cls._validate_ohlc(df):
                return None
            
            # Cache
            if use_cache:
                cls._cache[cache_key] = {
                    'data': df,
                    'timestamp': datetime.utcnow()
                }
            
            return df
            
        finally:
            db.close()
    
    @staticmethod
    def _validate_ohlc(df: pd.DataFrame) -> bool:
        """Validate OHLC data quality"""
        # ... validation code from BUG-009 ...
```

**Update all modules to use DataLoader:**
```python
# In technical_indicators.py, pattern_recognition.py, etc:
from data_utils import DataLoader

def _get_ohlc_data(self, limit: int = 200):
    return DataLoader.get_ohlc_data(
        self.account_id,
        self.symbol,
        self.timeframe,
        limit=limit
    )
```

---

## 🟢 LOW - Nice to Have (Nächsten Monat)

### BUG-013: Magic Numbers → Constants
**Priority:** 🟢 LOW  
**Effort:** 2 Stunden  

**Create:** `constants.py`

```python
# constants.py
"""Trading system constants"""

# Risk Management
MAX_DAILY_LOSS_PERCENT = 5.0
MAX_TOTAL_DRAWDOWN_PERCENT = 20.0
MAX_OPEN_POSITIONS = 10
MAX_CORRELATED_POSITIONS = 2

# Position Sizing
MIN_RISK_PERCENT = 0.5
MAX_RISK_PERCENT = 2.0

# TP/SL
MIN_RISK_REWARD_RATIO = 1.2
MIN_SL_DISTANCE_PERCENT = 0.05
MAX_TP_DISTANCE_PERCENT = 5.0

# Spread
MAX_SPREAD_MULTIPLIER = 3.0
MAJOR_PAIRS_MAX_SPREAD = 0.0003  # 3 pips
MINOR_PAIRS_MAX_SPREAD = 0.0005  # 5 pips

# Cache
INDICATOR_CACHE_TTL = 15  # seconds
PATTERN_CACHE_TTL = 60
OHLC_CACHE_TTL = 30

# Signals
MIN_SIGNAL_CONFIDENCE = 40
MIN_AUTOTRADE_CONFIDENCE = 60

# Timeouts
TICK_MAX_AGE_SECONDS = 60
COMMAND_TIMEOUT_MINUTES = 5
```

---

## 📊 IMPLEMENTATION TIMELINE

### Week 1 (Jetzt):
- [ ] BUG-001: Bare Except Statements (2h)
- [ ] BUG-002: Max Position Limits (2h)
- [ ] BUG-004: Trade Confirmation (4h)

**Total: 8 Stunden**

### Week 2:
- [ ] BUG-003: SQL Injection (6h)
- [ ] BUG-005: Race Conditions (1h)
- [ ] BUG-007: News Filter (2h)

**Total: 9 Stunden**

### Week 3:
- [ ] BUG-006: Indicator Sync (4h)
- [ ] BUG-008: Unit Tests Setup (8h)

**Total: 12 Stunden**

### Week 4:
- [ ] BUG-009: Data Validation (6h)
- [ ] BUG-010: Pattern Dedup (4h)
- [ ] BUG-011: Scorer Overfitting (3h)

**Total: 13 Stunden**

### Month 2:
- [ ] BUG-012: Code Refactoring (4h)
- [ ] BUG-013: Constants (2h)
- [ ] Additional Unit Tests (12h)

**Total: 18 Stunden**

---

## 🎯 SUCCESS METRICS

Nach Fixes sollten folgende Metriken erreicht werden:

| Metrik | Vorher | Ziel |
|--------|--------|------|
| Bare Except Count | 8 | 0 |
| SQL Injection Vulnerabilities | ? | 0 |
| Code Coverage | ~0% | >60% |
| Failed Trade Rate | ~5% | <1% |
| Silent Failures | Unknown | 0 |
| System Stability | 85% | 99% |

---

**Status:** 📋 Ready for Implementation  
**Last Updated:** 8. Oktober 2025

"""
Database models for ngTradingBot
SQLAlchemy ORM models for PostgreSQL
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Boolean,
    Numeric, Text, ForeignKey, Index, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import secrets

Base = declarative_base()


class Account(Base):
    """MT5 Account information"""
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True)
    mt5_account_number = Column(BigInteger, unique=True, nullable=False, index=True)
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    broker = Column(String(100))
    balance = Column(Numeric(15, 2), default=0.0)
    equity = Column(Numeric(15, 2), default=0.0)
    margin = Column(Numeric(15, 2), default=0.0)
    free_margin = Column(Numeric(15, 2), default=0.0)
    profit_today = Column(Numeric(15, 2), default=0.0)
    profit_week = Column(Numeric(15, 2), default=0.0)
    profit_month = Column(Numeric(15, 2), default=0.0)
    profit_year = Column(Numeric(15, 2), default=0.0)
    deposits_today = Column(Numeric(15, 2), default=0.0)
    deposits_week = Column(Numeric(15, 2), default=0.0)
    deposits_month = Column(Numeric(15, 2), default=0.0)
    deposits_year = Column(Numeric(15, 2), default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_heartbeat = Column(DateTime)

    # Relationships
    subscribed_symbols = relationship("SubscribedSymbol", back_populates="account", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="account", cascade="all, delete-orphan")
    commands = relationship("Command", back_populates="account", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="account", cascade="all, delete-orphan")

    @staticmethod
    def generate_api_key():
        """Generate a secure API key"""
        return secrets.token_urlsafe(48)

    def __repr__(self):
        return f"<Account(mt5={self.mt5_account_number}, broker={self.broker})>"


class BrokerSymbol(Base):
    """Available symbols at broker (sent by EA on connect) - GLOBAL

    NOTE: BrokerSymbols are now GLOBAL (no account_id). Broker symbol specs are the same for all.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'broker_symbols'
    __table_args__ = tuple()

    id = Column(Integer, primary_key=True)
    # account_id removed - broker symbols are global (database migration completed)
    symbol = Column(String(20), nullable=False, unique=True)
    description = Column(String(100))

    # Trading parameters from MT5
    volume_min = Column(Numeric(10, 2))
    volume_max = Column(Numeric(10, 2))
    volume_step = Column(Numeric(10, 2))
    stops_level = Column(Integer)  # Minimum distance for SL/TP in points
    freeze_level = Column(Integer)  # Freeze distance in points
    trade_mode = Column(Integer)  # 0=disabled, 1=longonly, 2=shortonly, 4=closeonly, 7=full
    digits = Column(Integer)  # Price digits
    point_value = Column(Numeric(20, 10))  # Point size
    contract_size = Column(Numeric(20, 2))  # Contract size (e.g., 100000 for forex, 5000 for XAGUSD)

    last_updated = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<BrokerSymbol(symbol={self.symbol}, vol_min={self.volume_min}, vol_max={self.volume_max})>"


class SubscribedSymbol(Base):
    """Symbols that EA is monitoring"""
    __tablename__ = 'subscribed_symbols'
    __table_args__ = (
        Index('idx_account_symbol', 'account_id', 'symbol'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    symbol = Column(String(20), nullable=False)
    tick_mode = Column(String(20), default='default')  # scalping, default, swing
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

    # Relationships
    account = relationship("Account", back_populates="subscribed_symbols")

    def __repr__(self):
        return f"<SubscribedSymbol(symbol={self.symbol}, mode={self.tick_mode})>"


class Tick(Base):
    """Tick data with spread tracking - 7 day retention (cleaned up daily)

    NOTE: Ticks are now GLOBAL (no account_id). A EURUSD tick is the same for everyone.
    """
    __tablename__ = 'ticks'
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - ticks are global (database migration completed)
    symbol = Column(String(20), nullable=False, index=True)
    bid = Column(Numeric(20, 5), nullable=False)
    ask = Column(Numeric(20, 5), nullable=False)
    spread = Column(Numeric(10, 5))  # Spread = Ask - Bid
    volume = Column(BigInteger)
    timestamp = Column(DateTime, nullable=False, index=True)
    tradeable = Column(Boolean, default=True)  # Trading hours status

    def __repr__(self):
        return f"<Tick(symbol={self.symbol}, bid={self.bid}, ask={self.ask}, spread={self.spread}, tradeable={self.tradeable})>"


class OHLCData(Base):
    """OHLC aggregated data - GLOBAL (no account_id)

    NOTE: OHLC data is now GLOBAL (no account_id). Candles are the same for everyone.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'ohlc_data'
    __table_args__ = (
        Index('idx_symbol_timeframe_timestamp', 'symbol', 'timeframe', 'timestamp', unique=True),
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - OHLC data is global (database migration completed)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)  # M1, M5, M15, H1, H4, D1
    open = Column(Numeric(20, 5), nullable=False)
    high = Column(Numeric(20, 5), nullable=False)
    low = Column(Numeric(20, 5), nullable=False)
    close = Column(Numeric(20, 5), nullable=False)
    volume = Column(BigInteger)
    timestamp = Column(DateTime, nullable=False)

    def __repr__(self):
        return f"<OHLC({self.symbol} {self.timeframe} O:{self.open} H:{self.high} L:{self.low} C:{self.close})>"


class Trade(Base):
    """Trade records - Single Source of Truth"""
    __tablename__ = 'trades'
    __table_args__ = (
        Index('idx_account_ticket', 'account_id', 'ticket'),
        Index('idx_status', 'status'),
        Index('idx_trades_signal_id', 'signal_id'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    ticket = Column(BigInteger, unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    type = Column(String(20), nullable=False)  # market_buy, market_sell, limit, stop
    direction = Column(String(10), nullable=False)  # buy, sell
    volume = Column(Numeric(10, 2), nullable=False)
    open_price = Column(Numeric(20, 5))
    open_time = Column(DateTime)
    close_price = Column(Numeric(20, 5))
    close_time = Column(DateTime)
    sl = Column(Numeric(20, 5))
    tp = Column(Numeric(20, 5))
    original_tp = Column(Numeric(20, 5))  # 🎯 Original TP for tracking extensions
    tp_extended_count = Column(Integer, default=0)  # 🎯 How many times TP was extended
    
    # ✅ COMPREHENSIVE TRACKING - Initial TP/SL Snapshot
    initial_tp = Column(Numeric(20, 5))  # TP at trade opening (for extension tracking)
    initial_sl = Column(Numeric(20, 5))  # SL at trade opening (for trailing detection)
    
    # ✅ COMPREHENSIVE TRACKING - Price Action at Entry
    entry_bid = Column(Numeric(20, 5))  # Bid price at entry
    entry_ask = Column(Numeric(20, 5))  # Ask price at entry
    entry_spread = Column(Numeric(10, 5))  # Spread at entry
    
    # ✅ COMPREHENSIVE TRACKING - Price Action at Exit
    exit_bid = Column(Numeric(20, 5))  # Bid price at exit
    exit_ask = Column(Numeric(20, 5))  # Ask price at exit
    exit_spread = Column(Numeric(10, 5))  # Spread at exit
    
    # ✅ COMPREHENSIVE TRACKING - Trailing Stop Tracking
    trailing_stop_active = Column(Boolean, default=False)  # Was TS activated?
    trailing_stop_moves = Column(Integer, default=0)  # How many times SL was moved by TS
    
    # ✅ COMPREHENSIVE TRACKING - MFE/MAE (Max Favorable/Adverse Excursion)
    max_favorable_excursion = Column(Numeric(10, 2), default=0)  # Max profit during trade (pips)
    max_adverse_excursion = Column(Numeric(10, 2), default=0)  # Max drawdown during trade (pips)
    
    # ✅ COMPREHENSIVE TRACKING - Performance Metrics
    pips_captured = Column(Numeric(10, 2))  # Profit/Loss in pips
    risk_reward_realized = Column(Numeric(10, 2))  # Actual R:R achieved
    hold_duration_minutes = Column(Integer)  # Trade duration in minutes
    
    # ✅ COMPREHENSIVE TRACKING - Market Context
    entry_volatility = Column(Numeric(10, 5))  # ATR/Spread at entry
    exit_volatility = Column(Numeric(10, 5))  # ATR/Spread at exit
    session = Column(String(20))  # Trading session (London/NY/Asia/Pacific)
    
    profit = Column(Numeric(15, 2))
    commission = Column(Numeric(15, 2))
    swap = Column(Numeric(15, 2))
    source = Column(String(20), nullable=False)  # ea_command, mt5_manual, autotrade
    command_id = Column(String(64), index=True)  # Link to command if ea_command
    signal_id = Column(Integer, ForeignKey('trading_signals.id'))  # Link to signal if from autotrade
    timeframe = Column(String(10))  # Timeframe signal was generated on
    entry_reason = Column(String(200))  # Why trade was opened: pattern, indicator confluence, etc
    entry_confidence = Column(Numeric(5, 2))  # Signal confidence at entry (for opportunity cost comparison)
    close_reason = Column(String(100))  # TP_HIT, SL_HIT, MANUAL, TRAILING_STOP, etc
    response_data = Column(JSONB)  # Full EA response
    status = Column(String(20), default='open')  # open, closed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="trades")
    signal = relationship("TradingSignal", foreign_keys=[signal_id])

    def __repr__(self):
        return f"<Trade(ticket={self.ticket}, {self.direction} {self.volume} {self.symbol} @ {self.open_price})>"


class TradeHistoryEvent(Base):
    """Trade modification history - tracks all TP/SL changes, volume modifications, etc."""
    __tablename__ = 'trade_history_events'
    __table_args__ = (
        Index('idx_trade_history_trade_id', 'trade_id'),
        Index('idx_trade_history_ticket', 'ticket'),
        Index('idx_trade_history_event_type', 'event_type'),
        Index('idx_trade_history_timestamp', 'timestamp'),
        Index('idx_trade_history_ticket_timestamp', 'ticket', 'timestamp'),
    )

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trades.id', ondelete='CASCADE'), nullable=False)
    ticket = Column(BigInteger, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # TP_MODIFIED, SL_MODIFIED, VOLUME_MODIFIED, PRICE_UPDATE
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Before/After Values
    old_value = Column(Numeric(20, 5))
    new_value = Column(Numeric(20, 5))
    
    # Context
    reason = Column(String(200))  # Human-readable reason (e.g., "Trailing Stop activated")
    source = Column(String(50))  # System component (e.g., "smart_trailing_stop", "manual")
    
    # Market State at time of change
    price_at_change = Column(Numeric(20, 5))
    spread_at_change = Column(Numeric(10, 5))
    
    # Additional metadata (renamed from 'metadata' - reserved word)
    event_metadata = Column(JSONB)

    def __repr__(self):
        return f"<TradeHistoryEvent(ticket={self.ticket}, type={self.event_type}, {self.old_value}->{self.new_value})>"


class Command(Base):
    """Commands sent from Server to EA"""
    __tablename__ = 'commands'

    id = Column(String(64), primary_key=True)  # UUID
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    command_type = Column(String(50), nullable=False)  # market_order, modify_order, close_position
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), default='pending')  # pending, sent, success, failed
    response = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)

    # Relationships
    account = relationship("Account", back_populates="commands")

    def __repr__(self):
        return f"<Command(id={self.id}, type={self.command_type}, status={self.status})>"


class Log(Base):
    """EA Logs and System Events"""
    __tablename__ = 'logs'
    __table_args__ = (
        Index('idx_timestamp', 'timestamp'),
        Index('idx_level', 'level'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    level = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    details = Column(JSONB)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    account = relationship("Account", back_populates="logs")

    def __repr__(self):
        return f"<Log({self.level}: {self.message[:50]})>"


class AccountTransaction(Base):
    """Account Transactions (Deposits, Withdrawals, Credits, etc.)"""
    __tablename__ = 'account_transactions'
    __table_args__ = (
        Index('idx_transactions_account', 'account_id'),
        Index('idx_transactions_timestamp', 'timestamp'),
        Index('idx_transactions_type', 'transaction_type'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    ticket = Column(BigInteger, unique=True, nullable=False)
    transaction_type = Column(String(50), nullable=False)  # BALANCE, CREDIT, BONUS, etc.
    amount = Column(Numeric(15, 2), nullable=False)
    balance_after = Column(Numeric(15, 2))
    comment = Column(Text)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<Transaction({self.transaction_type} {self.amount} @ {self.timestamp})>"


class TradingSignal(Base):
    """Trading Signals generated by pattern recognition and indicators - GLOBAL

    NOTE: Trading signals are now GLOBAL (no account_id). Strategies are universal.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'trading_signals'
    __table_args__ = (
        Index('idx_signal_symbol_timeframe', 'symbol', 'timeframe'),
        Index('idx_signal_status', 'status'),
        Index('idx_signal_created', 'created_at'),
        # CRITICAL: Prevent race condition - only ONE active signal per symbol/timeframe
        Index(
            'idx_unique_active_signal',
            'symbol', 'timeframe',
            unique=True,
            postgresql_where=text("status = 'active'")
        ),
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - trading signals are global (database migration completed)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)  # M5, M15, H1, H4, D1
    signal_type = Column(String(10), nullable=False)  # BUY, SELL, HOLD
    confidence = Column(Numeric(5, 2), nullable=False)  # 0-100%
    entry_price = Column(Numeric(20, 5))
    sl_price = Column(Numeric(20, 5))
    tp_price = Column(Numeric(20, 5))
    indicators_used = Column(JSONB)  # {'RSI': 32, 'MACD': {...}, 'EMA_20': 1.0850}
    patterns_detected = Column(JSONB)  # ['Bullish Engulfing', 'Above 200 EMA']
    reasons = Column(JSONB)  # ['RSI Oversold Bounce', 'MACD Bullish Crossover']

    # ✅ Continuous Signal Validation - stores indicator snapshot for validation
    indicator_snapshot = Column(JSONB)  # Snapshot of all indicators at signal creation
    last_validated = Column(DateTime)  # Timestamp of last validation check
    is_valid = Column(Boolean, default=True)  # False if ANY signal condition no longer holds

    status = Column(String(20), default='active')  # active, expired, executed, ignored
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # ✅ NEW: Track signal updates
    expires_at = Column(DateTime)
    executed_at = Column(DateTime)

    # No relationships - trading signals are global

    # Backward compatibility properties
    @property
    def sl(self):
        """Alias for sl_price for backward compatibility"""
        return self.sl_price

    @property
    def tp(self):
        """Alias for tp_price for backward compatibility"""
        return self.tp_price

    def __repr__(self):
        return f"<Signal({self.symbol} {self.timeframe} {self.signal_type} {self.confidence}%)>"


class PatternDetection(Base):
    """Candlestick Pattern Detections - GLOBAL

    NOTE: Pattern detections are now GLOBAL (no account_id). Patterns are universal.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'pattern_detections'
    __table_args__ = (
        Index('idx_pattern_symbol_timeframe', 'symbol', 'timeframe'),
        Index('idx_pattern_detected', 'detected_at'),
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - pattern detections are global (database migration completed)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    pattern_name = Column(String(100), nullable=False)  # 'Bullish Engulfing', 'Hammer', etc.
    pattern_type = Column(String(20), nullable=False)  # bullish, bearish, neutral
    reliability_score = Column(Numeric(5, 2))  # 0-100%
    ohlc_snapshot = Column(JSONB)  # Snapshot of OHLC data when pattern detected
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # No relationships - pattern detections are global

    def __repr__(self):
        return f"<Pattern({self.pattern_name} {self.symbol} {self.timeframe})>"


class IndicatorValue(Base):
    """Calculated Technical Indicator Values (Cache) - GLOBAL

    NOTE: Indicator values are now GLOBAL (no account_id). Technical indicators are universal.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'indicator_values'
    __table_args__ = (
        Index('idx_indicator_symbol_timeframe', 'symbol', 'timeframe', 'indicator_name'),
        Index('idx_indicator_calculated', 'calculated_at'),
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - indicator values are global (database migration completed)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    indicator_name = Column(String(50), nullable=False)  # RSI, MACD, EMA_20, etc.
    value = Column(JSONB, nullable=False)  # Single value or complex {'signal': 12.3, 'histogram': 0.5}
    calculated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # No relationships - indicator values are global

    def __repr__(self):
        return f"<Indicator({self.indicator_name} {self.symbol} {self.timeframe})>"


class AutoTradeConfig(Base):
    """Auto-Trading Configuration per Account"""
    __tablename__ = 'auto_trade_config'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), unique=True, nullable=False)

    # Enable/Disable - ✅ ENABLED BY DEFAULT as requested
    enabled = Column(Boolean, default=True, nullable=False)

    # Risk Management
    max_positions = Column(Integer, default=5, nullable=False)
    max_risk_per_trade = Column(Numeric(5, 4), default=0.02)  # 2% risk per trade
    position_size_percent = Column(Numeric(5, 4), default=0.01)  # 1% of balance per trade
    max_drawdown_percent = Column(Numeric(5, 4), default=0.10)  # 10% max drawdown

    # Signal Filtering - ✅ 60% DEFAULT CONFIDENCE as requested
    min_signal_confidence = Column(Numeric(5, 4), default=0.60)  # 60% minimum confidence (default)
    allowed_timeframes = Column(String(100), default='M5,M15,H1,H4')  # Comma-separated
    allowed_symbols = Column(Text)  # Comma-separated, NULL = all

    # Execution Settings
    check_interval_seconds = Column(Integer, default=10)  # How often to check for signals
    max_signal_age_minutes = Column(Integer, default=5)  # Don't execute old signals

    # Advanced
    use_dynamic_sizing = Column(Boolean, default=True)  # Calculate volume based on SL distance
    allow_hedging = Column(Boolean, default=False)  # Allow opposite direction trades
    trailing_stop_enabled = Column(Boolean, default=False)  # Future: enable trailing stops

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<AutoTradeConfig(account={self.account_id}, enabled={self.enabled}, max_pos={self.max_positions})>"


class BacktestRun(Base):
    """Backtesting Run Configuration and Results"""
    __tablename__ = 'backtest_runs'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)

    # Configuration
    name = Column(String(100), nullable=False)
    description = Column(Text)
    symbols = Column(String(200))  # Comma-separated symbols
    timeframes = Column(String(100))  # Comma-separated timeframes
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    initial_balance = Column(Numeric(15, 2), default=10000.0)

    # Strategy Settings
    min_confidence = Column(Numeric(5, 4), default=0.60)
    position_size_percent = Column(Numeric(5, 4), default=0.01)
    max_positions = Column(Integer, default=5)

    # Results (calculated after run)
    final_balance = Column(Numeric(15, 2))
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    win_rate = Column(Numeric(5, 4))  # Percentage as decimal
    profit_factor = Column(Numeric(10, 4))  # Gross Profit / Gross Loss
    total_profit = Column(Numeric(15, 2))
    total_loss = Column(Numeric(15, 2))
    max_drawdown = Column(Numeric(15, 2))
    max_drawdown_percent = Column(Numeric(5, 4))
    sharpe_ratio = Column(Numeric(10, 4))

    # Execution
    status = Column(String(20), default='pending')  # pending, running, completed, failed
    progress_percent = Column(Numeric(5, 2), default=0)  # 0-100
    current_status = Column(Text)  # Detailed current status message
    current_processing_date = Column(DateTime)  # Current date being processed
    processed_candles = Column(Integer, default=0)  # Number of candles processed
    total_candles = Column(Integer, default=0)  # Total candles to process
    estimated_completion = Column(DateTime)  # Estimated completion time
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    # Learned Indicator Scores (from backtest simulation)
    learned_scores = Column(JSONB)  # Symbol -> Timeframe -> [Indicator scores]

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])
    trades = relationship("BacktestTrade", back_populates="backtest_run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BacktestRun(id={self.id}, name={self.name}, status={self.status}, win_rate={self.win_rate})>"


class BacktestTrade(Base):
    """Virtual Trades from Backtesting"""
    __tablename__ = 'backtest_trades'
    __table_args__ = (
        Index('idx_backtest_symbol', 'backtest_run_id', 'symbol'),
        Index('idx_backtest_time', 'backtest_run_id', 'entry_time'),
    )

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id'), nullable=False)
    signal_id = Column(Integer, ForeignKey('trading_signals.id'))  # Original signal used

    # Trade Details
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    direction = Column(String(10), nullable=False)  # BUY, SELL
    volume = Column(Numeric(10, 2), nullable=False)

    # Entry
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Numeric(20, 5), nullable=False)
    entry_reason = Column(String(500))  # Signal reasons (patterns, indicators)
    sl = Column(Numeric(20, 5))
    tp = Column(Numeric(20, 5))

    # Exit
    exit_time = Column(DateTime)
    exit_price = Column(Numeric(20, 5))
    exit_reason = Column(String(50))  # TP_HIT, SL_HIT, END_OF_BACKTEST, TRAILING_STOP

    # Results
    profit = Column(Numeric(15, 2))
    profit_percent = Column(Numeric(10, 4))
    duration_minutes = Column(Integer)

    # Signal Metadata
    signal_confidence = Column(Numeric(5, 2))  # 0-100 confidence percentage
    trailing_stop_used = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    backtest_run = relationship("BacktestRun", back_populates="trades")
    signal = relationship("TradingSignal", foreign_keys=[signal_id])

    def __repr__(self):
        return f"<BacktestTrade(id={self.id}, {self.direction} {self.symbol}, profit={self.profit})>"


class TradeAnalytics(Base):
    """Aggregated Trade Analytics per Symbol/Timeframe"""
    __tablename__ = 'trade_analytics'
    __table_args__ = (
        Index('idx_analytics_symbol_tf', 'symbol', 'timeframe'),
        Index('idx_analytics_period', 'period_start', 'period_end'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)

    # Scope
    symbol = Column(String(20))  # NULL = all symbols
    timeframe = Column(String(10))  # NULL = all timeframes
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Trade Counts
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    breakeven_trades = Column(Integer, default=0)

    # Performance Metrics
    win_rate = Column(Numeric(5, 4))
    profit_factor = Column(Numeric(10, 4))
    total_profit = Column(Numeric(15, 2))
    total_loss = Column(Numeric(15, 2))
    net_profit = Column(Numeric(15, 2))

    # Best/Worst
    best_trade_profit = Column(Numeric(15, 2))
    worst_trade_loss = Column(Numeric(15, 2))
    avg_win = Column(Numeric(15, 2))
    avg_loss = Column(Numeric(15, 2))

    # Duration Stats
    avg_duration_minutes = Column(Integer)

    # Risk Metrics
    max_consecutive_wins = Column(Integer)
    max_consecutive_losses = Column(Integer)

    # Last Updated
    calculated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<TradeAnalytics(symbol={self.symbol}, tf={self.timeframe}, win_rate={self.win_rate})>"


class GlobalSettings(Base):
    """Global system settings for trading and backtesting"""
    __tablename__ = 'global_settings'

    id = Column(Integer, primary_key=True)
    
    # Risk Management
    max_positions = Column(Integer, default=5, nullable=False)
    max_positions_per_symbol_timeframe = Column(Integer, default=1, nullable=False)  # Max 1 position per symbol+timeframe
    risk_per_trade_percent = Column(Numeric(5, 4), default=0.01, nullable=False)  # 1% (Default changed from 2% to 1% on 2025-10-10)
    position_size_percent = Column(Numeric(5, 4), default=0.01, nullable=False)  # 1%
    max_drawdown_percent = Column(Numeric(5, 4), default=0.10, nullable=False)  # 10%
    
    # Signal Processing
    min_signal_confidence = Column(Numeric(5, 4), default=0.60, nullable=False)  # 60%
    signal_max_age_minutes = Column(Integer, default=60, nullable=False)  # Changed from 5 to 60 minutes - 2025-10-08

    # Auto-Trading
    autotrade_enabled = Column(Boolean, default=True, nullable=False)  # ✅ NEW: Persist auto-trade status
    autotrade_min_confidence = Column(Numeric(5, 2), default=60.0, nullable=False)  # ✅ NEW: Persist min confidence
    autotrade_risk_profile = Column(String(20), default='normal', nullable=False)  # ✅ NEW: 'moderate', 'normal', 'aggressive'

    # Cooldown Settings
    sl_cooldown_minutes = Column(Integer, default=60, nullable=False)  # 1 hour
    
    # Backtest Settings
    min_bars_required = Column(Integer, default=50, nullable=False)
    min_bars_d1 = Column(Integer, default=30, nullable=False)
    realistic_profit_factor = Column(Numeric(5, 4), default=0.60, nullable=False)  # 40% costs

    # Trailing Stop Settings (Smart Multi-Stage)
    trailing_stop_enabled = Column(Boolean, default=True, nullable=False)

    # Stage 1: Break-even
    breakeven_enabled = Column(Boolean, default=True, nullable=False)
    breakeven_trigger_percent = Column(Numeric(5, 2), default=30.0, nullable=False)  # 30% of TP distance
    breakeven_offset_points = Column(Numeric(6, 2), default=5.0, nullable=False)  # 5 points above/below entry

    # Stage 2: Partial trailing
    partial_trailing_trigger_percent = Column(Numeric(5, 2), default=50.0, nullable=False)  # 50% of TP distance
    partial_trailing_distance_percent = Column(Numeric(5, 2), default=40.0, nullable=False)  # Trail 40% behind

    # Stage 3: Aggressive trailing
    aggressive_trailing_trigger_percent = Column(Numeric(5, 2), default=75.0, nullable=False)  # 75% of TP distance
    aggressive_trailing_distance_percent = Column(Numeric(5, 2), default=25.0, nullable=False)  # Trail 25% behind

    # Stage 4: Near TP protection
    near_tp_trigger_percent = Column(Numeric(5, 2), default=90.0, nullable=False)  # 90% of TP distance
    near_tp_trailing_distance_percent = Column(Numeric(5, 2), default=15.0, nullable=False)  # Trail 15% behind

    # Trailing Stop Safety
    min_sl_distance_points = Column(Numeric(6, 2), default=10.0, nullable=False)  # Min 10 points from price
    max_sl_move_per_update = Column(Numeric(6, 2), default=100.0, nullable=False)  # Max 100 points per update

    # Metadata
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(100), default='system')

    def __repr__(self):
        return f"<GlobalSettings(max_pos={self.max_positions}, risk={self.risk_per_trade_percent})>"

    @classmethod
    def get_settings(cls, db):
        """Get global settings, create default if not exists"""
        settings = db.query(cls).first()
        if not settings:
            settings = cls()
            db.add(settings)
            db.commit()
        return settings


class IndicatorScore(Base):
    """Symbol-specific indicator performance scores - GLOBAL

    Tracks how well each indicator performs for each symbol.
    NOTE: Indicator scores are now GLOBAL (no account_id). Performance metrics are universal.
    Database migration completed to remove account_id column.
    """
    __tablename__ = 'indicator_scores'

    id = Column(Integer, primary_key=True)
    # account_id removed - indicator scores are global (database migration completed)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)  # M5, M15, H1, H4, D1
    indicator_name = Column(String(50), nullable=False, index=True)  # RSI, MACD, ADX, etc.

    # Performance metrics
    score = Column(Numeric(5, 2), default=50.0, nullable=False)  # 0-100, starts at neutral 50
    total_signals = Column(Integer, default=0, nullable=False)
    successful_signals = Column(Integer, default=0, nullable=False)  # Profitable trades
    failed_signals = Column(Integer, default=0, nullable=False)  # Losing trades

    # Profit metrics
    total_profit = Column(Numeric(15, 2), default=0.0)  # Sum of all profits/losses
    avg_profit = Column(Numeric(15, 2), default=0.0)  # Average profit per trade
    best_profit = Column(Numeric(15, 2), default=0.0)  # Best single trade
    worst_loss = Column(Numeric(15, 2), default=0.0)  # Worst single trade

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_signal_at = Column(DateTime)  # When last signal was generated

    # Composite index for fast lookups (account_id removed - global data)
    __table_args__ = (
        Index('idx_indicator_scores_lookup', 'symbol', 'timeframe', 'indicator_name', unique=True),
        Index('idx_indicator_scores_symbol', 'symbol', 'indicator_name'),
    )

    def __repr__(self):
        return f"<IndicatorScore({self.symbol} {self.timeframe} {self.indicator_name}: {self.score}% ({self.successful_signals}/{self.total_signals}))>"

    def update_score(self, was_profitable: bool, profit: float):
        """
        Update score based on trade result

        Args:
            was_profitable: Whether the trade was profitable
            profit: Profit/loss amount
        """
        self.total_signals += 1
        self.total_profit += profit

        if was_profitable:
            self.successful_signals += 1
            if profit > self.best_profit:
                self.best_profit = profit
        else:
            self.failed_signals += 1
            if profit < self.worst_loss:
                self.worst_loss = profit

        # Calculate new score (win rate weighted by profit)
        win_rate = (self.successful_signals / self.total_signals) * 100 if self.total_signals > 0 else 50.0

        # Calculate average profit
        self.avg_profit = self.total_profit / self.total_signals if self.total_signals > 0 else 0.0

        # Score = 70% win rate + 30% profit factor
        # Profit factor: avg_profit normalized to 0-100 scale (assuming max $100 avg profit = 100 score)
        profit_factor = min(100, max(0, (self.avg_profit / 100) * 100 + 50))

        self.score = (win_rate * 0.7) + (profit_factor * 0.3)
        self.score = max(0, min(100, self.score))  # Clamp to 0-100

        self.last_updated = datetime.utcnow()

    @classmethod
    def get_or_create(cls, db, symbol: str, timeframe: str, indicator_name: str):
        """Get existing score or create new one with default values

        NOTE: account_id parameter removed - indicator scores are now global
        """
        score = db.query(cls).filter_by(
            symbol=symbol,
            timeframe=timeframe,
            indicator_name=indicator_name
        ).first()

        if not score:
            score = cls(
                symbol=symbol,
                timeframe=timeframe,
                indicator_name=indicator_name,
                score=50.0  # Neutral starting score
            )
            db.add(score)
            db.commit()

        return score

    @classmethod
    def get_symbol_scores(cls, db, symbol: str, timeframe: str):
        """Get all indicator scores for a symbol/timeframe

        NOTE: account_id parameter removed - indicator scores are now global
        """
        return db.query(cls).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).all()

    @classmethod
    def get_top_indicators(cls, db, symbol: str, timeframe: str, limit: int = 5):
        """Get top performing indicators for a symbol

        NOTE: account_id parameter removed - indicator scores are now global
        """
        return db.query(cls).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).filter(cls.total_signals >= 5).order_by(cls.score.desc()).limit(limit).all()


# ========================================
# AUTO-OPTIMIZATION MODELS
# ========================================

class SymbolPerformanceTracking(Base):
    """Daily performance tracking per symbol for auto-enable/disable decisions"""
    __tablename__ = 'symbol_performance_tracking'
    __table_args__ = (
        Index('idx_symbol_perf_account_symbol', 'account_id', 'symbol'),
        Index('idx_symbol_perf_status', 'status'),
        Index('idx_symbol_perf_date', 'evaluation_date'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    symbol = Column(String(20), nullable=False)
    evaluation_date = Column(DateTime, nullable=False)

    # Symbol Status
    status = Column(String(20), nullable=False, default='active')  # 'active', 'watch', 'disabled'
    previous_status = Column(String(20))
    status_changed_at = Column(DateTime)
    auto_disabled_reason = Column(Text)

    # 14-Day Rolling Backtest Results
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id'))
    backtest_start_date = Column(DateTime)
    backtest_end_date = Column(DateTime)
    backtest_total_trades = Column(Integer, default=0)
    backtest_winning_trades = Column(Integer, default=0)
    backtest_losing_trades = Column(Integer, default=0)
    backtest_win_rate = Column(Numeric(5, 2))
    backtest_profit = Column(Numeric(15, 2))
    backtest_profit_percent = Column(Numeric(10, 4))
    backtest_max_drawdown = Column(Numeric(15, 2))
    backtest_max_drawdown_percent = Column(Numeric(10, 4))
    backtest_profit_factor = Column(Numeric(10, 4))
    backtest_sharpe_ratio = Column(Numeric(10, 4))
    backtest_avg_trade_duration = Column(Integer)
    backtest_best_trade = Column(Numeric(15, 2))
    backtest_worst_trade = Column(Numeric(15, 2))

    # Live Trading Results
    live_trades = Column(Integer, default=0)
    live_winning_trades = Column(Integer, default=0)
    live_losing_trades = Column(Integer, default=0)
    live_profit = Column(Numeric(15, 2))
    live_win_rate = Column(Numeric(5, 2))

    # Shadow Trading Results
    shadow_trades = Column(Integer, default=0)
    shadow_winning_trades = Column(Integer, default=0)
    shadow_losing_trades = Column(Integer, default=0)
    shadow_profit = Column(Numeric(15, 2))
    shadow_win_rate = Column(Numeric(5, 2))
    shadow_profitable_days = Column(Integer, default=0)

    # Auto-Decision Metrics
    consecutive_loss_days = Column(Integer, default=0)
    consecutive_profit_days = Column(Integer, default=0)
    meets_enable_criteria = Column(Boolean, default=False)
    meets_disable_criteria = Column(Boolean, default=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])
    backtest_run = relationship("BacktestRun", foreign_keys=[backtest_run_id])

    def __repr__(self):
        return f"<SymbolPerf(symbol={self.symbol}, date={self.evaluation_date}, status={self.status}, profit={self.backtest_profit})>"


class AutoOptimizationConfig(Base):
    """Configuration and thresholds for auto-optimization system"""
    __tablename__ = 'auto_optimization_config'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False, unique=True)

    # Feature Flags
    enabled = Column(Boolean, default=True)
    auto_disable_enabled = Column(Boolean, default=True)
    auto_enable_enabled = Column(Boolean, default=True)
    shadow_trading_enabled = Column(Boolean, default=True)

    # Backtest Configuration
    backtest_window_days = Column(Integer, default=14)
    backtest_schedule_time = Column(String(8), default='00:00:00')
    backtest_min_confidence = Column(Numeric(5, 4), default=0.60)

    # Auto-Disable Thresholds
    disable_consecutive_loss_days = Column(Integer, default=3)
    disable_min_win_rate = Column(Numeric(5, 2), default=35.0)
    disable_max_loss_percent = Column(Numeric(10, 4), default=-0.10)
    disable_max_drawdown_percent = Column(Numeric(10, 4), default=0.15)
    disable_min_trades = Column(Integer, default=5)

    # Auto-Enable Thresholds
    enable_consecutive_profit_days = Column(Integer, default=5)
    enable_min_win_rate = Column(Numeric(5, 2), default=55.0)
    enable_min_profit_percent = Column(Numeric(10, 4), default=0.05)
    enable_min_shadow_trades = Column(Integer, default=10)

    # Watch Status Thresholds
    watch_min_win_rate = Column(Numeric(5, 2), default=40.0)
    watch_max_win_rate = Column(Numeric(5, 2), default=50.0)
    watch_min_profit_percent = Column(Numeric(10, 4), default=-0.02)
    watch_max_profit_percent = Column(Numeric(10, 4), default=0.02)

    # Email Notifications
    email_enabled = Column(Boolean, default=True)
    email_daily_report = Column(Boolean, default=True)
    email_on_status_change = Column(Boolean, default=True)
    email_recipient = Column(String(255))

    # Kill Switch
    max_daily_loss_percent = Column(Numeric(10, 4), default=0.05)
    max_consecutive_losses = Column(Integer, default=5)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<AutoOptConfig(account={self.account_id}, enabled={self.enabled}, window={self.backtest_window_days}d)>"


class AutoOptimizationEvent(Base):
    """Audit trail of all auto-optimization decisions and actions"""
    __tablename__ = 'auto_optimization_events'
    __table_args__ = (
        Index('idx_auto_opt_events_account', 'account_id'),
        Index('idx_auto_opt_events_symbol', 'symbol'),
        Index('idx_auto_opt_events_type', 'event_type'),
        Index('idx_auto_opt_events_timestamp', 'event_timestamp'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    symbol = Column(String(20))
    event_type = Column(String(50), nullable=False)
    event_timestamp = Column(DateTime, default=datetime.utcnow)

    # Event Details
    old_status = Column(String(20))
    new_status = Column(String(20))
    trigger_reason = Column(Text)

    # Metrics at time of event
    metrics = Column(JSONB)

    # Related Objects
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id'))
    symbol_performance_id = Column(Integer, ForeignKey('symbol_performance_tracking.id'))

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])
    backtest_run = relationship("BacktestRun", foreign_keys=[backtest_run_id])
    symbol_performance = relationship("SymbolPerformanceTracking", foreign_keys=[symbol_performance_id])

    def __repr__(self):
        return f"<AutoOptEvent(symbol={self.symbol}, type={self.event_type}, {self.old_status}→{self.new_status})>"


class ShadowTrade(Base):
    """Simulated trades for disabled symbols to monitor recovery"""
    __tablename__ = 'shadow_trades'
    __table_args__ = (
        Index('idx_shadow_trades_account_symbol', 'account_id', 'symbol'),
        Index('idx_shadow_trades_entry_time', 'entry_time'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    symbol = Column(String(20), nullable=False)
    signal_id = Column(Integer, ForeignKey('trading_signals.id'))
    performance_tracking_id = Column(Integer, ForeignKey('symbol_performance_tracking.id'))

    # Trade Details
    timeframe = Column(String(10), nullable=False)
    direction = Column(String(10), nullable=False)
    volume = Column(Numeric(10, 2), nullable=False)

    # Entry
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Numeric(20, 5), nullable=False)
    sl = Column(Numeric(20, 5))
    tp = Column(Numeric(20, 5))

    # Exit (simulated)
    exit_time = Column(DateTime)
    exit_price = Column(Numeric(20, 5))
    exit_reason = Column(String(50))

    # Performance
    profit = Column(Numeric(15, 2))
    profit_percent = Column(Numeric(10, 4))
    duration_minutes = Column(Integer)

    # Status
    status = Column(String(20), default='open', nullable=False)  # open, closed

    # Signal Info
    signal_confidence = Column(Numeric(5, 2))
    entry_reason = Column(String(500))

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    is_simulated = Column(Boolean, default=True)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])
    signal = relationship("TradingSignal", foreign_keys=[signal_id])

    def __repr__(self):
        return f"<ShadowTrade(symbol={self.symbol}, {self.direction}, entry={self.entry_price}, profit={self.profit})>"


class DailyBacktestSchedule(Base):
    """Schedule and tracking of daily automated backtests"""
    __tablename__ = 'daily_backtest_schedule'
    __table_args__ = (
        Index('idx_daily_backtest_schedule_account', 'account_id'),
        Index('idx_daily_backtest_schedule_date', 'scheduled_date'),
        Index('idx_daily_backtest_schedule_status', 'status'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)

    scheduled_date = Column(DateTime, nullable=False)
    scheduled_time = Column(String(8), default='00:00:00')

    # Execution Status
    status = Column(String(20), default='pending')  # 'pending', 'running', 'completed', 'failed'
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Results
    backtest_runs_created = Column(Integer, default=0)
    total_symbols_evaluated = Column(Integer, default=0)
    symbols_enabled = Column(Integer, default=0)
    symbols_disabled = Column(Integer, default=0)
    symbols_watch = Column(Integer, default=0)

    # Errors
    error_message = Column(Text)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<DailyBacktestSchedule(date={self.scheduled_date}, status={self.status}, symbols={self.total_symbols_evaluated})>"


# ========================================
# SYMBOL-SPECIFIC DYNAMIC TRADING CONFIG
# ========================================

class SymbolTradingConfig(Base):
    """
    Per-symbol dynamic trading configuration with auto-adjusting risk management.

    This model enables each symbol+direction combination to learn independently:
    - Adjusts confidence thresholds based on performance
    - Scales risk up/down dynamically
    - Auto-pauses after consecutive losses
    - Learns market regime preferences
    - Tracks rolling 20-trade performance window
    """
    __tablename__ = 'symbol_trading_config'
    __table_args__ = (
        Index('idx_symbol_config_account_symbol', 'account_id', 'symbol'),
        Index('idx_symbol_config_status', 'status'),
        Index('idx_symbol_config_active', 'account_id', 'symbol', 'direction', postgresql_where=text("status = 'active'")),
        Index('idx_symbol_config_paused', 'account_id', 'symbol', postgresql_where=text("status = 'paused'")),
        Index('idx_symbol_config_performance', 'rolling_winrate', 'rolling_profit'),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10))  # NULL = both directions, 'BUY', 'SELL'

    # Dynamic Confidence Thresholds
    min_confidence_threshold = Column(Numeric(5, 2), default=50.0, nullable=False)
    confidence_adjustment_factor = Column(Numeric(5, 2), default=1.0, nullable=False)

    # Dynamic Risk Management
    risk_multiplier = Column(Numeric(5, 2), default=1.0, nullable=False)
    position_size_multiplier = Column(Numeric(5, 2), default=1.0, nullable=False)
    sl_multiplier = Column(Numeric(5, 2), default=1.0, nullable=False)
    tp_multiplier = Column(Numeric(5, 2), default=1.0, nullable=False)

    # Status & Auto-Pause
    status = Column(String(20), default='active', nullable=False)  # active, reduced_risk, paused, disabled
    auto_pause_enabled = Column(Boolean, default=True, nullable=False)
    pause_after_consecutive_losses = Column(Integer, default=3, nullable=False)
    resume_after_cooldown_hours = Column(Integer, default=24, nullable=False)
    paused_at = Column(DateTime)
    pause_reason = Column(Text)

    # Consecutive Performance Tracking
    consecutive_losses = Column(Integer, default=0, nullable=False)
    consecutive_wins = Column(Integer, default=0, nullable=False)
    last_trade_result = Column(String(10))  # WIN, LOSS, BREAKEVEN

    # Rolling Performance Window (Last 20 Trades)
    rolling_window_size = Column(Integer, default=20, nullable=False)
    rolling_trades_count = Column(Integer, default=0, nullable=False)
    rolling_wins = Column(Integer, default=0, nullable=False)
    rolling_losses = Column(Integer, default=0, nullable=False)
    rolling_breakeven = Column(Integer, default=0, nullable=False)
    rolling_profit = Column(Numeric(15, 2), default=0.0)
    rolling_winrate = Column(Numeric(5, 2))
    rolling_avg_profit = Column(Numeric(15, 2))
    rolling_profit_factor = Column(Numeric(10, 4))

    # Market Regime Preference Learning
    preferred_regime = Column(String(20))  # TRENDING, RANGING, ANY
    regime_performance_trending = Column(Numeric(5, 2))
    regime_performance_ranging = Column(Numeric(5, 2))
    regime_trades_trending = Column(Integer, default=0)
    regime_trades_ranging = Column(Integer, default=0)
    regime_wins_trending = Column(Integer, default=0)
    regime_wins_ranging = Column(Integer, default=0)

    # Session Performance (Daily Reset)
    session_trades_today = Column(Integer, default=0)
    session_profit_today = Column(Numeric(15, 2), default=0.0)
    session_date = Column(DateTime)

    # Performance History Snapshot
    performance_history = Column(JSONB)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_trade_at = Column(DateTime)
    last_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_adjustment_at = Column(DateTime)
    updated_by = Column(String(50), default='system')

    # Relationships
    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return (f"<SymbolTradingConfig({self.symbol} {self.direction or 'BOTH'}: "
                f"status={self.status}, conf={self.min_confidence_threshold}%, "
                f"risk={self.risk_multiplier}x, wr={self.rolling_winrate}%)>")

    @classmethod
    def get_or_create(cls, db, account_id: int, symbol: str, direction: str = None):
        """Get existing config or create new one with default values"""
        config = db.query(cls).filter_by(
            account_id=account_id,
            symbol=symbol,
            direction=direction
        ).first()

        if not config:
            config = cls(
                account_id=account_id,
                symbol=symbol,
                direction=direction
            )
            db.add(config)
            db.commit()

        return config

    def should_trade(self, signal_confidence: float, market_regime: str = None) -> tuple[bool, str]:
        """
        Determine if this symbol+direction should trade given current conditions

        Returns:
            (should_trade, reason)
        """
        # Check status
        if self.status == 'disabled':
            return False, "symbol_disabled"

        if self.status == 'paused':
            # Check if cooldown period has passed
            if self.paused_at:
                hours_paused = (datetime.utcnow() - self.paused_at).total_seconds() / 3600
                if hours_paused < self.resume_after_cooldown_hours:
                    return False, f"paused_cooldown_{int(self.resume_after_cooldown_hours - hours_paused)}h_remaining"

        # Check confidence threshold
        if signal_confidence < float(self.min_confidence_threshold):
            return False, f"confidence_too_low_{signal_confidence:.1f}<{self.min_confidence_threshold}"

        # Check market regime preference
        if market_regime and self.preferred_regime and self.preferred_regime != 'ANY':
            if market_regime != self.preferred_regime:
                # Allow trading in non-preferred regime but log it
                return True, f"regime_non_preferred_{market_regime}_vs_{self.preferred_regime}"

        return True, "approved"


class SymbolSpreadConfig(Base):
    """Per-symbol spread configuration for auto-trading spread validation"""
    __tablename__ = 'symbol_spread_config'

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)

    # Spread limits
    typical_spread = Column(Numeric(10, 5), nullable=False)  # Normal expected spread
    max_spread_multiplier = Column(Numeric(5, 2), default=3.0)  # Max = typical * multiplier
    absolute_max_spread = Column(Numeric(10, 5))  # Hard limit regardless of multiplier

    # Session-specific spreads (optional)
    asian_session_spread = Column(Numeric(10, 5))  # Wider spreads during Asian hours
    weekend_spread = Column(Numeric(10, 5))  # For crypto/indices 24/7

    # Configuration
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    use_dynamic_limits = Column(Boolean, default=True)  # Use multiplier vs absolute

    # Metadata
    asset_type = Column(String(20))  # FOREX, COMMODITY, INDEX, CRYPTO
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_max_spread(self, risk_profile='normal', is_asian_session=False, is_weekend=False):
        """
        Calculate maximum allowed spread for this symbol

        Args:
            risk_profile: 'moderate', 'normal', or 'aggressive'
            is_asian_session: Whether it's currently Asian trading session
            is_weekend: Whether it's weekend (for 24/7 assets)

        Returns:
            float: Maximum allowed spread
        """
        # Determine base spread based on session
        if is_weekend and self.weekend_spread:
            base = float(self.weekend_spread)
        elif is_asian_session and self.asian_session_spread:
            base = float(self.asian_session_spread)
        else:
            base = float(self.typical_spread)

        # Apply risk profile multiplier
        risk_multipliers = {
            'moderate': 0.8,   # More conservative
            'normal': 1.2,     # Slightly tolerant
            'aggressive': 2.0  # More tolerant
        }
        profile_multiplier = risk_multipliers.get(risk_profile, 1.2)

        # Calculate max spread
        if self.use_dynamic_limits:
            max_spread = base * float(self.max_spread_multiplier) * profile_multiplier
        else:
            max_spread = base * profile_multiplier

        # Apply absolute limit if set
        if self.absolute_max_spread:
            max_spread = min(max_spread, float(self.absolute_max_spread) * profile_multiplier)

        return max_spread

    def __repr__(self):
        return f"<SymbolSpreadConfig(symbol={self.symbol}, typical={self.typical_spread}, max_mult={self.max_spread_multiplier})>"

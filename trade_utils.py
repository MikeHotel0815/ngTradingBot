"""
Trade Utility Functions
Helper functions for trade-related calculations and enrichment
"""

from datetime import datetime
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


def get_pip_value(symbol: str) -> float:
    """
    Get pip value for a symbol

    Args:
        symbol: Trading symbol (e.g., 'EURUSD', 'BTCUSD')

    Returns:
        Pip value (e.g., 0.0001 for EURUSD, 1.0 for BTCUSD)
    """
    symbol_upper = symbol.upper()

    # Crypto pairs (1 pip = 1.0)
    if any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'LTC']):
        return 1.0

    # JPY pairs (1 pip = 0.01)
    if 'JPY' in symbol_upper:
        return 0.01

    # Indices (1 pip = 1.0)
    if any(idx in symbol_upper for idx in ['US500', 'DE40', 'UK100', 'NASDAQ']):
        return 1.0

    # Precious metals
    if symbol_upper in ['XAUUSD', 'GOLD']:  # Gold
        return 0.01
    if symbol_upper in ['XAGUSD', 'SILVER']:  # Silver
        return 0.001

    # Standard Forex pairs (1 pip = 0.0001)
    return 0.0001


def get_current_session(symbol: str) -> str:
    """
    Get current trading session for a symbol

    Args:
        symbol: Trading symbol

    Returns:
        Session name: 'ASIA', 'LONDON', 'OVERLAP', 'US', 'CLOSED'
    """
    try:
        from market_hours import MarketHours
        session = MarketHours.get_trading_session(symbol)
        return session if session else 'UNKNOWN'
    except ImportError:
        # Fallback to simple time-based logic if market_hours not available
        hour_utc = datetime.utcnow().hour

        # Simple session detection (UTC hours)
        if 0 <= hour_utc < 7:
            return 'ASIA'
        elif 7 <= hour_utc < 12:
            return 'LONDON'
        elif 12 <= hour_utc < 16:
            return 'OVERLAP'  # London + US overlap
        elif 16 <= hour_utc < 21:
            return 'US'
        else:
            return 'ASIA'  # After US close
    except Exception as e:
        logger.warning(f"Error getting session for {symbol}: {e}")
        return 'UNKNOWN'


def enrich_trade_metadata(trade, signal=None) -> None:
    """
    Enrich trade with additional metadata fields

    Calculates and sets:
    - session: Trading session when trade was opened
    - entry_reason: Why the trade was opened (from signal)
    - entry_confidence: Signal confidence score
    - timeframe: Signal timeframe
    - signal_id: Link to signal

    Args:
        trade: Trade object to enrich
        signal: Optional TradingSignal object
    """
    # Set trading session
    if not trade.session:
        trade.session = get_current_session(trade.symbol)
        logger.debug(f"Trade {trade.mt5_ticket if hasattr(trade, 'mt5_ticket') else trade.id}: Set session = {trade.session}")

    # Set signal-related fields if signal provided
    if signal:
        if not trade.signal_id:
            trade.signal_id = signal.id

        if not trade.entry_confidence and signal.confidence:
            trade.entry_confidence = float(signal.confidence)

        if not trade.timeframe and signal.timeframe:
            trade.timeframe = signal.timeframe

        if not trade.entry_reason and signal.reasons:
            if isinstance(signal.reasons, list):
                trade.entry_reason = ', '.join(signal.reasons)
            else:
                trade.entry_reason = str(signal.reasons)


def calculate_trade_metrics_on_close(trade) -> Dict:
    """
    Calculate trade metrics when trade is closed

    Calculates:
    - risk_reward_realized: Actual R:R ratio achieved
    - hold_duration_minutes: How long trade was open
    - pips_captured: Pips gained/lost

    Args:
        trade: Closed trade object

    Returns:
        Dict with calculated metrics
    """
    metrics = {}

    try:
        # Calculate hold duration
        if trade.open_time and trade.close_time:
            duration = (trade.close_time - trade.open_time).total_seconds() / 60
            metrics['hold_duration_minutes'] = int(duration)
            trade.hold_duration_minutes = int(duration)
            logger.debug(f"Trade {trade.id}: Hold duration = {duration:.0f} minutes")

        # Calculate risk/reward ratio
        if trade.initial_sl and trade.open_price and trade.profit is not None:
            initial_risk = abs(trade.open_price - trade.initial_sl)
            if initial_risk > 0:
                # Realized R:R = Actual Profit / Initial Risk
                # Profit is in account currency, need to normalize by risk distance
                risk_reward = trade.profit / initial_risk if initial_risk > 0 else 0
                metrics['risk_reward_realized'] = round(risk_reward, 2)
                trade.risk_reward_realized = round(risk_reward, 2)
                logger.debug(f"Trade {trade.id}: Risk/Reward realized = {risk_reward:.2f}")

        # Calculate pips captured
        if trade.open_price and trade.close_price and trade.direction:
            pip_value = get_pip_value(trade.symbol)

            if trade.direction == 'BUY':
                pips = (trade.close_price - trade.open_price) / pip_value
            else:  # SELL
                pips = (trade.open_price - trade.close_price) / pip_value

            metrics['pips_captured'] = round(pips, 2)
            trade.pips_captured = round(pips, 2)
            logger.debug(f"Trade {trade.id}: Pips captured = {pips:.2f}")

    except Exception as e:
        logger.error(f"Error calculating metrics for trade {trade.id}: {e}")

    return metrics


def calculate_entry_volatility(symbol: str, account_id: int) -> Optional[float]:
    """
    Calculate entry volatility (ATR) at trade open time

    Args:
        symbol: Trading symbol
        account_id: Account ID

    Returns:
        ATR value or None
    """
    try:
        from session_volatility_analyzer import SessionVolatilityAnalyzer
        analyzer = SessionVolatilityAnalyzer()

        # Get database session
        from database import ScopedSession
        db = ScopedSession()
        try:
            volatility = analyzer.calculate_recent_volatility(db, symbol, account_id)
            return round(volatility, 5) if volatility else None
        finally:
            db.close()

    except Exception as e:
        logger.warning(f"Could not calculate entry volatility for {symbol}: {e}")
        return None

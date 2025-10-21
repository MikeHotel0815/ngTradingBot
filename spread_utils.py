"""
Spread utilities for realistic P&L calculation
"""

from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session
from models import Tick
import logging

logger = logging.getLogger(__name__)


def get_spread_at_time(db: Session, symbol: str, timestamp: datetime, fallback_spread: float = None) -> float:
    """
    Get spread for a symbol at a specific time.

    Args:
        db: Database session
        symbol: Trading symbol
        timestamp: Time to get spread for
        fallback_spread: Default spread if no tick data available

    Returns:
        Spread in price units (e.g., 0.00020 for EURUSD = 2 pips)
    """
    try:
        # Query tick closest to timestamp
        tick = db.query(Tick).filter(
            Tick.symbol == symbol,
            Tick.timestamp <= timestamp
        ).order_by(Tick.timestamp.desc()).first()

        if tick and tick.spread:
            return float(tick.spread)

        # Fallback: calculate from bid/ask if spread column not available
        if tick and tick.bid and tick.ask:
            return float(tick.ask - tick.bid)

        # No tick data available - use fallback
        if fallback_spread is not None:
            return fallback_spread

        # Default spreads by symbol type
        return get_default_spread(symbol)

    except Exception as e:
        logger.error(f"Error getting spread for {symbol} at {timestamp}: {e}")
        return get_default_spread(symbol)


def get_default_spread(symbol: str) -> float:
    """
    Get default spread for symbol based on typical market conditions.

    These are conservative estimates for backtesting.
    Real spreads can be higher during news events or low liquidity.
    """
    symbol_upper = symbol.upper()

    # Forex majors (tight spreads)
    if symbol_upper in ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF']:
        return 0.00020  # 2 pips

    # Forex crosses
    if symbol_upper in ['EURJPY', 'GBPJPY', 'EURGBP', 'AUDUSD', 'NZDUSD', 'USDCAD']:
        return 0.00030  # 3 pips

    # Gold (XAUUSD)
    if 'XAU' in symbol_upper:
        return 0.50  # 50 cents spread

    # Silver (XAGUSD)
    if 'XAG' in symbol_upper:
        return 0.030  # 3 cents spread

    # Bitcoin
    if 'BTC' in symbol_upper:
        return 50.0  # $50 spread

    # Ethereum
    if 'ETH' in symbol_upper:
        return 5.0  # $5 spread

    # Indices (DAX, S&P500, etc.)
    if any(idx in symbol_upper for idx in ['DAX', 'DE40', 'SPX', 'US500', 'NDX', 'US100']):
        return 2.0  # 2 points spread

    # Default fallback
    return 0.00050  # 5 pips


def calculate_spread_cost(
    spread: float,
    lot_size: float,
    symbol: str,
    contract_size: float = None
) -> float:
    """
    Calculate the cost of spread for a trade.

    **NOTE**: This is for STATISTICAL PURPOSES ONLY!
    In reality, the spread cost is already included when using Bid/Ask prices:
    - BUY: Entry at ASK (Bid + Spread) → Immediate loss = spread
    - SELL: Entry at BID (Ask - Spread) → Immediate loss = spread

    Do NOT subtract spread cost from profit if you're already using correct Bid/Ask prices!

    Args:
        spread: Spread in price units (e.g., 0.00020 for 2 pips on EURUSD)
        lot_size: Position size in lots (e.g., 0.10)
        symbol: Trading symbol
        contract_size: Contract size per lot (optional, auto-calculated if not provided)

    Returns:
        Spread cost in account currency (USD) for statistical tracking

    Example:
        EURUSD:
        - Spread: 0.00020 (2 pips)
        - Lot size: 0.10
        - Contract size: 100,000
        - Cost: 0.00020 × 0.10 × 100,000 = $2.00
    """
    if contract_size is None:
        contract_size = get_contract_size(symbol)

    # Spread cost = spread (in price units) × lot_size × contract_size
    spread_cost = spread * lot_size * contract_size

    return spread_cost


def get_contract_size(symbol: str, db_session=None) -> float:
    """
    Get contract size (units per 1 standard lot) for symbol.

    IMPROVED: Automatically fetches from MT5 via database (updated by EA).
    Falls back to heuristic-based detection if DB not available.

    This is also called "point value multiplier" because:
    spread_cost = spread × lot_size × contract_size

    Args:
        symbol: Trading symbol
        db_session: Optional database session for fetching contract size from BrokerSymbol

    Returns:
        Contract size (units per lot)
    """
    symbol_upper = symbol.upper()

    # ✅ PRIORITY 1: Try to get contract size from database (MT5-provided value)
    if db_session:
        try:
            from models import BrokerSymbol
            broker_symbol = db_session.query(BrokerSymbol).filter_by(symbol=symbol).first()
            if broker_symbol and broker_symbol.contract_size:
                contract_size = float(broker_symbol.contract_size)
                # Sanity check: contract size should be > 0
                if contract_size > 0:
                    return contract_size
        except Exception as e:
            # DB not available or error - fall through to fallback
            pass

    # ✅ FALLBACK: Heuristic-based detection (legacy method)
    # This ensures the system works even before MT5 sends symbol specs

    # IMPORTANT: Check crypto FIRST before USD check (BTCUSD, ETHUSD contain USD!)
    # Bitcoin: 1 lot = 1 BTC (usually)
    # Example: 8.0 spread × 0.01 lot × 1 = $0.08
    if 'BTC' in symbol_upper:
        return 1.0

    # Ethereum: 1 lot = 1 ETH (usually)
    if 'ETH' in symbol_upper:
        return 1.0

    # Gold (XAUUSD): 1 lot = 100 oz
    # Example: 0.50 spread × 0.02 lot × 100 = $1.00
    if 'XAU' in symbol_upper:
        return 100.0

    # Silver (XAGUSD): 1 lot = 5000 oz (typically)
    # ✅ FIXED: Was 50.0 (factor 100 error), now correct
    if 'XAG' in symbol_upper:
        return 5000.0

    # Indices: 1 lot = 1 contract (usually $1 per point)
    if any(idx in symbol_upper for idx in ['DAX', 'DE40', 'SPX', 'US500', 'NDX', 'US100']):
        return 1.0

    # Forex: 1 standard lot = 100,000 units (check AFTER crypto/metals/indices!)
    if any(fx in symbol_upper for fx in ['EUR', 'GBP', 'USD', 'JPY', 'CHF', 'AUD', 'CAD', 'NZD']):
        if 'JPY' in symbol_upper:
            # JPY pairs: spread is in 0.01, contract is 100,000
            # Example: 0.018 spread × 0.1 lot × 1,000 = $1.80
            return 1000.0
        # Non-JPY: spread is in 0.00001, contract is 100,000
        # Example: 0.00020 spread × 0.1 lot × 100,000 = $2.00
        return 100000.0

    # Default: assume Forex
    return 100000.0


def get_point_value(symbol: str) -> float:
    """
    DEPRECATED: Use get_contract_size() instead.

    This function is kept for backward compatibility.
    """
    return get_contract_size(symbol)


def get_average_spread(db: Session, symbol: str, hours: int = 24) -> dict:
    """
    Get average spread statistics for a symbol over the last N hours.

    Returns:
        dict with avg_spread, min_spread, max_spread, sample_count
    """
    from datetime import timedelta

    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        ticks = db.query(Tick).filter(
            Tick.symbol == symbol,
            Tick.timestamp >= cutoff_time,
            Tick.spread.isnot(None)
        ).all()

        if not ticks:
            return {
                'avg_spread': get_default_spread(symbol),
                'min_spread': None,
                'max_spread': None,
                'sample_count': 0
            }

        spreads = [float(t.spread) for t in ticks]

        return {
            'avg_spread': sum(spreads) / len(spreads),
            'min_spread': min(spreads),
            'max_spread': max(spreads),
            'sample_count': len(spreads)
        }

    except Exception as e:
        logger.error(f"Error calculating average spread for {symbol}: {e}")
        return {
            'avg_spread': get_default_spread(symbol),
            'min_spread': None,
            'max_spread': None,
            'sample_count': 0
        }


def detect_spread_spike(current_spread: float, symbol: str, db: Session = None, threshold_multiplier: float = 2.5) -> dict:
    """
    Detect abnormal spread spikes that may indicate:
    - News events
    - Low liquidity periods
    - Market disruption
    - Data quality issues

    Args:
        current_spread: Current spread to check
        symbol: Trading symbol
        db: Database session (optional, for historical comparison)
        threshold_multiplier: Multiplier of average spread to trigger alert (default: 2.5x)

    Returns:
        dict with:
            - is_spike: bool
            - current_spread: float
            - avg_spread: float (if available)
            - spike_ratio: float (current / avg)
            - severity: str ('normal', 'elevated', 'high', 'critical')
    """
    result = {
        'is_spike': False,
        'current_spread': current_spread,
        'avg_spread': None,
        'spike_ratio': 1.0,
        'severity': 'normal'
    }

    # Get historical average if DB available
    if db:
        stats = get_average_spread(db, symbol, hours=24)
        avg_spread = stats['avg_spread']
    else:
        avg_spread = get_default_spread(symbol)

    result['avg_spread'] = avg_spread

    if avg_spread and avg_spread > 0:
        spike_ratio = current_spread / avg_spread
        result['spike_ratio'] = spike_ratio

        # Classify severity
        if spike_ratio >= threshold_multiplier * 2:  # 5x+ normal
            result['is_spike'] = True
            result['severity'] = 'critical'
            logger.warning(f"🚨 CRITICAL spread spike on {symbol}: {current_spread:.5f} ({spike_ratio:.1f}x normal)")
        elif spike_ratio >= threshold_multiplier * 1.5:  # 3.75x+ normal
            result['is_spike'] = True
            result['severity'] = 'high'
            logger.warning(f"⚠️ High spread spike on {symbol}: {current_spread:.5f} ({spike_ratio:.1f}x normal)")
        elif spike_ratio >= threshold_multiplier:  # 2.5x+ normal
            result['is_spike'] = True
            result['severity'] = 'elevated'
            logger.info(f"📊 Elevated spread on {symbol}: {current_spread:.5f} ({spike_ratio:.1f}x normal)")

    return result

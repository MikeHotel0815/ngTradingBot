"""
Trading Session & Market Context Helper
Provides utilities for determining trading sessions and market context
"""

from datetime import datetime, time
import pytz


def get_current_trading_session():
    """
    Determine current trading session based on UTC time
    
    Returns:
        str: Session name (London/NY/Asia/Pacific/Off-Hours)
    """
    now = datetime.utcnow()
    utc_time = now.time()
    
    # Trading session times (UTC)
    # Note: These overlap intentionally for crossover periods
    sessions = {
        'Tokyo': (time(0, 0), time(9, 0)),      # 00:00 - 09:00 UTC
        'London': (time(8, 0), time(17, 0)),    # 08:00 - 17:00 UTC
        'NY': (time(13, 0), time(22, 0)),       # 13:00 - 22:00 UTC
        'Sydney': (time(22, 0), time(7, 0)),    # 22:00 - 07:00 UTC (crosses midnight)
    }
    
    # Check which session we're in (priority order for overlaps)
    # London/NY overlap: 13:00-17:00 UTC (most volume)
    if time(13, 0) <= utc_time < time(17, 0):
        return 'London/NY'
    
    # London session
    if time(8, 0) <= utc_time < time(13, 0):
        return 'London'
    
    # NY session
    if time(17, 0) <= utc_time < time(22, 0):
        return 'NY'
    
    # Sydney/Tokyo overlap: 00:00-07:00 UTC
    if time(0, 0) <= utc_time < time(7, 0):
        return 'Sydney/Tokyo'
    
    # Tokyo only: 07:00-09:00 UTC
    if time(7, 0) <= utc_time < time(9, 0):
        return 'Tokyo'
    
    # Sydney only: 22:00-00:00 UTC
    if time(22, 0) <= utc_time <= time(23, 59):
        return 'Sydney'
    
    # Off-hours (very low volume)
    return 'Off-Hours'


def calculate_pips(entry_price, exit_price, direction, symbol='EURUSD'):
    """
    Calculate profit/loss in pips

    Args:
        entry_price: Entry price
        exit_price: Exit price
        direction: 'BUY' or 'SELL'
        symbol: Trading symbol (for JPY pair detection)

    Returns:
        float: Pips captured (positive = profit, negative = loss)
    """
    if not entry_price or not exit_price:
        return 0.0

    entry = float(entry_price)
    exit = float(exit_price)

    symbol_upper = symbol.upper()

    # ✅ FIX: Different symbols have different pip sizes
    # JPY pairs: 0.01 = 1 pip (multiplier 100)
    # XAUUSD (Gold), XAGUSD (Silver), indices: 0.01 = 1 pip (multiplier 100)
    # BTCUSD, ETHUSD: 1.00 = 1 pip (multiplier 1)
    # Standard forex: 0.0001 = 1 pip (multiplier 10000)

    if 'JPY' in symbol_upper:
        pip_multiplier = 100  # JPY pairs: 0.01 = 1 pip
    elif symbol_upper in ['XAUUSD', 'XAGUSD', 'GOLD', 'SILVER']:
        pip_multiplier = 100  # ✅ Gold/Silver: 0.01 = 1 pip (not 10000!)
    elif symbol_upper in ['BTCUSD', 'ETHUSD', 'BTC', 'ETH']:
        pip_multiplier = 1    # ✅ Crypto: 1.00 = 1 pip
    elif symbol_upper.startswith('DE') or symbol_upper.startswith('US') or '.c' in symbol_upper:
        pip_multiplier = 100  # ✅ Indices: 0.01 = 1 pip
    else:
        pip_multiplier = 10000  # Standard forex: 0.0001 = 1 pip

    if direction.upper() == 'BUY':
        pips = (exit - entry) * pip_multiplier
    else:  # SELL
        pips = (entry - exit) * pip_multiplier

    return round(pips, 2)


def calculate_risk_reward(entry_price, exit_price, initial_sl, direction):
    """
    Calculate realized Risk:Reward ratio
    
    Args:
        entry_price: Entry price
        exit_price: Exit price
        initial_sl: Initial stop loss
        direction: 'BUY' or 'SELL'
    
    Returns:
        float: R:R ratio (e.g., 2.5 means 2.5:1 reward)
    """
    if not entry_price or not exit_price or not initial_sl:
        return None
    
    entry = float(entry_price)
    exit = float(exit_price)
    sl = float(initial_sl)
    
    # Calculate initial risk (distance to SL)
    if direction.upper() == 'BUY':
        risk = entry - sl
        reward = exit - entry
    else:  # SELL
        risk = sl - entry
        reward = entry - exit
    
    # Avoid division by zero
    if risk == 0:
        return None
    
    # Calculate R:R ratio
    rr = reward / risk
    
    return round(rr, 2)


def get_pip_value(symbol):
    """
    Get pip value for different symbols
    
    Args:
        symbol: Trading symbol
    
    Returns:
        float: Pip size (0.0001 for most pairs, 0.01 for JPY pairs)
    """
    symbol_upper = symbol.upper()
    
    # JPY pairs
    if 'JPY' in symbol_upper:
        return 0.01
    
    # Most other pairs
    return 0.0001

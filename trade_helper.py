"""
Trade Helper Functions
Volume normalization and trade validation
"""

import logging
from database import ScopedSession
from models import BrokerSymbol

logger = logging.getLogger(__name__)


def normalize_volume(account_id, symbol, volume):
    """
    Normalize volume to match symbol's min/max/step requirements from database

    Args:
        account_id: Account ID
        symbol: Symbol name (e.g. "DE40.c", "EURUSD")
        volume: Requested volume

    Returns:
        Normalized volume, or None if symbol specs not available
    """
    db = ScopedSession()
    try:
        # Get symbol specs from database
        broker_symbol = db.query(BrokerSymbol).filter_by(
            symbol=symbol
        ).first()

        if not broker_symbol:
            logger.warning(f"Symbol specs not found in DB for {symbol}")
            return volume  # Return original volume if no specs available

        # Get volume constraints
        volume_min = float(broker_symbol.volume_min) if broker_symbol.volume_min else 0.01
        volume_max = float(broker_symbol.volume_max) if broker_symbol.volume_max else 100.0
        volume_step = float(broker_symbol.volume_step) if broker_symbol.volume_step else 0.01

        # Ensure volume is at least the minimum
        if volume < volume_min:
            logger.warning(f"Volume {volume} is below minimum {volume_min} for {symbol}. Using minimum.")
            volume = volume_min

        # Ensure volume is at most the maximum
        if volume > volume_max:
            logger.warning(f"Volume {volume} exceeds maximum {volume_max} for {symbol}. Using maximum.")
            volume = volume_max

        # Round volume to the nearest step
        if volume_step > 0:
            volume = round(volume / volume_step) * volume_step

        logger.info(f"Normalized volume for {symbol}: {volume} (min={volume_min}, max={volume_max}, step={volume_step})")

        return volume

    except Exception as e:
        logger.error(f"Error normalizing volume for {symbol}: {e}")
        return volume  # Return original volume on error

    finally:
        db.close()


def validate_trade_params(account_id, symbol, volume, sl=None, tp=None):
    """
    Validate trade parameters against symbol specifications

    Args:
        account_id: Account ID
        symbol: Symbol name
        volume: Trade volume
        sl: Stop Loss price (optional)
        tp: Take Profit price (optional)

    Returns:
        dict with 'valid' (bool) and 'errors' (list of error messages)
    """
    db = ScopedSession()
    try:
        # Get symbol specs
        broker_symbol = db.query(BrokerSymbol).filter_by(
            symbol=symbol
        ).first()

        errors = []

        if not broker_symbol:
            errors.append(f"Symbol specifications not available for {symbol}")
            return {'valid': False, 'errors': errors}

        # Check trade mode
        trade_mode = broker_symbol.trade_mode if broker_symbol.trade_mode is not None else 7
        if trade_mode == 0:
            errors.append(f"Trading is disabled for {symbol}")

        # Check volume
        if broker_symbol.volume_min and volume < float(broker_symbol.volume_min):
            errors.append(f"Volume {volume} is below minimum {broker_symbol.volume_min}")

        if broker_symbol.volume_max and volume > float(broker_symbol.volume_max):
            errors.append(f"Volume {volume} exceeds maximum {broker_symbol.volume_max}")

        # Check volume step
        if broker_symbol.volume_step:
            step = float(broker_symbol.volume_step)
            if step > 0:
                remainder = volume % step
                if remainder > 0.0001:  # Small epsilon for floating point comparison
                    errors.append(f"Volume {volume} does not match step size {step}")

        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    except Exception as e:
        logger.error(f"Error validating trade params for {symbol}: {e}")
        return {'valid': False, 'errors': [str(e)]}

    finally:
        db.close()


def get_symbol_info(account_id, symbol):
    """
    Get symbol trading information from database

    Args:
        account_id: Account ID
        symbol: Symbol name

    Returns:
        dict with symbol specs, or None if not found
    """
    db = ScopedSession()
    try:
        broker_symbol = db.query(BrokerSymbol).filter_by(
            symbol=symbol
        ).first()

        if not broker_symbol:
            return None

        return {
            'symbol': broker_symbol.symbol,
            'volume_min': float(broker_symbol.volume_min) if broker_symbol.volume_min else None,
            'volume_max': float(broker_symbol.volume_max) if broker_symbol.volume_max else None,
            'volume_step': float(broker_symbol.volume_step) if broker_symbol.volume_step else None,
            'stops_level': broker_symbol.stops_level,
            'freeze_level': broker_symbol.freeze_level,
            'trade_mode': broker_symbol.trade_mode,
            'digits': broker_symbol.digits,
            'point_value': float(broker_symbol.point_value) if broker_symbol.point_value else None
        }

    except Exception as e:
        logger.error(f"Error getting symbol info for {symbol}: {e}")
        return None

    finally:
        db.close()

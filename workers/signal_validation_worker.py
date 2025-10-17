#!/usr/bin/env python3
"""
Signal Validation Worker
Continuously validates active signals and deactivates invalid ones

Runs every 30 seconds to ensure only valid signals are available for trading
"""

import logging
from datetime import datetime, timedelta
from database import ScopedSession
from models import TradingSignal, OHLCData
from sqlalchemy import and_, desc

logger = logging.getLogger(__name__)


def validate_signal(db, signal: TradingSignal) -> dict:
    """
    Validate if a trading signal is still valid based on current market conditions
    
    Returns:
        dict with 'valid' (bool) and 'reason' (str)
    """
    try:
        # Get latest OHLC data for this symbol/timeframe
        latest_ohlc = db.query(OHLCData).filter(
            and_(
                OHLCData.symbol == signal.symbol,
                OHLCData.timeframe == signal.timeframe
            )
        ).order_by(desc(OHLCData.timestamp)).first()
        
        if not latest_ohlc:
            return {
                'valid': False,
                'reason': 'No OHLC data available'
            }
        
        # Check if OHLC data is recent (within 2x timeframe period)
        timeframe_minutes = {
            'M5': 5,
            'M15': 15,
            'H1': 60,
            'H4': 240,
            'D1': 1440
        }
        max_data_age_minutes = timeframe_minutes.get(signal.timeframe, 60) * 2
        data_age = datetime.utcnow() - latest_ohlc.timestamp
        
        if data_age > timedelta(minutes=max_data_age_minutes):
            return {
                'valid': False,
                'reason': f'OHLC data too old ({int(data_age.total_seconds()/60)}min)'
            }
        
        current_price = float(latest_ohlc.close)
        
        # BUY Signal Validation
        if signal.signal_type == 'BUY':
            # Entry price should still be relevant (not too far from current price)
            if signal.entry_price:
                entry_price = float(signal.entry_price)
                # If price moved up too much (>5% for forex, >10% for crypto/indices), signal may be stale
                price_diff_pct = ((current_price - entry_price) / entry_price) * 100
                
                if price_diff_pct > 10:  # Price ran away upward
                    return {
                        'valid': False,
                        'reason': f'Price moved too far up (+{price_diff_pct:.2f}%)'
                    }
                
                if price_diff_pct < -5:  # Price dropped significantly below entry
                    return {
                        'valid': False,
                        'reason': f'Price dropped too far (-{abs(price_diff_pct):.2f}%)'
                    }
            
            # Check if SL would be hit immediately
            if signal.sl_price and current_price <= float(signal.sl_price):
                return {
                    'valid': False,
                    'reason': 'Current price at/below SL level'
                }
        
        # SELL Signal Validation
        elif signal.signal_type == 'SELL':
            if signal.entry_price:
                entry_price = float(signal.entry_price)
                price_diff_pct = ((entry_price - current_price) / entry_price) * 100
                
                if price_diff_pct > 10:  # Price ran away downward
                    return {
                        'valid': False,
                        'reason': f'Price moved too far down (+{price_diff_pct:.2f}%)'
                    }
                
                if price_diff_pct < -5:  # Price rallied significantly above entry
                    return {
                        'valid': False,
                        'reason': f'Price rallied too far (+{abs(price_diff_pct):.2f}%)'
                    }
            
            # Check if SL would be hit immediately
            if signal.sl_price and current_price >= float(signal.sl_price):
                return {
                    'valid': False,
                    'reason': 'Current price at/above SL level'
                }
        
        # Signal is still valid
        return {
            'valid': True,
            'reason': 'Signal conditions still valid'
        }
        
    except Exception as e:
        logger.error(f"Error validating signal {signal.id}: {e}")
        return {
            'valid': False,
            'reason': f'Validation error: {str(e)}'
        }


def run_signal_validation_worker():
    """
    Main worker function - validates all active signals
    Runs every 30 seconds
    """
    db = ScopedSession()
    try:
        # Get all active signals
        active_signals = db.query(TradingSignal).filter(
            TradingSignal.status == 'active'
        ).all()
        
        if not active_signals:
            logger.debug("No active signals to validate")
            return
        
        logger.info(f"🔍 Validating {len(active_signals)} active signals...")
        
        deactivated_count = 0
        
        for signal in active_signals:
            validation = validate_signal(db, signal)
            
            if not validation['valid']:
                # Deactivate invalid signal
                signal.status = 'expired'
                logger.warning(
                    f"❌ Signal #{signal.id} deactivated: {signal.symbol} {signal.timeframe} "
                    f"{signal.signal_type} - Reason: {validation['reason']}"
                )
                deactivated_count += 1
        
        if deactivated_count > 0:
            db.commit()
            logger.info(f"✅ Deactivated {deactivated_count} invalid signal(s)")
        else:
            logger.info("✅ All signals still valid")
            
    except Exception as e:
        logger.error(f"Signal validation worker error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    # For testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_signal_validation_worker()

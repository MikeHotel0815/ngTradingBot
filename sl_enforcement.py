#!/usr/bin/env python3
"""
Stop Loss Enforcement Module

Ensures ALL trades have valid Stop Loss before execution.
Prevents catastrophic losses like XAGUSD -$78.92.

Features:
1. Signal-level SL validation (must be set during generation)
2. Trade-level SL validation (before execution)
3. Symbol-specific Max Loss limits
4. ATR-based fallback SL calculation
"""

import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from models import TradingSignal, BrokerSymbol, Account

logger = logging.getLogger(__name__)


class SLEnforcement:
    """Enforce Stop Loss requirements across all trading operations"""

    # Symbol-specific maximum loss per trade (in account currency)
    # UPDATED 2025-10-27: Relaxed limits for aggressive trading mode
    # Previous limits (2025-10-26) were too strict and blocked all trades
    # Balance: Conservative SL protection vs. Allowing trades to execute
    MAX_LOSS_PER_TRADE = {
        'XAGUSD': 8.00,   # Silver: Max 8 EUR loss (relaxed from 3 EUR)
        'XAUUSD': 100.00, # Gold: Max 100 EUR loss (relaxed from 5 EUR - volatile but profitable)
        'DE40.c': 10.00,  # DAX: Max 10 EUR loss (relaxed from 3 EUR)
        'US500.c': 15.00, # S&P500: Max 15 EUR loss (relaxed from 2 EUR - high frequency)
        'BTCUSD': 25.00,  # Bitcoin: Max 25 EUR loss (relaxed from 15 EUR - 87% WR, +64 EUR/month)
        'ETHUSD': 10.00,  # Ethereum: Max 10 EUR loss (relaxed from 6 EUR)
        'USDJPY': 6.00,   # USDJPY: Max 6 EUR loss (relaxed from 2 EUR)
        'EURUSD': 6.00,   # EURUSD: Max 6 EUR loss (relaxed from 2 EUR)
        'GBPUSD': 6.00,   # GBPUSD: Max 6 EUR loss (relaxed from 2 EUR)
        'AUDUSD': 6.00,   # AUDUSD: Max 6 EUR loss (relaxed from 2 EUR)
        'FOREX': 6.00,    # Default Forex: Max 6 EUR loss (relaxed from 2 EUR)
        'DEFAULT': 10.00  # Fallback: Max 10 EUR loss (relaxed from 2.5 EUR - aggressive mode)
    }

    # Minimum SL distance as percentage of entry price
    MIN_SL_DISTANCE_PCT = {
        'XAGUSD': 0.3,    # 0.3% minimum (~15 pips at $50)
        'XAUUSD': 0.2,    # 0.2% minimum (~$5 at $2500)
        'DE40.c': 0.4,    # 0.4% minimum (~70 points at 18000)
        'US500.c': 0.3,   # 0.3% minimum
        'FOREX': 0.1,     # 0.1% minimum (~10 pips)
        'CRYPTO': 0.5,    # 0.5% minimum (volatile)
        'DEFAULT': 0.15   # 0.15% default
    }

    def __init__(self):
        pass

    def validate_signal_sl(
        self,
        signal: TradingSignal,
        db: Session
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Validate that signal has valid Stop Loss

        Args:
            signal: TradingSignal object
            db: Database session

        Returns:
            (is_valid, reason, suggested_sl)
            - is_valid: True if SL is valid
            - reason: Explanation if invalid
            - suggested_sl: Calculated SL if current one is invalid
        """
        # Check 1: SL must be set and non-zero
        sl_price = getattr(signal, 'sl_price', None) or getattr(signal, 'sl', None)

        if not sl_price or float(sl_price) == 0:
            # Calculate fallback SL
            suggested_sl = self._calculate_fallback_sl(
                db=db,
                symbol=signal.symbol,
                signal_type=signal.signal_type,
                entry_price=float(signal.entry_price)
            )

            return (
                False,
                f"SL is not set (sl={sl_price}). CRITICAL: All signals MUST have Stop Loss!",
                suggested_sl
            )

        entry = float(signal.entry_price)
        sl = float(sl_price)

        # Check 2: SL must be in correct direction
        if signal.signal_type == 'BUY':
            if sl >= entry:
                return (False, f"BUY signal SL ({sl}) must be BELOW entry ({entry})", None)
        else:  # SELL
            if sl <= entry:
                return (False, f"SELL signal SL ({sl}) must be ABOVE entry ({entry})", None)

        # Check 3: SL distance must be reasonable (not too tight)
        sl_distance_pct = abs(entry - sl) / entry * 100
        min_distance = self._get_min_sl_distance(signal.symbol)

        if sl_distance_pct < min_distance:
            return (
                False,
                f"SL too tight: {sl_distance_pct:.2f}% (min: {min_distance}%)",
                None
            )

        # Check 4: Max loss limit
        max_loss_check = self._validate_max_loss(
            db=db,
            symbol=signal.symbol,
            entry_price=entry,
            sl_price=sl,
            volume=0.01  # Use minimum volume for validation
        )

        if not max_loss_check['valid']:
            return (False, max_loss_check['reason'], max_loss_check['suggested_sl'])

        # All checks passed
        return (True, "SL valid", None)

    def validate_trade_sl(
        self,
        db: Session,
        symbol: str,
        signal_type: str,
        entry_price: float,
        sl_price: float,
        volume: float
    ) -> Dict:
        """
        Validate SL before trade execution

        Args:
            db: Database session
            symbol: Trading symbol
            signal_type: 'BUY' or 'SELL'
            entry_price: Entry price
            sl_price: Stop Loss price
            volume: Trade volume (lot size)

        Returns:
            {
                'valid': bool,
                'reason': str,
                'max_loss_eur': float,
                'suggested_sl': float or None
            }
        """
        # Check 1: SL must be set
        if not sl_price or sl_price == 0:
            suggested_sl = self._calculate_fallback_sl(db, symbol, signal_type, entry_price)
            return {
                'valid': False,
                'reason': 'SL is 0.00 - REJECTED! All trades MUST have Stop Loss.',
                'max_loss_eur': 0,
                'suggested_sl': suggested_sl
            }

        # Check 2: Direction validation
        if signal_type == 'BUY' and sl_price >= entry_price:
            return {
                'valid': False,
                'reason': f'BUY trade SL ({sl_price}) must be below entry ({entry_price})',
                'max_loss_eur': 0,
                'suggested_sl': None
            }

        if signal_type == 'SELL' and sl_price <= entry_price:
            return {
                'valid': False,
                'reason': f'SELL trade SL ({sl_price}) must be above entry ({entry_price})',
                'max_loss_eur': 0,
                'suggested_sl': None
            }

        # Check 3: Max loss limit
        return self._validate_max_loss(db, symbol, entry_price, sl_price, volume)

    def _validate_max_loss(
        self,
        db: Session,
        symbol: str,
        entry_price: float,
        sl_price: float,
        volume: float
    ) -> Dict:
        """
        Validate trade doesn't exceed max loss limit

        Returns:
            {
                'valid': bool,
                'reason': str,
                'max_loss_eur': float,
                'suggested_sl': float or None
            }
        """
        # Get broker symbol info
        broker_symbol = db.query(BrokerSymbol).filter_by(symbol=symbol).first()

        if not broker_symbol:
            logger.warning(f"Broker symbol {symbol} not found, using defaults")
            pip_value = 10.0  # Default: 10 EUR per lot per pip for forex
        else:
            # Calculate pip value
            contract_size = float(broker_symbol.contract_size or 100000)
            point = float(broker_symbol.point_value or 0.00001)
            pip_value = contract_size * point * 10  # 1 pip = 10 points

        # Calculate SL distance in pips
        sl_distance = abs(entry_price - sl_price)
        sl_distance_pips = sl_distance / (point * 10) if broker_symbol else sl_distance * 10000

        # Calculate potential loss
        potential_loss_eur = sl_distance_pips * pip_value * volume

        # Get max allowed loss for this symbol
        max_loss = self.MAX_LOSS_PER_TRADE.get(symbol)
        if not max_loss:
            # Check if it's a forex pair
            if any(curr in symbol for curr in ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']):
                max_loss = self.MAX_LOSS_PER_TRADE['FOREX']
            else:
                max_loss = self.MAX_LOSS_PER_TRADE['DEFAULT']

        if potential_loss_eur > max_loss:
            # Calculate suggested SL that respects max loss
            max_sl_distance_pips = max_loss / (pip_value * volume)
            max_sl_distance = max_sl_distance_pips * (point * 10) if broker_symbol else max_sl_distance_pips / 10000

            # Determine suggested SL based on direction
            if entry_price > sl_price:  # BUY
                suggested_sl = entry_price - max_sl_distance
            else:  # SELL
                suggested_sl = entry_price + max_sl_distance

            return {
                'valid': False,
                'reason': (
                    f'Max loss exceeded: {potential_loss_eur:.2f} EUR > {max_loss:.2f} EUR max. '
                    f'Reduce lot size or tighten SL.'
                ),
                'max_loss_eur': potential_loss_eur,
                'suggested_sl': suggested_sl
            }

        return {
            'valid': True,
            'reason': f'Max loss OK: {potential_loss_eur:.2f} EUR <= {max_loss:.2f} EUR',
            'max_loss_eur': potential_loss_eur,
            'suggested_sl': None
        }

    def _get_min_sl_distance(self, symbol: str) -> float:
        """Get minimum SL distance for symbol"""
        distance = self.MIN_SL_DISTANCE_PCT.get(symbol)
        if distance:
            return distance

        # Check category
        if 'BTC' in symbol or 'ETH' in symbol or 'CRYPTO' in symbol:
            return self.MIN_SL_DISTANCE_PCT['CRYPTO']
        elif any(curr in symbol for curr in ['USD', 'EUR', 'GBP', 'JPY']):
            return self.MIN_SL_DISTANCE_PCT['FOREX']
        else:
            return self.MIN_SL_DISTANCE_PCT['DEFAULT']

    def _calculate_fallback_sl(
        self,
        db: Session,
        symbol: str,
        signal_type: str,
        entry_price: float
    ) -> float:
        """
        Calculate fallback SL based on symbol-specific parameters

        Uses 1.5x ATR or fixed percentage if ATR not available
        """
        try:
            # Try to get ATR
            from technical_indicators import TechnicalIndicators

            # Use H1 timeframe for ATR (most stable)
            ti = TechnicalIndicators(account_id=1, symbol=symbol, timeframe='H1')
            atr_data = ti.calculate_atr()

            if atr_data and atr_data['value'] > 0:
                # Use 1.5x ATR for SL distance
                sl_distance = atr_data['value'] * 1.5

                if signal_type == 'BUY':
                    sl = entry_price - sl_distance
                else:  # SELL
                    sl = entry_price + sl_distance

                logger.info(f"Calculated fallback SL using ATR: {sl:.5f} (ATR={atr_data['value']:.5f}, distance={sl_distance:.5f})")
                return sl

        except Exception as e:
            logger.warning(f"ATR-based SL calculation failed: {e}")

        # Fallback: Use fixed percentage
        min_distance_pct = self._get_min_sl_distance(symbol)
        sl_distance = entry_price * (min_distance_pct * 2 / 100)  # 2x minimum distance

        if signal_type == 'BUY':
            sl = entry_price - sl_distance
        else:  # SELL
            sl = entry_price + sl_distance

        logger.info(f"Calculated fallback SL using {min_distance_pct*2}% distance: {sl:.5f}")
        return sl


# Global singleton
_sl_enforcement = None


def get_sl_enforcement() -> SLEnforcement:
    """Get global SL Enforcement instance"""
    global _sl_enforcement
    if _sl_enforcement is None:
        _sl_enforcement = SLEnforcement()
    return _sl_enforcement


def enforce_signal_sl(signal: TradingSignal, db: Session) -> bool:
    """
    Enforce SL on signal - update signal with valid SL if missing

    Args:
        signal: TradingSignal object
        db: Database session

    Returns:
        True if signal has valid SL (or was fixed), False if cannot be fixed
    """
    enforcer = get_sl_enforcement()
    is_valid, reason, suggested_sl = enforcer.validate_signal_sl(signal, db)

    if not is_valid:
        logger.warning(f"Signal #{signal.id} SL invalid: {reason}")

        if suggested_sl:
            # Update signal with suggested SL
            logger.info(f"Auto-fixing Signal #{signal.id} SL: {suggested_sl:.5f}")
            signal.sl_price = Decimal(str(suggested_sl))
            db.commit()
            return True
        else:
            # Cannot fix - reject signal
            logger.error(f"Cannot fix Signal #{signal.id} SL - marking as expired")
            signal.status = 'expired'
            db.commit()
            return False

    return True

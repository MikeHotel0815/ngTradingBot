#!/usr/bin/env python3
"""
Dynamic Position Sizing Calculator

Calculates optimal lot size based on:
1. Signal confidence (higher confidence = larger position)
2. Account balance (scales with growth)
3. Risk percentage per trade
4. Symbol volatility (ATR-based adjustment)

Prevents over-leveraging while maximizing profit on high-confidence signals.
"""

import logging
from typing import Dict, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from models import Account, BrokerSymbol
from sqlalchemy import text

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Dynamic position sizing with confidence-based multipliers
    """

    def __init__(self):
        # 🎯 DYNAMIC RISK TIERS - Risk per trade adjusts based on account size
        # Small accounts need lower risk % to survive, large accounts can take more risk
        self.balance_risk_tiers = [
            (0, 500, 1.0),          # <500€: 1.0% max risk per trade
            (500, 1000, 1.5),       # 500-1000€: 1.5% max risk
            (1000, 2000, 2.0),      # 1000-2000€: 2.0% max risk
            (2000, 5000, 2.5),      # 2000-5000€: 2.5% max risk
            (5000, 10000, 3.0),     # 5000-10k€: 3.0% max risk
            (10000, float('inf'), 3.5),  # >10k€: 3.5% max risk
        ]

        # Confidence-based multipliers (applied to base risk)
        self.confidence_multipliers = {
            'very_high': 1.3,  # 85%+ confidence: +30% more risk
            'high': 1.15,      # 75-84%: +15% more risk
            'medium': 1.0,     # 60-74%: base risk
            'low': 0.75,       # 50-59%: -25% less risk
            'very_low': 0.5,   # <50%: -50% less risk
        }

        # Symbol-specific risk adjustments (volatile assets = lower risk)
        self.symbol_risk_factors = {
            'BTCUSD': 0.4,   # Very volatile, heavily reduce risk
            'ETHUSD': 0.5,
            'XAUUSD': 0.6,   # Gold very volatile
            'XAGUSD': 0.5,   # Silver even more volatile
            'DE40.c': 0.8,   # Index moderately volatile
            'US500.c': 0.8,  # S&P500
            'EURUSD': 1.0,   # Stable forex, standard risk
            'GBPUSD': 0.9,   # Slightly more volatile than EUR
            'AUDUSD': 0.95,  # Somewhat stable
            'USDJPY': 1.0,
        }

        # Min/Max lot sizes
        self.min_lot_size = 0.01
        self.max_lot_size = 10.0  # Safety limit

        # Account balance tiers for base lot scaling (fallback)
        self.balance_tiers = [
            (0, 500, 0.01),        # <500 EUR: 0.01 lot base
            (500, 1000, 0.01),     # 500-1000: 0.01 lot
            (1000, 2000, 0.02),    # 1000-2000: 0.02 lot
            (2000, 5000, 0.03),    # 2000-5000: 0.03 lot
            (5000, 10000, 0.05),   # 5000-10k: 0.05 lot
            (10000, float('inf'), 0.10),  # >10k: 0.10 lot base
        ]

    def get_confidence_multiplier(self, confidence: float) -> float:
        """
        Get risk multiplier based on signal confidence

        Args:
            confidence: Signal confidence (0-100)

        Returns:
            Risk multiplier
        """
        if confidence >= 85:
            return self.confidence_multipliers['very_high']
        elif confidence >= 75:
            return self.confidence_multipliers['high']
        elif confidence >= 60:
            return self.confidence_multipliers['medium']
        elif confidence >= 50:
            return self.confidence_multipliers['low']
        else:
            return self.confidence_multipliers['very_low']

    def get_dynamic_risk_percent(self, balance: float) -> float:
        """
        🎯 Get dynamic risk percentage based on account balance

        Small accounts (<1000€) need conservative risk to survive drawdowns.
        Large accounts can take more risk as they have more buffer.

        Args:
            balance: Account balance in EUR

        Returns:
            Max risk percentage per trade (e.g., 1.5 for 1.5%)
        """
        for min_bal, max_bal, risk_pct in self.balance_risk_tiers:
            if min_bal <= balance < max_bal:
                logger.debug(f"Balance {balance:.2f}€ → Dynamic risk: {risk_pct}% per trade")
                return risk_pct

        # Fallback: minimum risk
        return 1.0

    def get_base_lot_from_balance(self, balance: float) -> float:
        """
        Get base lot size from account balance tier

        Args:
            balance: Account balance in EUR

        Returns:
            Base lot size
        """
        for min_bal, max_bal, lot_size in self.balance_tiers:
            if min_bal <= balance < max_bal:
                return lot_size

        return self.min_lot_size

    def get_symbol_risk_factor(self, symbol: str) -> float:
        """Get risk factor for symbol (lower = reduce position)"""
        symbol_upper = symbol.upper()
        return self.symbol_risk_factors.get(symbol_upper, 1.0)

    def calculate_lot_size(
        self,
        db: Session,
        account_id: int,
        symbol: str,
        confidence: float,
        sl_distance_pips: float,
        entry_price: float
    ) -> float:
        """
        Calculate optimal lot size

        Args:
            db: Database session
            account_id: Account ID
            symbol: Trading symbol
            confidence: Signal confidence (0-100)
            sl_distance_pips: Distance to SL in pips
            entry_price: Entry price

        Returns:
            Lot size (rounded to symbol's lot step)
        """
        try:
            # Get account balance
            account = db.query(Account).filter_by(id=account_id).first()
            if not account or not account.balance:
                logger.warning(f"Account {account_id} not found or no balance, using min lot")
                return self.min_lot_size

            balance = float(account.balance)

            # 🎯 DYNAMIC RISK: Get balance-appropriate risk percentage
            # Small accounts (1000€) → 1.5% max, Large accounts (10k€) → 3.5% max
            dynamic_risk_percent = self.get_dynamic_risk_percent(balance)

            # Get symbol info
            broker_symbol = db.query(BrokerSymbol).filter_by(
                symbol=symbol
            ).first()

            if not broker_symbol:
                logger.warning(f"Symbol {symbol} not found in broker symbols, using min lot")
                return self.min_lot_size

            contract_size = float(broker_symbol.contract_size or 100000)
            lot_step = float(broker_symbol.volume_step or 0.01)

            # 1. Get base lot from balance tier (fallback)
            base_lot = self.get_base_lot_from_balance(balance)

            # 2. Apply confidence multiplier
            confidence_multiplier = self.get_confidence_multiplier(confidence)

            # 3. Apply symbol risk factor
            symbol_risk_factor = self.get_symbol_risk_factor(symbol)

            # 4. Calculate risk-based lot size
            # 🎯 USE DYNAMIC RISK instead of GlobalSettings
            # Risk amount = balance * dynamic_risk% * confidence_mult * symbol_factor
            risk_amount = balance * (dynamic_risk_percent / 100) * confidence_multiplier * symbol_risk_factor

            # Convert pip distance to price distance
            point = float(broker_symbol.point_value)
            digits = int(broker_symbol.digits)

            # Calculate pip value (how much 1 pip movement = in account currency)
            # For standard lot (1.0), 1 pip = contract_size * point
            pip_value_per_lot = contract_size * point * 10  # 10 because 1 pip = 10 points

            # Calculate lot size from risk
            # lot_size = risk_amount / (sl_distance_pips * pip_value_per_lot)
            if sl_distance_pips > 0 and pip_value_per_lot > 0:
                risk_based_lot = risk_amount / (sl_distance_pips * pip_value_per_lot)
            else:
                risk_based_lot = base_lot

            # 5. Final lot = average of base_lot and risk_based_lot (prevents extremes)
            final_lot = (base_lot + risk_based_lot) / 2

            # 6. 🎯 Use dynamic risk percentage for max loss limit (balance-dependent)
            # Small accounts (1000€) get 1.5% max risk, large accounts (10k€) get 3.5%
            max_risk_pct = dynamic_risk_percent

            # Calculate max loss based on CURRENT balance (dynamic!)
            max_loss_limit = balance * (max_risk_pct / 100.0)

            # Calculate what loss this lot size would generate with current SL distance
            potential_loss = final_lot * sl_distance_pips * pip_value_per_lot

            # If potential loss exceeds limit, reduce lot size proportionally
            if potential_loss > max_loss_limit:
                # Calculate max safe lot size
                max_safe_lot = max_loss_limit / (sl_distance_pips * pip_value_per_lot)

                logger.warning(
                    f"⚠️ Reducing lot size for {symbol}: "
                    f"Original: {final_lot:.3f} lot (loss: €{potential_loss:.2f}) → "
                    f"Adjusted: {max_safe_lot:.3f} lot (max loss: €{max_loss_limit:.2f} "
                    f"= {max_risk_pct}% of €{balance:.2f})"
                )

                final_lot = max_safe_lot

            # 7. 🎯 STRICT BALANCE-SCALED VOLUME CAPS (BEFORE ROUNDING!)
            # Small accounts must have lower max lot size to prevent over-risking
            if balance < 500:
                max_volume_cap = 0.01  # <€500: max 0.01 lot
            elif balance < 1000:
                max_volume_cap = 0.03  # €500-1000: max 0.03 lot
            elif balance < 2000:
                max_volume_cap = 0.05  # €1000-2000: max 0.05 lot
            elif balance < 5000:
                max_volume_cap = 0.10  # €2000-5000: max 0.10 lot
            elif balance < 10000:
                max_volume_cap = 0.20  # €5000-10k: max 0.20 lot
            else:
                max_volume_cap = 0.50  # >€10k: max 0.50 lot

            # Apply balance-scaled cap BEFORE rounding
            if final_lot > max_volume_cap:
                logger.warning(
                    f"⚖️ BALANCE CAP: {symbol} lot {final_lot:.3f} "
                    f"exceeds max for €{balance:.2f} balance → capped at {max_volume_cap:.2f}"
                )
                final_lot = max_volume_cap

            # 8. Round to lot step
            final_lot = round(final_lot / lot_step) * lot_step

            # 9. Apply min/max limits
            final_lot = max(self.min_lot_size, min(self.max_lot_size, final_lot))

            # Recalculate final potential loss
            final_potential_loss = final_lot * sl_distance_pips * pip_value_per_lot

            logger.info(
                f"📊 Position Size: {symbol} | "
                f"Balance: €{balance:.2f} | "
                f"🎯 Dynamic Risk: {dynamic_risk_percent}% | "
                f"Confidence: {confidence:.1f}% (x{confidence_multiplier:.2f}) | "
                f"Symbol Factor: x{symbol_risk_factor:.2f} | "
                f"Base Lot: {base_lot:.2f} | "
                f"Risk Lot: {risk_based_lot:.3f} | "
                f"Final: {final_lot:.2f} lot | "
                f"Max Loss: €{final_potential_loss:.2f} (limit: €{max_loss_limit:.2f} = {dynamic_risk_percent}% of balance)"
            )

            return final_lot

        except Exception as e:
            logger.error(f"Error calculating lot size: {e}", exc_info=True)
            return self.min_lot_size

    def can_open_position(
        self,
        db: Session,
        account_id: int,
        symbol: str
    ) -> tuple[bool, str]:
        """
        Check if new position can be opened (correlation + exposure checks)

        Returns:
            (can_open, reason)
        """
        try:
            # Check max positions per symbol
            open_count = db.execute(text("""
                SELECT COUNT(*) as count
                FROM trades
                WHERE account_id = :account_id
                AND symbol = :symbol
                AND status = 'open'
            """), {'account_id': account_id, 'symbol': symbol}).fetchone()

            if open_count and open_count.count >= 1:
                return False, f"max_positions_per_symbol_{symbol}"

            # Check total open positions
            total_open = db.execute(text("""
                SELECT COUNT(*) as count
                FROM trades
                WHERE account_id = :account_id
                AND status = 'open'
            """), {'account_id': account_id}).fetchone()

            if total_open and total_open.count >= 5:
                return False, "max_total_positions_exceeded"

            return True, "ok"

        except Exception as e:
            logger.error(f"Error checking position limits: {e}")
            return False, "error_checking_limits"


# Global singleton
_position_sizer = None


def get_position_sizer() -> PositionSizer:
    """Get global PositionSizer instance"""
    global _position_sizer
    if _position_sizer is None:
        _position_sizer = PositionSizer()
    return _position_sizer

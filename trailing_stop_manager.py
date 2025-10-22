#!/usr/bin/env python3
"""
Smart Trailing Stop Manager for ngTradingBot
Implements multi-stage trailing stop strategy with break-even protection
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from models import Trade, Command, GlobalSettings, Tick, BrokerSymbol
from database import ScopedSession

logger = logging.getLogger(__name__)


class TrailingStopManager:
    """
    Smart trailing stop with multiple stages:

    Stage 1: Break-Even Move
    - When profit reaches X% of TP distance, move SL to entry (break-even + spread)

    Stage 2: Partial Trailing
    - When profit reaches Y% of TP distance, start trailing with wider distance

    Stage 3: Aggressive Trailing
    - When profit reaches Z% of TP distance, tighten trailing distance

    Stage 4: Near TP Protection
    - When very close to TP, aggressive trailing to lock in maximum profit
    """

    def __init__(self):
        self.redis = None  # Will be set by app.py if needed

        # Default settings (can be overridden by GlobalSettings)
        self.default_settings = {
            'trailing_stop_enabled': True,

            # Stage 1: Break-even - ✅ CONSERVATIVE (let profits run)
            'breakeven_enabled': True,
            'breakeven_trigger_percent': 50.0,  # ✅ Move to BE at 50% (was 20% - TOO AGGRESSIVE)
            'breakeven_offset_pips': 8.0,       # ✅ More breathing room (was 2.0 - TOO TIGHT)

            # Stage 2: Partial trailing - ✅ BALANCED
            'partial_trailing_trigger_percent': 60.0,  # ✅ Start at 60% (was 40%)
            'partial_trailing_distance_percent': 40.0,  # ✅ Trail 40% behind (was 30%)

            # Stage 3: Aggressive trailing - ✅ CONSERVATIVE
            'aggressive_trailing_trigger_percent': 75.0,  # ✅ Start at 75% (was 60%)
            'aggressive_trailing_distance_percent': 25.0,  # ✅ Trail 25% behind (was 15%)

            # Stage 4: Near TP protection - ✅ ONLY NEAR TP
            'near_tp_trigger_percent': 90.0,    # ✅ Start at 90% (was 80%)
            'near_tp_trailing_distance_percent': 15.0,  # ✅ Trail 15% behind (was 10%)

            # Stage 5: Dynamic TP Extension - 🎯 NEW!
            'dynamic_tp_enabled': True,         # 🎯 Enable dynamic TP raising
            'tp_extension_trigger_percent': 80.0,  # 🎯 Raise TP at 80% progress
            'tp_extension_multiplier': 1.5,     # 🎯 Extend by 50% of original distance

            # Safety settings
            'min_sl_distance_points': 10.0,     # Never set SL closer than this
            'max_sl_move_per_update': 100.0,    # Max points SL can move in one update
            'trailing_update_interval': 5,       # Only update every 5 seconds per trade
        }

        # ✅ NEW: Symbol-specific trailing stop configuration
        self.symbol_specific_settings = {
            'BTCUSD': {
                'max_sl_move_per_update': 500000.0,  # ✅ BTC needs MASSIVE movements (500k pips = 5000 price points at 0.01 point)
                'min_trailing_pips': 100.0,          # Minimum 100 pip trail for BTC
                'breakeven_trigger_percent': 15.0,  # 🚀 Even earlier breakeven for volatile asset
                'aggressive_trailing_trigger_percent': 50.0,  # 🚀 More aggressive
            },
            'ETHUSD': {
                'max_sl_move_per_update': 200000.0,  # ✅ ETH needs large movements (200k pips = 2000 price points at 0.01 point)
                'min_trailing_pips': 50.0,
                'breakeven_trigger_percent': 15.0,
                'aggressive_trailing_trigger_percent': 50.0,
            },
            'XAUUSD': {
                'max_sl_move_per_update': 10000.0,  # ✅ Gold uses 0.01 point, 10k pips = 100 price points
                'min_trailing_pips': 20.0,
                'breakeven_trigger_percent': 20.0,
                'aggressive_trailing_trigger_percent': 55.0,
            },
            'DE40.c': {
                'max_sl_move_per_update': 50000.0,  # ✅ DAX Index needs large movements (50k pips = 500 price points at 0.01 point)
                'min_trailing_pips': 50.0,
                'breakeven_trigger_percent': 20.0,
                'aggressive_trailing_trigger_percent': 55.0,
            },
            'EURUSD': {
                'max_sl_move_per_update': 100.0,   # Standard FOREX
                'min_trailing_pips': 10.0,
                'aggressive_trailing_trigger_percent': 60.0,  # ✅ Aggressive for EURUSD
            },
            'GBPUSD': {
                'max_sl_move_per_update': 100.0,
                'min_trailing_pips': 12.0,
                'aggressive_trailing_trigger_percent': 60.0,
            },
            'USDJPY': {
                'max_sl_move_per_update': 100.0,
                'min_trailing_pips': 10.0,
                'aggressive_trailing_trigger_percent': 60.0,  # ✅ Aggressive
            },
        }

        # Track last trailing stop update time per trade
        self.last_update_time = {}

    def _load_settings(self, db: Session, symbol: str = None) -> Dict:
        """
        Load trailing stop settings from database or use defaults.
        Applies symbol-specific overrides if symbol is provided.
        """
        try:
            settings = GlobalSettings.get_settings(db)

            # Merge with defaults
            result = self.default_settings.copy()

            # Override with database settings if they exist
            if hasattr(settings, 'trailing_stop_enabled'):
                result['trailing_stop_enabled'] = settings.trailing_stop_enabled
            if hasattr(settings, 'breakeven_trigger_percent'):
                result['breakeven_trigger_percent'] = float(settings.breakeven_trigger_percent)
            if hasattr(settings, 'partial_trailing_trigger_percent'):
                result['partial_trailing_trigger_percent'] = float(settings.partial_trailing_trigger_percent)

            # ✅ NEW: Apply symbol-specific settings
            if symbol and symbol in self.symbol_specific_settings:
                symbol_settings = self.symbol_specific_settings[symbol]
                result.update(symbol_settings)
                logger.debug(f"Applied symbol-specific TS settings for {symbol}: {symbol_settings}")

            return result

        except Exception as e:
            logger.warning(f"Could not load trailing stop settings, using defaults: {e}")
            return self.default_settings

    def get_symbol_info(self, db: Session, symbol: str, account_id: int) -> Dict:
        """Get symbol specifications from BrokerSymbol table (broker_symbols is global - no account_id)"""
        try:
            broker_symbol = db.query(BrokerSymbol).filter_by(
                symbol=symbol
            ).first()

            if broker_symbol:
                return {
                    'digits': int(broker_symbol.digits),
                    'point': float(broker_symbol.point_value),
                    'stops_level': int(broker_symbol.stops_level) if broker_symbol.stops_level else 10
                }
            else:
                # Fallback: derive from symbol name
                logger.warning(f"No BrokerSymbol entry for {symbol}, using fallback")
                if 'JPY' in symbol:
                    return {'digits': 3, 'point': 0.001, 'stops_level': 10}
                else:
                    return {'digits': 5, 'point': 0.00001, 'stops_level': 10}
        except Exception as e:
            logger.error(f"Error loading symbol info: {e}")
            # Safe fallback
            return {'digits': 5, 'point': 0.00001, 'stops_level': 10}

    def get_current_spread(self, db: Session, symbol: str, account_id: int) -> float:
        """Get current spread from latest tick (ticks are global - no account_id)"""
        try:
            latest_tick = db.query(Tick).filter_by(
                symbol=symbol
            ).order_by(Tick.timestamp.desc()).first()

            if latest_tick:
                spread = float(latest_tick.ask) - float(latest_tick.bid)
                return spread
            else:
                logger.warning(f"No tick data for {symbol}, using default spread")
                return 0.00020  # Default 2 pips spread
        except Exception as e:
            logger.error(f"Error getting spread: {e}")
            return 0.00020

    def calculate_dynamic_pip_distance(self, trade: Trade, db: Session, symbol_info: Dict) -> float:
        """
        Calculate dynamic pip distance based on position size and account balance
        Returns distance in PIPS (not price points)

        Logic:
        - Smaller positions (< 0.05 lots) = 10-20 pips
        - Medium positions (0.05-0.1 lots) = 20-30 pips
        - Larger positions (> 0.1 lots) = 30-50 pips
        - Adjusted by account balance (higher balance = can afford wider stops)
        """
        try:
            volume = float(trade.volume)

            # Get account balance
            from models import Account
            account = db.query(Account).filter_by(id=trade.account_id).first()
            balance = float(account.balance) if account and account.balance else 1000.0

            # Base pip distance calculation
            if volume <= 0.01:
                base_pips = 10  # Micro lots: very tight
            elif volume <= 0.05:
                base_pips = 15  # Small positions
            elif volume <= 0.1:
                base_pips = 25  # Medium positions
            elif volume <= 0.5:
                base_pips = 35  # Larger positions
            else:
                base_pips = 50  # Very large positions

            # Adjust based on account balance (risk management)
            # Larger accounts can afford slightly wider stops for better breathing room
            if balance >= 5000:
                balance_multiplier = 1.3
            elif balance >= 1000:
                balance_multiplier = 1.1
            else:
                balance_multiplier = 1.0  # Small accounts need tight stops

            dynamic_pips = base_pips * balance_multiplier

            # Apply min/max limits
            min_pips = max(10, symbol_info.get('stops_level', 10))
            max_pips = 100

            dynamic_pips = max(min_pips, min(dynamic_pips, max_pips))

            logger.debug(f"Dynamic pip calculation for {trade.symbol} (vol={volume}): "
                        f"base={base_pips}, balance_mult={balance_multiplier:.2f}, "
                        f"final={dynamic_pips:.2f} pips (limits: {min_pips}-{max_pips})")

            return dynamic_pips

        except Exception as e:
            logger.error(f"Error calculating dynamic pips: {e}")
            return 20.0  # Safe fallback

    def should_update_trailing_stop(self, trade: Trade) -> bool:
        """Check if enough time has passed since last update"""
        now = datetime.utcnow()
        last_update = self.last_update_time.get(trade.ticket)

        if not last_update:
            return True

        interval = self.default_settings['trailing_update_interval']
        elapsed = (now - last_update).total_seconds()

        return elapsed >= interval

    def calculate_trailing_stop(
        self,
        trade: Trade,
        current_price: float,
        settings: Dict,
        db: Session = None
    ) -> Optional[Dict]:
        """
        Calculate new trailing stop level based on current price and profit
        Uses dynamic pip calculation based on position size and account balance

        Returns:
            Dict with 'new_sl', 'stage', 'reason' or None if no adjustment needed
        """
        try:
            if not settings.get('trailing_stop_enabled', True):
                return None

            # Determine direction
            is_buy = trade.direction.upper() in ['BUY', '0'] if isinstance(trade.direction, str) else trade.direction == 0

            # Get entry, SL, TP
            entry_price = float(trade.open_price)
            current_sl = float(trade.sl) if trade.sl else None
            tp_price = float(trade.tp) if trade.tp else None

            if not tp_price:
                logger.debug(f"Trade {trade.ticket} has no TP, skipping trailing stop")
                return None

            if not current_sl:
                logger.debug(f"Trade {trade.ticket} has no SL, skipping trailing stop")
                return None

            # Get symbol specifications and spread
            if db:
                symbol_info = self.get_symbol_info(db, trade.symbol, trade.account_id)
                spread = self.get_current_spread(db, trade.symbol, trade.account_id)
                dynamic_pips = self.calculate_dynamic_pip_distance(trade, db, symbol_info)

                # Store for use in calculations
                settings['dynamic_trailing_pips'] = dynamic_pips
                settings['symbol_point'] = symbol_info['point']
                settings['symbol_digits'] = symbol_info['digits']
                settings['current_spread'] = spread

                logger.info(f"Trade {trade.ticket}: Using {dynamic_pips:.2f} pips trailing stop "
                           f"(point={symbol_info['point']}, spread={spread/symbol_info['point']:.1f} pips)")
            else:
                settings['dynamic_trailing_pips'] = 20.0  # Fallback
                settings['symbol_point'] = 0.00001
                settings['symbol_digits'] = 5
                settings['current_spread'] = 0.00020

            # Calculate distances
            if is_buy:
                # BUY trade
                tp_distance = tp_price - entry_price
                current_profit_distance = current_price - entry_price
                sl_distance = current_price - current_sl
            else:
                # SELL trade
                tp_distance = entry_price - tp_price
                current_profit_distance = entry_price - current_price
                sl_distance = current_sl - current_price

            # Calculate profit as percentage of TP distance
            profit_percent = (current_profit_distance / tp_distance * 100) if tp_distance > 0 else 0

            logger.debug(
                f"Trade {trade.ticket} ({trade.symbol}): "
                f"Profit {profit_percent:.1f}% of TP distance, "
                f"Current SL distance: {sl_distance:.5f}, "
                f"Dynamic pips: {settings.get('dynamic_trailing_pips', 20):.2f}"
            )

            # Determine which stage to apply
            new_sl = None
            stage = None
            reason = None

            # Stage 4: Near TP Protection (highest priority)
            if profit_percent >= settings['near_tp_trigger_percent']:
                new_sl, reason = self._calculate_near_tp_protection(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "near_tp"

            # Stage 3: Aggressive Trailing
            elif profit_percent >= settings['aggressive_trailing_trigger_percent']:
                new_sl, reason = self._calculate_aggressive_trailing(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "aggressive"

            # Stage 2: Partial Trailing
            elif profit_percent >= settings['partial_trailing_trigger_percent']:
                new_sl, reason = self._calculate_partial_trailing(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "partial"

            # Stage 1: Break-even
            elif settings.get('breakeven_enabled') and profit_percent >= settings['breakeven_trigger_percent']:
                new_sl, reason = self._calculate_breakeven(
                    is_buy, entry_price, settings
                )
                stage = "breakeven"

            # No stage triggered
            if not new_sl:
                return None

            # 🎯 DYNAMIC TP EXTENSION - Check if TP should be raised
            tp_extension_result = None
            if settings.get('dynamic_tp_enabled', True):
                tp_extension_result = self._check_and_extend_tp(
                    trade, profit_percent, is_buy, entry_price, tp_price, current_price, settings, db
                )

            # Validate new SL
            if not self._validate_new_sl(is_buy, new_sl, current_sl, current_price, settings):
                return None

            # Check if SL actually needs to move
            sl_change = abs(new_sl - current_sl)
            if sl_change < 0.00001:  # Less than 0.1 pip
                return None

            # Only move SL in profit direction (never worse)
            if is_buy:
                if new_sl <= current_sl:
                    return None  # Don't move SL down
            else:
                if new_sl >= current_sl:
                    return None  # Don't move SL up

            logger.info(
                f"🎯 Trailing Stop [{stage.upper()}]: Trade {trade.ticket} ({trade.symbol}) - "
                f"Moving SL from {current_sl:.5f} to {new_sl:.5f} ({reason})"
            )

            result = {
                'new_sl': round(new_sl, 5),
                'stage': stage,
                'reason': reason,
                'profit_percent': round(profit_percent, 1)
            }

            # 🎯 Add TP extension info if it happened
            if tp_extension_result:
                result['tp_extended'] = True
                result['new_tp'] = tp_extension_result['new_tp']
                result['tp_extension_reason'] = tp_extension_result['reason']

            return result

        except Exception as e:
            logger.error(f"Error calculating trailing stop for trade {trade.ticket}: {e}")
            return None

    def _calculate_breakeven(
        self,
        is_buy: bool,
        entry_price: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate break-even SL with spread protection"""
        symbol_point = settings.get('symbol_point', 0.00001)
        spread = settings.get('current_spread', 0.00020)
        dynamic_pips = settings.get('dynamic_trailing_pips', 20.0)

        # Offset = spread + 30% of dynamic trailing pips (for safety buffer)
        spread_pips = spread / symbol_point
        safety_pips = dynamic_pips * 0.3
        total_offset_pips = spread_pips + safety_pips
        offset = total_offset_pips * symbol_point

        if is_buy:
            new_sl = entry_price + offset  # Entry + spread + buffer
        else:
            new_sl = entry_price - offset  # Entry - spread - buffer

        return new_sl, f"Break-even + {total_offset_pips:.1f} pips (spread {spread_pips:.1f} + buffer {safety_pips:.1f})"

    def _calculate_partial_trailing(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate partial trailing SL using dynamic pip distance"""
        symbol_point = settings.get('symbol_point', 0.00001)
        dynamic_pips = settings.get('dynamic_trailing_pips', 20.0)

        # Use 100% of dynamic pips for partial trailing
        trail_distance = dynamic_pips * symbol_point

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Partial trail {dynamic_pips:.1f} pips"

    def _calculate_aggressive_trailing(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate aggressive trailing SL using tighter dynamic pips"""
        symbol_point = settings.get('symbol_point', 0.00001)
        dynamic_pips = settings.get('dynamic_trailing_pips', 20.0)

        # Use 60% of dynamic pips for aggressive trailing (tighter)
        aggressive_pips = dynamic_pips * 0.6
        trail_distance = aggressive_pips * symbol_point

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Aggressive trail {aggressive_pips:.1f} pips"

    def _calculate_near_tp_protection(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate near-TP protection SL using very tight dynamic pips"""
        symbol_point = settings.get('symbol_point', 0.00001)
        dynamic_pips = settings.get('dynamic_trailing_pips', 20.0)

        # Use 40% of dynamic pips for near-TP protection (very tight)
        near_tp_pips = dynamic_pips * 0.4
        trail_distance = near_tp_pips * symbol_point

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Near-TP protection {near_tp_pips:.1f} pips"

    def _check_and_extend_tp(
        self,
        trade: Trade,
        profit_percent: float,
        is_buy: bool,
        entry_price: float,
        current_tp: float,
        current_price: float,
        settings: Dict,
        db: Session
    ) -> Optional[Dict]:
        """
        🎯 DYNAMIC TP EXTENSION
        
        Extends TP when trade reaches 80%+ progress towards current TP.
        This allows trades to "ride the trend" and maximize profits.
        
        Logic:
        - Trigger at 80% of distance to current TP (configurable)
        - Extend TP by 50% of ORIGINAL distance (not current)
        - Can extend multiple times for strong trends
        - Safety: Track extensions to prevent runaway TPs
        
        Returns:
        - Dict with new_tp and reason if extended
        - None if no extension needed
        """
        try:
            trigger_percent = settings.get('tp_extension_trigger_percent', 80.0)
            extension_multiplier = settings.get('tp_extension_multiplier', 1.5)
            max_extensions = 5  # Safety: Max 5 extensions per trade
            
            # Only extend if we've reached trigger threshold
            if profit_percent < trigger_percent:
                return None
                
            # Get original TP (stored when trade opened)
            original_tp = float(trade.original_tp) if trade.original_tp else float(current_tp)
            
            # Safety check: Don't extend too many times
            extension_count = trade.tp_extended_count if trade.tp_extended_count else 0
            if extension_count >= max_extensions:
                logger.debug(f"Trade {trade.ticket}: Max TP extensions ({max_extensions}) reached")
                return None
            
            # Calculate original TP distance
            if is_buy:
                original_distance = original_tp - entry_price
            else:
                original_distance = entry_price - original_tp
                
            # Calculate new extended TP
            # Extension = original_distance * (multiplier - 1.0)
            # Example: 50 pips original * (1.5 - 1.0) = 25 pips extension
            extension_distance = original_distance * (extension_multiplier - 1.0)
            
            if is_buy:
                new_tp = current_tp + extension_distance
                # Safety: TP must be above current price
                if new_tp <= current_price:
                    return None
            else:
                new_tp = current_tp - extension_distance
                # Safety: TP must be below current price
                if new_tp >= current_price:
                    return None
            
            # 🎯 Update trade in database
            if not trade.original_tp:
                trade.original_tp = current_tp  # Store original TP first time
                
            trade.tp = new_tp
            trade.tp_extended_count = extension_count + 1
            db.commit()
            
            # 🎯 Create modify_tp command for MT5
            from models import Command
            import uuid
            
            command_id = str(uuid.uuid4())
            modify_command = Command(
                id=command_id,
                account_id=trade.account_id,
                command_type='MODIFY_TRADE',  # ✅ Use MODIFY_TRADE (supports both SL and TP)
                payload={
                    'ticket': int(trade.ticket),
                    'sl': round(float(trade.sl), 5),  # ✅ Keep current SL
                    'tp': round(new_tp, 5),  # ✅ New extended TP
                    'reason': f'dynamic_extension_{extension_count + 1}',
                    'original_tp': round(float(original_tp), 5),
                    'extension_pips': round(extension_distance / settings.get('symbol_point', 0.00001), 1)
                },
                status='pending'
            )
            db.add(modify_command)
            db.commit()
            
            logger.info(
                f"🚀 TP EXTENDED: Trade {trade.ticket} ({trade.symbol}) - "
                f"Extension #{extension_count + 1}: TP {current_tp:.5f} → {new_tp:.5f} "
                f"(+{extension_distance / settings.get('symbol_point', 0.00001):.1f} pips)"
            )
            
            return {
                'new_tp': round(new_tp, 5),
                'reason': f'Extended by {extension_distance / settings.get("symbol_point", 0.00001):.1f} pips (#{extension_count + 1})',
                'extension_count': extension_count + 1
            }
            
        except Exception as e:
            logger.error(f"Error extending TP for trade {trade.ticket}: {e}")
            return None

    def _validate_new_sl(
        self,
        is_buy: bool,
        new_sl: float,
        current_sl: float,
        current_price: float,
        settings: Dict
    ) -> bool:
        """Validate that new SL is safe and makes sense"""

        # Check minimum distance from current price
        min_distance = settings['min_sl_distance_points'] * 0.00001
        actual_distance = abs(new_sl - current_price)

        if actual_distance < min_distance:
            logger.debug(f"New SL too close to price ({actual_distance:.5f} < {min_distance:.5f})")
            return False

        # Check max movement per update
        # ✅ FIX: Use symbol point instead of hardcoded 0.00001
        symbol_point = settings.get('symbol_point', 0.00001)
        max_move = settings['max_sl_move_per_update'] * symbol_point
        sl_movement = abs(new_sl - current_sl)

        if sl_movement > max_move:
            logger.warning(f"SL movement too large ({sl_movement:.5f} > {max_move:.5f}) "
                         f"[max_move_pips={settings['max_sl_move_per_update']}, point={symbol_point}]")
            return False

        # Ensure SL is on correct side of price
        if is_buy:
            if new_sl >= current_price:
                logger.warning(f"Invalid BUY SL: {new_sl:.5f} >= {current_price:.5f}")
                return False
        else:
            if new_sl <= current_price:
                logger.warning(f"Invalid SELL SL: {new_sl:.5f} <= {current_price:.5f}")
                return False

        return True

    def send_sl_modify_command(
        self,
        db: Session,
        trade: Trade,
        new_sl: float,
        reason: str
    ) -> bool:
        """
        Send command to MT5 EA to modify stop loss

        Returns:
            True if command created successfully
        """
        try:
            # Create modify command (EA expects MODIFY_TRADE with both SL and TP)
            import uuid
            command = Command(
                id=str(uuid.uuid4()),
                account_id=trade.account_id,
                command_type='MODIFY_TRADE',
                status='pending',
                created_at=datetime.utcnow(),
                payload={
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'sl': float(new_sl),
                    'tp': float(trade.tp) if trade.tp else 0.0,  # EA requires TP field
                }
            )

            db.add(command)
            db.commit()

            # Update last update time
            self.last_update_time[trade.ticket] = datetime.utcnow()

            logger.info(
                f"✅ SL Modify command created: Ticket {trade.ticket} → "
                f"New SL {new_sl:.5f} ({reason})"
            )

            return True

        except Exception as e:
            logger.error(f"Error creating SL modify command: {e}")
            db.rollback()
            return False

    def process_trade(
        self,
        db: Session,
        trade: Trade,
        current_price: float
    ) -> Optional[Dict]:
        """
        Process a single trade for trailing stop adjustment

        Returns:
            Dict with result info or None if no action taken
        """
        try:
            # Check if update is needed (rate limiting)
            if not self.should_update_trailing_stop(trade):
                return None

            # Load settings (with symbol-specific overrides)
            settings = self._load_settings(db, symbol=trade.symbol)

            # Calculate new trailing stop with dynamic pip calculation
            result = self.calculate_trailing_stop(trade, current_price, settings, db=db)

            if not result:
                return None

            # Send modify command
            success = self.send_sl_modify_command(
                db=db,
                trade=trade,
                new_sl=result['new_sl'],
                reason=result['reason']
            )

            if success:
                return {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'stage': result['stage'],
                    'old_sl': float(trade.sl),
                    'new_sl': result['new_sl'],
                    'reason': result['reason'],
                    'profit_percent': result['profit_percent']
                }

            return None

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket} for trailing stop: {e}")
            return None

    def _calculate_price_to_eur(self, symbol: str, price_diff: float, volume: float, current_price: float, eurusd_rate: float = 1.0) -> float:
        """
        Convert price difference to EUR value using MT5-accurate formulas.

        This mimics exactly how MT5 calculates profit, then converts to account currency (EUR).

        Args:
            symbol: Trading symbol (e.g., 'EURUSD', 'USDJPY', 'XAUUSD')
            price_diff: Price difference in symbol's price units
            volume: Position volume in lots
            current_price: Current market price (for JPY pairs conversion)
            eurusd_rate: Current EUR/USD exchange rate for USD->EUR conversion

        Returns:
            EUR value of the price difference
        """
        from spread_utils import get_contract_size

        symbol_upper = symbol.upper()
        contract_size = get_contract_size(symbol)

        # For XXX/EUR pairs: quote currency is EUR - direct calculation!
        if symbol_upper.endswith('EUR'):
            return price_diff * volume * contract_size

        # For XXX/USD pairs: quote currency is USD
        elif symbol_upper.endswith('USD'):
            profit_in_usd = price_diff * volume * contract_size
            # Convert USD to EUR: 1 USD = 1/eurusd_rate EUR
            profit_in_eur = profit_in_usd / eurusd_rate
            return profit_in_eur

        # For XXX/JPY pairs: quote currency is JPY
        elif symbol_upper.endswith('JPY'):
            # Profit in JPY
            profit_in_jpy = price_diff * volume * 100000
            # Convert JPY to USD
            profit_in_usd = profit_in_jpy / current_price
            # Convert USD to EUR
            profit_in_eur = profit_in_usd / eurusd_rate
            return profit_in_eur

        # For EUR/XXX pairs: base currency is EUR
        elif symbol_upper.startswith('EUR'):
            if symbol_upper == 'EURUSD':
                profit_in_usd = price_diff * volume * contract_size
                profit_in_eur = profit_in_usd / eurusd_rate
                return profit_in_eur
            elif symbol_upper == 'EURJPY':
                profit_in_jpy = price_diff * volume * 100000
                profit_in_usd = profit_in_jpy / current_price
                profit_in_eur = profit_in_usd / eurusd_rate
                return profit_in_eur
            else:
                profit_in_quote = price_diff * volume * contract_size
                profit_in_usd = profit_in_quote * 1.25  # Approximate for GBP
                profit_in_eur = profit_in_usd / eurusd_rate
                return profit_in_eur

        # For other pairs: quote = USD
        else:
            profit_in_usd = price_diff * volume * contract_size
            profit_in_eur = profit_in_usd / eurusd_rate
            return profit_in_eur

    def get_trailing_stop_info(
        self,
        trade: Trade,
        current_price: float,
        db: Session
    ) -> Optional[Dict]:
        """
        Get current trailing stop information for display purposes

        Returns:
            Dict with trailing stop stage, profit %, next trigger, etc.
        """
        try:
            # Load settings (with symbol-specific overrides)
            settings = self._load_settings(db, symbol=trade.symbol)

            if not settings.get('trailing_stop_enabled', True):
                return None

            # Determine direction
            is_buy = trade.direction.upper() in ['BUY', '0'] if isinstance(trade.direction, str) else trade.direction == 0

            # Get entry, SL, TP (convert all to float to avoid Decimal type issues)
            try:
                entry_price = float(trade.open_price) if trade.open_price is not None else 0.0
                current_sl = float(trade.sl) if trade.sl is not None else None
                tp_price = float(trade.tp) if trade.tp is not None else None
                current_price = float(current_price) if current_price is not None else 0.0
            except (ValueError, TypeError) as e:
                logger.error(f"Error converting trade {trade.ticket} values to float: {e}")
                return None

            if not tp_price or not current_sl:
                return None

            # Calculate distances
            if is_buy:
                tp_distance = tp_price - entry_price
                current_profit_distance = current_price - entry_price
                sl_distance_pips = (current_price - current_sl) / 0.0001  # Rough pip estimate
                sl_distance_price = current_price - current_sl
            else:
                tp_distance = entry_price - tp_price
                current_profit_distance = entry_price - current_price
                sl_distance_pips = (current_sl - current_price) / 0.0001  # Rough pip estimate
                sl_distance_price = current_sl - current_price

            # Calculate profit as percentage of TP distance
            profit_percent = (current_profit_distance / tp_distance * 100) if tp_distance > 0 else 0

            # Calculate EUR value for SL distance using MT5-accurate conversion
            volume = float(trade.volume) if trade.volume else 0.0

            # Get EUR/USD rate for accurate conversion from latest tick data
            from models import Tick
            from sqlalchemy import desc
            eurusd_rate = 1.0  # Fallback
            try:
                # Ticks are global - no account_id
                eurusd_tick_bid = db.query(Tick.bid).filter(
                    Tick.symbol == 'EURUSD'
                ).order_by(desc(Tick.timestamp)).first()
                if eurusd_tick_bid and eurusd_tick_bid[0]:
                    eurusd_rate = float(eurusd_tick_bid[0])
            except Exception as e:
                logger.debug(f"Could not get EURUSD rate from ticks: {e}")

            if sl_distance_price > 0:
                sl_distance_eur = self._calculate_price_to_eur(
                    trade.symbol, sl_distance_price, volume, current_price, eurusd_rate
                )
            else:
                sl_distance_eur = 0

            # Calculate protected profit/loss (from entry to SL)
            # This is the actual P&L if SL is hit, can be negative!
            if is_buy:
                protected_profit_distance = current_sl - entry_price  # Can be negative
            else:
                protected_profit_distance = entry_price - current_sl  # Can be negative

            # Always calculate the EUR value, even if it's a loss
            protected_profit_eur = self._calculate_price_to_eur(
                trade.symbol, abs(protected_profit_distance), volume, current_price, eurusd_rate
            )
            # Apply sign: negative if it's a loss
            if protected_profit_distance < 0:
                protected_profit_eur = -protected_profit_eur

            # Determine current stage
            stage = None
            stage_label = "None"
            next_trigger = None
            next_trigger_percent = None

            if profit_percent >= settings['near_tp_trigger_percent']:
                stage = "near_tp"
                stage_label = "Near TP"
                next_trigger = None  # Final stage
            elif profit_percent >= settings['aggressive_trailing_trigger_percent']:
                stage = "aggressive"
                stage_label = "Aggressive"
                next_trigger = "Near TP"
                next_trigger_percent = settings['near_tp_trigger_percent']
            elif profit_percent >= settings['partial_trailing_trigger_percent']:
                stage = "partial"
                stage_label = "Partial"
                next_trigger = "Aggressive"
                next_trigger_percent = settings['aggressive_trailing_trigger_percent']
            elif settings.get('breakeven_enabled') and profit_percent >= settings['breakeven_trigger_percent']:
                stage = "breakeven"
                stage_label = "Break-Even"
                next_trigger = "Partial"
                next_trigger_percent = settings['partial_trailing_trigger_percent']
            else:
                stage = "waiting"
                stage_label = "Waiting"
                next_trigger = "Break-Even" if settings.get('breakeven_enabled') else "Partial"
                next_trigger_percent = settings['breakeven_trigger_percent'] if settings.get('breakeven_enabled') else settings['partial_trailing_trigger_percent']

            return {
                'enabled': True,
                'stage': stage,
                'stage_label': stage_label,
                'profit_percent': round(profit_percent, 1),
                'sl_distance_pips': round(sl_distance_pips, 1),
                'sl_distance_eur': round(sl_distance_eur, 2),
                'protected_profit_eur': round(protected_profit_eur, 2),
                'next_trigger': next_trigger,
                'next_trigger_percent': next_trigger_percent
            }

        except Exception as e:
            logger.error(f"Error getting trailing stop info for trade {trade.ticket}: {e}")
            return None


# Singleton instance
_manager = None


def get_trailing_stop_manager():
    """Get or create trailing stop manager instance"""
    global _manager
    if _manager is None:
        _manager = TrailingStopManager()
    return _manager

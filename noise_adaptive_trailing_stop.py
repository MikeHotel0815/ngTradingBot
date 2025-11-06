"""
Noise-Adaptive Trailing Stop System
Dynamically adjusts trailing stop distance based on:
- 60-second tick volatility
- Trading session (Asia/London/US/Overlap)
- Market regime (TRENDING/RANGING/CHOPPY)
- Progress toward Take Profit
- Current spread

Formula: Final_Distance = (Base_ATR × Vol_60s × Session × Progress × Regime) + Spread_Buffer
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from sqlalchemy import func
from models import Trade, Tick
from technical_indicators import TechnicalIndicators
from session_volatility_analyzer import SessionVolatilityAnalyzer
from smart_tp_sl import SymbolConfig

logger = logging.getLogger(__name__)


class NoiseAdaptiveTrailingStop:
    """
    Unified trailing stop system that adapts to market noise in real-time.
    Combines best features from multiple existing implementations.
    """

    def __init__(self, account_id: int = 3):
        self.account_id = account_id
        self.session_analyzer = SessionVolatilityAnalyzer()

        # Symbol-specific noise profiles (from smart_trailing_stop_v2.py)
        self.noise_profiles = {
            'BTCUSD': {
                'typical_spread': 0.10,
                'noise_threshold': 0.15,
                'calm_threshold': 0.05,
                'volatile_threshold': 0.50,
            },
            'XAUUSD': {
                'typical_spread': 0.30,
                'noise_threshold': 0.50,
                'calm_threshold': 0.10,
                'volatile_threshold': 2.00,
            },
            'XAGUSD': {
                'typical_spread': 0.010,
                'noise_threshold': 0.025,
                'calm_threshold': 0.005,
                'volatile_threshold': 0.10,
            },
            'EURUSD': {
                'typical_spread': 0.00010,  # 1 pip
                'noise_threshold': 0.00020,  # 2 pips
                'calm_threshold': 0.00005,   # 0.5 pip
                'volatile_threshold': 0.00050, # 5 pips
            },
            'GBPUSD': {
                'typical_spread': 0.00015,
                'noise_threshold': 0.00025,
                'calm_threshold': 0.00008,
                'volatile_threshold': 0.00060,
            },
            'USDJPY': {
                'typical_spread': 0.010,
                'noise_threshold': 0.020,
                'calm_threshold': 0.005,
                'volatile_threshold': 0.050,
            },
            'AUDUSD': {
                'typical_spread': 0.00012,
                'noise_threshold': 0.00022,
                'calm_threshold': 0.00006,
                'volatile_threshold': 0.00055,
            },
            'US500.c': {
                'typical_spread': 0.50,
                'noise_threshold': 2.00,
                'calm_threshold': 0.80,
                'volatile_threshold': 8.00,
            },
            'DE40.c': {
                'typical_spread': 1.00,
                'noise_threshold': 3.00,
                'calm_threshold': 1.50,
                'volatile_threshold': 10.00,
            },
        }

    def analyze_60s_volatility(self, db, symbol: str, window_seconds: int = 60) -> Dict:
        """
        Analyze last 60 seconds of tick data to measure real-time market noise.

        Returns:
            {
                'volatility_score': 0.0-1.0,  # 0=calm, 1=very volatile
                'classification': 'calm'|'normal'|'volatile',
                'avg_jump': float,  # Average tick-to-tick movement
                'max_jump': float,  # Largest single tick movement
                'tick_count': int,
            }
        """
        cutoff_time = datetime.utcnow() - timedelta(seconds=window_seconds)

        ticks = db.query(Tick).filter(
            Tick.symbol == symbol,
            Tick.timestamp >= cutoff_time
        ).order_by(Tick.timestamp.asc()).all()

        if len(ticks) < 5:
            logger.warning(f"Insufficient tick data for {symbol}: {len(ticks)} ticks")
            return {
                'volatility_score': 0.5,
                'classification': 'normal',
                'avg_jump': 0.0,
                'max_jump': 0.0,
                'tick_count': len(ticks),
            }

        # Calculate tick-to-tick price jumps
        jumps = []
        for i in range(1, len(ticks)):
            prev_mid = (ticks[i-1].bid + ticks[i-1].ask) / 2
            curr_mid = (ticks[i].bid + ticks[i].ask) / 2
            jump = abs(curr_mid - prev_mid)
            jumps.append(jump)

        avg_jump = sum(jumps) / len(jumps) if jumps else 0.0
        max_jump = max(jumps) if jumps else 0.0

        # Get symbol-specific thresholds
        profile = self.noise_profiles.get(symbol, {
            'calm_threshold': avg_jump * 0.5,
            'noise_threshold': avg_jump * 1.5,
            'volatile_threshold': avg_jump * 3.0,
        })

        calm_threshold = profile.get('calm_threshold', 0.0001)
        noise_threshold = profile.get('noise_threshold', 0.0003)
        volatile_threshold = profile.get('volatile_threshold', 0.0010)

        # Classify volatility
        if avg_jump < calm_threshold:
            classification = 'calm'
            volatility_score = 0.3
        elif avg_jump < noise_threshold:
            classification = 'normal'
            volatility_score = 0.5
        elif avg_jump < volatile_threshold:
            classification = 'volatile'
            volatility_score = 0.8
        else:
            classification = 'very_volatile'
            volatility_score = 1.0

        logger.info(f"{symbol} 60s volatility: {classification} (avg_jump={avg_jump:.5f}, score={volatility_score:.2f})")

        return {
            'volatility_score': volatility_score,
            'classification': classification,
            'avg_jump': avg_jump,
            'max_jump': max_jump,
            'tick_count': len(ticks),
        }

    def get_base_atr(self, db, symbol: str, timeframe: str = 'M15') -> float:
        """
        Get base ATR value for the symbol.
        Uses TechnicalIndicators if OHLC data exists, otherwise fallback to profile.
        """
        try:
            ti = TechnicalIndicators(db, symbol=symbol, timeframe=timeframe, bars=50)
            atr_data = ti.calculate_atr(period=14)
            if atr_data and 'value' in atr_data:
                return atr_data['value']
        except Exception as e:
            logger.warning(f"Could not calculate ATR for {symbol}: {e}")

        # Fallback: Use asset class default
        for asset_class, config in SymbolConfig.ASSET_CLASSES.items():
            if symbol in config.get('symbols', []):
                fallback_atr_pct = config.get('fallback_atr_pct', 0.001)
                # Get approximate price from recent tick
                tick = db.query(Tick).filter(Tick.symbol == symbol).order_by(Tick.timestamp.desc()).first()
                if tick:
                    mid_price = (tick.bid + tick.ask) / 2
                    return mid_price * fallback_atr_pct

        # Ultimate fallback
        logger.warning(f"No ATR available for {symbol}, using default 0.001")
        return 0.001

    def get_session_multiplier(self, symbol: str, db) -> Tuple[float, str]:
        """
        Get session-based volatility multiplier.

        Returns:
            (multiplier, session_name)
            multiplier: 0.7 (Asian) to 1.5 (Overlap)
        """
        return self.session_analyzer.get_trailing_distance_multiplier(symbol, db, datetime.utcnow())

    def get_progress_multiplier(self, profit_pct_to_tp: float) -> float:
        """
        Progressive tightening as trade approaches TP.

        Args:
            profit_pct_to_tp: Percentage of distance from entry to TP (0-100)

        Returns:
            multiplier: 1.0 (early) to 0.3 (near TP)
        """
        if profit_pct_to_tp < 25:
            return 1.0  # Wide trailing
        elif profit_pct_to_tp < 50:
            return 0.8  # Medium-wide
        elif profit_pct_to_tp < 75:
            return 0.6  # Medium-tight
        elif profit_pct_to_tp < 90:
            return 0.4  # Tight
        else:
            return 0.3  # Very tight (near TP)

    def get_regime_multiplier(self, db, symbol: str, timeframe: str = 'M15') -> Tuple[float, str]:
        """
        Get market regime multiplier.

        Returns:
            (multiplier, regime)
            multiplier: 0.7 (TRENDING) to 1.3 (CHOPPY)
        """
        try:
            ti = TechnicalIndicators(db, symbol=symbol, timeframe=timeframe, bars=50)
            regime_data = ti.detect_market_regime()
            regime = regime_data.get('regime', 'RANGING')

            # Regime-specific multipliers
            regime_multipliers = {
                'TRENDING': 0.7,    # Tighter SL in strong trend
                'RANGING': 1.0,     # Normal SL in range
                'CHOPPY': 1.3,      # Wider SL in choppy market
                'TOO_WEAK': 1.5,    # Very wide SL if trend is weak
            }

            multiplier = regime_multipliers.get(regime, 1.0)
            logger.info(f"{symbol} regime: {regime} (multiplier={multiplier:.2f})")

            return multiplier, regime
        except Exception as e:
            logger.warning(f"Could not detect regime for {symbol}: {e}")
            return 1.0, 'UNKNOWN'

    def get_current_spread(self, db, symbol: str) -> float:
        """Get current bid-ask spread from latest tick."""
        tick = db.query(Tick).filter(Tick.symbol == symbol).order_by(Tick.timestamp.desc()).first()
        if tick:
            spread = tick.ask - tick.bid
            return spread

        # Fallback to profile
        profile = self.noise_profiles.get(symbol, {})
        return profile.get('typical_spread', 0.0001)

    def calculate_dynamic_trail_distance(self, db, trade: Trade, current_price: float) -> Dict:
        """
        Calculate optimal trailing stop distance using unified formula.

        Formula:
            Final_Distance = (Base_ATR × Vol_60s × Session × Progress × Regime) + Spread_Buffer

        Returns:
            {
                'new_sl_distance': float,  # Distance in price units
                'new_sl_price': float,     # Absolute SL price
                'components': {
                    'base_atr': float,
                    'vol_60s_multiplier': float,
                    'session_multiplier': float,
                    'progress_multiplier': float,
                    'regime_multiplier': float,
                    'spread_buffer': float,
                },
                'analysis': {
                    'volatility': dict,
                    'session': str,
                    'regime': str,
                    'profit_pct_to_tp': float,
                },
                'safety_checks': {
                    'max_from_profit': float,
                    'min_from_spread': float,
                    'applied_cap': bool,
                    'applied_floor': bool,
                }
            }
        """
        symbol = trade.symbol
        direction = trade.direction.upper()
        entry_price = float(trade.open_price)
        tp_price = float(trade.tp_price) if trade.tp_price else None

        logger.info(f"Calculating dynamic trail distance for Trade #{trade.ticket} ({symbol} {direction})")

        # Step 1: Base ATR (volatility baseline)
        base_atr = self.get_base_atr(db, symbol, timeframe='M15')
        logger.info(f"  Base ATR: {base_atr:.5f}")

        # Step 2: 60-second volatility multiplier
        volatility_analysis = self.analyze_60s_volatility(db, symbol, window_seconds=60)
        vol_60s_multiplier = 0.8 + (volatility_analysis['volatility_score'] * 0.6)  # 0.8 - 1.4
        logger.info(f"  60s volatility: {volatility_analysis['classification']} (mult={vol_60s_multiplier:.2f})")

        # Step 3: Session multiplier
        session_multiplier, session_name = self.get_session_multiplier(symbol, db)
        logger.info(f"  Session: {session_name} (mult={session_multiplier:.2f})")

        # Step 4: Progress toward TP
        if tp_price:
            if direction == 'BUY':
                total_distance = tp_price - entry_price
                current_progress = current_price - entry_price
            else:  # SELL
                total_distance = entry_price - tp_price
                current_progress = entry_price - current_price

            profit_pct_to_tp = (current_progress / total_distance * 100) if total_distance > 0 else 0
            profit_pct_to_tp = max(0, min(100, profit_pct_to_tp))  # Clamp 0-100
        else:
            profit_pct_to_tp = 0

        progress_multiplier = self.get_progress_multiplier(profit_pct_to_tp)
        logger.info(f"  Progress: {profit_pct_to_tp:.1f}% to TP (mult={progress_multiplier:.2f})")

        # Step 5: Market regime multiplier
        regime_multiplier, regime = self.get_regime_multiplier(db, symbol, timeframe='M15')

        # Step 6: Spread buffer (2x current spread)
        current_spread = self.get_current_spread(db, symbol)
        spread_buffer = current_spread * 2.0
        logger.info(f"  Spread buffer: {spread_buffer:.5f} (2x current spread)")

        # Calculate base distance (before safety checks)
        base_distance = (
            base_atr *
            vol_60s_multiplier *
            session_multiplier *
            progress_multiplier *
            regime_multiplier
        )

        final_distance = base_distance + spread_buffer

        logger.info(f"  Base distance: {base_distance:.5f}, Final (with spread): {final_distance:.5f}")

        # Safety checks
        applied_cap = False
        applied_floor = False

        # Safety 1: Max 50% of current profit
        current_profit = abs(current_price - entry_price)
        max_from_profit = current_profit * 0.5
        if final_distance > max_from_profit and current_profit > 0:
            logger.warning(f"  Capping distance to 50% of profit: {final_distance:.5f} → {max_from_profit:.5f}")
            final_distance = max_from_profit
            applied_cap = True

        # Safety 2: Minimum 2x spread
        min_from_spread = current_spread * 2.0
        if final_distance < min_from_spread:
            logger.warning(f"  Raising to minimum 2x spread: {final_distance:.5f} → {min_from_spread:.5f}")
            final_distance = min_from_spread
            applied_floor = True

        # Calculate new SL price
        if direction == 'BUY':
            new_sl_price = current_price - final_distance
        else:  # SELL
            new_sl_price = current_price + final_distance

        logger.info(f"  → New SL: {new_sl_price:.5f} (distance: {final_distance:.5f})")

        return {
            'new_sl_distance': final_distance,
            'new_sl_price': new_sl_price,
            'components': {
                'base_atr': base_atr,
                'vol_60s_multiplier': vol_60s_multiplier,
                'session_multiplier': session_multiplier,
                'progress_multiplier': progress_multiplier,
                'regime_multiplier': regime_multiplier,
                'spread_buffer': spread_buffer,
            },
            'analysis': {
                'volatility': volatility_analysis,
                'session': session_name,
                'regime': regime,
                'profit_pct_to_tp': profit_pct_to_tp,
            },
            'safety_checks': {
                'max_from_profit': max_from_profit,
                'min_from_spread': min_from_spread,
                'applied_cap': applied_cap,
                'applied_floor': applied_floor,
            }
        }

    def should_update_sl(self, db, trade: Trade, current_price: float, new_sl_price: float) -> Tuple[bool, str]:
        """
        Determine if SL should be updated (only move SL closer, never wider).

        Returns:
            (should_update, reason)
        """
        current_sl = float(trade.sl_price) if trade.sl_price else None
        direction = trade.direction.upper()

        if not current_sl:
            return True, "No SL set yet"

        # Only move SL in favorable direction
        if direction == 'BUY':
            if new_sl_price > current_sl:
                # Get base ATR for minimum movement threshold
                base_atr = self.get_base_atr(db, trade.symbol, timeframe='M15')
                movement = new_sl_price - current_sl

                # Only update if movement is significant (at least 0.5x ATR)
                if movement >= base_atr * 0.5:
                    return True, f"Moving SL up by {movement:.5f} (≥0.5x ATR)"
                else:
                    return False, f"Movement too small: {movement:.5f} < {base_atr * 0.5:.5f}"
            else:
                return False, f"Would move SL down (not allowed for BUY)"
        else:  # SELL
            if new_sl_price < current_sl:
                base_atr = self.get_base_atr(db, trade.symbol, timeframe='M15')
                movement = current_sl - new_sl_price

                if movement >= base_atr * 0.5:
                    return True, f"Moving SL down by {movement:.5f} (≥0.5x ATR)"
                else:
                    return False, f"Movement too small: {movement:.5f} < {base_atr * 0.5:.5f}"
            else:
                return False, f"Would move SL up (not allowed for SELL)"

    def update_trailing_stop(self, db, trade: Trade, current_price: float,
                           dry_run: bool = False) -> Optional[Dict]:
        """
        Update trailing stop for a trade if conditions are met.

        Args:
            db: Database session
            trade: Trade object
            current_price: Current market price
            dry_run: If True, don't actually update the trade

        Returns:
            dict with update details, or None if no update needed
        """
        calculation = self.calculate_dynamic_trail_distance(db, trade, current_price)
        new_sl_price = calculation['new_sl_price']

        should_update, reason = self.should_update_sl(db, trade, current_price, new_sl_price)

        if not should_update:
            logger.info(f"Trade #{trade.ticket}: No SL update - {reason}")
            return None

        old_sl = float(trade.sl_price) if trade.sl_price else None

        if not dry_run:
            trade.sl_price = new_sl_price
            db.commit()
            logger.info(f"✅ Trade #{trade.ticket}: Updated SL {old_sl:.5f} → {new_sl_price:.5f}")
        else:
            logger.info(f"[DRY RUN] Trade #{trade.ticket}: Would update SL {old_sl:.5f} → {new_sl_price:.5f}")

        return {
            'trade_ticket': trade.ticket,
            'symbol': trade.symbol,
            'direction': trade.direction,
            'old_sl': old_sl,
            'new_sl': new_sl_price,
            'sl_change': new_sl_price - old_sl if old_sl else 0,
            'current_price': current_price,
            'reason': reason,
            'calculation': calculation,
            'dry_run': dry_run,
        }


if __name__ == '__main__':
    # Test module standalone
    import sys
    from database import SessionLocal

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    db = SessionLocal()
    nas = NoiseAdaptiveTrailingStop(account_id=3)

    # Get all open trades
    open_trades = db.query(Trade).filter(
        Trade.account_id == 3,
        Trade.status == 'open'
    ).all()

    print(f"\n{'='*80}")
    print(f"Noise-Adaptive Trailing Stop - Test Run")
    print(f"{'='*80}\n")
    print(f"Found {len(open_trades)} open trades\n")

    for trade in open_trades:
        # Get current price from latest tick
        tick = db.query(Tick).filter(Tick.symbol == trade.symbol).order_by(Tick.timestamp.desc()).first()
        if not tick:
            print(f"❌ Trade #{trade.ticket}: No tick data available")
            continue

        current_price = tick.bid if trade.direction.upper() == 'BUY' else tick.ask

        print(f"\n{'─'*80}")
        print(f"Trade #{trade.ticket}: {trade.symbol} {trade.direction}")
        print(f"Entry: {trade.open_price:.5f}, Current: {current_price:.5f}, TP: {trade.tp_price:.5f}")
        print(f"Current SL: {trade.sl_price:.5f}")
        print(f"{'─'*80}")

        result = nas.update_trailing_stop(db, trade, current_price, dry_run=True)

        if result:
            calc = result['calculation']
            comp = calc['components']
            analysis = calc['analysis']

            print(f"\n✅ Update Recommended:")
            print(f"   Old SL: {result['old_sl']:.5f}")
            print(f"   New SL: {result['new_sl']:.5f}")
            print(f"   Change: {result['sl_change']:.5f}")
            print(f"\n📊 Components:")
            print(f"   Base ATR: {comp['base_atr']:.5f}")
            print(f"   60s Vol Mult: {comp['vol_60s_multiplier']:.2f} ({analysis['volatility']['classification']})")
            print(f"   Session Mult: {comp['session_multiplier']:.2f} ({analysis['session']})")
            print(f"   Progress Mult: {comp['progress_multiplier']:.2f} ({analysis['profit_pct_to_tp']:.1f}% to TP)")
            print(f"   Regime Mult: {comp['regime_multiplier']:.2f} ({analysis['regime']})")
            print(f"   Spread Buffer: {comp['spread_buffer']:.5f}")
            print(f"\n🛡️ Safety Checks:")
            print(f"   Max (50% profit): {calc['safety_checks']['max_from_profit']:.5f}")
            print(f"   Min (2x spread): {calc['safety_checks']['min_from_spread']:.5f}")
            print(f"   Cap applied: {calc['safety_checks']['applied_cap']}")
            print(f"   Floor applied: {calc['safety_checks']['applied_floor']}")
        else:
            print(f"\n⏸️  No update needed")

    print(f"\n{'='*80}\n")
    db.close()

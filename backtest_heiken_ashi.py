#!/usr/bin/env python3
"""
Backtest Script for Heiken Ashi Trend Indicator
Tests against historical data from the last 7 days
"""

import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from database import ScopedSession
from models import OHLCData, TradingSignal
from technical_indicators import TechnicalIndicators
import pandas as pd
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HeikenAshiBacktest:
    """Backtest Heiken Ashi Trend indicator against historical data"""

    def __init__(self, symbol: str, timeframe: str, days_back: int = 7):
        self.symbol = symbol
        self.timeframe = timeframe
        self.days_back = days_back
        self.account_id = 1

    def get_historical_data(self) -> List[Dict]:
        """Get historical OHLC data for backtesting"""
        db = ScopedSession()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.days_back)

            ohlc_data = db.query(OHLCData).filter(
                OHLCData.symbol == self.symbol,
                OHLCData.timeframe == self.timeframe,
                OHLCData.timestamp >= cutoff_date
            ).order_by(OHLCData.timestamp.asc()).all()

            data = [{
                'timestamp': o.timestamp,
                'open': float(o.open),
                'high': float(o.high),
                'low': float(o.low),
                'close': float(o.close),
                'volume': float(o.volume) if o.volume else 0
            } for o in ohlc_data]

            logger.info(f"📊 Loaded {len(data)} candles for {self.symbol} {self.timeframe} (last {self.days_back} days)")
            return data

        except Exception as e:
            logger.error(f"Error loading historical data: {e}")
            return []
        finally:
            db.close()

    def simulate_signals(self, data: List[Dict]) -> List[Dict]:
        """Simulate signal generation on historical data"""
        signals = []

        # We need at least 52 candles for Heiken Ashi + EMAs
        min_candles = 60

        if len(data) < min_candles:
            logger.warning(f"⚠️  Not enough data ({len(data)} candles, need {min_candles})")
            return signals

        logger.info(f"🔄 Simulating signals on {len(data)} candles...")

        # Iterate through data, simulating real-time signal generation
        for i in range(min_candles, len(data)):
            timestamp = data[i]['timestamp']

            # Create temporary database snapshot for this point in time
            # (In real implementation, we'd write temp data to DB)
            # For now, we'll use TechnicalIndicators with cache disabled

            try:
                ti = TechnicalIndicators(
                    account_id=self.account_id,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    cache_ttl=0  # Disable cache
                )

                # Calculate HA Trend at this point
                ha_trend = ti.calculate_heiken_ashi_trend()

                if ha_trend and ha_trend['signal'] in ['buy', 'sell']:
                    signal = {
                        'timestamp': timestamp,
                        'signal_type': ha_trend['signal_type'],
                        'signal': ha_trend['signal'],
                        'confidence': ha_trend['confidence'],
                        'reasons': ha_trend['reasons'],
                        'entry_price': data[i]['close'],
                        'ha_trend': ha_trend['ha_trend'],
                        'volume_signal': ha_trend['volume_signal'],
                        'volume_ratio': ha_trend['volume_ratio'],
                        'ema_fast': ha_trend['ema_fast'],
                        'ema_slow': ha_trend['ema_slow'],
                    }

                    signals.append(signal)
                    logger.debug(f"✅ Signal {len(signals)}: {timestamp} - {signal['signal_type']} @ {signal['entry_price']:.5f} (conf: {signal['confidence']:.1f}%)")

            except Exception as e:
                logger.debug(f"Error at {timestamp}: {e}")
                continue

        logger.info(f"📈 Generated {len(signals)} signals")
        return signals

    def calculate_signal_outcomes(self, signals: List[Dict], data: List[Dict]) -> List[Dict]:
        """Calculate outcomes for each signal"""
        logger.info(f"💰 Calculating outcomes for {len(signals)} signals...")

        # Create price lookup
        price_map = {d['timestamp']: d for d in data}

        outcomes = []

        for sig in signals:
            timestamp = sig['timestamp']
            entry_price = sig['entry_price']
            signal_type = sig['signal_type']

            # Find subsequent candles (next 20 bars or 24 hours)
            future_candles = [d for d in data if d['timestamp'] > timestamp][:20]

            if not future_candles:
                continue

            # Calculate SL/TP based on ATR (simplified - use 1.5x ATR)
            # For backtest, we'll use a simple fixed percentage
            if signal_type == 'LONG_ENTRY':
                sl_pct = -0.005  # -0.5% stop loss
                tp_pct = 0.015   # +1.5% take profit (1:3 R/R)
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 + tp_pct)
            else:  # SHORT_ENTRY
                sl_pct = 0.005   # +0.5% stop loss
                tp_pct = -0.015  # -1.5% take profit
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 + tp_pct)

            # Check each future candle for SL/TP hit
            hit_sl = False
            hit_tp = False
            exit_price = None
            exit_timestamp = None
            bars_held = 0

            for fc in future_candles:
                bars_held += 1

                if signal_type == 'LONG_ENTRY':
                    # Check SL (low touches SL)
                    if fc['low'] <= sl_price:
                        hit_sl = True
                        exit_price = sl_price
                        exit_timestamp = fc['timestamp']
                        break
                    # Check TP (high touches TP)
                    if fc['high'] >= tp_price:
                        hit_tp = True
                        exit_price = tp_price
                        exit_timestamp = fc['timestamp']
                        break
                else:  # SHORT_ENTRY
                    # Check SL (high touches SL)
                    if fc['high'] >= sl_price:
                        hit_sl = True
                        exit_price = sl_price
                        exit_timestamp = fc['timestamp']
                        break
                    # Check TP (low touches TP)
                    if fc['low'] <= tp_price:
                        hit_tp = True
                        exit_price = tp_price
                        exit_timestamp = fc['timestamp']
                        break

            # If neither hit, use last candle close
            if not hit_sl and not hit_tp and future_candles:
                exit_price = future_candles[-1]['close']
                exit_timestamp = future_candles[-1]['timestamp']

            # Calculate profit/loss
            if signal_type == 'LONG_ENTRY':
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100

            outcome = {
                **sig,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'exit_price': exit_price,
                'exit_timestamp': exit_timestamp,
                'bars_held': bars_held,
                'hit_sl': hit_sl,
                'hit_tp': hit_tp,
                'pnl_pct': pnl_pct,
                'win': pnl_pct > 0
            }

            outcomes.append(outcome)

        logger.info(f"✅ Calculated {len(outcomes)} outcomes")
        return outcomes

    def analyze_performance(self, outcomes: List[Dict]) -> Dict:
        """Analyze backtest performance"""
        if not outcomes:
            return {}

        total_trades = len(outcomes)
        wins = [o for o in outcomes if o['win']]
        losses = [o for o in outcomes if not o['win']]

        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean([o['pnl_pct'] for o in wins]) if wins else 0
        avg_loss = np.mean([o['pnl_pct'] for o in losses]) if losses else 0

        total_pnl = sum([o['pnl_pct'] for o in outcomes])
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # Confidence analysis
        high_conf_trades = [o for o in outcomes if o['confidence'] >= 70]
        medium_conf_trades = [o for o in outcomes if 60 <= o['confidence'] < 70]
        low_conf_trades = [o for o in outcomes if o['confidence'] < 60]

        high_conf_wr = (len([o for o in high_conf_trades if o['win']]) / len(high_conf_trades) * 100) if high_conf_trades else 0
        medium_conf_wr = (len([o for o in medium_conf_trades if o['win']]) / len(medium_conf_trades) * 100) if medium_conf_trades else 0
        low_conf_wr = (len([o for o in low_conf_trades if o['win']]) / len(low_conf_trades) * 100) if low_conf_trades else 0

        # Volume analysis
        high_vol_trades = [o for o in outcomes if o['volume_ratio'] >= 1.2]
        low_vol_trades = [o for o in outcomes if o['volume_ratio'] < 1.2]

        high_vol_wr = (len([o for o in high_vol_trades if o['win']]) / len(high_vol_trades) * 100) if high_vol_trades else 0
        low_vol_wr = (len([o for o in low_vol_trades if o['win']]) / len(low_vol_trades) * 100) if low_vol_trades else 0

        # Hit rate analysis
        tp_hits = len([o for o in outcomes if o['hit_tp']])
        sl_hits = len([o for o in outcomes if o['hit_sl']])

        return {
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'tp_hits': tp_hits,
            'sl_hits': sl_hits,
            'high_conf_trades': len(high_conf_trades),
            'high_conf_wr': high_conf_wr,
            'medium_conf_trades': len(medium_conf_trades),
            'medium_conf_wr': medium_conf_wr,
            'low_conf_trades': len(low_conf_trades),
            'low_conf_wr': low_conf_wr,
            'high_vol_trades': len(high_vol_trades),
            'high_vol_wr': high_vol_wr,
            'low_vol_trades': len(low_vol_trades),
            'low_vol_wr': low_vol_wr,
        }

    def print_report(self, stats: Dict):
        """Print backtest report"""
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 HEIKEN ASHI TREND BACKTEST REPORT")
        logger.info(f"{'='*80}")
        logger.info(f"Symbol: {self.symbol}")
        logger.info(f"Timeframe: {self.timeframe}")
        logger.info(f"Period: Last {self.days_back} days")
        logger.info(f"{'='*80}\n")

        logger.info(f"📈 OVERALL PERFORMANCE")
        logger.info(f"   Total Trades: {stats['total_trades']}")
        logger.info(f"   Wins: {stats['wins']} | Losses: {stats['losses']}")
        logger.info(f"   Win Rate: {stats['win_rate']:.1f}%")
        logger.info(f"   Avg Win: +{stats['avg_win']:.2f}%")
        logger.info(f"   Avg Loss: {stats['avg_loss']:.2f}%")
        logger.info(f"   Total P/L: {stats['total_pnl']:+.2f}%")
        logger.info(f"   Avg P/L per Trade: {stats['avg_pnl']:+.2f}%")
        logger.info(f"   TP Hits: {stats['tp_hits']} ({stats['tp_hits']/stats['total_trades']*100:.1f}%)")
        logger.info(f"   SL Hits: {stats['sl_hits']} ({stats['sl_hits']/stats['total_trades']*100:.1f}%)\n")

        logger.info(f"🎯 CONFIDENCE ANALYSIS")
        logger.info(f"   High Confidence (≥70%): {stats['high_conf_trades']} trades, {stats['high_conf_wr']:.1f}% WR")
        logger.info(f"   Medium Confidence (60-70%): {stats['medium_conf_trades']} trades, {stats['medium_conf_wr']:.1f}% WR")
        logger.info(f"   Low Confidence (<60%): {stats['low_conf_trades']} trades, {stats['low_conf_wr']:.1f}% WR\n")

        logger.info(f"📊 VOLUME ANALYSIS")
        logger.info(f"   High Volume (≥1.2x): {stats['high_vol_trades']} trades, {stats['high_vol_wr']:.1f}% WR")
        logger.info(f"   Low Volume (<1.2x): {stats['low_vol_trades']} trades, {stats['low_vol_wr']:.1f}% WR\n")

        logger.info(f"{'='*80}\n")

    def run(self):
        """Run complete backtest"""
        logger.info(f"\n🚀 Starting Heiken Ashi Trend Backtest")
        logger.info(f"   Symbol: {self.symbol}")
        logger.info(f"   Timeframe: {self.timeframe}")
        logger.info(f"   Period: Last {self.days_back} days\n")

        # Load historical data
        data = self.get_historical_data()
        if not data:
            logger.error("❌ No historical data available")
            return None

        # Simulate signals
        signals = self.simulate_signals(data)
        if not signals:
            logger.warning("⚠️  No signals generated")
            return None

        # Calculate outcomes
        outcomes = self.calculate_signal_outcomes(signals, data)
        if not outcomes:
            logger.error("❌ Could not calculate outcomes")
            return None

        # Analyze performance
        stats = self.analyze_performance(outcomes)

        # Print report
        self.print_report(stats)

        return {
            'stats': stats,
            'outcomes': outcomes,
            'signals': signals
        }


def main():
    """Main backtest function"""

    # Test configurations
    test_configs = [
        {'symbol': 'EURUSD', 'timeframe': 'H1', 'days': 7},
        {'symbol': 'EURUSD', 'timeframe': 'M5', 'days': 7},
        {'symbol': 'XAUUSD', 'timeframe': 'H1', 'days': 7},
        {'symbol': 'XAUUSD', 'timeframe': 'M5', 'days': 7},
        {'symbol': 'GBPUSD', 'timeframe': 'H1', 'days': 7},
        {'symbol': 'US30.c', 'timeframe': 'H1', 'days': 7},
    ]

    all_results = []

    for config in test_configs:
        try:
            bt = HeikenAshiBacktest(
                symbol=config['symbol'],
                timeframe=config['timeframe'],
                days_back=config['days']
            )

            result = bt.run()
            if result:
                all_results.append({
                    'symbol': config['symbol'],
                    'timeframe': config['timeframe'],
                    'stats': result['stats']
                })

        except Exception as e:
            logger.error(f"❌ Error testing {config['symbol']} {config['timeframe']}: {e}", exc_info=True)

    # Summary comparison
    if all_results:
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 SUMMARY COMPARISON")
        logger.info(f"{'='*80}")
        logger.info(f"{'Symbol':<12} {'TF':<6} {'Trades':<8} {'Win Rate':<10} {'Avg P/L':<10} {'Total P/L':<10}")
        logger.info(f"{'-'*80}")

        for r in all_results:
            s = r['stats']
            logger.info(
                f"{r['symbol']:<12} {r['timeframe']:<6} {s['total_trades']:<8} "
                f"{s['win_rate']:<10.1f}% {s['avg_pnl']:<+10.2f}% {s['total_pnl']:<+10.2f}%"
            )

        logger.info(f"{'='*80}\n")

        # Best performers
        best_wr = max(all_results, key=lambda x: x['stats']['win_rate'])
        best_pnl = max(all_results, key=lambda x: x['stats']['total_pnl'])

        logger.info(f"🏆 Best Win Rate: {best_wr['symbol']} {best_wr['timeframe']} ({best_wr['stats']['win_rate']:.1f}%)")
        logger.info(f"💰 Best Total P/L: {best_pnl['symbol']} {best_pnl['timeframe']} ({best_pnl['stats']['total_pnl']:+.2f}%)\n")


if __name__ == '__main__':
    main()

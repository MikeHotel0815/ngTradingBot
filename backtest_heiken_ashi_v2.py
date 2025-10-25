#!/usr/bin/env python3
"""
Backtest Script for Heiken Ashi Trend Indicator - Version 2
Direct calculation on historical data without DB dependency
"""

import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from database import ScopedSession
from models import OHLCData
import pandas as pd
import numpy as np
import talib

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HeikenAshiBacktestV2:
    """Backtest Heiken Ashi Trend with direct calculations"""

    def __init__(self, symbol: str, timeframe: str, days_back: int = 7):
        self.symbol = symbol
        self.timeframe = timeframe
        self.days_back = days_back

    def get_historical_data(self) -> pd.DataFrame:
        """Get historical OHLC data as DataFrame"""
        db = ScopedSession()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.days_back)

            ohlc_data = db.query(OHLCData).filter(
                OHLCData.symbol == self.symbol,
                OHLCData.timeframe == self.timeframe,
                OHLCData.timestamp >= cutoff_date
            ).order_by(OHLCData.timestamp.asc()).all()

            if not ohlc_data:
                return None

            df = pd.DataFrame([{
                'timestamp': o.timestamp,
                'open': float(o.open),
                'high': float(o.high),
                'low': float(o.low),
                'close': float(o.close),
                'volume': float(o.volume) if o.volume else 0
            } for o in ohlc_data])

            logger.info(f"📊 Loaded {len(df)} candles for {self.symbol} {self.timeframe}")
            return df

        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return None
        finally:
            db.close()

    def calculate_heiken_ashi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Heiken Ashi candles"""
        ha_df = df.copy()

        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_open = pd.Series([0.0] * len(df), index=df.index)
        ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2

        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2

        ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

        ha_df['ha_open'] = ha_open
        ha_df['ha_close'] = ha_close
        ha_df['ha_high'] = ha_high
        ha_df['ha_low'] = ha_low

        # Determine trend
        ha_df['ha_bullish'] = ha_close > ha_open
        ha_df['ha_bearish'] = ha_close < ha_open

        # Body and wicks
        ha_df['ha_body'] = abs(ha_close - ha_open)
        ha_df['ha_upper_wick'] = ha_high - pd.concat([ha_open, ha_close], axis=1).max(axis=1)
        ha_df['ha_lower_wick'] = pd.concat([ha_open, ha_close], axis=1).min(axis=1) - ha_low

        # Strong signals (no opposite wick)
        ha_df['ha_no_lower_wick'] = ha_df['ha_lower_wick'] < (ha_df['ha_body'] * 0.1)
        ha_df['ha_no_upper_wick'] = ha_df['ha_upper_wick'] < (ha_df['ha_body'] * 0.1)

        return ha_df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all required indicators"""
        result_df = df.copy()

        # EMAs
        result_df['ema_8'] = talib.EMA(df['close'].values, timeperiod=8)
        result_df['ema_30'] = talib.EMA(df['close'].values, timeperiod=30)

        # Price vs EMAs
        result_df['price_above_emas'] = (df['close'] > result_df['ema_8']) & (df['close'] > result_df['ema_30'])
        result_df['price_below_emas'] = (df['close'] < result_df['ema_8']) & (df['close'] < result_df['ema_30'])

        # EMA alignment
        result_df['ema_bullish_aligned'] = result_df['ema_8'] > result_df['ema_30']
        result_df['ema_bearish_aligned'] = result_df['ema_8'] < result_df['ema_30']

        # Volume analysis
        result_df['volume_avg'] = df['volume'].rolling(window=20).mean()
        result_df['volume_ratio'] = df['volume'] / result_df['volume_avg']

        # ATR for SL/TP
        result_df['atr'] = talib.ATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)

        return result_df

    def detect_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect Heiken Ashi Trend signals"""
        signal_df = df.copy()

        # Initialize signal columns
        signal_df['signal'] = 'neutral'
        signal_df['confidence'] = 0

        # Detect recent reversals (need at least 5 bars lookback)
        signal_df['recent_reversal'] = False

        for i in range(5, len(signal_df)):
            current_bullish = signal_df['ha_bullish'].iloc[i]
            current_bearish = signal_df['ha_bearish'].iloc[i]

            # Check last 4 bars for opposite color
            lookback = signal_df.iloc[i-4:i]

            if current_bullish and lookback['ha_bearish'].any():
                signal_df.loc[signal_df.index[i], 'recent_reversal'] = True
            elif current_bearish and lookback['ha_bullish'].any():
                signal_df.loc[signal_df.index[i], 'recent_reversal'] = True

        # LONG ENTRY conditions
        long_entry = (
            (signal_df['ha_bullish']) &
            (signal_df['ha_no_lower_wick']) &
            (signal_df['price_above_emas']) &
            (signal_df['ema_bullish_aligned']) &
            (signal_df['recent_reversal'])
        )

        # SHORT ENTRY conditions
        short_entry = (
            (signal_df['ha_bearish']) &
            (signal_df['ha_no_upper_wick']) &
            (signal_df['price_below_emas']) &
            (signal_df['ema_bearish_aligned']) &
            (signal_df['recent_reversal'])
        )

        # Set signals
        signal_df.loc[long_entry, 'signal'] = 'buy'
        signal_df.loc[short_entry, 'signal'] = 'sell'

        # Calculate confidence for signals
        for i in signal_df[signal_df['signal'] != 'neutral'].index:
            confidence = 50  # Base

            # HA strength (simple version)
            confidence += 10

            # EMA alignment
            confidence += 15

            # Recent reversal
            if signal_df.loc[i, 'recent_reversal']:
                confidence += 10

            # Volume boost
            vol_ratio = signal_df.loc[i, 'volume_ratio']
            if not pd.isna(vol_ratio):
                if vol_ratio >= 1.5:
                    confidence = int(confidence * 1.3)
                elif vol_ratio >= 1.2:
                    confidence = int(confidence * 1.15)
                elif vol_ratio < 0.8:
                    confidence = int(confidence * 0.85)

            signal_df.loc[i, 'confidence'] = min(100, confidence)

        return signal_df

    def backtest_signals(self, df: pd.DataFrame) -> List[Dict]:
        """Backtest all detected signals"""
        trades = []

        signals = df[df['signal'] != 'neutral'].copy()

        logger.info(f"📈 Found {len(signals)} potential signals")

        for idx, row in signals.iterrows():
            timestamp = row['timestamp']
            signal_type = row['signal']
            entry_price = row['close']
            confidence = row['confidence']
            atr = row['atr']

            # Calculate SL/TP using ATR
            if pd.isna(atr) or atr == 0:
                atr = entry_price * 0.005  # Fallback 0.5%

            if signal_type == 'buy':
                sl_price = entry_price - (atr * 1.5)
                tp_price = entry_price + (atr * 3)  # 1:2 R/R
            else:  # sell
                sl_price = entry_price + (atr * 1.5)
                tp_price = entry_price - (atr * 3)

            # Find future candles
            future_idx = df.index[df.index > idx][:20]  # Next 20 bars

            if len(future_idx) == 0:
                continue

            # Check for SL/TP hit
            hit_sl = False
            hit_tp = False
            exit_price = None
            exit_timestamp = None
            bars_held = 0

            for future_i in future_idx:
                bars_held += 1
                future_row = df.loc[future_i]

                if signal_type == 'buy':
                    # Check SL
                    if future_row['low'] <= sl_price:
                        hit_sl = True
                        exit_price = sl_price
                        exit_timestamp = future_row['timestamp']
                        break
                    # Check TP
                    if future_row['high'] >= tp_price:
                        hit_tp = True
                        exit_price = tp_price
                        exit_timestamp = future_row['timestamp']
                        break
                else:  # sell
                    # Check SL
                    if future_row['high'] >= sl_price:
                        hit_sl = True
                        exit_price = sl_price
                        exit_timestamp = future_row['timestamp']
                        break
                    # Check TP
                    if future_row['low'] <= tp_price:
                        hit_tp = True
                        exit_price = tp_price
                        exit_timestamp = future_row['timestamp']
                        break

            # If neither hit, close at last bar
            if not hit_sl and not hit_tp:
                last_future = df.loc[future_idx[-1]]
                exit_price = last_future['close']
                exit_timestamp = last_future['timestamp']

            # Calculate P/L
            if signal_type == 'buy':
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100

            trade = {
                'timestamp': timestamp,
                'signal': signal_type,
                'confidence': confidence,
                'entry_price': entry_price,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'exit_price': exit_price,
                'exit_timestamp': exit_timestamp,
                'bars_held': bars_held,
                'hit_sl': hit_sl,
                'hit_tp': hit_tp,
                'pnl_pct': pnl_pct,
                'win': pnl_pct > 0,
                'volume_ratio': row['volume_ratio']
            }

            trades.append(trade)

        logger.info(f"✅ Backtested {len(trades)} trades")
        return trades

    def analyze_performance(self, trades: List[Dict]) -> Dict:
        """Analyze backtest results"""
        if not trades:
            return {}

        total = len(trades)
        wins = [t for t in trades if t['win']]
        losses = [t for t in trades if not t['win']]

        win_rate = len(wins) / total * 100
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        total_pnl = sum([t['pnl_pct'] for t in trades])
        avg_pnl = total_pnl / total

        # Confidence buckets
        high_conf = [t for t in trades if t['confidence'] >= 70]
        medium_conf = [t for t in trades if 60 <= t['confidence'] < 70]
        low_conf = [t for t in trades if t['confidence'] < 60]

        high_conf_wr = len([t for t in high_conf if t['win']]) / len(high_conf) * 100 if high_conf else 0
        medium_conf_wr = len([t for t in medium_conf if t['win']]) / len(medium_conf) * 100 if medium_conf else 0
        low_conf_wr = len([t for t in low_conf if t['win']]) / len(low_conf) * 100 if low_conf else 0

        # Volume buckets
        high_vol = [t for t in trades if t['volume_ratio'] >= 1.2]
        low_vol = [t for t in trades if t['volume_ratio'] < 1.2]

        high_vol_wr = len([t for t in high_vol if t['win']]) / len(high_vol) * 100 if high_vol else 0
        low_vol_wr = len([t for t in low_vol if t['win']]) / len(low_vol) * 100 if low_vol else 0

        return {
            'total_trades': total,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'tp_hits': len([t for t in trades if t['hit_tp']]),
            'sl_hits': len([t for t in trades if t['hit_sl']]),
            'high_conf_trades': len(high_conf),
            'high_conf_wr': high_conf_wr,
            'medium_conf_trades': len(medium_conf),
            'medium_conf_wr': medium_conf_wr,
            'low_conf_trades': len(low_conf),
            'low_conf_wr': low_conf_wr,
            'high_vol_trades': len(high_vol),
            'high_vol_wr': high_vol_wr,
            'low_vol_trades': len(low_vol),
            'low_vol_wr': low_vol_wr,
        }

    def print_report(self, stats: Dict):
        """Print backtest report"""
        if not stats:
            logger.warning("⚠️  No trades to analyze")
            return

        logger.info(f"\n{'='*80}")
        logger.info(f"📊 HEIKEN ASHI TREND BACKTEST - {self.symbol} {self.timeframe}")
        logger.info(f"{'='*80}")
        logger.info(f"Period: Last {self.days_back} days\n")

        logger.info(f"📈 OVERALL PERFORMANCE")
        logger.info(f"   Total Trades: {stats['total_trades']}")
        logger.info(f"   Wins: {stats['wins']} | Losses: {stats['losses']}")
        logger.info(f"   Win Rate: {stats['win_rate']:.1f}%")
        logger.info(f"   Avg Win: +{stats['avg_win']:.2f}%")
        logger.info(f"   Avg Loss: {stats['avg_loss']:.2f}%")
        logger.info(f"   Total P/L: {stats['total_pnl']:+.2f}%")
        logger.info(f"   Avg P/L: {stats['avg_pnl']:+.2f}%")
        logger.info(f"   TP Hits: {stats['tp_hits']} | SL Hits: {stats['sl_hits']}\n")

        logger.info(f"🎯 CONFIDENCE ANALYSIS")
        logger.info(f"   High (≥70%): {stats['high_conf_trades']} trades, {stats['high_conf_wr']:.1f}% WR")
        logger.info(f"   Medium (60-70%): {stats['medium_conf_trades']} trades, {stats['medium_conf_wr']:.1f}% WR")
        logger.info(f"   Low (<60%): {stats['low_conf_trades']} trades, {stats['low_conf_wr']:.1f}% WR\n")

        logger.info(f"📊 VOLUME ANALYSIS")
        logger.info(f"   High Vol (≥1.2x): {stats['high_vol_trades']} trades, {stats['high_vol_wr']:.1f}% WR")
        logger.info(f"   Low Vol (<1.2x): {stats['low_vol_trades']} trades, {stats['low_vol_wr']:.1f}% WR\n")

        logger.info(f"{'='*80}\n")

    def run(self):
        """Run full backtest"""
        logger.info(f"\n🚀 Starting backtest: {self.symbol} {self.timeframe}")

        # Load data
        df = self.get_historical_data()
        if df is None or len(df) < 60:
            logger.error("❌ Insufficient data")
            return None

        # Calculate Heiken Ashi
        df = self.calculate_heiken_ashi(df)

        # Calculate indicators
        df = self.calculate_indicators(df)

        # Detect signals
        df = self.detect_signals(df)

        # Backtest
        trades = self.backtest_signals(df)

        if not trades:
            logger.warning("⚠️  No trades generated")
            return None

        # Analyze
        stats = self.analyze_performance(trades)

        # Report
        self.print_report(stats)

        return {'stats': stats, 'trades': trades}


def main():
    """Main execution"""
    configs = [
        {'symbol': 'EURUSD', 'timeframe': 'H1', 'days_back': 30},
        {'symbol': 'EURUSD', 'timeframe': 'M5', 'days_back': 30},
        {'symbol': 'XAUUSD', 'timeframe': 'H1', 'days_back': 30},
        {'symbol': 'XAUUSD', 'timeframe': 'M5', 'days_back': 30},
        {'symbol': 'GBPUSD', 'timeframe': 'H1', 'days_back': 30},
        {'symbol': 'USDJPY', 'timeframe': 'H1', 'days_back': 30},
        {'symbol': 'DE40.c', 'timeframe': 'H1', 'days_back': 30},
    ]

    all_results = []

    for config in configs:
        try:
            bt = HeikenAshiBacktestV2(**config)
            result = bt.run()

            if result:
                all_results.append({
                    'symbol': config['symbol'],
                    'timeframe': config['timeframe'],
                    'stats': result['stats']
                })

        except Exception as e:
            logger.error(f"❌ Error: {config['symbol']} {config['timeframe']}: {e}", exc_info=True)

    # Summary
    if all_results:
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 SUMMARY - ALL SYMBOLS")
        logger.info(f"{'='*80}")
        logger.info(f"{'Symbol':<12} {'TF':<6} {'Trades':<8} {'Win Rate':<12} {'Avg P/L':<12} {'Total P/L':<12}")
        logger.info(f"{'-'*80}")

        for r in all_results:
            s = r['stats']
            logger.info(
                f"{r['symbol']:<12} {r['timeframe']:<6} {s['total_trades']:<8} "
                f"{s['win_rate']:<12.1f}% {s['avg_pnl']:<+12.2f}% {s['total_pnl']:<+12.2f}%"
            )

        logger.info(f"{'='*80}\n")

        # Best performers
        if len(all_results) > 0:
            best_wr = max(all_results, key=lambda x: x['stats']['win_rate'])
            best_pnl = max(all_results, key=lambda x: x['stats']['total_pnl'])

            logger.info(f"🏆 Best Win Rate: {best_wr['symbol']} {best_wr['timeframe']} ({best_wr['stats']['win_rate']:.1f}%)")
            logger.info(f"💰 Best Total P/L: {best_pnl['symbol']} {best_pnl['timeframe']} ({best_pnl['stats']['total_pnl']:+.2f}%)\n")


if __name__ == '__main__':
    main()

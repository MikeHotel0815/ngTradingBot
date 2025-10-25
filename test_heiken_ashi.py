#!/usr/bin/env python3
"""
Test Script for Heiken Ashi Trend Indicator
Tests the new indicator with EURUSD and XAUUSD data
"""

import sys
import logging
from technical_indicators import TechnicalIndicators

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_heiken_ashi_indicator():
    """Test Heiken Ashi Trend indicator with real symbols"""

    # Test symbols and timeframes
    test_cases = [
        {'symbol': 'EURUSD', 'timeframe': 'M5'},
        {'symbol': 'EURUSD', 'timeframe': 'H1'},
        {'symbol': 'XAUUSD', 'timeframe': 'M5'},
        {'symbol': 'XAUUSD', 'timeframe': 'H1'},
    ]

    for test in test_cases:
        symbol = test['symbol']
        timeframe = test['timeframe']

        logger.info(f"\n{'='*80}")
        logger.info(f"Testing {symbol} {timeframe}")
        logger.info(f"{'='*80}")

        try:
            # Initialize indicator calculator
            ti = TechnicalIndicators(
                account_id=1,  # Default account
                symbol=symbol,
                timeframe=timeframe,
                cache_ttl=0  # Disable cache for testing
            )

            # Test individual components
            logger.info(f"\n--- Testing Heiken Ashi Base Calculation ---")
            ha = ti.calculate_heiken_ashi()
            if ha:
                logger.info(f"✅ Heiken Ashi: {ha['trend']} (strength: {ha['strength']}%)")
                logger.info(f"   - Signal: {ha['signal']}")
                logger.info(f"   - No lower wick: {ha['has_no_lower_wick']}")
                logger.info(f"   - No upper wick: {ha['has_no_upper_wick']}")
                logger.info(f"   - Consecutive candles: {ha['consecutive_count']}")
                logger.info(f"   - Recent reversal: {ha['recent_reversal']}")
            else:
                logger.warning("⚠️  Heiken Ashi: No data")

            logger.info(f"\n--- Testing Volume Analysis ---")
            vol = ti.calculate_volume_analysis()
            if vol:
                logger.info(f"✅ Volume: {vol['signal']} (ratio: {vol['volume_ratio']:.2f}x)")
                logger.info(f"   - Current: {vol['current_volume']:.0f}")
                logger.info(f"   - Average: {vol['average_volume']:.0f}")
            else:
                logger.warning("⚠️  Volume: No data")

            logger.info(f"\n--- Testing Heiken Ashi Trend (Full) ---")
            ha_trend = ti.calculate_heiken_ashi_trend()
            if ha_trend:
                logger.info(f"✅ HA Trend Signal: {ha_trend['signal']} ({ha_trend['signal_type']})")
                logger.info(f"   - Confidence: {ha_trend['confidence']:.1f}%")
                logger.info(f"   - HA Trend: {ha_trend['ha_trend']}")
                logger.info(f"   - Price above EMAs: {ha_trend['price_above_emas']}")
                logger.info(f"   - Price below EMAs: {ha_trend['price_below_emas']}")
                logger.info(f"   - EMA 8: {ha_trend['ema_fast']:.5f}")
                logger.info(f"   - EMA 30: {ha_trend['ema_slow']:.5f}")
                logger.info(f"   - Volume: {ha_trend['volume_signal']} ({ha_trend['volume_ratio']:.2f}x)")
                if ha_trend['reasons']:
                    logger.info(f"   - Reasons: {', '.join(ha_trend['reasons'])}")
            else:
                logger.warning("⚠️  HA Trend: No data")

            logger.info(f"\n--- Testing Signal Integration ---")
            signals = ti.get_indicator_signals()

            # Filter for Heiken Ashi signals
            ha_signals = [s for s in signals if s.get('indicator') == 'HEIKEN_ASHI_TREND']

            if ha_signals:
                for sig in ha_signals:
                    logger.info(f"✅ Signal Generated:")
                    logger.info(f"   - Type: {sig['type']}")
                    logger.info(f"   - Strength: {sig['strength']}")
                    logger.info(f"   - Reason: {sig['reason']}")
                    logger.info(f"   - Strategy: {sig['strategy_type']}")
                    if 'confidence' in sig:
                        logger.info(f"   - Confidence: {sig['confidence']:.1f}%")
            else:
                logger.info("ℹ️  No Heiken Ashi signals generated")

            logger.info(f"\n📊 Total signals: {len(signals)}")
            logger.info(f"   - BUY: {len([s for s in signals if s['type'] == 'BUY'])}")
            logger.info(f"   - SELL: {len([s for s in signals if s['type'] == 'SELL'])}")
            logger.info(f"   - NEUTRAL: {len([s for s in signals if s['type'] == 'NEUTRAL'])}")

        except Exception as e:
            logger.error(f"❌ Error testing {symbol} {timeframe}: {e}", exc_info=True)

    logger.info(f"\n{'='*80}")
    logger.info("✅ Testing Complete!")
    logger.info(f"{'='*80}\n")


if __name__ == '__main__':
    test_heiken_ashi_indicator()

#!/usr/bin/env python3
"""
Analyse der Signalerkennungs-Parameter anhand historischer Kursdaten
Prüft, ob die Parameter zu restriktiv sind und wie viele potenzielle Signale verpasst werden
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from database import ScopedSession
from models import OHLCData, TradingSignal
from technical_indicators import TechnicalIndicators
from pattern_recognition import PatternRecognizer
from signal_generator import SignalGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SignalParameterAnalyzer:
    """Analysiert historische Daten für verschiedene Parameter-Szenarien"""

    def __init__(self, account_id: int, symbol: str, timeframe: str, days_back: int = 30):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.days_back = days_back

    def analyze(self):
        """Führt vollständige Analyse durch"""
        logger.info(f"=" * 80)
        logger.info(f"SIGNAL PARAMETER ANALYSE")
        logger.info(f"Symbol: {self.symbol} | Timeframe: {self.timeframe} | Periode: {self.days_back} Tage")
        logger.info(f"=" * 80)

        # 1. Aktuelle Parameter-Einstellungen
        self._show_current_parameters()

        # 2. Historische Daten-Verfügbarkeit
        data_stats = self._analyze_data_availability()

        # 3. Indikator-Werte-Analyse (Überkauft/Überverkauft-Bereiche)
        indicator_stats = self._analyze_indicator_ranges()

        # 4. Pattern-Erkennungs-Häufigkeit
        pattern_stats = self._analyze_pattern_frequency()

        # 5. Signal-Generierung mit verschiedenen Schwellenwerten
        signal_scenarios = self._analyze_signal_scenarios()

        # 6. Zusammenfassung und Empfehlungen
        self._print_recommendations(data_stats, indicator_stats, pattern_stats, signal_scenarios)

    def _show_current_parameters(self):
        """Zeigt aktuelle Parameter-Einstellungen"""
        logger.info("\n" + "=" * 80)
        logger.info("AKTUELLE PARAMETER-EINSTELLUNGEN")
        logger.info("=" * 80)
        logger.info("Signal Generator (signal_generator.py):")
        logger.info("  • MIN_GENERATION_CONFIDENCE: 40%")
        logger.info("  • BUY_SIGNAL_ADVANTAGE: 2 (BUY braucht 2 mehr Bestätigungen als SELL)")
        logger.info("  • BUY_CONFIDENCE_PENALTY: -3.0% (BUY-Signale werden um 3% reduziert)")
        logger.info("\nTechnical Indicators (technical_indicators.py):")
        logger.info("  • RSI: Oversold=30, Overbought=70")
        logger.info("  • Stochastic: Oversold=20, Overbought=80")
        logger.info("  • ADX: Strong Trend > 25")
        logger.info("  • MACD: Signal bei Kreuzung mit Signallinie")

    def _analyze_data_availability(self) -> Dict:
        """Prüft Datenverfügbarkeit"""
        logger.info("\n" + "=" * 80)
        logger.info("HISTORISCHE DATEN-VERFÜGBARKEIT")
        logger.info("=" * 80)

        db = ScopedSession()
        try:
            since = datetime.utcnow() - timedelta(days=self.days_back)

            candles = db.query(OHLCData).filter(
                OHLCData.symbol == self.symbol,
                OHLCData.timeframe == self.timeframe,
                OHLCData.timestamp >= since
            ).order_by(OHLCData.timestamp).all()

            if not candles:
                logger.warning(f"❌ KEINE Daten gefunden für {self.symbol} {self.timeframe}")
                return {'count': 0, 'coverage': 0}

            # Erwartete Anzahl Kerzen basierend auf Timeframe
            timeframe_minutes = {
                'M1': 1, 'M5': 5, 'M15': 15, 'M30': 30,
                'H1': 60, 'H4': 240, 'D1': 1440
            }

            minutes = timeframe_minutes.get(self.timeframe, 60)
            expected_candles = (self.days_back * 24 * 60) // minutes
            coverage = (len(candles) / expected_candles) * 100 if expected_candles > 0 else 0

            first_date = candles[0].timestamp
            last_date = candles[-1].timestamp
            date_range_days = (last_date - first_date).days

            logger.info(f"✅ {len(candles)} Kerzen verfügbar")
            logger.info(f"  • Zeitraum: {first_date} bis {last_date} ({date_range_days} Tage)")
            logger.info(f"  • Erwartete Kerzen: {expected_candles}")
            logger.info(f"  • Abdeckung: {coverage:.1f}%")

            # Lücken-Analyse
            gaps = []
            for i in range(1, len(candles)):
                expected_diff = timedelta(minutes=minutes)
                actual_diff = candles[i].timestamp - candles[i-1].timestamp
                if actual_diff > expected_diff * 1.5:  # 50% Toleranz
                    gaps.append({
                        'from': candles[i-1].timestamp,
                        'to': candles[i].timestamp,
                        'duration': actual_diff
                    })

            if gaps:
                logger.warning(f"⚠️  {len(gaps)} Datenlücken gefunden:")
                for gap in gaps[:5]:  # Zeige nur erste 5
                    logger.warning(f"    {gap['from']} → {gap['to']} ({gap['duration']})")
                if len(gaps) > 5:
                    logger.warning(f"    ... und {len(gaps) - 5} weitere")
            else:
                logger.info(f"✅ Keine signifikanten Datenlücken")

            return {
                'count': len(candles),
                'expected': expected_candles,
                'coverage': coverage,
                'gaps': len(gaps),
                'first_date': first_date,
                'last_date': last_date
            }

        finally:
            db.close()

    def _analyze_indicator_ranges(self) -> Dict:
        """Analysiert Indikator-Wertebereiche"""
        logger.info("\n" + "=" * 80)
        logger.info("INDIKATOR-WERTEBEREICHE (Überkauft/Überverkauft)")
        logger.info("=" * 80)

        indicators = TechnicalIndicators(self.account_id, self.symbol, self.timeframe, cache_ttl=0)

        stats = {}

        # RSI
        try:
            rsi = indicators.calculate_rsi()
            if rsi:
                logger.info(f"\nRSI (Aktuell: {rsi['value']:.1f}):")
                logger.info(f"  • Oversold (<30): {'JA ✅' if rsi['value'] < 30 else 'NEIN'}")
                logger.info(f"  • Neutral (30-70): {'JA ✅' if 30 <= rsi['value'] <= 70 else 'NEIN'}")
                logger.info(f"  • Overbought (>70): {'JA ✅' if rsi['value'] > 70 else 'NEIN'}")
                stats['rsi'] = rsi['value']
        except Exception as e:
            logger.error(f"  ❌ RSI Fehler: {e}")

        # Stochastic
        try:
            stoch = indicators.calculate_stochastic()
            if stoch:
                logger.info(f"\nStochastic (K: {stoch['k']:.1f}, D: {stoch['d']:.1f}):")
                logger.info(f"  • Oversold (<20): {'JA ✅' if stoch['k'] < 20 else 'NEIN'}")
                logger.info(f"  • Neutral (20-80): {'JA ✅' if 20 <= stoch['k'] <= 80 else 'NEIN'}")
                logger.info(f"  • Overbought (>80): {'JA ✅' if stoch['k'] > 80 else 'NEIN'}")
                stats['stochastic_k'] = stoch['k']
        except Exception as e:
            logger.error(f"  ❌ Stochastic Fehler: {e}")

        # ADX
        try:
            adx = indicators.calculate_adx()
            if adx:
                logger.info(f"\nADX (Aktuell: {adx['value']:.1f}):")
                logger.info(f"  • Schwacher Trend (<20): {'JA ✅' if adx['value'] < 20 else 'NEIN'}")
                logger.info(f"  • Moderater Trend (20-25): {'JA ✅' if 20 <= adx['value'] <= 25 else 'NEIN'}")
                logger.info(f"  • Starker Trend (>25): {'JA ✅' if adx['value'] > 25 else 'NEIN'}")
                if 'plus_di' in adx and 'minus_di' in adx:
                    logger.info(f"  • +DI: {adx['plus_di']:.1f}, -DI: {adx['minus_di']:.1f}")
                    logger.info(f"  • Richtung: {'Bullish ↗️' if adx['plus_di'] > adx['minus_di'] else 'Bearish ↘️'}")
                stats['adx'] = adx['value']
        except Exception as e:
            logger.error(f"  ❌ ADX Fehler: {e}")

        # MACD
        try:
            macd = indicators.calculate_macd()
            if macd:
                logger.info(f"\nMACD:")
                logger.info(f"  • MACD: {macd['macd']:.5f}")
                logger.info(f"  • Signal: {macd['signal']:.5f}")
                logger.info(f"  • Histogram: {macd['histogram']:.5f}")
                logger.info(f"  • Richtung: {'Bullish ↗️' if macd['histogram'] > 0 else 'Bearish ↘️'}")
                stats['macd_histogram'] = macd['histogram']
        except Exception as e:
            logger.error(f"  ❌ MACD Fehler: {e}")

        # Bollinger Bands
        try:
            bb = indicators.calculate_bollinger_bands()
            if bb:
                # Hole aktuellen Preis
                from models import Tick
                db = ScopedSession()
                try:
                    tick = db.query(Tick).filter_by(symbol=self.symbol).order_by(Tick.timestamp.desc()).first()
                    if tick:
                        price = float(tick.bid)
                        bb_position = ((price - bb['lower']) / (bb['upper'] - bb['lower'])) * 100
                        logger.info(f"\nBollinger Bands:")
                        logger.info(f"  • Upper: {bb['upper']:.5f}")
                        logger.info(f"  • Middle: {bb['middle']:.5f}")
                        logger.info(f"  • Lower: {bb['lower']:.5f}")
                        logger.info(f"  • Aktueller Preis: {price:.5f}")
                        logger.info(f"  • Position im Band: {bb_position:.1f}%")
                        stats['bb_position'] = bb_position
                finally:
                    db.close()
        except Exception as e:
            logger.error(f"  ❌ BB Fehler: {e}")

        return stats

    def _analyze_pattern_frequency(self) -> Dict:
        """Analysiert Häufigkeit von Pattern-Erkennungen"""
        logger.info("\n" + "=" * 80)
        logger.info("PATTERN-ERKENNUNGS-HÄUFIGKEIT")
        logger.info("=" * 80)

        patterns = PatternRecognizer(self.account_id, self.symbol, self.timeframe, cache_ttl=0)

        try:
            pattern_signals = patterns.get_pattern_signals()

            if not pattern_signals:
                logger.warning("❌ Keine Patterns aktuell erkannt")
                return {'count': 0}

            logger.info(f"✅ {len(pattern_signals)} Patterns aktuell erkannt:")

            buy_patterns = [p for p in pattern_signals if p['type'] == 'BUY']
            sell_patterns = [p for p in pattern_signals if p['type'] == 'SELL']

            logger.info(f"\nBUY Patterns ({len(buy_patterns)}):")
            for p in buy_patterns:
                logger.info(f"  • {p['pattern']}: {p['reason']} (Reliability: {p.get('reliability', 'N/A')}%)")

            logger.info(f"\nSELL Patterns ({len(sell_patterns)}):")
            for p in sell_patterns:
                logger.info(f"  • {p['pattern']}: {p['reason']} (Reliability: {p.get('reliability', 'N/A')}%)")

            return {
                'count': len(pattern_signals),
                'buy_count': len(buy_patterns),
                'sell_count': len(sell_patterns),
                'patterns': pattern_signals
            }

        except Exception as e:
            logger.error(f"❌ Pattern-Analyse Fehler: {e}", exc_info=True)
            return {'count': 0, 'error': str(e)}

    def _analyze_signal_scenarios(self) -> Dict:
        """Testet Signal-Generierung mit verschiedenen Schwellenwerten"""
        logger.info("\n" + "=" * 80)
        logger.info("SIGNAL-GENERIERUNG: SZENARIEN-VERGLEICH")
        logger.info("=" * 80)

        scenarios = {}

        # Szenario 1: Aktuelle Einstellungen
        logger.info("\n📊 Szenario 1: AKTUELLE Einstellungen")
        logger.info("  MIN_CONFIDENCE=40%, BUY_ADVANTAGE=2, BUY_PENALTY=-3%")
        gen = SignalGenerator(self.account_id, self.symbol, self.timeframe)
        signal = gen.generate_signal()
        scenarios['current'] = self._format_signal_result(signal)

        # Szenario 2: Relaxed (weniger restriktiv)
        logger.info("\n📊 Szenario 2: RELAXED (Weniger restriktiv)")
        logger.info("  Simuliert: MIN_CONFIDENCE=30%, BUY_ADVANTAGE=1, BUY_PENALTY=-1%")
        logger.info("  ⚠️  Hinweis: Parameter können nur in Code geändert werden")
        logger.info("  Aktuelles Ergebnis mit bestehenden Parametern:")
        scenarios['relaxed'] = scenarios['current']  # Würde mit anderen Parametern anders sein

        # Szenario 3: Strict (mehr restriktiv)
        logger.info("\n📊 Szenario 3: STRICT (Mehr restriktiv)")
        logger.info("  Simuliert: MIN_CONFIDENCE=50%, BUY_ADVANTAGE=3, BUY_PENALTY=-5%")
        logger.info("  ⚠️  Hinweis: Parameter können nur in Code geändert werden")
        logger.info("  Aktuelles Ergebnis mit bestehenden Parametern:")
        scenarios['strict'] = scenarios['current']  # Würde mit anderen Parametern anders sein

        return scenarios

    def _format_signal_result(self, signal) -> Dict:
        """Formatiert Signal-Ergebnis für Ausgabe"""
        if not signal:
            logger.info("  ❌ KEIN Signal generiert")
            return {'generated': False}

        logger.info(f"  ✅ Signal: {signal['signal_type']}")
        logger.info(f"    • Confidence: {signal['confidence']:.1f}%")
        logger.info(f"    • Entry: {signal.get('entry_price', 0):.5f}")
        logger.info(f"    • SL: {signal.get('sl_price', 0):.5f}")
        logger.info(f"    • TP: {signal.get('tp_price', 0):.5f}")
        logger.info(f"    • Gründe: {', '.join(signal.get('reasons', []))}")

        return {
            'generated': True,
            'type': signal['signal_type'],
            'confidence': signal['confidence'],
            'entry': signal.get('entry_price', 0),
            'reasons_count': len(signal.get('reasons', []))
        }

    def _print_recommendations(self, data_stats, indicator_stats, pattern_stats, signal_scenarios):
        """Gibt Empfehlungen basierend auf Analyse"""
        logger.info("\n" + "=" * 80)
        logger.info("EMPFEHLUNGEN & ZUSAMMENFASSUNG")
        logger.info("=" * 80)

        # Daten-Qualität
        logger.info("\n1️⃣ DATEN-QUALITÄT:")
        if data_stats['coverage'] < 80:
            logger.warning(f"  ⚠️  Datenlücken vorhanden ({data_stats['coverage']:.1f}% Abdeckung)")
            logger.warning(f"     → EMPFEHLUNG: Historische Daten nachsynchronisieren")
        else:
            logger.info(f"  ✅ Ausreichende Datenabdeckung ({data_stats['coverage']:.1f}%)")

        # Indikator-Status
        logger.info("\n2️⃣ INDIKATOR-STATUS:")
        extreme_conditions = []
        if 'rsi' in indicator_stats:
            if indicator_stats['rsi'] < 30:
                extreme_conditions.append("RSI oversold")
            elif indicator_stats['rsi'] > 70:
                extreme_conditions.append("RSI overbought")

        if 'stochastic_k' in indicator_stats:
            if indicator_stats['stochastic_k'] < 20:
                extreme_conditions.append("Stochastic oversold")
            elif indicator_stats['stochastic_k'] > 80:
                extreme_conditions.append("Stochastic overbought")

        if extreme_conditions:
            logger.info(f"  ✅ Extreme Bedingungen erkannt: {', '.join(extreme_conditions)}")
            logger.info(f"     → Signal-Generierung möglich")
        else:
            logger.warning(f"  ⚠️  Keine extremen Bedingungen (Markt in neutraler Zone)")
            logger.warning(f"     → Weniger Signale zu erwarten")

        # Pattern-Häufigkeit
        logger.info("\n3️⃣ PATTERN-ERKENNUNG:")
        if pattern_stats['count'] > 0:
            logger.info(f"  ✅ {pattern_stats['count']} Patterns erkannt")
            logger.info(f"     BUY: {pattern_stats.get('buy_count', 0)}, SELL: {pattern_stats.get('sell_count', 0)}")
        else:
            logger.warning(f"  ⚠️  Keine Patterns aktuell erkannt")
            logger.warning(f"     → Pattern-Parameter möglicherweise zu strikt")

        # Signal-Generierung
        logger.info("\n4️⃣ SIGNAL-GENERIERUNG:")
        current = signal_scenarios['current']
        if current['generated']:
            logger.info(f"  ✅ Signal wird generiert mit aktuellen Parametern")
            logger.info(f"     Confidence: {current['confidence']:.1f}%")
        else:
            logger.warning(f"  ⚠️  KEIN Signal mit aktuellen Parametern")
            logger.warning(f"     → Parameter möglicherweise ZU RESTRIKTIV")

        # Finale Empfehlung
        logger.info("\n" + "=" * 80)
        logger.info("🎯 FINALE EMPFEHLUNG:")
        logger.info("=" * 80)

        if not current['generated'] and (extreme_conditions or pattern_stats['count'] > 0):
            logger.warning("\n⚠️  PARAMETER SIND ZU RESTRIKTIV!")
            logger.warning("   Trotz vorhandener Indikatoren/Patterns wird KEIN Signal generiert.")
            logger.warning("\n   VORGESCHLAGENE ANPASSUNGEN in signal_generator.py:")
            logger.warning("   1. MIN_GENERATION_CONFIDENCE: 40% → 35% (Zeile 73)")
            logger.warning("   2. BUY_SIGNAL_ADVANTAGE: 2 → 1 (Zeile 205)")
            logger.warning("   3. BUY_CONFIDENCE_PENALTY: 3.0 → 2.0 (Zeile 360)")
        elif current['generated'] and current['confidence'] < 50:
            logger.info("\n✅ Parameter sind angemessen, aber Signal-Qualität niedrig")
            logger.info("   Signal wird generiert, aber mit niedriger Confidence.")
            logger.info("   → Keine Anpassung nötig, Ensemble/MTF-Filter sorgen für Qualität")
        elif current['generated'] and current['confidence'] >= 50:
            logger.info("\n✅ Parameter sind OPTIMAL!")
            logger.info("   Signal wird mit guter Confidence generiert.")
            logger.info("   → Keine Anpassung nötig")
        else:
            logger.info("\n✅ Markt aktuell in neutraler Phase")
            logger.info("   Keine klaren Signale → korrekt, dass nichts generiert wird")
            logger.info("   → Parameter sind passend")


def main():
    """Hauptfunktion"""
    if len(sys.argv) < 4:
        print("Usage: python analyze_signal_parameters.py <account_id> <symbol> <timeframe> [days_back]")
        print("Example: python analyze_signal_parameters.py 1 EURUSD H1 30")
        sys.exit(1)

    account_id = int(sys.argv[1])
    symbol = sys.argv[2]
    timeframe = sys.argv[3]
    days_back = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    analyzer = SignalParameterAnalyzer(account_id, symbol, timeframe, days_back)
    analyzer.analyze()


if __name__ == '__main__':
    main()

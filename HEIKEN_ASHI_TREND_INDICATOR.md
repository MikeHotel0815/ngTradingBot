# Heiken Ashi Trend w/vol Signals - Implementation

## Overview

Der **Heiken Ashi Trend w/vol Signals** Indikator wurde erfolgreich in das Trading System integriert. Dieser Indikator kombiniert drei leistungsstarke Techniken zur Trend-Erkennung:

1. **Heiken Ashi Kerzen** - Geglättete Preisdarstellung zur Noise-Filterung
2. **EMA 8/30 Bestätigung** - Trend-Richtungsfilter
3. **Volumen-Analyse** - Signalstärken-Bestätigung

## Source

- **TradingView**: [Heiken Ashi Trend w/vol Signals](https://www.tradingview.com/script/xEwtRwVZ-Heiken-Ashi-Trend-w-vol-Signals/)
- **Implementiert am**: 2025-10-25

## Implementation Details

### 1. Heiken Ashi Berechnung (`calculate_heiken_ashi()`)

**Formeln:**
```python
HA Close = (Open + High + Low + Close) / 4
HA Open = (Previous HA Open + Previous HA Close) / 2
HA High = max(High, HA Open, HA Close)
HA Low = min(Low, HA Open, HA Close)
```

**Signale:**
- **Strong Bullish**: Grüne Kerze ohne unteren Docht (< 10% des Body)
- **Strong Bearish**: Rote Kerze ohne oberen Docht (< 10% des Body)
- **Trend Strength**: Basierend auf konsekutiven gleichfarbigen Kerzen (max 5)

**Output:**
```python
{
    'ha_open': float,
    'ha_close': float,
    'ha_high': float,
    'ha_low': float,
    'trend': str,  # 'strong_bullish', 'bullish', 'neutral', 'bearish', 'strong_bearish'
    'signal': str,  # 'strong_buy', 'buy', 'neutral', 'sell', 'strong_sell'
    'strength': int,  # 0-100%
    'has_no_lower_wick': bool,
    'has_no_upper_wick': bool,
    'consecutive_count': int,
    'recent_reversal': bool
}
```

### 2. Volumen-Analyse (`calculate_volume_analysis()`)

**Berechnung:**
- Vergleicht aktuelles Volumen mit 20-Period Durchschnitt
- Kategorisiert Volumen-Stärke

**Kategorien:**
- **Very High**: Ratio ≥ 1.5x (Boost: +30%)
- **High**: Ratio ≥ 1.2x (Boost: +15%)
- **Normal**: 0.8x < Ratio < 1.2x (Boost: 0%)
- **Low**: Ratio ≤ 0.8x (Penalty: -15%)
- **Very Low**: Ratio ≤ 0.6x (Penalty: -15%)

**Output:**
```python
{
    'current_volume': float,
    'average_volume': float,
    'volume_ratio': float,
    'signal': str,  # 'high_volume', 'above_average', 'neutral', 'below_average', 'low_volume'
    'strength': str  # 'very_high', 'high', 'normal', 'low', 'very_low'
}
```

### 3. Heiken Ashi Trend (`calculate_heiken_ashi_trend()`)

**Kombiniert alle drei Komponenten:**

#### LONG Entry Bedingungen:
1. HA Signal: `strong_buy` oder `buy`
2. HA Kerze: Keine unterer Docht (`has_no_lower_wick = True`)
3. Preis: Über beiden EMAs (8 & 30)
4. EMAs: Bullish aligned (EMA 8 > EMA 30)
5. Reversal: Kürzliche rote Kerze in letzten 4 Bars

**Confidence Berechnung:**
```python
Base: HA Strength (40-100%)
+ Strong HA Signal: +10%
+ EMA Alignment: +15%
+ Recent Reversal: +10%
× Volume Multiplier: 0.85x - 1.3x
= Final Confidence (capped at 100%)
```

#### SHORT Entry Bedingungen:
1. HA Signal: `strong_sell` oder `sell`
2. HA Kerze: Keine oberer Docht (`has_no_upper_wick = True`)
3. Preis: Unter beiden EMAs (8 & 30)
4. EMAs: Bearish aligned (EMA 8 < EMA 30)
5. Reversal: Kürzliche grüne Kerze in letzten 4 Bars

**Exit Signale:**
- **LONG EXIT**: Erste bearish Kerze nach bullish Trend
- **SHORT EXIT**: Erste bullish Kerze nach bearish Trend

**Output:**
```python
{
    'signal': str,  # 'buy', 'sell', 'exit_long', 'exit_short', 'neutral'
    'signal_type': str,  # 'LONG_ENTRY', 'SHORT_ENTRY', 'LONG_EXIT', 'SHORT_EXIT'
    'confidence': int,  # 0-100%
    'reasons': List[str],
    'ha_trend': str,
    'price_above_emas': bool,
    'price_below_emas': bool,
    'ema_fast': float,
    'ema_slow': float,
    'volume_signal': str,
    'volume_ratio': float
}
```

## Integration in Signal Generator

### Added to `calculate_all()`

```python
indicators['EMA_8'] = self.calculate_ema(8)
indicators['EMA_30'] = self.calculate_ema(30)
indicators['HEIKEN_ASHI_TREND'] = self.calculate_heiken_ashi_trend()
indicators['VOLUME'] = self.calculate_volume_analysis()
```

### Added to `get_indicator_signals()`

Der Indikator wird als **Trend-Following** Strategie klassifiziert:

```python
if indicators['HEIKEN_ASHI_TREND']:
    ha_trend = indicators['HEIKEN_ASHI_TREND']
    if ha_trend['signal'] == 'buy' and ha_trend['signal_type'] == 'LONG_ENTRY':
        signals.append({
            'indicator': 'HEIKEN_ASHI_TREND',
            'type': 'BUY',
            'reason': f"HA Trend: {', '.join(ha_trend['reasons'])}",
            'strength': 'very_strong' | 'strong' | 'medium' | 'weak',  # Based on confidence
            'strategy_type': 'trend_following',
            'confidence': ha_trend['confidence']
        })
```

**Confidence → Strength Mapping:**
- ≥ 80%: `very_strong`
- ≥ 70%: `strong`
- ≥ 60%: `medium`
- < 60%: `weak`

## Market Regime Integration

Der Heiken Ashi Trend Indikator ist als **trend_following** markiert:

### TRENDING Markets
- ✅ **AKTIV** - Signale werden generiert
- Ideal für starke Trends mit klarer Richtung
- Kombiniert gut mit: MACD, ADX, SuperTrend, Ichimoku

### RANGING Markets
- ❌ **INAKTIV** - Signale werden gefiltert
- Verhindert False Signals in Seitwärtsmärkten
- Mean-Reversion Strategien werden bevorzugt (RSI, BB, Stochastic)

### TOO_WEAK Markets (ADX < 12)
- ❌ **INAKTIV** - Alle Signale werden gefiltert

## Performance Characteristics

### Strengths
1. **Noise Reduction**: Heiken Ashi glättet Preisbewegungen
2. **Trend Confirmation**: Mehrfache Filter (HA + EMA + Volume)
3. **High Confidence**: Nur starke Setups werden signalisiert
4. **Volume Validation**: Verhindert schwache Signale

### Ideal Conditions
- **Timeframes**: H1, H4, D1 (wie im Original TradingView Script)
- **Market**: Starke Trends (ADX > 25)
- **Volume**: Überdurchschnittlich (Ratio > 1.2x)
- **Setup**: Pullback nach Reversal + EMA Alignment

### Limitations
- Nicht geeignet für Ranging Markets (wird automatisch gefiltert)
- Benötigt klare Trend-Richtung
- Späte Einstiege möglich (wartet auf Bestätigung)

## Testing

### Test Script: `test_heiken_ashi.py`

```bash
cd /projects/ngTradingBot
python3 test_heiken_ashi.py
```

Tests:
- ✅ Heiken Ashi Base Calculation
- ✅ Volume Analysis
- ✅ Full HA Trend Indicator
- ✅ Signal Integration in `get_indicator_signals()`

### Manual Testing in Docker

```bash
docker exec -it ngTradingBot bash
cd /app
python3 test_heiken_ashi.py
```

## Usage in Trading System

Der Indikator wird automatisch vom `signal_generator.py` verwendet:

1. **Calculation**: Bei jedem Signal-Generation Zyklus
2. **Caching**: 15 Sekunden TTL (wie alle Indikatoren)
3. **Regime Filtering**: Nur in TRENDING Markets aktiv
4. **Confidence Integration**: Fließt in Gesamt-Signal-Confidence ein

### Signal Flow

```
OHLC Data
    ↓
Heiken Ashi Calculation
    ↓
EMA 8/30 Confirmation
    ↓
Volume Analysis
    ↓
HA Trend Signal (confidence + reasons)
    ↓
get_indicator_signals() [marked as trend_following]
    ↓
Regime Filter (only TRENDING markets)
    ↓
Signal Aggregation (signal_generator.py)
    ↓
Trading Signal (if confidence ≥ 50%)
```

## Configuration

### Default Parameters

```python
# EMA Periods (from TradingView original)
ema_fast = 8
ema_slow = 30

# Volume Analysis
volume_period = 20

# HA Trend Detection
wick_threshold = 0.1  # 10% of body size
reversal_lookback = 4  # bars
consecutive_max = 5  # bars
```

### Customization

Parameters können in Zukunft über Symbol-spezifische Config erweitert werden:

```python
# Example: symbol_config.json
{
    "EURUSD": {
        "heiken_ashi_trend": {
            "ema_fast": 8,
            "ema_slow": 30,
            "volume_period": 20,
            "min_confidence": 60
        }
    }
}
```

## Files Modified

1. ✅ `technical_indicators.py`
   - Added: `calculate_heiken_ashi()`
   - Added: `calculate_volume_analysis()`
   - Added: `calculate_heiken_ashi_trend()`
   - Modified: `calculate_all()` - Added EMA 8/30, HA Trend, Volume
   - Modified: `get_indicator_signals()` - Added HA Trend signal generation

2. ✅ `test_heiken_ashi.py` (NEW)
   - Test script for validation

3. ✅ `HEIKEN_ASHI_TREND_INDICATOR.md` (NEW)
   - This documentation file

## Next Steps

### Production Deployment

1. **Restart Signal Workers**:
   ```bash
   docker exec -it ngTradingBot supervisorctl restart signal_worker
   ```

2. **Monitor Logs**:
   ```bash
   docker logs -f ngTradingBot | grep "HEIKEN_ASHI"
   ```

3. **Verify Signals**:
   - Check WebUI for new signals
   - Look for "HA Trend:" in signal reasons

### Performance Validation

Track these metrics over 24-48 hours:

- **Signal Count**: How many HA Trend signals are generated?
- **Win Rate**: Do HA Trend signals improve overall win rate?
- **Confidence Correlation**: Is higher HA confidence = higher win rate?
- **Volume Impact**: Does high volume boost actual performance?

### Potential Optimizations

If performance is good, consider:

1. **Parameter Tuning**: Test different EMA periods (e.g., 5/21, 13/50)
2. **Symbol-Specific Config**: Different params for Forex vs Metals
3. **Multi-Timeframe**: Combine H1 + H4 HA Trend for higher confidence
4. **SL/TP Integration**: Use HA candles for dynamic stop-loss placement

## Support

For issues or questions:
- Check logs: `docker logs ngTradingBot`
- Review signal history in database
- Adjust confidence thresholds in signal_generator.py

## Changelog

### 2025-10-25
- ✅ Initial implementation
- ✅ Heiken Ashi base calculation
- ✅ Volume analysis integration
- ✅ Full HA Trend indicator
- ✅ Signal generation integration
- ✅ Regime-based filtering
- ✅ Test script created
- ✅ Documentation completed

# Confidence Threshold Anpassungen - 16. Oktober 2025

## Problem
Symbole erreichten die Confidence-Schwellwerte nicht, was zu wenig Trading-Aktivität führte.

## Root Cause Analysis

### Multi-Layer Filtering System:
1. **Signal Generation**: MIN_GENERATION_CONFIDENCE = 40%
2. **BUY Penalty**: Automatisch -5% für alle BUY-Signale
3. **Symbol Config**: Statische Schwellwerte 60-70%
4. **Auto-Trader**: Nimmt MAX(global_confidence, symbol_confidence)
5. **Ensemble Validation**: BUY ≥45%, SELL ≥40% + 2/7 Indikatoren

### Beispiel-Szenario (vorher):
```
Signal berechnet:           58%
- BUY Penalty:             -5%  → 53%
- Multi-TF Adjustment:     -5%  → 48%
Ensemble Check:            PASS (48% > 45%)
Symbol Config (EURUSD):    FAIL (48% < 60%)
❌ Signal wird NICHT getradet
```

## Implementierte Änderungen

### 1. Symbol-Spezifische Schwellwerte (symbol_config.py)

| Symbol  | Alt   | Neu   | Änderung | Begründung |
|---------|-------|-------|----------|------------|
| EURUSD  | 60%   | 48%   | -12%     | Hauptpaar, gute Liquidität |
| GBPUSD  | 65%   | 52%   | -13%     | 87.5% WR, qualitativ gut |
| USDJPY  | 60%   | 48%   | -12%     | Konsistente Performance |
| XAUUSD  | 65%   | 52%   | -13%     | Balance Quality/Quantity |
| BTCUSD  | 70%   | 62%   | -8%      | Schlechte WR, weiterhin streng |
| DE40.c  | 55%   | 45%   | -10%     | 100% WR, perfekt |

### 2. Kategorie-Defaults (symbol_config.py)

| Kategorie  | Alt   | Neu   | Änderung |
|------------|-------|-------|----------|
| INDEX      | 55%   | 45%   | -10%     |
| FOREX      | 65%   | 50%   | -15%     |
| CRYPTO     | 60%   | 55%   | -5%      |
| COMMODITY  | 60%   | 50%   | -10%     |

### 3. BUY-Penalty Reduktion (signal_generator.py)

```python
# Alt: -5% Penalty für BUY-Signale
# Neu: -3% Penalty für BUY-Signale
confidence = max(0, confidence - 3.0)  # Reduziert von 5.0
```

## Erwartete Auswirkungen

### Beispiel-Szenario (nachher):
```
Signal berechnet:           58%
- BUY Penalty:             -3%  → 55%
- Multi-TF Adjustment:     -5%  → 50%
Ensemble Check:            PASS (50% > 45%)
Symbol Config (EURUSD):    PASS (50% > 48%)
✅ Signal wird getradet
```

### Quantitative Erwartung:
- **Signal-Durchlass-Rate**: +30-50% mehr Signale
- **BUY-Signal-Durchlass**: +40% (Penalty-Reduktion)
- **EURUSD/GBPUSD**: +50-70% mehr Trades
- **BTCUSD**: Weiterhin selektiv (62% threshold)

### Qualitätssicherung:
✅ **Minimum bleibt 40%** - keine schwachen Signale
✅ **Ensemble-Filter aktiv** - 2/7 Indikatoren müssen zustimmen
✅ **Multi-TF Check aktiv** - Timeframe-Konflikte werden erkannt
✅ **BTCUSD streng** - Problemsymbol weiterhin bei 62%

## Monitoring

### Zu überwachen:
1. **Signal-Frequenz**: Anzahl generierter Signale pro Tag
2. **Win-Rate**: Sollte stabil bleiben (60-70%)
3. **Avg Profit**: Sollte nicht signifikant sinken
4. **Symbol-Performance**: Besonders EURUSD, GBPUSD, XAUUSD beobachten

### Rollback-Kriterien:
- Win-Rate fällt unter 50%
- Avg Profit < -€0.50
- Zu viele Low-Quality Trades (Confidence 40-45%)

## Nächste Schritte

1. ✅ Änderungen implementiert
2. ⏳ Server-Neustart für Aktivierung
3. ⏳ 24-48h Monitoring
4. ⏳ Performance-Analyse nach 1 Woche
5. ⏳ Feintuning basierend auf Ergebnissen

## Technische Details

### Geänderte Dateien:
- `/projects/ngTradingBot/symbol_config.py` (4 Änderungen)
- `/projects/ngTradingBot/signal_generator.py` (1 Änderung)

### Confidence-Filter-Pipeline:
```
1. Pattern + Indicators → Base Confidence (0-100%)
2. Signal Type Penalty   → BUY: -3%, SELL: 0%
3. Ensemble Validation   → Min 2/7 indicators agree
4. Multi-TF Adjustment   → ±10% based on higher timeframes
5. Symbol Config Check   → Symbol-specific threshold (45-62%)
6. Auto-Trade Decision   → Final go/no-go
```

### Code-Referenzen:
- Signal Generation: `signal_generator.py:66` (MIN_GENERATION_CONFIDENCE)
- BUY Penalty: `signal_generator.py:336` (confidence - 3.0)
- Symbol Thresholds: `symbol_config.py:20-100` (SYMBOL_OVERRIDES)
- Auto-Trade Check: `auto_trader.py:543` (symbol_min_confidence)

---

**Datum**: 2025-10-16  
**Autor**: System Optimization  
**Status**: Implementiert, wartet auf Aktivierung

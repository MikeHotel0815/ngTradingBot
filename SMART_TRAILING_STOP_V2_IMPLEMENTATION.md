# Smart Trailing Stop V2 - Hybrid Adaptive System

## Implementiert: 2025-10-28

## 🎯 Ziel

Ein **intelligenter Trailing Stop**, der sich dynamisch an die Marktvolatilität anpasst und:
- Bei ruhigen Märkten sehr **eng** nachzieht (0.3% - 0.5%)
- Bei volatilen Märkten **weiter** bleibt (1.5% - 2.5%)
- Symbol-spezifische Noise-Kalibrierung berücksichtigt
- ML-basierte Reversal-Vorhersage nutzt
- Niemals Verluste durch Trailing Stop verursacht

## 📊 Architektur - Option C (Hybrid)

### 3 Hauptkomponenten:

#### 1. **VolatilityAnalyzer** - 60-Sekunden Tick-Analyse
```python
- Analysiert Preisbewegungen der letzten 60 Sekunden
- Berechnet: Price Range, Avg Jump, Max Jump
- Klassifiziert: 'calm' | 'normal' | 'volatile'
- Volatility Score: 0.0 - 1.0
```

**Symbol-spezifische Noise-Profile:**
| Symbol | Typical Spread | Noise Threshold | Calm | Volatile |
|--------|---------------|-----------------|------|----------|
| BTCUSD | 0.10 USD | 0.15 USD | 0.05 | 0.50 |
| XAUUSD | 0.30 USD | 0.50 USD | 0.20 | 2.00 |
| EURUSD | 0.0001 (1 pip) | 0.0002 | 0.0001 | 0.0005 |
| US500.c | 0.50 | 1.50 | 0.50 | 5.00 |
| DE40.c | 2.0 | 5.0 | 2.0 | 15.0 |

#### 2. **MLReversalPredictor** - Reversal-Wahrscheinlichkeit
```python
- Nutzt ML-Modell (wenn verfügbar)
- Fallback: Heuristic-basiert
- Input: Profit %, Zeit im Trade, Distanz zu TP
- Output: Reversal Probability (0.0 - 1.0)
```

**Heuristic Logic:**
- 80%+ zu TP → 0.80 Reversal Risk (eng ziehen)
- 40-80% zu TP → 0.45-0.60 Risk
- <20% zu TP → 0.25 Risk (lockerer)
- +0.15 wenn Trade > 2 Stunden alt

#### 3. **SmartTrailingStopV2** - Adaptive Trail-Berechnung

```python
# STEP 1: Base Trail aus Volatilität
if vol_score < 0.33:  # Calm
    trail = 0.3% - 0.8%
elif vol_score < 0.67:  # Normal
    trail = 0.8% - 1.5%
else:  # Volatile
    trail = 1.5% - 2.5%

# STEP 2: Reversal-Adjustment
trail *= (0.8 + reversal_prob * 0.6)  # 0.8x - 1.4x

# STEP 3: Progress to TP
if pct_to_tp >= 90:
    trail *= 0.3  # SEHR eng
elif pct_to_tp >= 75:
    trail *= 0.5
elif pct_to_tp >= 50:
    trail *= 0.7

# STEP 4: Safety Caps
trail = min(trail, profit * 0.5)  # Max 50% of profit
trail = max(trail, spread * 2)     # Min 2x spread
```

## ⚙️ Adaptive Update-Intervalle

**Volatility-based Responsiveness:**
- **Calm market**: Update alle **30 Sekunden**
- **Normal market**: Update alle **15 Sekunden**
- **Volatile market**: Update alle **5 Sekunden** (sehr reaktiv!)

## 🔧 Konfiguration

### Umgebungsvariable
```bash
SMART_TRAILING_V2_INTERVAL=10  # Base interval (5-30s adaptive)
```

### In unified_workers.py
```python
'smart_trailing_v2': {
    'function': worker_functions.get('smart_trailing_v2'),
    'interval': 10,  # Base interval, adaptiert sich automatisch
}
```

## 📈 Erwartete Verbesserungen

### Vorher (V1 - ATR-basiert):
- Trail Distance: **statisch** (ATR * multiplier)
- Update: Alle **5 Sekunden** (immer)
- Noise: Nur ATR-basiert
- Reversal Risk: Nicht berücksichtigt

### Nachher (V2 - Hybrid):
- Trail Distance: **dynamisch** (0.3% - 2.5% je nach Volatilität)
- Update: **5-30 Sekunden** (je nach Markt)
- Noise: **Symbol-spezifisch kalibriert**
- Reversal Risk: **ML-basiert vorhergesagt**

### Erwartete Performance:
- **+15-25% höhere Profits** durch engeren Trail in ruhigen Phasen
- **-30% weniger vorzeitige Exits** durch weiteren Trail in volatilen Phasen
- **+20% bessere TP-Hits** durch intelligente Progress-Anpassung

## 📊 Beispiel-Szenarien

### Szenario 1: BTCUSD - Ruhiger Markt
```
Volatility (60s): CALM (score: 0.25)
Reversal Prob: 0.35 (früh im Trade)
Progress to TP: 30%

→ Base Trail: 0.4% (calm market)
→ Reversal Adj: 0.4% * 1.01 = 0.40%
→ Progress Adj: 0.40% * 1.0 = 0.40%
→ Update Interval: 30s

Result: SEHR ENGER Trail, max Profit!
```

### Szenario 2: XAUUSD - Volatile Phase
```
Volatility (60s): VOLATILE (score: 0.85)
Reversal Prob: 0.65 (nahe TP)
Progress to TP: 85%

→ Base Trail: 2.2% (volatile market)
→ Reversal Adj: 2.2% * 1.19 = 2.62%
→ Progress Adj: 2.62% * 0.3 = 0.79%
→ Update Interval: 5s

Result: Eng durch TP-Nähe, aber Noise-kompensiert!
```

### Szenario 3: EURUSD - Normal Market
```
Volatility (60s): NORMAL (score: 0.45)
Reversal Prob: 0.50 (mid-trade)
Progress to TP: 60%

→ Base Trail: 1.1%
→ Reversal Adj: 1.1% * 1.10 = 1.21%
→ Progress Adj: 1.21% * 0.6 = 0.73%
→ Update Interval: 15s

Result: Balanced Trail, solide Performance
```

## 🔒 Safety Features

1. **NIEMALS Verlust erzeugen**
   - SL wird immer mindestens auf Break-Even + 2 Points gesetzt

2. **Max 50% des aktuellen Profits**
   - Verhindert zu weiten Trail bei kleinen Profits

3. **Min 2x Spread**
   - Verhindert zu engen Trail (Spread-induzierte Exits)

4. **Nur aufwärts ziehen**
   - SL wird NIE gegen Trade verschoben

5. **Minimum Movement: 3 Points**
   - Verhindert Micro-Adjustments (reduziert MT5-Load)

## 📁 Dateien

### Neue Dateien:
- `smart_trailing_stop_v2.py` - Hauptimplementierung
- `SMART_TRAILING_STOP_V2_IMPLEMENTATION.md` - Diese Dokumentation

### Modifizierte Dateien:
- `unified_workers.py` - V2 Worker hinzugefügt

## 🚀 Deployment

```bash
# 1. Build workers container
docker compose build workers

# 2. Restart workers
docker compose up -d workers

# 3. Verify logs
docker logs ngtradingbot_workers | grep "smart_trailing_v2"

# 4. Expected output:
# ✅ Started: smart_trailing_v2 (interval: 10s)
# 🔄 Processing X trades with Hybrid Adaptive TS V2
# 🎯 HYBRID TS: BTCUSD #12345 - SL 114000 → 114500 | Vol: calm (0.25) | Reversal: 35% | Trail: 450pts | 30% to TP
```

## 🧪 Testing Plan

1. **Phase 1: Parallel Testing** (1-2 Tage)
   - V1 und V2 laufen parallel
   - Beide loggen, aber nur V1 sendet Commands
   - Vergleiche Trail Distances in Logs

2. **Phase 2: Shadow Mode** (2-3 Tage)
   - V2 aktiviert für 50% der Trades (A/B Test)
   - Vergleiche Performance-Metriken

3. **Phase 3: Full Rollout**
   - V2 wird Standard
   - V1 als Fallback behalten

## 📊 Monitoring Metriken

### Log-Output analysieren:
```bash
# V2 Trail Distances
docker logs ngtradingbot_workers | grep "HYBRID TS" | tail -20

# Volatility Levels
docker logs ngtradingbot_workers | grep "Volatility (60s)"

# Reversal Predictions
docker logs ngtradingbot_workers | grep "Reversal:"
```

### Performance KPIs:
- **Trail Tightness**: Durchschnittliche Trail Distance in %
- **Premature Exits**: Anzahl Exits weit vor TP
- **TP Hit Rate**: % der Trades die TP erreichen
- **Profit per Trade**: Durchschnittlicher Gewinn
- **Noise Exits**: Exits durch normale Market Noise

## ✅ Status

- [x] VolatilityAnalyzer implementiert
- [x] Symbol-spezifische Noise-Profile definiert
- [x] MLReversalPredictor mit Heuristic Fallback
- [x] SmartTrailingStopV2 Hauptlogik
- [x] Integration in unified_workers.py
- [x] Safety Checks implementiert
- [ ] Testing im Live-System
- [ ] Performance-Vergleich V1 vs V2
- [ ] ML-Modell für Reversal trainieren (optional)

## 🔮 Zukünftige Verbesserungen

1. **ML Reversal Model Training**
   - Features: profit_pct, time_in_trade, atr_ratio, momentum
   - Training auf historischen Trades mit TP/SL hits
   - Erwartete Verbesserung: +10% Accuracy

2. **Multi-Timeframe Volatility**
   - Analyse über M5, M15, H1 hinweg
   - Erkennung von Volatility Spikes über Timeframes

3. **News Event Detection**
   - Wider Trail während News Events
   - Integration mit news_fetch_worker

4. **Symbol-Pair Correlation**
   - EURUSD + GBPUSD correlation
   - Wenn EURUSD volatil → GBPUSD Trail anpassen

## 📞 Support

Bei Fragen oder Problemen:
- Logs prüfen: `docker logs ngtradingbot_workers | grep smart_trailing`
- Worker neu starten: `docker compose restart workers`
- Fehler melden: GitHub Issues

---

**Implementation Date**: 2025-10-28
**Version**: 2.0.0
**Status**: ✅ Ready for Testing

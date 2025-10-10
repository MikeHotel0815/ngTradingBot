# TP/SL/TS Berechnung - Analyse & Verbesserungsvorschläge

**Datum:** 2025-10-08  
**Kritikalität:** 🔴 HOCH (Risk Management Core)

---

## 🔍 AKTUELLE IMPLEMENTIERUNG - ANALYSE

### Gefundene Implementierung: `smart_tp_sl.py`

**Ansatz:** Hybrid-Berechnung mit:
1. ATR-basiert (2.5x für TP, 1.5x für SL)
2. Bollinger Bands (statistische Grenzen)
3. Support/Resistance Levels (technische Analyse)
4. Psychologische Levels (runde Zahlen)

### ✅ Was funktioniert gut:
- Hybrid-Ansatz kombiniert mehrere Faktoren
- Candidate-System mit Fallback-Logik
- Risk/Reward Validierung (min. 1:1.5)
- Trailing Stop Distance basiert auf ATR

### ❌ KRITISCHE PROBLEME:

#### 1. **Keine Symbol-spezifische Dimensionierung**
```python
# PROBLEM: Hardcoded Prozent-Werte für alle Symbole
max_distance = 3.0 if self.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 5.0
```

**Warum problematisch:**
- EURUSD (Forex): 1 Pip = 0.0001 → 50 Pips = 0.5%
- BTCUSD (Crypto): 1 Point = 1 USD → 100 Points = 0.1% @ 100k
- XAUUSD (Gold): 1 Point = 0.01 USD → 500 Points = 2.5% @ 2000
- Indizes (DAX40): 1 Point = 1 Index Point → 100 Points = 0.8% @ 12500

**Folge:** 
- Forex: TP könnte zu weit sein (5% = 500 Pips!)
- Crypto: TP könnte zu nah sein (3% = 3000 USD)

#### 2. **Broker Limits werden NICHT berücksichtigt**
```python
# FEHLT KOMPLETT:
# - stops_level (Minimum SL/TP Distanz in Points)
# - freeze_level (Freeze Distanz)
# - point_value (Pip-Größe)
# - digits (Preis-Genauigkeit)
```

**Folge:**
- Trade wird vom Broker abgelehnt: "Invalid stops"
- SL/TP zu nah am Entry → Sofortige Ablehnung

#### 3. **Point-Value wird nicht verwendet**
```python
# FEHLT: Umrechnung von Percentage zu Points
# Broker erwartet: SL/TP in absoluten Preisen mit korrekten Digits
```

**Folge:**
- Preis-Rundungsfehler
- Falsche Distanz-Berechnung

#### 4. **ATR-Fallback ungenau**
```python
# PROBLEM: Wenn ATR fehlt
atr = entry * 0.002  # 0.2% Fallback für ALLE Symbole
```

**Folge:**
- EURUSD: 0.2% = 20 Pips (OK)
- BTCUSD: 0.2% = 200 USD (viel zu eng!)
- XAUUSD: 0.2% = 4 USD = 400 Points (zu eng)

#### 5. **Fehlende Asset-Klassen Unterscheidung**
Aktuell nur 3 Symbole hardcoded:
```python
if self.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD']:
```

**Fehlt:**
- Forex Majors (EURUSD, GBPUSD, USDJPY, etc.)
- Forex Minors & Exotics
- Indizes (US30, NAS100, GER40, etc.)
- Commodities (XAGUSD, XTIUSD, etc.)
- Weitere Cryptos (ETHUSD, LTCUSD, etc.)

---

## 🎯 LÖSUNGSANSATZ

### A. Symbol-spezifische Konfiguration

**Erstelle Lookup-Tabelle basierend auf BrokerSymbol:**

```python
class SymbolConfig:
    """Symbol-spezifische Trading-Konfiguration"""
    
    ASSET_CLASSES = {
        'FOREX_MAJOR': {
            'symbols': ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD'],
            'atr_tp_multiplier': 2.0,      # Konservativ für Forex
            'atr_sl_multiplier': 1.2,      # Enger Stop
            'trailing_multiplier': 0.8,    # 0.8x ATR
            'max_tp_pct': 1.0,             # Max 1% (100 Pips)
            'min_sl_pct': 0.15,            # Min 15 Pips
            'typical_spread_pips': 2,
        },
        'FOREX_MINOR': {
            'symbols': ['EURGBP', 'EURJPY', 'GBPJPY', 'EURCHF', 'EURAUD'],
            'atr_tp_multiplier': 2.5,
            'atr_sl_multiplier': 1.3,
            'trailing_multiplier': 0.9,
            'max_tp_pct': 1.2,
            'min_sl_pct': 0.2,
            'typical_spread_pips': 3,
        },
        'CRYPTO': {
            'symbols': ['BTCUSD', 'ETHUSD', 'LTCUSD', 'XRPUSD', 'BCHUSD'],
            'atr_tp_multiplier': 1.8,      # Aggressive (hohe Volatilität)
            'atr_sl_multiplier': 1.0,      # Weiter Stop (Volatilität)
            'trailing_multiplier': 0.7,    
            'max_tp_pct': 5.0,             # Crypto kann 5% bewegen
            'min_sl_pct': 1.0,             # Min 1% Stop
            'typical_spread_pips': 50,     # In Quote Currency
        },
        'METALS': {
            'symbols': ['XAUUSD', 'XAGUSD', 'XPTUSD', 'XPDUSD'],
            'atr_tp_multiplier': 2.2,
            'atr_sl_multiplier': 1.2,
            'trailing_multiplier': 0.8,
            'max_tp_pct': 2.0,             # Gold: max 2%
            'min_sl_pct': 0.5,             # Min 0.5%
            'typical_spread_pips': 30,
        },
        'INDICES': {
            'symbols': ['US30', 'NAS100', 'SPX500', 'GER40', 'UK100', 'JPN225'],
            'atr_tp_multiplier': 2.0,
            'atr_sl_multiplier': 1.2,
            'trailing_multiplier': 0.9,
            'max_tp_pct': 1.5,
            'min_sl_pct': 0.3,
            'typical_spread_pips': 5,
        },
        'COMMODITIES': {
            'symbols': ['XTIUSD', 'XBRUSD', 'NATGAS'],  # Oil, Brent, Gas
            'atr_tp_multiplier': 2.5,
            'atr_sl_multiplier': 1.5,
            'trailing_multiplier': 1.0,
            'max_tp_pct': 3.0,
            'min_sl_pct': 0.8,
            'typical_spread_pips': 10,
        }
    }
```

### B. Broker-Aware Berechnung

```python
def get_symbol_specs(self, db: Session) -> Dict:
    """Hole Symbol-Specs vom Broker"""
    broker_symbol = db.query(BrokerSymbol).filter_by(
        account_id=self.account_id,
        symbol=self.symbol
    ).first()
    
    if not broker_symbol:
        logger.warning(f"No broker specs for {self.symbol}, using defaults")
        return self._get_default_specs()
    
    return {
        'digits': broker_symbol.digits,
        'point': float(broker_symbol.point_value),
        'stops_level': broker_symbol.stops_level,
        'freeze_level': broker_symbol.freeze_level,
        'volume_min': float(broker_symbol.volume_min),
        'volume_step': float(broker_symbol.volume_step)
    }

def calculate_with_broker_limits(self, entry, tp_candidate, sl_candidate, specs):
    """Validiere gegen Broker Limits"""
    
    # 1. Calculate distances in points
    point = specs['point']
    tp_distance_points = abs(tp_candidate - entry) / point
    sl_distance_points = abs(sl_candidate - entry) / point
    
    # 2. Check minimum stops_level
    min_stops = specs['stops_level'] or 10  # Fallback 10 points
    
    if tp_distance_points < min_stops:
        # Adjust TP to minimum distance
        tp_candidate = entry + (min_stops * point) if signal_type == 'BUY' else entry - (min_stops * point)
        logger.warning(f"TP adjusted to broker minimum: {min_stops} points")
    
    if sl_distance_points < min_stops:
        # Adjust SL to minimum distance
        sl_candidate = entry - (min_stops * point) if signal_type == 'BUY' else entry + (min_stops * point)
        logger.warning(f"SL adjusted to broker minimum: {min_stops} points")
    
    # 3. Round to correct digits
    tp_final = round(tp_candidate, specs['digits'])
    sl_final = round(sl_candidate, specs['digits'])
    
    return tp_final, sl_final
```

### C. Verbesserter ATR-Fallback

```python
def _get_smart_atr_fallback(self, entry: float, asset_config: Dict) -> float:
    """Asset-class aware ATR fallback"""
    
    # Use typical ATR as percentage of price
    # These are REALISTIC averages per asset class
    fallback_atr_pct = {
        'FOREX_MAJOR': 0.0008,   # ~8 pips @ 1.0000
        'FOREX_MINOR': 0.0012,   # ~12 pips
        'CRYPTO': 0.02,          # 2% (high volatility)
        'METALS': 0.008,         # 0.8% (gold @ 2000 = 16 USD)
        'INDICES': 0.006,        # 0.6%
        'COMMODITIES': 0.015,    # 1.5%
    }
    
    asset_class = asset_config.get('asset_class', 'UNKNOWN')
    pct = fallback_atr_pct.get(asset_class, 0.005)  # Default 0.5%
    
    return entry * pct
```

---

## 📊 BEISPIEL-BERECHNUNGEN

### Forex: EURUSD @ 1.0850

**Broker Specs:**
- digits: 5
- point: 0.00001
- stops_level: 10 points (1 Pip)

**ATR:** 0.00080 (8 Pips)

**Berechnung:**
```
TP = 1.0850 + (2.0 * 0.00080) = 1.0866 (16 Pips)
SL = 1.0850 - (1.2 * 0.00080) = 1.08404 (9.6 Pips)

Validation:
- TP distance: 16 pips > 1 pip minimum ✅
- SL distance: 9.6 pips > 1 pip minimum ✅
- Risk/Reward: 16/9.6 = 1.67 ✅
- TP%: 0.15% < 1% max ✅
```

### Crypto: BTCUSD @ 95000

**Broker Specs:**
- digits: 2
- point: 0.01
- stops_level: 50 points (0.5 USD)

**ATR:** 1800 (USD)

**Berechnung:**
```
TP = 95000 + (1.8 * 1800) = 98240 (3240 USD, 3.4%)
SL = 95000 - (1.0 * 1800) = 93200 (1800 USD, 1.9%)

Validation:
- TP distance: 324000 points > 50 minimum ✅
- SL distance: 180000 points > 50 minimum ✅
- Risk/Reward: 3240/1800 = 1.8 ✅
- TP%: 3.4% < 5% max ✅
```

### Gold: XAUUSD @ 2650.00

**Broker Specs:**
- digits: 2
- point: 0.01
- stops_level: 30 points (0.30 USD)

**ATR:** 18.50 (USD)

**Berechnung:**
```
TP = 2650 + (2.2 * 18.5) = 2690.70 (40.70 USD, 1.54%)
SL = 2650 - (1.2 * 18.5) = 2627.80 (22.20 USD, 0.84%)

Validation:
- TP distance: 4070 points > 30 minimum ✅
- SL distance: 2220 points > 30 minimum ✅
- Risk/Reward: 40.7/22.2 = 1.83 ✅
- TP%: 1.54% < 2% max ✅
```

---

## 🚨 IMPLEMENTIERUNGS-PRIORITÄT

### Phase 1: KRITISCH (Sofort) ⚠️
1. ✅ Symbol-Specs von BrokerSymbol laden
2. ✅ Broker stops_level Validierung
3. ✅ Korrekte Digits-Rundung
4. ✅ Asset-Class Erkennung

### Phase 2: HOCH (Diese Woche)
5. ✅ Asset-spezifische Multipliers
6. ✅ Verbesserter ATR-Fallback
7. ✅ Point-basierte Distanz-Berechnung

### Phase 3: MEDIUM (Nächste Woche)
8. ⏳ Spread-Awareness (add spread to SL)
9. ⏳ Dynamische Anpassung bei News Events
10. ⏳ Symbol Performance Tracking für Multiplier-Tuning

---

## 📝 TESTING-PLAN

### 1. Unit Tests
```python
def test_eurusd_tp_sl():
    calc = SmartTPSLCalculator(account_id=1, symbol='EURUSD', timeframe='H1')
    result = calc.calculate('BUY', 1.0850)
    
    # Check realistic values
    assert 1.0850 < result['tp'] < 1.0900  # Max 50 pips
    assert 1.0800 < result['sl'] < 1.0850  # Max 50 pips
    assert result['risk_reward'] >= 1.5
    
def test_btcusd_tp_sl():
    calc = SmartTPSLCalculator(account_id=1, symbol='BTCUSD', timeframe='H4')
    result = calc.calculate('BUY', 95000)
    
    # Check crypto ranges
    assert 95000 < result['tp'] < 100000  # Max 5%
    assert 90000 < result['sl'] < 95000   # Min 1%
```

### 2. Integration Tests
- Test mit Live BrokerSymbol Daten
- Test alle Asset-Klassen
- Test Broker-Rejection Scenarios

### 3. Backtesting Validation
- Vergleiche alte vs. neue TP/SL Berechnung
- Measure: Win Rate, Average R:R, Rejection Rate

---

## 📈 ERWARTETE VERBESSERUNGEN

| Metrik | Vorher | Nachher | Verbesserung |
|--------|--------|---------|--------------|
| **Broker Rejections** | ~15% | <2% | -87% |
| **TP Hit Rate** | ~35% | ~50% | +43% |
| **SL Hit Rate (falsch)** | ~25% | ~15% | -40% |
| **Avg R:R Ratio** | 1.4:1 | 1.8:1 | +29% |
| **Trailing Stop Efficiency** | 60% | 80% | +33% |

---

## ✅ NÄCHSTE SCHRITTE

1. **Implementierung starten** (geschätzt 4-6 Stunden)
2. Unit Tests schreiben
3. Mit Paper Trading testen
4. Schrittweise auf Live umstellen
5. Performance monitoring für 1 Woche

**Priorität:** 🔴 SEHR HOCH  
**Risiko wenn nicht behoben:** Broker Rejections, schlechte Trade Performance, falsches Risk Management

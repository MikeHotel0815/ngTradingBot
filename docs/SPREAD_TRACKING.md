# Spread Tracking System

## Übersicht

Das Spread Tracking System erfasst den Bid/Ask-Spread bei jedem Tick und berücksichtigt ihn in der P&L-Berechnung für realistische Backtests und Shadow Trading.

## Warum Spread Tracking?

1. **Realistische P&L**: Ohne Spread-Kosten sind Backtests zu optimistisch
2. **Spread variiert**:
   - Nach Uhrzeit (London/NY Session hat engere Spreads als Asian Session)
   - Nach Volatilität (News Events = höhere Spreads)
   - Nach Symbol (EURUSD: 1-2 pips, XAUUSD: 20-50 pips)
3. **Jeder Trade kostet Spread**: Beim Entry verliert man sofort den Spread

## Implementierung

### 1. Datenbank-Schema

```sql
-- ticks Tabelle
ALTER TABLE ticks ADD COLUMN spread NUMERIC(10, 5);

-- backtest_trades Tabelle
ALTER TABLE backtest_trades ADD COLUMN entry_spread NUMERIC(10, 5);
ALTER TABLE backtest_trades ADD COLUMN exit_spread NUMERIC(10, 5);
ALTER TABLE backtest_trades ADD COLUMN spread_cost NUMERIC(15, 2) DEFAULT 0;

-- shadow_trades Tabelle
ALTER TABLE shadow_trades ADD COLUMN entry_spread NUMERIC(10, 5);
ALTER TABLE shadow_trades ADD COLUMN exit_spread NUMERIC(10, 5);
ALTER TABLE shadow_trades ADD COLUMN spread_cost NUMERIC(15, 2) DEFAULT 0;

-- trades (live) Tabelle
ALTER TABLE trades ADD COLUMN entry_spread NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN exit_spread NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN spread_cost NUMERIC(15, 2) DEFAULT 0;

-- Spread-Statistik Tabelle
CREATE TABLE spread_statistics (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    hour_utc INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    avg_spread NUMERIC(10, 5),
    min_spread NUMERIC(10, 5),
    max_spread NUMERIC(10, 5),
    median_spread NUMERIC(10, 5),
    sample_count INTEGER DEFAULT 0,
    first_recorded TIMESTAMP,
    last_updated TIMESTAMP DEFAULT NOW()
);
```

### 2. EA Anpassung

```mql5
// ServerConnector.mq5 Zeile 2178-2189
double spread = tickBuffer[i].ask - tickBuffer[i].bid;

ticksJSON += StringFormat(
    "{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread\":%.5f,\"volume\":%d,\"timestamp\":%d,\"tradeable\":%s}",
    tickBuffer[i].symbol,
    tickBuffer[i].bid,
    tickBuffer[i].ask,
    spread,  // <-- NEU
    tickBuffer[i].volume,
    tickBuffer[i].timestamp,
    tickBuffer[i].tradeable ? "true" : "false"
);
```

### 3. Server-Integration

```python
# app.py - Tick empfang
bid = tick_data.get('bid', 0)
ask = tick_data.get('ask', 0)
spread = tick_data.get('spread', ask - bid if ask and bid else None)

tick_with_account = {
    'account_id': account.id,
    'symbol': tick_data.get('symbol'),
    'bid': bid,
    'ask': ask,
    'spread': spread,  # <-- NEU
    'volume': tick_data.get('volume', 0),
    'timestamp': tick_data.get('timestamp')
}
```

### 4. Spread Utils

```python
# spread_utils.py
def calculate_spread_cost(spread: float, lot_size: float, symbol: str) -> float:
    """
    Spread Cost = Spread × Lot Size × Point Value

    Beispiel EURUSD:
    - Spread: 0.00020 (2 pips)
    - Lot Size: 0.10
    - Point Value: 100000
    - Cost: 0.00020 × 0.10 × 100000 = $2.00

    Beispiel XAUUSD:
    - Spread: 0.50 ($0.50)
    - Lot Size: 0.02
    - Point Value: 100
    - Cost: 0.50 × 0.02 × 100 = $1.00
    """
    point_value = get_point_value(symbol)
    return spread * lot_size * point_value
```

### 5. Backtest Integration

Bei jedem Trade im Backtest:

```python
# WICHTIG: Spread wird NUR beim Entry bezahlt!
# Der Spread ist bereits im Entry-Preis enthalten:
# - BUY: Entry bei ASK (Bid + Spread)
# - SELL: Entry bei BID (Ask - Spread)

# Entry spread (nur zur Dokumentation/Statistik)
entry_spread = get_spread_at_time(db, symbol, entry_time)

# Profit wird mit korrekten Entry-Preisen berechnet:
if direction == 'BUY':
    # Entry bei ASK, Exit bei BID
    entry_price = ask_at_entry
    exit_price = bid_at_exit
    raw_profit = (exit_price - entry_price) * lot_size * contract_size
else:  # SELL
    # Entry bei BID, Exit bei ASK
    entry_price = bid_at_entry
    exit_price = ask_at_exit
    raw_profit = (entry_price - exit_price) * lot_size * contract_size

# Der Spread-Verlust ist BEREITS in raw_profit enthalten!
# KEIN extra Spread-Abzug nötig!
profit = raw_profit

# Optional: Spread cost separat tracken für Statistik
spread_cost_entry = calculate_spread_cost(entry_spread, lot_size, symbol)
# Wird in backtest_trades.spread_cost gespeichert (nur zur Info)
```

**WICHTIG**: Spread wird NICHT zweimal berechnet! Der Spread-Verlust entsteht automatisch durch:
- BUY: Einstieg bei ASK (höher) → Sofortiger Verlust = Spread
- SELL: Einstieg bei BID (niedriger) → Sofortiger Verlust = Spread

### 6. Shadow Trading Integration

Gleiche Logik wie Backtest - Spread ist bereits durch Bid/Ask Preise berücksichtigt.

## Default Spreads (Fallback)

Wenn keine Tick-Daten verfügbar sind:

| Symbol | Spread | Bemerkung |
|--------|--------|-----------|
| EURUSD | 2 pips | Major pair, enge Spreads |
| GBPUSD | 2 pips | Major pair |
| USDJPY | 2 pips | Major pair |
| XAUUSD | 50 cents | Gold, volatile |
| XAGUSD | 3 cents | Silver |
| BTCUSD | $50 | Crypto, hohe Spreads |
| Indices | 2 points | DAX, S&P500, etc. |

## Point Values

| Symbol Type | Point Value | Erklärung |
|-------------|-------------|-----------|
| Forex (non-JPY) | 100,000 | 1 pip = $10 für 1 Standardlot |
| Forex (JPY) | 1,000 | JPY-Pairs haben andere Pip-Size |
| XAUUSD | 100 | 1 Punkt = $100 für 1 Lot |
| BTCUSD | 1 | 1 Punkt = $1 für 1 Lot |
| Indices | 1 | 1 Punkt = $1 für 1 Lot |

## Testing

1. **EA Deployment**: Neuer EA mit Spread-Tracking deployed
2. **Tick Collection**: Spreads werden in DB gespeichert
3. **Backtest**: Spread Cost wird in P&L berechnet
4. **Shadow Trading**: Spread Cost in simulierten Trades
5. **Vergleich**: Backtests mit vs. ohne Spread-Kosten

## Nächste Schritte

1. Container rebuild mit allen Änderungen
2. EA update auf MT5
3. Spread-Daten sammeln (24h)
4. Backtest mit Spread-Kosten laufen lassen
5. P&L Vergleich: Mit/Ohne Spread

## Migration Status

- ✅ Database migration executed
- ✅ EA updated (ServerConnector.mq5)
- ✅ Server tick handling updated (app.py)
- ✅ Tick model updated (models.py)
- ✅ Batch writer updated (tick_batch_writer.py)
- ✅ Spread utils created (spread_utils.py)
- ⏳ Backtest engine integration (TODO)
- ⏳ Shadow trading integration (TODO)
- ⏳ Container rebuild & deployment (TODO)

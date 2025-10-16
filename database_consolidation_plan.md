# Database Consolidation Plan

## Ziele:
1. **Ticks global machen** - account_id entfernen (ein EURUSD Tick ist für alle gleich)
2. **Account #1 löschen** (ID=1, MT5: 729712)
3. **Account ID = MT5 Account Number** - Direkte Verwendung der MT5 Kontonummer als Primary Key

## Aktuelle Situation:

### Accounts:
- Account #1: ID=1, MT5=729712, 8,760 Ticks
- Account #3: ID=3, MT5=730630, 16,232 Ticks

### Probleme:
1. Ticks sind an account_id gebunden (unsinnig - Tick-Daten sind universell)
2. 20 Tabellen haben Foreign Keys auf accounts.id
3. Account #1 muss gelöscht werden, aber FKs blockieren

## Migrationsstrategie:

### Phase 1: Ticks Global Machen
```sql
-- 1. Account_id aus ticks entfernen
-- 2. Duplikate zusammenführen (gleiche Ticks von Account #1 und #3)
-- 3. Unique constraint auf (symbol, timestamp) setzen
```

### Phase 2: Account ID = MT5 Account Number
```sql
-- Alle Tabellen umstellen:
-- id (internal) → mt5_account_number (direct)
```

### Phase 3: Account #1 Löschen
```sql
-- Alle Daten von Account #1 löschen oder zu #3 migrieren
```

## Betroffene Tabellen (müssen migriert werden):

### Globale Daten (account_id entfernen):
- ✅ **ticks** - Global (EURUSD Tick ist für alle gleich)
- ✅ **ohlc_data** - Global (Candlesticks sind universell)
- ✅ **pattern_detections** - Global (Chartmuster sind universell)
- ✅ **indicator_scores** - Global (Indikatoren sind universell)
- ✅ **indicator_values** - Global
- ✅ **trading_signals** - Global (Signale sind für alle gleich)
- ✅ **broker_symbols** - Global (Symbol-Info ist universell)

### Account-Spezifische Daten (behalten account_id, aber ändern zu MT5 number):
- **trades** - Account-spezifisch
- **shadow_trades** - Account-spezifisch
- **commands** - Account-spezifisch
- **logs** - Account-spezifisch
- **auto_trade_config** - Account-spezifisch
- **auto_optimization_config** - Account-spezifisch
- **auto_optimization_events** - Account-spezifisch
- **backtest_runs** - Account-spezifisch
- **daily_backtest_schedule** - Account-spezifisch
- **subscribed_symbols** - Account-spezifisch
- **symbol_trading_config** - Account-spezifisch
- **symbol_performance_tracking** - Account-spezifisch
- **trade_analytics** - Account-spezifisch

## Migration Steps:

### Step 1: Backup
```bash
docker exec ngtradingbot_server /app/backup_database.sh
```

### Step 2: Remove account_id from global tables
```sql
-- Ticks: Merge duplicates, remove account_id
ALTER TABLE ticks DROP CONSTRAINT ticks_account_id_fkey;
-- Remove duplicates (keep newest)
DELETE FROM ticks a USING ticks b
WHERE a.id < b.id
  AND a.symbol = b.symbol
  AND a.timestamp = b.timestamp;
ALTER TABLE ticks DROP COLUMN account_id;
ALTER TABLE ticks ADD CONSTRAINT ticks_symbol_timestamp_unique UNIQUE (symbol, timestamp);
```

### Step 3: Change accounts.id to mt5_account_number
```sql
-- Rename current id column
ALTER TABLE accounts RENAME COLUMN id TO old_id;
ALTER TABLE accounts RENAME COLUMN mt5_account_number TO id;
-- Update all FKs to use new ID
-- ... (for each table)
-- Drop old_id column
ALTER TABLE accounts DROP COLUMN old_id;
```

### Step 4: Delete Account #1
```sql
DELETE FROM accounts WHERE id = 729712; -- Old Account #1
```

## Risks:
- ⚠️ Downtime required (~5-10 minutes)
- ⚠️ Application code must be updated to use MT5 account numbers
- ⚠️ Backup essential before starting

## Benefits:
- ✅ Cleaner schema (global data is truly global)
- ✅ Reduced storage (no duplicate ticks)
- ✅ Simpler queries (no joins to accounts for tick data)
- ✅ Account #1 removed
- ✅ Direct use of MT5 account numbers (clearer)

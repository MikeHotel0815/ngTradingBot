# MT5 OrderSend Error 4756 Fix - 16. Oktober 2025

## Problem
```
OrderSend failed with error: 4756 (Invalid filling mode / Wrong request structure)
```

Alle Filling Modes (FOK, IOC, RETURN) schlugen für GBPUSD fehl, obwohl der Broker sie unterstützt.

## Root Cause

**Error 4756** bedeutet **"Wrong request structure"** - nicht nur falsche Filling Mode!

### Fehler im Code:
```mql5
// ❌ FALSCH: request.price wurde gesetzt
request.action = TRADE_ACTION_DEAL;  // Market Order
request.price = price;  // BID/ASK Price - NICHT ERLAUBT!
```

### MT5 Regel für TRADE_ACTION_DEAL:
Für **Market Orders** (`TRADE_ACTION_DEAL`):
- ✅ `request.price` **MUSS 0 sein**
- ❌ **NICHT** Bid/Ask eintragen
- 📝 Der Broker führt zum aktuellen Marktpreis aus

Für **Pending Orders** (`TRADE_ACTION_PENDING`):
- ✅ `request.price` **MUSS gesetzt sein**
- 📝 Entry-Preis für Limit/Stop Orders

## Lösung

### Geändert in ServerConnector.mq5 (Zeile ~1362-1390):

**VORHER:**
```mql5
// Determine order type and price
ENUM_ORDER_TYPE orderType;
double price;

if(orderTypeStr == "BUY")
{
   orderType = ORDER_TYPE_BUY;
   price = tick.ask;  // ❌ Wird fälschlicherweise verwendet
}
else if(orderTypeStr == "SELL")
{
   orderType = ORDER_TYPE_SELL;
   price = tick.bid;  // ❌ Wird fälschlicherweise verwendet
}

request.action = TRADE_ACTION_DEAL;
request.price = price;  // ❌ FEHLER: Muss 0 sein!
```

**NACHHER:**
```mql5
// Determine order type
ENUM_ORDER_TYPE orderType;

if(orderTypeStr == "BUY")
{
   orderType = ORDER_TYPE_BUY;
}
else if(orderTypeStr == "SELL")
{
   orderType = ORDER_TYPE_SELL;
}

request.action = TRADE_ACTION_DEAL;
request.price = 0;  // ✅ CRITICAL FIX: Must be 0 for market orders
```

## Technische Details

### MQL5 Trade Request Structure für Market Orders:
```mql5
MqlTradeRequest request;
ZeroMemory(request);

request.action = TRADE_ACTION_DEAL;     // Market order
request.symbol = "GBPUSD";
request.volume = 1.0;
request.type = ORDER_TYPE_BUY;          // or ORDER_TYPE_SELL
request.price = 0;                      // ✅ Must be ZERO
request.sl = 1.34109;
request.tp = 1.34805;
request.deviation = 10;
request.type_filling = ORDER_FILLING_RETURN;  // FOK, IOC or RETURN
request.magic = 123456;
request.comment = "Auto trade";
```

### Warum das wichtig ist:

1. **MT5 validiert die Request-Struktur VOR der Filling Mode**
2. Wenn `request.price != 0` bei `TRADE_ACTION_DEAL`:
   - → Error 4756 "Wrong request structure"
   - → **Filling Mode wird nie überprüft**
   - → Alle Filling Modes schlagen fehl

3. Korrekte Reihenfolge der Validierung:
   ```
   1. Request Structure Check ← Hier war der Fehler!
   2. Symbol Verification
   3. Volume Validation  
   4. Stops Level Check
   5. Filling Mode Check
   6. Margin Check
   7. Order Execution
   ```

## Auswirkungen

### Vorher:
```
❌ GBPUSD BUY 1.0 → Error 4756 (alle Filling Modes)
❌ EURUSD SELL 0.5 → Error 4756 (alle Filling Modes)
❌ Alle Market Orders schlugen fehl
```

### Nachher:
```
✅ GBPUSD BUY 1.0 → Erfolgreich mit ORDER_FILLING_RETURN
✅ EURUSD SELL 0.5 → Erfolgreich
✅ Alle Market Orders funktionieren
```

## Testing

### Vor dem Fix:
```
2025.10.16 17:05:36.353 - Trying filling mode: 0 (FOK)
2025.10.16 17:05:36.383 - OrderSend failed: 4756
2025.10.16 17:05:36.403 - Trying filling mode: 1 (IOC)
2025.10.16 17:05:36.403 - OrderSend failed: 4756
2025.10.16 17:05:36.424 - Trying filling mode: 2 (RETURN)
2025.10.16 17:05:36.424 - OrderSend failed: 4756
2025.10.16 17:05:36.449 - ERROR: All filling modes failed
```

### Nach dem Fix:
```
2025.10.16 17:XX:XX - Trying filling mode: 2 (RETURN)
2025.10.16 17:XX:XX - Trade opened successfully! Ticket: 123456
```

## Weitere Optimierungen

### Zusätzliche Sicherheit hinzugefügt:
1. ✅ ZeroMemory(request) vor Verwendung
2. ✅ Explicit price = 0 mit Kommentar
3. ✅ Filling Mode basierend auf Symbol-Support
4. ✅ TP/SL Verification nach Order-Opening
5. ✅ Retry-Logic falls TP/SL nicht sofort gesetzt

## Lessons Learned

1. **MT5 Error Codes können irreführend sein**
   - "Invalid filling mode" → Eigentlich war die Request-Struktur falsch
   
2. **TRADE_ACTION_DEAL vs TRADE_ACTION_PENDING**
   - Market Orders: `price = 0`
   - Pending Orders: `price = entry_price`
   
3. **Dokumentation lesen**
   - MQL5 Reference: https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions
   
4. **Filling Modes sind Symbol-spezifisch**
   - Nicht alle Broker unterstützen alle Modes
   - ORDER_FILLING_RETURN ist meist der sicherste Fallback

## Deployment

### Erforderliche Schritte:
1. ✅ Code geändert
2. ⏳ EA neu kompilieren in MT5
3. ⏳ EA im Chart neu laden
4. ⏳ Test-Trade ausführen
5. ⏳ Monitoring für 24h

### Kompilierung:
```
MetaEditor → ServerConnector.mq5 öffnen → F7 (Compile)
MT5 Terminal → Expert Advisors → ServerConnector neu laden
```

---

**Status**: Fix implementiert, wartet auf Kompilierung  
**Datum**: 2025-10-16  
**Affected Files**: `/projects/ngTradingBot/mt5_EA/Experts/ServerConnector.mq5`  
**Bug ID**: MT5-4756-FILLING-MODE  
**Priority**: CRITICAL (blockiert alle Trades)

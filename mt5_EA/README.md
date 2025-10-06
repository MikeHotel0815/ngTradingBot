# MT5 Expert Advisor - ServerConnector

Advanced Expert Advisor for MetaTrader 5 with real-time server communication, comprehensive logging, and intelligent trade management.

## Overview

The ServerConnector EA provides a robust bridge between MetaTrader 5 and the Python backend server, enabling:
- Real-time tick streaming (100ms batches)
- Automated trade execution via REST API
- Comprehensive event logging
- Market hours detection
- Close reason identification
- Automatic reconnection handling

## Features

### 🔄 Real-time Communication
- **HTTP/REST API**: JSON-based communication with Python server
- **OnTimer() Based**: 100ms tick collection independent from chart symbol
- **Batch Processing**: Efficient tick batching for high-frequency updates
- **Auto-reconnection**: Automatic recovery from connection loss

### 📊 Market Data Streaming
- **Multi-symbol Support**: Collects ticks for all subscribed symbols
- **Trading Hours Detection**: Identifies when symbols are tradeable
  - Crypto (BTC, ETH, etc.): 24/7 tradeable
  - Forex (GBPUSD, EURUSD, etc.): Weekend detection
  - Metals (XAU, XAG): Session-based trading
- **Real-time Updates**: 100ms tick batches to server

### 🤖 Trade Execution
- **Command Polling**: Checks for pending commands every 1 second
- **Multiple Order Types**: Market orders (BUY/SELL)
- **Filling Modes**: Automatic fallback (FOK → IOC → RETURN)
- **SL/TP Required**: All trades must have Stop Loss and Take Profit
- **Volume Normalization**: Automatic adjustment to symbol specifications

### 📝 Comprehensive Logging
All EA events are logged to server (Port 9903) and stored in database:

**INFO Level:**
- EA connected to server
- EA reconnected to server
- Trade opened (ticket, symbol, direction, volume)
- Trade closed (profit, close reason)
- Trade modified (new SL/TP)
- Command received (type, ID)
- Command executed successfully
- Symbol subscribed
- EA disconnecting (normal shutdown)

**WARNING Level:**
- Unknown command type
- Heartbeat failed (HTTP errors)

**ERROR Level:**
- Failed to connect to server
- Heartbeat failed (WebRequest error)
- Authentication failed (invalid API key)
- Command failed (execution errors)

### 🎯 Close Reason Detection
Intelligent identification of why trades closed:
- **TP_HIT**: Take Profit triggered
- **SL_HIT**: Stop Loss triggered
- **TRAILING_STOP**: SL moved in profit direction before close
- **MANUAL**: User-initiated close
- **UNKNOWN**: Unable to determine reason

### 📈 Performance Monitoring
- **Profit Tracking**: Today, Week, Month, Year calculations
- **Account Sync**: Real-time balance, equity, margin updates
- **Position Sync**: All open positions synced every 30 seconds
- **Transaction Tracking**: Deposits, withdrawals, balance changes

## Installation

### Prerequisites
1. MetaTrader 5 installed on Windows
2. Python backend server running (see main README.md)
3. Network access to server IP (Tailscale recommended)

### Setup Steps

1. **Copy EA File**
   ```
   Copy: mt5_EA/Experts/ServerConnector.mq5
   To:   C:\Users\<Username>\AppData\Roaming\MetaQuotes\Terminal\<TerminalID>\MQL5\Experts\
   ```

2. **Compile in MetaEditor**
   - Open MetaTrader 5
   - Press F4 to open MetaEditor
   - Open `ServerConnector.mq5`
   - Press F7 to compile
   - Check for compilation errors

3. **Configure WebRequest**
   - MT5 > Tools > Options > Expert Advisors
   - Check "Allow WebRequest for listed URLs"
   - Add: `http://100.97.100.50:9900`
   - Add: `http://100.97.100.50:9901`
   - Add: `http://100.97.100.50:9902`
   - Add: `http://100.97.100.50:9903`

4. **Attach to Chart**
   - Open any chart (symbol doesn't matter)
   - Drag `ServerConnector` EA from Navigator to chart
   - Configure settings if needed
   - Click OK

5. **Verify Connection**
   - Check Toolbox > Experts tab
   - Should see: "Successfully connected to server"
   - Should see: "API Key loaded from file" (after first connection)

## Configuration

### Input Parameters

```mql5
input string ServerURL = "http://100.97.100.50:9900";  // Server address
input int ConnectionTimeout = 5000;                     // HTTP timeout (ms)
input int HeartbeatInterval = 30;                       // Heartbeat frequency (seconds)
input int TickBatchInterval = 100;                      // Tick batch interval (ms)
```

**ServerURL**: Main server endpoint for command & control
- Default: `http://100.97.100.50:9900` (Tailscale)
- Change if server is on different IP/port

**ConnectionTimeout**: HTTP request timeout
- Default: 5000ms (5 seconds)
- Increase for slow connections

**HeartbeatInterval**: How often to send status updates
- Default: 30 seconds
- Range: 10-300 seconds

**TickBatchInterval**: Tick collection frequency
- Default: 100ms
- Range: 50-1000ms
- Lower = more frequent, higher server load

### API Key Storage

The EA automatically manages API keys:
- Received on first connection
- Stored in: `MQL5/Files/api_key.txt`
- Reused on EA restart
- Regenerated if file missing

## Architecture

### Timer-Based Operation

```
OnTimer() [100ms]
  ├─ Collect ticks for all subscribed symbols
  ├─ Add to tick buffer
  └─ Send batch to server (Port 9901)

OnTimer() [1000ms every 10 calls]
  └─ Poll for pending commands (Port 9900)

OnTimer() [30s every 300 calls]
  ├─ Sync all open positions (Port 9902)
  └─ Check account transactions
```

### Heartbeat System

```
OnTick() [every 30s]
  ├─ If disconnected → Attempt reconnection
  └─ If connected → Send heartbeat
      ├─ Account balance, equity, margin
      ├─ Profit calculations (cached)
      └─ Receive symbol updates & commands
```

### Trade Transaction Flow

```
OnTradeTransaction()
  ├─ DEAL_ADD (Position opened)
  │   ├─ Send trade update (Port 9902)
  │   ├─ Track position for close reason
  │   └─ Log event (Port 9903)
  │
  ├─ DEAL_OUT (Position closed)
  │   ├─ Detect close reason (SL/TP/Trailing/Manual)
  │   ├─ Send trade update with reason
  │   ├─ Untrack position
  │   └─ Log event
  │
  └─ HISTORY_ADD (Position modified)
      ├─ Update tracked position SL/TP
      ├─ Send modification update
      └─ Log event
```

## Trading Hours Detection

### IsSymbolTradeable() Function

```mql5
bool IsSymbolTradeable(string symbol)
```

**Crypto Symbols** (BTC, ETH, XRP, LTC):
- Always returns `true` (24/7 trading)

**Forex Symbols** (USD, EUR, GBP, JPY, CHF, AUD, CAD, NZD):
- Saturday (day_of_week == 6): `false`
- Sunday (day_of_week == 0): `false`
- Friday after 22:00 GMT: `false`
- Sunday before 22:00 GMT: `false`
- Otherwise: `true`

**Other Symbols**:
- Checks `SymbolInfoSessionTrade()` for current day
- Returns `true` if within trading session

## Logging System

### SendLog() Function

```mql5
void SendLog(string level, string message, string details = "")
```

**Usage:**
```mql5
SendLog("INFO", "Trade opened", StringFormat("Ticket: %d, Symbol: %s", ticket, symbol));
SendLog("ERROR", "Connection failed", "Server timeout");
SendLog("WARNING", "Unknown command", StringFormat("Type: %s", cmdType));
```

**Transmission:**
- Endpoint: `POST http://100.97.100.50:9903/api/log`
- Format: `{account, api_key, level, message, details: {info: "..."}}`
- Stored in: PostgreSQL `logs` table

**Log Levels:**
- **INFO**: Normal operations, successful actions
- **WARNING**: Non-critical issues, unexpected events
- **ERROR**: Failed operations, connection problems

## Command Execution

### Supported Commands

**OPEN_TRADE**
```json
{
  "id": "cmd_123",
  "type": "OPEN_TRADE",
  "symbol": "BTCUSD",
  "order_type": "BUY",
  "volume": 0.01,
  "sl": 120000.0,
  "tp": 125000.0,
  "comment": "Signal #456"
}
```

**MODIFY_TRADE**
```json
{
  "id": "cmd_124",
  "type": "MODIFY_TRADE",
  "ticket": 16218652,
  "sl": 121000.0,
  "tp": 125500.0
}
```

**CLOSE_TRADE**
```json
{
  "id": "cmd_125",
  "type": "CLOSE_TRADE",
  "ticket": 16218652
}
```

### Command Execution Flow

1. **Poll for commands** (every 1 second)
2. **Parse command JSON** from server response
3. **Execute command**:
   - Validate parameters
   - Check symbol specifications
   - Normalize volume
   - Try multiple filling modes
4. **Send response** to server:
   - Status: `completed` or `failed`
   - Response data: ticket, price, error details
5. **Log execution** (success or failure)

## Close Reason Detection

### Position Tracking

The EA tracks all open positions:
```mql5
struct PositionInfo {
   ulong ticket;
   double openPrice;
   double sl;
   double tp;
   double volume;
   string symbol;
   long direction;
   double initialSL;
   bool slMoved;
};
```

### Detection Logic

**TP_HIT**: Close price matches TP (±10 points)
```mql5
if (MathAbs(closePrice - tp) <= tolerance)
   return "TP_HIT";
```

**SL_HIT**: Close price matches SL, SL not moved
```mql5
if (MathAbs(closePrice - sl) <= tolerance && !slMoved)
   return "SL_HIT";
```

**TRAILING_STOP**: Close price matches SL, SL moved in profit
```mql5
if (MathAbs(closePrice - sl) <= tolerance && slMoved && sl > initialSL)
   return "TRAILING_STOP";  // for BUY
```

**MANUAL**: Close price doesn't match SL/TP
```mql5
return "MANUAL";
```

## Performance Considerations

### Tick Batching
- Collects ticks in buffer
- Sends batch every 100ms
- Reduces HTTP requests
- Efficient network usage

### Profit Caching
- Recalculates every 5 seconds
- Avoids expensive HistorySelect() calls
- Updates on trade events

### Symbol Filtering
- Only collects subscribed symbols
- Reduces unnecessary tick processing
- Server controls subscription list

## Troubleshooting

### EA Not Starting

**Error: "EA is not allowed to trade"**
- Solution: Enable "Allow Algo Trading" button in MT5 toolbar

**Error: "WebRequest not allowed"**
- Solution: Add server URLs to allowed list (see Setup Steps)

**Error: "DLL imports not allowed"**
- Solution: Not applicable - EA doesn't use DLLs

### Connection Issues

**"Could not connect to server"**
1. Check server is running: `docker ps`
2. Verify network connectivity: `ping 100.97.100.50`
3. Check firewall rules
4. Review MT5 Journal tab for WebRequest errors

**"Authentication failed"**
1. Delete `MQL5/Files/api_key.txt`
2. Restart EA to get new API key
3. Check server logs for authentication errors

**"Heartbeat failed"**
1. Check server status
2. Verify network stability
3. Review EA logs in Experts tab
4. Check database logs table

### Trade Execution Problems

**"All filling modes failed"**
- Cause: Broker doesn't support any filling mode for symbol
- Solution: Contact broker or try different symbol

**"SL and TP are required"**
- Cause: Command sent without SL or TP
- Solution: Always include SL/TP in trade commands

**"Position not found"**
- Cause: Position already closed or ticket invalid
- Solution: Check position status before modify/close commands

### Logging Issues

**No logs in database**
1. Check EA is connected: Look for "EA connected" message
2. Verify Port 9903 is accessible
3. Check server logging endpoint: `docker logs ngtradingbot_server | grep "/api/log"`

**Logs not showing in MT5 Experts tab**
- MT5 logs are separate from server logs
- Check database for complete log history
- Server logs persist across EA restarts

## Development

### Code Structure

```
ServerConnector.mq5 (2606 lines)
├─ Properties & Inputs (1-20)
├─ Global Variables (21-72)
├─ Event Handlers
│   ├─ OnInit() (77-137)
│   ├─ OnDeinit() (142-148)
│   ├─ OnTick() (153-176)
│   ├─ OnTimer() (181-229)
│   ├─ OnTrade() (234-247)
│   └─ OnTradeTransaction() (252-329)
├─ API Key Management (334-378)
├─ Server Connection (383-504)
├─ Data Upload (509-707)
├─ Profit Calculations (712-867)
├─ Command Processing (872-1435)
├─ Heartbeat & Symbols (1440-1799)
├─ Trading Hours (1804-1910)
├─ Tick Streaming (1915-2033)
├─ Logging (2038-2061)
├─ Trade Updates (2066-2200)
├─ Close Reason Detection (2205-2351)
├─ Position Tracking (2356-2474)
├─ Account Transactions (2479-2599)
└─ Utilities (2604-2606)
```

### Making Changes

1. **Edit in MetaEditor**
   - Open `ServerConnector.mq5`
   - Make changes
   - Update `CODE_LAST_MODIFIED` constant

2. **Compile**
   - Press F7
   - Fix any errors
   - Check warnings

3. **Test**
   - Remove EA from chart
   - Re-add EA to chart
   - Monitor Experts tab
   - Check server logs

4. **Deploy**
   - Copy .ex5 to production MT5
   - Restart EA on all charts

### Adding New Log Events

```mql5
// Example: Log symbol price update
SendLog("INFO", "Price updated",
    StringFormat("Symbol: %s, Bid: %.5f, Ask: %.5f", symbol, bid, ask));
```

### Adding New Commands

1. Add command type to server
2. Add case in `ProcessCommands()`
3. Implement execution function
4. Send response to server
5. Add logging

## Version History

**2025-10-04 09:20:00**
- ✅ Comprehensive logging system
- ✅ Trading hours detection
- ✅ Enhanced IsSymbolTradeable()
- ✅ Connection/reconnection logging
- ✅ Trade event logging
- ✅ Command execution logging
- ✅ Error and warning logging

**2025-10-03**
- OnTimer() based tick collection
- 100ms interval for all symbols
- Position sync improvements

**2025-10-02**
- Close reason detection
- Trailing stop identification
- Multi-port communication

**2025-10-01**
- Initial implementation
- Basic server connection
- Tick streaming

## Support

For issues and questions:
1. Check EA logs in MT5 Experts tab
2. Check server logs: `docker logs ngtradingbot_server`
3. Check database logs: `SELECT * FROM logs ORDER BY timestamp DESC`
4. Review this documentation

## License

Proprietary - All rights reserved

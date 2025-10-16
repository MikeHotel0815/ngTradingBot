//+------------------------------------------------------------------+
//|                                              ServerConnector.mq5 |
//|                                    ngTradingBot MT5 Expert       |
//|                                                                  |
//+------------------------------------------------------------------+
#property copyright "ngTradingBot"
#property link      ""
#property version   "1.00"
#property strict

// MANUAL: Update this date when code is modified!
#define CODE_LAST_MODIFIED "2025-10-16 15:40:00"  // FINAL: Deposits/Withdrawals tracking complete, debug logging removed

// Input parameters
input string ServerURL = "http://100.97.100.50:9900";  // Python server URL (Tailscale)
input int    ConnectionTimeout = 5000;                  // Timeout in milliseconds
input int    HeartbeatInterval = 30;                    // Heartbeat every N seconds
input int    TickBatchInterval = 100;                   // Tick batch interval in milliseconds
input int    MagicNumber = 999888;                      // Magic number to identify EA trades

// Global variables
datetime lastHeartbeat = 0;
datetime lastTickBatch = 0;
datetime lastCommandCheck = 0;
datetime lastPositionSync = 0;
bool serverConnected = false;
string apiKey = "";  // Received from server on first connect
string sessionId = "";

// Trade tracking for close reason detection
struct PositionInfo {
   ulong ticket;
   double openPrice;
   double sl;
   double tp;
   double volume;
   string symbol;
   long direction;  // POSITION_TYPE_BUY or POSITION_TYPE_SELL
   double initialSL;  // Original SL for trailing stop detection
   bool slMoved;      // Track if SL was moved in profit direction
};
PositionInfo trackedPositions[];
int trackedPositionCount = 0;

// Symbol management
string subscribedSymbols[];
int symbolCount = 0;

// Profit caching
double cachedProfitToday = 0.0;
double cachedProfitWeek = 0.0;
double cachedProfitMonth = 0.0;
double cachedProfitYear = 0.0;
int lastDealsCount = 0;
datetime lastProfitUpdate = 0;
bool profitUpdateInProgress = false;  // Mutex to prevent race conditions

// Deposits/Withdrawals caching
double cachedDepositsToday = 0.0;
double cachedDepositsWeek = 0.0;
double cachedDepositsMonth = 0.0;
double cachedDepositsYear = 0.0;

// Transaction tracking
datetime lastTransactionCheck = 0;

// Tick buffer structure
struct TickData {
   string symbol;
   double bid;
   double ask;
   ulong volume;
   long timestamp;
   bool tradeable;  // Trading hours check
};
TickData tickBuffer[];
int tickBufferCount = 0;

// File paths
#define API_KEY_FILE "api_key.txt"

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("========================================");
   Print("ServerConnector EA starting...");
   Print("Code Last Modified: ", CODE_LAST_MODIFIED);
   Print("Server URL: ", ServerURL);
   Print("========================================");

   // Try to load API key from file
   LoadAPIKey();

   // Test connection to server
   if(ConnectToServer())
   {
      Print("Successfully connected to server at: ", ServerURL);
      serverConnected = true;
      SendLog("INFO", "EA connected to server", StringFormat("Account: %d, Server: %s", AccountInfoInteger(ACCOUNT_LOGIN), ServerURL));

      // Load subscribed symbols from server response
      LoadSubscribedSymbols();

      // Send symbol specifications for all subscribed symbols
      SendSymbolSpecifications();

      // Send historical OHLC data for all subscribed symbols
      SendAllHistoricalData();
   }
   else
   {
      Print("WARNING: Could not connect to server at: ", ServerURL);
      Print("EA will continue attempting to connect...");
      serverConnected = false;
      SendLog("ERROR", "Failed to connect to server", StringFormat("Server: %s", ServerURL));
   }

   // Set timer for tick batch sending (in milliseconds)
   EventSetMillisecondTimer(TickBatchInterval);

   // Initialize transaction check to account creation (0 = load all history)
   lastTransactionCheck = 0;

   // Track all existing open positions
   if(serverConnected)
   {
      Print("Tracking existing open positions...");
      int totalPositions = PositionsTotal();
      for(int i = 0; i < totalPositions; i++)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0)
         {
            TrackPosition(ticket);
         }
      }
      Print("Tracking ", trackedPositionCount, " open positions");
   }

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(serverConnected)
   {
      DisconnectFromServer();
   }
   Print("ServerConnector EA stopped. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Ticks are now collected in OnTimer() to be independent from chart symbol
   // This function is kept for compatibility but mainly handles heartbeat

   // Send heartbeat periodically
   if(TimeCurrent() - lastHeartbeat >= HeartbeatInterval)
   {
      if(!serverConnected)
      {
         // Try to reconnect
         serverConnected = ConnectToServer();
         if(serverConnected)
         {
            SendLog("INFO", "EA reconnected to server", "Connection restored");
         }
      }
      else
      {
         // Send heartbeat
         SendHeartbeat();
      }
      lastHeartbeat = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Timer function for batch sending                                 |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Collect ticks for ALL subscribed symbols on every timer tick
   // This makes the EA independent from chart symbol ticks
   for(int i = 0; i < symbolCount; i++)
   {
      MqlTick tick;
      if(SymbolInfoTick(subscribedSymbols[i], tick))
      {
         // Add to buffer
         AddTickToBuffer(subscribedSymbols[i], tick);
      }
   }

   // Send tick batch if we have any
   if(tickBufferCount > 0 && serverConnected && apiKey != "")
   {
      SendTickBatch();
   }

   // Check for pending commands every 1 second (using millisecond timer set to 100ms, so check every 10 timer calls)
   static int timerCallCount = 0;
   timerCallCount++;

   if(timerCallCount >= 10 && serverConnected && apiKey != "")  // Every 1000ms (10 x 100ms)
   {
      CheckForCommands();
      timerCallCount = 0;
   }

   // Check for account transactions every 30 seconds (300 timer calls at 100ms)
   static int transactionTimerCount = 0;
   transactionTimerCount++;

   if(transactionTimerCount >= 300 && serverConnected && apiKey != "")  // Every 30 seconds
   {
      CheckAccountTransactions();
      transactionTimerCount = 0;
   }

   // Sync all open positions every 30 seconds (300 timer calls at 100ms)
   static int positionSyncTimerCount = 0;
   positionSyncTimerCount++;

   if(positionSyncTimerCount >= 300 && serverConnected && apiKey != "")  // Every 30 seconds
   {
      SyncAllPositions();
      positionSyncTimerCount = 0;
   }
}

//+------------------------------------------------------------------+
//| Trade event - triggered when trade happens                       |
//+------------------------------------------------------------------+
void OnTrade()
{
   // When a trade closes, immediately recalculate and send profit update
   if(!serverConnected || apiKey == "")
      return;

   // Force profit cache update
   lastProfitUpdate = 0;
   UpdateProfitCache();

   // Send immediate profit update to server
   SendProfitUpdate();
}

//+------------------------------------------------------------------+
//| Trade transaction event - captures ALL trade operations          |
//+------------------------------------------------------------------+
void OnTradeTransaction(
   const MqlTradeTransaction& trans,
   const MqlTradeRequest& request,
   const MqlTradeResult& result
)
{
   if(!serverConnected || apiKey == "")
      return;

   // We're interested in deal executions (actual trades)
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      ulong dealTicket = trans.deal;

      if(HistoryDealSelect(dealTicket))
      {
         ENUM_DEAL_ENTRY dealEntry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
         ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE);

         // Only process BUY/SELL deals, not balance operations
         if(dealType == DEAL_TYPE_BUY || dealType == DEAL_TYPE_SELL)
         {
            if(dealEntry == DEAL_ENTRY_IN)
            {
               // Position opened
               ulong positionTicket = trans.position;
               SendTradeUpdate(positionTicket, "OPEN");

               // Track this position for close reason detection
               TrackPosition(positionTicket);

               // Log trade open
               if(PositionSelectByTicket(positionTicket))
               {
                  string symbol = PositionGetString(POSITION_SYMBOL);
                  double volume = PositionGetDouble(POSITION_VOLUME);
                  string direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
                  SendLog("INFO", "Trade opened", StringFormat("Ticket: %d, %s %s %.2f", positionTicket, direction, symbol, volume));
               }
            }
            else if(dealEntry == DEAL_ENTRY_OUT)
            {
               // Position closed
               ulong positionTicket = trans.position;
               string closeReason = DetectCloseReason(positionTicket, dealTicket);
               SendTradeUpdate(positionTicket, "CLOSE", closeReason);

               // Log trade close
               double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
               string symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
               SendLog("INFO", "Trade closed", StringFormat("Ticket: %d, %s, Profit: %.2f, Reason: %s", positionTicket, symbol, profit, closeReason));

               // Remove from tracking
               UntrackPosition(positionTicket);
            }
         }
      }
   }
   // Position modification (SL/TP changed)
   else if(trans.type == TRADE_TRANSACTION_HISTORY_ADD)
   {
      // Check if this is a modification of an existing position
      if(trans.order_type == ORDER_TYPE_BUY || trans.order_type == ORDER_TYPE_SELL)
      {
         SendTradeUpdate(trans.position, "MODIFY");
         UpdateTrackedPosition(trans.position);

         // Log modification
         if(PositionSelectByTicket(trans.position))
         {
            string symbol = PositionGetString(POSITION_SYMBOL);
            double sl = PositionGetDouble(POSITION_SL);
            double tp = PositionGetDouble(POSITION_TP);
            SendLog("INFO", "Trade modified", StringFormat("Ticket: %d, %s, SL: %.5f, TP: %.5f", trans.position, symbol, sl, tp));
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Load API key from file                                           |
//+------------------------------------------------------------------+
void LoadAPIKey()
{
   int fileHandle = FileOpen(API_KEY_FILE, FILE_READ|FILE_TXT);

   if(fileHandle != INVALID_HANDLE)
   {
      apiKey = FileReadString(fileHandle);
      FileClose(fileHandle);
      Print("API Key loaded from file");
   }
   else
   {
      Print("No API key file found - will request new one");
   }
}

//+------------------------------------------------------------------+
//| Save API key to file                                             |
//+------------------------------------------------------------------+
void SaveAPIKey(string key)
{
   int fileHandle = FileOpen(API_KEY_FILE, FILE_WRITE|FILE_TXT);

   if(fileHandle != INVALID_HANDLE)
   {
      FileWriteString(fileHandle, key);
      FileClose(fileHandle);
      Print("API Key saved to file");
   }
   else
   {
      Print("ERROR: Could not save API key to file");
   }
}

//+------------------------------------------------------------------+
//| Parse JSON value (simple parser for api_key)                    |
//+------------------------------------------------------------------+
string ParseJSONValue(string json, string key)
{
   string searchKey = "\"" + key + "\":\"";
   int startPos = StringFind(json, searchKey);

   if(startPos == -1)
      return "";

   startPos += StringLen(searchKey);
   int endPos = StringFind(json, "\"", startPos);

   if(endPos == -1)
      return "";

   return StringSubstr(json, startPos, endPos - startPos);
}

//+------------------------------------------------------------------+
//| Get all available symbols from broker                            |
//+------------------------------------------------------------------+
string GetAvailableSymbols()
{
   int totalSymbols = SymbolsTotal(false);  // false = ALL symbols at broker, not just Market Watch
   string symbolsJSON = "[";
   int addedCount = 0;

   for(int i = 0; i < totalSymbols; i++)
   {
      string symbolName = SymbolName(i, false);

      if(symbolName != "")
      {
         if(addedCount > 0)
            symbolsJSON += ",";

         symbolsJSON += "\"" + symbolName + "\"";
         addedCount++;
      }
   }

   symbolsJSON += "]";

   Print("Found ", addedCount, " available symbols at broker (all symbols, not just Market Watch)");
   return symbolsJSON;
}

//+------------------------------------------------------------------+
//| Connect to Python server                                         |
//+------------------------------------------------------------------+
bool ConnectToServer()
{
   string url = ServerURL + "/api/connect";
   string headers = "Content-Type: application/json\r\n";

   // Get all available symbols from broker
   string availableSymbols = GetAvailableSymbols();

   // Prepare connection data with available symbols
   string jsonData = StringFormat(
      "{\"account\":%d,\"broker\":\"%s\",\"platform\":\"MT5\",\"timestamp\":%d,\"available_symbols\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoString(ACCOUNT_COMPANY),
      TimeCurrent(),
      availableSymbols
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   ResetLastError();
   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      string response = CharArrayToString(result);
      Print("Server response: ", response);

      // Parse and save API key from response
      string newApiKey = ParseJSONValue(response, "api_key");
      if(newApiKey != "")
      {
         apiKey = newApiKey;
         SaveAPIKey(apiKey);
         Print("Received and saved API key");
      }

      return true;
   }
   else if(res == -1)
   {
      int error = GetLastError();
      Print("WebRequest error: ", error);
      Print("Make sure the URL is added to Tools->Options->Expert Advisors->Allow WebRequest for listed URL");
      Print("Add: ", ServerURL);
      return false;
   }
   else
   {
      Print("Server returned error code: ", res);
      return false;
   }
}

//+------------------------------------------------------------------+
//| Send historical OHLC data for a symbol                           |
//+------------------------------------------------------------------+
bool SendHistoricalData(string symbol, ENUM_TIMEFRAMES timeframe, int barsCount)
{
   if(apiKey == "")
   {
      Print("Cannot send historical data - no API key");
      return false;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, true);

   int copied = CopyRates(symbol, timeframe, 0, barsCount, rates);
   if(copied <= 0)
   {
      Print("Failed to copy rates for ", symbol, " ", EnumToString(timeframe));
      return false;
   }

   // Convert timeframe enum to string
   string tfString;
   switch(timeframe)
   {
      case PERIOD_M1:  tfString = "M1"; break;
      case PERIOD_M5:  tfString = "M5"; break;
      case PERIOD_M15: tfString = "M15"; break;
      case PERIOD_H1:  tfString = "H1"; break;
      case PERIOD_H4:  tfString = "H4"; break;
      case PERIOD_D1:  tfString = "D1"; break;
      default: tfString = "M1"; break;
   }

   // Build JSON array of OHLC data
   string candlesJson = "[";
   for(int i = copied - 1; i >= 0; i--)  // Send oldest to newest
   {
      if(i < copied - 1) candlesJson += ",";

      candlesJson += StringFormat(
         "{\"timestamp\":%d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%d}",
         rates[i].time,
         rates[i].open,
         rates[i].high,
         rates[i].low,
         rates[i].close,
         rates[i].tick_volume
      );
   }
   candlesJson += "]";

   // Prepare request
   string url = ServerURL + "/api/ohlc/historical";
   string headers = "Content-Type: application/json\r\nX-API-Key: " + apiKey + "\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"symbol\":\"%s\",\"timeframe\":\"%s\",\"candles\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      symbol,
      tfString,
      candlesJson
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   ResetLastError();
   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      Print("Sent ", copied, " historical candles for ", symbol, " ", tfString);
      return true;
   }
   else
   {
      Print("Failed to send historical data for ", symbol, " ", tfString, " - HTTP ", res);
      return false;
   }
}

//+------------------------------------------------------------------+
//| Send symbol specifications to server                             |
//+------------------------------------------------------------------+
void SendSymbolSpecifications()
{
   if(apiKey == "")
   {
      Print("Cannot send symbol specs - no API key");
      return;
   }

   Print("======================================");
   Print("Sending symbol specifications...");
   Print("======================================");

   // Build JSON array of symbol specs
   string specsJSON = "[";

   for(int i = 0; i < symbolCount; i++)
   {
      string symbol = subscribedSymbols[i];

      if(i > 0)
         specsJSON += ",";

      specsJSON += StringFormat(
         "{\"symbol\":\"%s\",\"volume_min\":%.2f,\"volume_max\":%.2f,\"volume_step\":%.2f,\"stops_level\":%d,\"freeze_level\":%d,\"trade_mode\":%d,\"digits\":%d,\"point_value\":%.10f}",
         symbol,
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN),
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX),
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP),
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL),
         SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE),
         SymbolInfoInteger(symbol, SYMBOL_DIGITS),
         SymbolInfoDouble(symbol, SYMBOL_POINT)
      );
   }

   specsJSON += "]";

   // Prepare request
   string url = ServerURL + "/api/symbol_specs";
   string headers = "Content-Type: application/json\r\nX-API-Key: " + apiKey + "\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"symbols\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      specsJSON
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   ResetLastError();
   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      Print("Symbol specifications sent successfully for ", symbolCount, " symbols");
   }
   else
   {
      Print("Failed to send symbol specifications - HTTP ", res);
   }
}

//+------------------------------------------------------------------+
//| Send historical data for all subscribed symbols                  |
//+------------------------------------------------------------------+
void SendAllHistoricalData()
{
   Print("======================================");
   Print("Sending historical OHLC data...");
   Print("======================================");

   ENUM_TIMEFRAMES timeframes[] = {PERIOD_H1, PERIOD_H4};
   int barCounts[] = {168, 84};  // H1:7d, H4:14d - optimized for auto-optimization system

   for(int s = 0; s < symbolCount; s++)
   {
      string symbol = subscribedSymbols[s];

      for(int t = 0; t < ArraySize(timeframes); t++)
      {
         SendHistoricalData(symbol, timeframes[t], barCounts[t]);
         Sleep(100);  // Small delay to avoid overwhelming server
      }
   }

   Print("Historical data upload complete");
}

//+------------------------------------------------------------------+
//| Calculate total deposits since account creation                  |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Get deposits/withdrawals since a specific time                   |
//+------------------------------------------------------------------+
double GetDepositsSince(datetime sinceTime)
{
   double totalDeposits = 0.0;

   // Get history since specified time
   if(!HistorySelect(sinceTime, TimeCurrent()))
   {
      Print("Failed to select history for deposits");
      return 0.0;
   }

   int totalDeals = HistoryDealsTotal();

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket > 0)
      {
         ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);

         // Only count BALANCE operations (deposits/withdrawals)
         if(dealType == DEAL_TYPE_BALANCE)
         {
            double dealProfit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
            totalDeposits += dealProfit;
         }
      }
   }

   return totalDeposits;
}

//+------------------------------------------------------------------+
//| Get total deposits since account creation                        |
//+------------------------------------------------------------------+
double GetTotalDeposits()
{
   return GetDepositsSince(0);  // All time
}

//+------------------------------------------------------------------+
//| Calculate profit since a given timestamp                         |
//+------------------------------------------------------------------+
double GetProfitSince(datetime sinceTime)
{
   double totalProfit = 0.0;

   // Get closed deals from history
   if(!HistorySelect(sinceTime, TimeCurrent()))
   {
      Print("Failed to select history");
      return 0.0;
   }

   int totalDeals = HistoryDealsTotal();

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket > 0)
      {
         // ✅ FIX: Exclude balance operations (deposits/withdrawals)
         ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
         
         // Only count trading deals (BUY, SELL), not balance adjustments
         if(dealType == DEAL_TYPE_BALANCE)
            continue;
         
         double dealProfit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
         double dealSwap = HistoryDealGetDouble(ticket, DEAL_SWAP);
         double dealCommission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);

         totalProfit += dealProfit + dealSwap + dealCommission;
      }
   }

   return totalProfit;
}

//+------------------------------------------------------------------+
//| Get deposits/withdrawals for today                               |
//+------------------------------------------------------------------+
double GetDepositsToday()
{
   MqlDateTime today;
   TimeToStruct(TimeCurrent(), today);
   today.hour = 0;
   today.min = 0;
   today.sec = 0;

   datetime startOfDay = StructToTime(today);
   return GetDepositsSince(startOfDay);
}

//+------------------------------------------------------------------+
//| Get deposits/withdrawals for this week                           |
//+------------------------------------------------------------------+
double GetDepositsWeek()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   int dayOfWeek = now.day_of_week;  // 0=Sunday, 1=Monday, ..., 6=Saturday
   int daysToMonday = (dayOfWeek == 0) ? 6 : (dayOfWeek - 1);  // Days since Monday

   datetime startOfWeek = TimeCurrent() - (daysToMonday * 86400);
   MqlDateTime weekStart;
   TimeToStruct(startOfWeek, weekStart);
   weekStart.hour = 0;
   weekStart.min = 0;
   weekStart.sec = 0;

   return GetDepositsSince(StructToTime(weekStart));
}

//+------------------------------------------------------------------+
//| Get deposits/withdrawals for this month                          |
//+------------------------------------------------------------------+
double GetDepositsMonth()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   now.day = 1;
   now.hour = 0;
   now.min = 0;
   now.sec = 0;

   datetime startOfMonth = StructToTime(now);
   return GetDepositsSince(startOfMonth);
}

//+------------------------------------------------------------------+
//| Get deposits/withdrawals for this year                           |
//+------------------------------------------------------------------+
double GetDepositsYear()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   now.mon = 1;
   now.day = 1;
   now.hour = 0;
   now.min = 0;
   now.sec = 0;

   datetime startOfYear = StructToTime(now);
   return GetDepositsSince(startOfYear);
}

//+------------------------------------------------------------------+
//| Get profit for today                                             |
//+------------------------------------------------------------------+
double GetProfitToday()
{
   MqlDateTime today;
   TimeToStruct(TimeCurrent(), today);
   today.hour = 0;
   today.min = 0;
   today.sec = 0;

   datetime startOfDay = StructToTime(today);
   return GetProfitSince(startOfDay);
}

//+------------------------------------------------------------------+
//| Get profit for this week                                         |
//+------------------------------------------------------------------+
double GetProfitWeek()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   // Calculate days since Monday (day_of_week: 0=Sunday, 1=Monday, ...)
   int daysSinceMonday = (now.day_of_week == 0) ? 6 : now.day_of_week - 1;

   datetime startOfWeek = TimeCurrent() - (daysSinceMonday * 86400);

   MqlDateTime weekStart;
   TimeToStruct(startOfWeek, weekStart);
   weekStart.hour = 0;
   weekStart.min = 0;
   weekStart.sec = 0;

   return GetProfitSince(StructToTime(weekStart));
}

//+------------------------------------------------------------------+
//| Get profit for this month                                        |
//+------------------------------------------------------------------+
double GetProfitMonth()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   now.day = 1;
   now.hour = 0;
   now.min = 0;
   now.sec = 0;

   datetime startOfMonth = StructToTime(now);
   return GetProfitSince(startOfMonth);
}

//+------------------------------------------------------------------+
//| Get profit for this year (relative to deposits)                  |
//+------------------------------------------------------------------+
double GetProfitYear()
{
   // Return actual profit: Current Balance - Total Deposits
   double currentBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   double totalDeposits = GetTotalDeposits();

   return currentBalance - totalDeposits;
}

//+------------------------------------------------------------------+
//| Update profit cache (only when deals change)                     |
//+------------------------------------------------------------------+
void UpdateProfitCache()
{
   // Mutex to prevent race conditions
   if(profitUpdateInProgress)
      return;

   // Only update every 5 seconds to avoid performance issues
   if(TimeCurrent() - lastProfitUpdate < 5)
      return;

   profitUpdateInProgress = true;

   // Update profit cache
   cachedProfitToday = GetProfitToday();
   cachedProfitWeek = GetProfitWeek();
   cachedProfitMonth = GetProfitMonth();
   cachedProfitYear = GetProfitYear();
   
   // Update deposits cache
   cachedDepositsToday = GetDepositsToday();
   cachedDepositsWeek = GetDepositsWeek();
   cachedDepositsMonth = GetDepositsMonth();
   cachedDepositsYear = GetDepositsYear();
   
   lastProfitUpdate = TimeCurrent();

   profitUpdateInProgress = false;
}

//+------------------------------------------------------------------+
//| Send profit update to server (called after trade closes)         |
//+------------------------------------------------------------------+
void SendProfitUpdate()
{
   string url = ServerURL + "/api/profit_update";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,\"profit_today\":%.2f,\"profit_week\":%.2f,\"profit_month\":%.2f,\"profit_year\":%.2f}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      cachedProfitToday,
      cachedProfitWeek,
      cachedProfitMonth,
      cachedProfitYear
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );
}

//+------------------------------------------------------------------+
//| Process commands from server response                            |
//+------------------------------------------------------------------+
void ProcessCommands(string response)
{
   // Simple parser for commands array
   int commandsStart = StringFind(response, "\"commands\":[");
   if(commandsStart < 0)
      return;

   int arrayStart = commandsStart + 12; // After "commands":[
   int arrayEnd = StringFind(response, "]", arrayStart);

   string commandsStr = StringSubstr(response, arrayStart, arrayEnd - arrayStart);

   // Check if empty array
   if(StringLen(commandsStr) < 5)
      return;

   Print("Processing commands from server...");

   // Simple command parser - look for each command object
   int pos = 0;
   while(pos < StringLen(commandsStr))
   {
      int objStart = StringFind(commandsStr, "{", pos);
      if(objStart < 0) break;

      int objEnd = StringFind(commandsStr, "}", objStart);
      if(objEnd < 0) break;

      string cmdObj = StringSubstr(commandsStr, objStart, objEnd - objStart + 1);

      // Parse command ID
      string cmdId = ParseJSONString(cmdObj, "id");
      string cmdType = ParseJSONString(cmdObj, "type");

      Print("Executing command: ", cmdType, " (ID: ", cmdId, ")");
      SendLog("INFO", "Command received", StringFormat("Type: %s, ID: %s", cmdType, cmdId));

      if(cmdType == "OPEN_TRADE")
      {
         ExecuteOpenTrade(cmdId, cmdObj);
      }
      else if(cmdType == "MODIFY_TRADE")
      {
         ExecuteModifyTrade(cmdId, cmdObj);
      }
      else if(cmdType == "CLOSE_TRADE")
      {
         ExecuteCloseTrade(cmdId, cmdObj);
      }
      else if(cmdType == "REQUEST_HISTORICAL_DATA")
      {
         ExecuteRequestHistoricalData(cmdId, cmdObj);
      }
      else
      {
         SendLog("WARNING", "Unknown command type", StringFormat("Type: %s, ID: %s", cmdType, cmdId));
      }

      pos = objEnd + 1;
   }
}

//+------------------------------------------------------------------+
//| Parse JSON string value (helper function)                        |
//+------------------------------------------------------------------+
string ParseJSONString(string json, string key)
{
   string searchKey = "\"" + key + "\":\"";
   int startPos = StringFind(json, searchKey);
   if(startPos == -1)
      return "";

   startPos += StringLen(searchKey);
   int endPos = StringFind(json, "\"", startPos);
   if(endPos == -1)
      return "";

   return StringSubstr(json, startPos, endPos - startPos);
}

//+------------------------------------------------------------------+
//| Execute OPEN_TRADE command                                       |
//+------------------------------------------------------------------+
void ExecuteOpenTrade(string commandId, string cmdObj)
{
   // Extract symbol, order_type, volume (fields are now flat, not nested in payload)
   string symbol = ParseJSONString(cmdObj, "symbol");
   string orderTypeStr = ParseJSONString(cmdObj, "order_type");
   string comment = ParseJSONString(cmdObj, "comment");

   if(symbol == "")
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"No symbol found\"}");
      return;
   }

   // Parse volume (numeric)
   double volume = 0.01;
   int volPos = StringFind(cmdObj, "\"volume\":");
   if(volPos >= 0)
   {
      string volStr = StringSubstr(cmdObj, volPos + 9, 10);
      volume = StringToDouble(volStr);
   }

   // Normalize volume to symbol's min/max/step
   double volumeMin = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double volumeMax = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double volumeStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

   // Ensure volume is at least the minimum
   if(volume < volumeMin)
   {
      Print("WARNING: Volume ", volume, " is below minimum ", volumeMin, " for ", symbol, ". Using minimum.");
      volume = volumeMin;
   }

   // Ensure volume is at most the maximum
   if(volume > volumeMax)
   {
      Print("WARNING: Volume ", volume, " exceeds maximum ", volumeMax, " for ", symbol, ". Using maximum.");
      volume = volumeMax;
   }

   // Round volume to the nearest step
   if(volumeStep > 0)
   {
      volume = MathRound(volume / volumeStep) * volumeStep;

      // Re-validate after rounding
      if(volume < volumeMin)
         volume = volumeMin;
      if(volume > volumeMax)
         volume = volumeMax;
   }

   // Parse SL (numeric) - REQUIRED
   double sl = 0;
   int slPos = StringFind(cmdObj, "\"sl\":");
   if(slPos >= 0)
   {
      string slStr = StringSubstr(cmdObj, slPos + 5, 15);
      sl = StringToDouble(slStr);
   }

   // Parse TP (numeric) - REQUIRED
   double tp = 0;
   int tpPos = StringFind(cmdObj, "\"tp\":");
   if(tpPos >= 0)
   {
      string tpStr = StringSubstr(cmdObj, tpPos + 5, 15);
      tp = StringToDouble(tpStr);
   }

   // Validate that SL and TP are set
   if(sl == 0 || tp == 0)
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"SL and TP are required and must not be 0\"}");
      Print("ERROR: Trade rejected - SL and TP must be set! SL: ", sl, " TP: ", tp);
      return;
   }

   Print("Opening trade: ", symbol, " ", orderTypeStr, " ", volume, " SL: ", sl, " TP: ", tp);

   // Get current price
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Failed to get tick data\"}");
      return;
   }

   // Validate SL/TP distance with stops level
   int stopsLevel = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double minDistance = stopsLevel * point;
   
   double currentPrice = (orderTypeStr == "BUY") ? tick.ask : tick.bid;
   
   // For BUY: SL must be below price, TP above
   // For SELL: SL must be above price, TP below
   if(orderTypeStr == "BUY")
   {
      if(sl >= currentPrice)
      {
         SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Invalid SL: %.5f >= Price: %.5f (BUY)\",\"error_code\":130}", sl, currentPrice));
         Print("ERROR: BUY order - SL must be below current price! SL: ", sl, " Price: ", currentPrice);
         return;
      }
      if(tp <= currentPrice)
      {
         SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Invalid TP: %.5f <= Price: %.5f (BUY)\",\"error_code\":130}", tp, currentPrice));
         Print("ERROR: BUY order - TP must be above current price! TP: ", tp, " Price: ", currentPrice);
         return;
      }
      
      // Check minimum distance
      if(stopsLevel > 0)
      {
         double slDistance = currentPrice - sl;
         double tpDistance = tp - currentPrice;
         
         if(slDistance < minDistance)
         {
            SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"SL too close: %.5f < %.5f (min %d points)\",\"error_code\":130}", slDistance, minDistance, stopsLevel));
            Print("ERROR: SL too close to price! Distance: ", slDistance, " Min: ", minDistance, " (", stopsLevel, " points)");
            return;
         }
         if(tpDistance < minDistance)
         {
            SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"TP too close: %.5f < %.5f (min %d points)\",\"error_code\":130}", tpDistance, minDistance, stopsLevel));
            Print("ERROR: TP too close to price! Distance: ", tpDistance, " Min: ", minDistance, " (", stopsLevel, " points)");
            return;
         }
      }
   }
   else if(orderTypeStr == "SELL")
   {
      if(sl <= currentPrice)
      {
         SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Invalid SL: %.5f <= Price: %.5f (SELL)\",\"error_code\":130}", sl, currentPrice));
         Print("ERROR: SELL order - SL must be above current price! SL: ", sl, " Price: ", currentPrice);
         return;
      }
      if(tp >= currentPrice)
      {
         SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Invalid TP: %.5f >= Price: %.5f (SELL)\",\"error_code\":130}", tp, currentPrice));
         Print("ERROR: SELL order - TP must be below current price! TP: ", tp, " Price: ", currentPrice);
         return;
      }
      
      // Check minimum distance
      if(stopsLevel > 0)
      {
         double slDistance = sl - currentPrice;
         double tpDistance = currentPrice - tp;
         
         if(slDistance < minDistance)
         {
            SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"SL too close: %.5f < %.5f (min %d points)\",\"error_code\":130}", slDistance, minDistance, stopsLevel));
            Print("ERROR: SL too close to price! Distance: ", slDistance, " Min: ", minDistance, " (", stopsLevel, " points)");
            return;
         }
         if(tpDistance < minDistance)
         {
            SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"TP too close: %.5f < %.5f (min %d points)\",\"error_code\":130}", tpDistance, minDistance, stopsLevel));
            Print("ERROR: TP too close to price! Distance: ", tpDistance, " Min: ", minDistance, " (", stopsLevel, " points)");
            return;
         }
      }
   }

   // Debug: Print symbol properties
   Print("DEBUG Symbol Properties for ", symbol, ":");
   Print("  Volume Min: ", SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN));
   Print("  Volume Max: ", SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX));
   Print("  Volume Step: ", SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP));
   Print("  Stops Level: ", SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL), " points");
   Print("  Freeze Level: ", SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL), " points");
   Print("  Trade Mode: ", SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE));
   Print("  Digits: ", SymbolInfoInteger(symbol, SYMBOL_DIGITS));
   Print("  Point: ", SymbolInfoDouble(symbol, SYMBOL_POINT));
   Print("  Current Bid: ", tick.bid, " Ask: ", tick.ask);

   // Determine order type and price
   ENUM_ORDER_TYPE orderType;
   double price;

   if(orderTypeStr == "BUY")
   {
      orderType = ORDER_TYPE_BUY;
      price = tick.ask;
   }
   else if(orderTypeStr == "SELL")
   {
      orderType = ORDER_TYPE_SELL;
      price = tick.bid;
   }
   else
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Invalid order type\"}");
      return;
   }

   // Prepare trade request
   MqlTradeRequest request;
   MqlTradeResult result;

   ZeroMemory(request);
   ZeroMemory(result);

   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = volume;
   request.type = orderType;
   request.price = price;
   request.sl = sl;
   request.tp = tp;
   request.deviation = 10;
   request.magic = MagicNumber;
   request.comment = comment;

   // Get symbol's supported filling modes
   int filling = (int)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   
   // Build list of filling modes to try based on what symbol supports
   ENUM_ORDER_TYPE_FILLING fillingModes[3];
   int fillingCount = 0;
   
   // Check which modes are supported and add them in order of preference
   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
   {
      fillingModes[fillingCount++] = ORDER_FILLING_FOK;
   }
   if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
   {
      fillingModes[fillingCount++] = ORDER_FILLING_IOC;
   }
   // RETURN mode is always available as fallback for market orders
   fillingModes[fillingCount++] = ORDER_FILLING_RETURN;
   
   Print("Symbol ", symbol, " supports filling modes: ", filling, " (trying ", fillingCount, " modes)");
   
   bool orderSuccess = false;

   for(int fm = 0; fm < fillingCount; fm++)
   {
      request.type_filling = fillingModes[fm];

      Print("Trying filling mode: ", fillingModes[fm], " for ", symbol);

      if(OrderSend(request, result))
      {
         if(result.retcode == TRADE_RETCODE_DONE)
         {
            // CRITICAL FIX: Verify TP/SL were actually set by broker
            // Some brokers/symbols don't accept TP/SL in initial order and return 0
            Sleep(500);  // Give broker time to process

            double actualSL = 0;
            double actualTP = 0;
            bool tpslVerified = false;

            // Try to read actual TP/SL from opened position (with retries)
            for(int retry = 0; retry < 3; retry++)
            {
               if(PositionSelectByTicket(result.order))
               {
                  actualSL = PositionGetDouble(POSITION_SL);
                  actualTP = PositionGetDouble(POSITION_TP);

                  if(actualSL != 0 && actualTP != 0)
                  {
                     tpslVerified = true;
                     break;
                  }
               }
               Sleep(200);
            }

            // If broker didn't set TP/SL, try to modify position
            if(!tpslVerified || actualSL == 0 || actualTP == 0)
            {
               Print("WARNING: Broker did not set TP/SL in initial order! Attempting to modify position...");
               Print("  Requested: SL=", sl, " TP=", tp);
               Print("  Got: SL=", actualSL, " TP=", actualTP);

               // Attempt to modify position with TP/SL
               MqlTradeRequest modifyReq;
               MqlTradeResult modifyRes;
               ZeroMemory(modifyReq);
               ZeroMemory(modifyRes);

               modifyReq.action = TRADE_ACTION_SLTP;
               modifyReq.position = result.order;
               modifyReq.symbol = symbol;
               modifyReq.sl = sl;
               modifyReq.tp = tp;

               if(OrderSend(modifyReq, modifyRes))
               {
                  if(modifyRes.retcode == TRADE_RETCODE_DONE)
                  {
                     Print("SUCCESS: TP/SL set via modify! SL:", sl, " TP:", tp);
                     actualSL = sl;
                     actualTP = tp;
                     tpslVerified = true;
                  }
                  else
                  {
                     Print("ERROR: Modify failed with retcode: ", modifyRes.retcode);
                     SendLog("ERROR", "TP/SL modification failed", StringFormat("Ticket %d retcode %d", result.order, modifyRes.retcode));
                  }
               }
               else
               {
                  int modError = GetLastError();
                  Print("ERROR: Modify OrderSend failed: ", modError, " - ", ErrorDescription(modError));
                  SendLog("ERROR", "TP/SL modification failed", StringFormat("Ticket %d error %d", result.order, modError));
               }
            }

            // Send response with ACTUAL TP/SL values (not requested ones!)
            string responseData = StringFormat(
               "{\"ticket\":%d,\"price\":%.5f,\"volume\":%.2f,\"sl\":%.5f,\"tp\":%.5f,\"tpsl_verified\":%s}",
               result.order,
               result.price,
               result.volume,
               actualSL,
               actualTP,
               tpslVerified ? "true" : "false"
            );
            SendCommandResponse(commandId, "completed", responseData);
            Print("Trade opened successfully! Ticket: ", result.order, " Filling mode: ", fillingModes[fm], " TP/SL verified: ", tpslVerified);
            SendLog("INFO", "Command executed successfully", StringFormat("OPEN_TRADE: %s %s %.2f @ %.5f, Ticket: %d, SL: %.5f, TP: %.5f", orderTypeStr, symbol, volume, result.price, result.order, actualSL, actualTP));
            orderSuccess = true;
            break;
         }
         else
         {
            Print("Order failed with retcode: ", result.retcode, " for filling mode: ", fillingModes[fm]);
         }
      }
      else
      {
         int errorCode = GetLastError();
         Print("OrderSend failed with error: ", errorCode, " (", ErrorDescription(errorCode), ") for filling mode: ", fillingModes[fm]);

         // If it's not a filling mode error, no point trying other modes
         if(errorCode != 4756 && errorCode != 10030)
         {
            string errorData = StringFormat(
               "{\"error\":\"OrderSend failed\",\"error_code\":%d,\"error_desc\":\"%s\"}",
               errorCode,
               ErrorDescription(errorCode)
            );
            SendCommandResponse(commandId, "failed", errorData);
            orderSuccess = true; // Stop trying
            break;
         }
      }
   }

   // If all filling modes failed
   if(!orderSuccess)
   {
      string errorData = "{\"error\":\"All filling modes failed\",\"error_code\":4756}";
      SendCommandResponse(commandId, "failed", errorData);
      Print("ERROR: All filling modes (FOK, IOC, RETURN) failed for ", symbol);
      SendLog("ERROR", "Command failed", StringFormat("OPEN_TRADE failed for %s: All filling modes rejected", symbol));
   }
}

//+------------------------------------------------------------------+
//| Execute MODIFY_TRADE command (set SL/TP on existing position)    |
//+------------------------------------------------------------------+
void ExecuteModifyTrade(string commandId, string cmdObj)
{
   // Parse ticket - manual parsing for large ulong values
   ulong ticket = 0;
   int ticketPos = StringFind(cmdObj, "\"ticket\":");
   if(ticketPos >= 0)
   {
      // "ticket": is 9 characters, so skip 9 positions to get to the value
      string afterTicket = StringSubstr(cmdObj, ticketPos + 9, 30);

      // Find the first digit
      int digitStart = -1;
      for(int i = 0; i < StringLen(afterTicket); i++)
      {
         int chr = StringGetCharacter(afterTicket, i);
         if(chr >= '0' && chr <= '9')
         {
            digitStart = i;
            break;
         }
      }

      if(digitStart >= 0)
      {
         // Manual parsing: convert each digit
         for(int i = digitStart; i < StringLen(afterTicket); i++)
         {
            int chr = StringGetCharacter(afterTicket, i);
            if(chr >= '0' && chr <= '9')
            {
               ticket = ticket * 10 + (chr - '0');
            }
            else
            {
               break; // Stop at first non-digit
            }
         }
         Print("DEBUG MODIFY: Parsed ticket = ", ticket);
      }
   }

   if(ticket == 0)
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"No ticket provided\"}");
      return;
   }

   // Parse SL (numeric) - REQUIRED
   double sl = 0;
   int slPos = StringFind(cmdObj, "\"sl\":");
   if(slPos >= 0)
   {
      string slStr = StringSubstr(cmdObj, slPos + 5, 15);
      sl = StringToDouble(slStr);
   }

   // Parse TP (numeric) - REQUIRED
   double tp = 0;
   int tpPos = StringFind(cmdObj, "\"tp\":");
   if(tpPos >= 0)
   {
      string tpStr = StringSubstr(cmdObj, tpPos + 5, 15);
      tp = StringToDouble(tpStr);
   }

   // Validate that SL and TP are set
   if(sl == 0 || tp == 0)
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"SL and TP are required and must not be 0\"}");
      Print("ERROR: Modify rejected - SL and TP must be set! SL: ", sl, " TP: ", tp);
      return;
   }

   // Find position by searching all open positions
   string symbol = "";
   int totalPositions = PositionsTotal();
   bool positionFound = false;

   for(int i = 0; i < totalPositions; i++)
   {
      ulong posTicket = PositionGetTicket(i);
      if(posTicket == ticket)
      {
         symbol = PositionGetString(POSITION_SYMBOL);
         positionFound = true;
         break;
      }
   }

   if(!positionFound)
   {
      SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Position %d not found. Total positions: %d\"}", ticket, totalPositions));
      Print("ERROR: Position with ticket ", ticket, " not found. Total open positions: ", totalPositions);
      return;
   }

   Print("Modifying position: Ticket ", ticket, " Symbol ", symbol, " SL: ", sl, " TP: ", tp);

   // Prepare trade request
   MqlTradeRequest request;
   MqlTradeResult result;

   ZeroMemory(request);
   ZeroMemory(result);

   request.action = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.symbol = symbol;
   request.sl = sl;
   request.tp = tp;

   // Send modify order
   if(OrderSend(request, result))
   {
      if(result.retcode == TRADE_RETCODE_DONE)
      {
         string responseData = StringFormat(
            "{\"ticket\":%d,\"sl\":%.5f,\"tp\":%.5f}",
            ticket,
            sl,
            tp
         );
         SendCommandResponse(commandId, "completed", responseData);
         Print("Position modified successfully! Ticket: ", ticket, " SL: ", sl, " TP: ", tp);
      }
      else
      {
         string errorData = StringFormat(
            "{\"error\":\"Modify failed\",\"retcode\":%d}",
            result.retcode
         );
         SendCommandResponse(commandId, "failed", errorData);
         Print("Modify failed with retcode: ", result.retcode);
      }
   }
   else
   {
      int errorCode = GetLastError();
      string errorData = StringFormat(
         "{\"error\":\"OrderSend failed\",\"error_code\":%d,\"error_desc\":\"%s\"}",
         errorCode,
         ErrorDescription(errorCode)
      );
      SendCommandResponse(commandId, "failed", errorData);
      Print("OrderSend function failed with error: ", errorCode, " - ", ErrorDescription(errorCode));
   }
}

//+------------------------------------------------------------------+
//| Execute CLOSE_TRADE command                                      |
//+------------------------------------------------------------------+
void ExecuteCloseTrade(string commandId, string cmdObj)
{
   Print("DEBUG CLOSE: Full cmdObj = ", cmdObj);

   // Parse ticket - manual parsing for large ulong values
   ulong ticket = 0;
   int ticketPos = StringFind(cmdObj, "\"ticket\":");
   Print("DEBUG CLOSE: ticketPos = ", ticketPos);

   if(ticketPos >= 0)
   {
      // "ticket": is 9 characters, so skip 9 positions to get to the value
      string afterTicket = StringSubstr(cmdObj, ticketPos + 9, 30);
      Print("DEBUG CLOSE: afterTicket substring = '", afterTicket, "'");

      // Find the first digit
      int digitStart = -1;
      for(int i = 0; i < StringLen(afterTicket); i++)
      {
         int chr = StringGetCharacter(afterTicket, i);
         if(chr >= '0' && chr <= '9')
         {
            digitStart = i;
            Print("DEBUG CLOSE: First digit found at position ", i, " character code ", chr);
            break;
         }
      }

      if(digitStart >= 0)
      {
         // Manual parsing: convert each digit
         for(int i = digitStart; i < StringLen(afterTicket); i++)
         {
            int chr = StringGetCharacter(afterTicket, i);
            if(chr >= '0' && chr <= '9')
            {
               ticket = ticket * 10 + (chr - '0');
            }
            else
            {
               Print("DEBUG CLOSE: Stopped parsing at character code ", chr);
               break; // Stop at first non-digit
            }
         }
         Print("DEBUG CLOSE: Final parsed ticket = ", ticket);
      }
   }

   if(ticket == 0)
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"No ticket provided\"}");
      return;
   }

   // Find position
   string symbol = "";
   int totalPositions = PositionsTotal();
   bool positionFound = false;

   for(int i = 0; i < totalPositions; i++)
   {
      ulong posTicket = PositionGetTicket(i);
      if(posTicket == ticket)
      {
         symbol = PositionGetString(POSITION_SYMBOL);
         positionFound = true;
         break;
      }
   }

   if(!positionFound)
   {
      SendCommandResponse(commandId, "failed", StringFormat("{\"error\":\"Position %d not found\"}", ticket));
      Print("ERROR: Position with ticket ", ticket, " not found");
      return;
   }

   Print("Closing position: Ticket ", ticket, " Symbol ", symbol);

   // Prepare close request
   MqlTradeRequest request;
   MqlTradeResult result;

   ZeroMemory(request);
   ZeroMemory(result);

   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = symbol;
   request.volume = PositionGetDouble(POSITION_VOLUME);
   request.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (request.type == ORDER_TYPE_SELL) ? SymbolInfoDouble(symbol, SYMBOL_BID) : SymbolInfoDouble(symbol, SYMBOL_ASK);
   request.deviation = 10;
   request.type_filling = ORDER_FILLING_IOC;

   // Send close order
   if(OrderSend(request, result))
   {
      if(result.retcode == TRADE_RETCODE_DONE)
      {
         string responseData = StringFormat(
            "{\"ticket\":%d,\"close_price\":%.5f}",
            ticket,
            result.price
         );
         SendCommandResponse(commandId, "completed", responseData);
         Print("Position closed successfully! Ticket: ", ticket, " Price: ", result.price);
      }
      else
      {
         string errorData = StringFormat(
            "{\"error\":\"Close failed\",\"retcode\":%d}",
            result.retcode
         );
         SendCommandResponse(commandId, "failed", errorData);
         Print("Close failed with retcode: ", result.retcode);
      }
   }
   else
   {
      int errorCode = GetLastError();
      string errorData = StringFormat(
         "{\"error\":\"OrderSend failed\",\"error_code\":%d,\"error_desc\":\"%s\"}",
         errorCode,
         ErrorDescription(errorCode)
      );
      SendCommandResponse(commandId, "failed", errorData);
      Print("OrderSend function failed with error: ", errorCode, " - ", ErrorDescription(errorCode));
   }
}

//+------------------------------------------------------------------+
//| Execute REQUEST_HISTORICAL_DATA command                          |
//+------------------------------------------------------------------+
void ExecuteRequestHistoricalData(string commandId, string cmdObj)
{
   // Extract parameters from command
   string symbol = ParseJSONString(cmdObj, "symbol");
   string timeframeStr = ParseJSONString(cmdObj, "timeframe");

   // Parse start_date and end_date (Unix timestamps)
   long startTimestamp = 0;
   long endTimestamp = 0;

   int startPos = StringFind(cmdObj, "\"start_date\":");
   if(startPos >= 0)
   {
      string startStr = StringSubstr(cmdObj, startPos + 13, 15);
      startTimestamp = StringToInteger(startStr);
   }

   int endPos = StringFind(cmdObj, "\"end_date\":");
   if(endPos >= 0)
   {
      string endStr = StringSubstr(cmdObj, endPos + 11, 15);
      endTimestamp = StringToInteger(endStr);
   }

   // Validation
   if(symbol == "" || timeframeStr == "")
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Missing symbol or timeframe\"}");
      return;
   }

   if(startTimestamp <= 0 || endTimestamp <= 0)
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Invalid date range\"}");
      return;
   }

   // Convert timeframe string to enum
   ENUM_TIMEFRAMES timeframe;
   if(timeframeStr == "M1") timeframe = PERIOD_M1;
   else if(timeframeStr == "M5") timeframe = PERIOD_M5;
   else if(timeframeStr == "M15") timeframe = PERIOD_M15;
   else if(timeframeStr == "H1") timeframe = PERIOD_H1;
   else if(timeframeStr == "H4") timeframe = PERIOD_H4;
   else if(timeframeStr == "D1") timeframe = PERIOD_D1;
   else
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Invalid timeframe\"}");
      return;
   }

   Print("Requesting historical data for ", symbol, " ", timeframeStr, " from ", TimeToString((datetime)startTimestamp), " to ", TimeToString((datetime)endTimestamp));

   // Copy rates for the specified date range
   MqlRates rates[];
   ArraySetAsSeries(rates, true);

   int copied = CopyRates(symbol, timeframe, (datetime)startTimestamp, (datetime)endTimestamp, rates);

   if(copied <= 0)
   {
      string errorMsg = StringFormat("{\"error\":\"Failed to copy rates for %s %s\",\"bars_copied\":%d}", symbol, timeframeStr, copied);
      SendCommandResponse(commandId, "failed", errorMsg);
      Print("Failed to copy rates: ", GetLastError());
      return;
   }

   Print("Copied ", copied, " bars for ", symbol, " ", timeframeStr);

   // Send historical data to server
   bool success = SendHistoricalDataRange(symbol, timeframe, rates, copied);

   if(success)
   {
      string responseData = StringFormat("{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"bars_sent\":%d}", symbol, timeframeStr, copied);
      SendCommandResponse(commandId, "completed", responseData);
   }
   else
   {
      SendCommandResponse(commandId, "failed", "{\"error\":\"Failed to send historical data to server\"}");
   }
}

//+------------------------------------------------------------------+
//| Send historical data from MqlRates array                         |
//+------------------------------------------------------------------+
bool SendHistoricalDataRange(string symbol, ENUM_TIMEFRAMES timeframe, MqlRates &rates[], int count)
{
   if(apiKey == "")
   {
      Print("Cannot send historical data - no API key");
      return false;
   }

   // Convert timeframe enum to string
   string tfString;
   switch(timeframe)
   {
      case PERIOD_M1:  tfString = "M1"; break;
      case PERIOD_M5:  tfString = "M5"; break;
      case PERIOD_M15: tfString = "M15"; break;
      case PERIOD_H1:  tfString = "H1"; break;
      case PERIOD_H4:  tfString = "H4"; break;
      case PERIOD_D1:  tfString = "D1"; break;
      default: tfString = "M1"; break;
   }

   // Build JSON array of OHLC data (send in chunks to avoid payload too large)
   int chunkSize = 10000;  // Send 10000 bars at a time (optimized for speed - ~9 chunks for 1 year M5 data)
   int totalChunks = (int)MathCeil((double)count / chunkSize);

   for(int chunk = 0; chunk < totalChunks; chunk++)
   {
      int startIdx = chunk * chunkSize;
      int endIdx = MathMin(startIdx + chunkSize, count);

      string candlesJson = "[";
      for(int i = count - endIdx; i < count - startIdx; i++)  // Send oldest to newest
      {
         if(i > count - endIdx) candlesJson += ",";

         candlesJson += StringFormat(
            "{\"timestamp\":%d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%d}",
            rates[i].time,
            rates[i].open,
            rates[i].high,
            rates[i].low,
            rates[i].close,
            rates[i].tick_volume
         );
      }
      candlesJson += "]";

      // Prepare request
      string url = ServerURL + "/api/ohlc/historical";
      string headers = "Content-Type: application/json\r\nX-API-Key: " + apiKey + "\r\n";

      string jsonData = StringFormat(
         "{\"account\":%d,\"symbol\":\"%s\",\"timeframe\":\"%s\",\"candles\":%s}",
         AccountInfoInteger(ACCOUNT_LOGIN),
         symbol,
         tfString,
         candlesJson
      );

      char post[];
      char result[];
      string resultHeaders;

      ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

      ResetLastError();
      int res = WebRequest(
         "POST",
         url,
         headers,
         ConnectionTimeout,
         post,
         result,
         resultHeaders
      );

      if(res == 200)
      {
         Print("Sent chunk ", chunk + 1, "/", totalChunks, " (", endIdx - startIdx, " bars) for ", symbol, " ", tfString);
      }
      else
      {
         Print("Failed to send historical data chunk ", chunk + 1, "/", totalChunks, " for ", symbol, " ", tfString, " - HTTP ", res);
         return false;
      }

      Sleep(50);  // Small delay between chunks
   }

   Print("Successfully sent ", count, " historical candles for ", symbol, " ", tfString, " in ", totalChunks, " chunks");
   return true;
}

//+------------------------------------------------------------------+
//| Send command response to server                                  |
//+------------------------------------------------------------------+
void SendCommandResponse(string commandId, string status, string responseData)
{
   string url = ServerURL + "/api/command_response";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"command_id\":\"%s\",\"status\":\"%s\",\"response\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      commandId,
      status,
      responseData
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );
}

//+------------------------------------------------------------------+
//| Check for pending commands from server (immediate polling)       |
//+------------------------------------------------------------------+
void CheckForCommands()
{
   if(apiKey == "")
      return;

   string url = ServerURL + "/api/get_commands";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\"}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      string response = CharArrayToString(result);

      // Check if response contains commands
      int commandsPos = StringFind(response, "\"commands\":[");
      if(commandsPos >= 0)
      {
         // Process pending commands
         ProcessCommands(response);
      }
   }
}

//+------------------------------------------------------------------+
//| Send heartbeat to server                                         |
//+------------------------------------------------------------------+
bool SendHeartbeat()
{
   if(apiKey == "")
   {
      Print("No API key available, cannot send heartbeat");
      return false;
   }

   string url = ServerURL + "/api/heartbeat";
   string headers = "Content-Type: application/json\r\n";

   // Update profit cache
   UpdateProfitCache();

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"timestamp\":%d,\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,\"profit_today\":%.2f,\"profit_week\":%.2f,\"profit_month\":%.2f,\"profit_year\":%.2f,\"deposits_today\":%.2f,\"deposits_week\":%.2f,\"deposits_month\":%.2f,\"deposits_year\":%.2f}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      TimeCurrent(),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      cachedProfitToday,
      cachedProfitWeek,
      cachedProfitMonth,
      cachedProfitYear,
      cachedDepositsToday,
      cachedDepositsWeek,
      cachedDepositsMonth,
      cachedDepositsYear
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      // Parse response to check for symbol list updates
      string response = CharArrayToString(result);

      // Check if response contains symbols array
      int symbolsPos = StringFind(response, "\"symbols\":[");
      if(symbolsPos >= 0)
      {
         // Parse symbols from response and reload if changed
         ParseAndUpdateSymbols(response);
      }

      // Check if response contains commands
      int commandsPos = StringFind(response, "\"commands\":[");
      if(commandsPos >= 0)
      {
         // Process pending commands
         ProcessCommands(response);
      }

      return true;
   }
   else
   {
      Print("Heartbeat failed with code: ", res);
      if(res == -1)
      {
         int error = GetLastError();
         Print("WebRequest error: ", error);
         SendLog("ERROR", "Heartbeat failed", StringFormat("WebRequest error: %d", error));
         serverConnected = false;
      }
      else if(res == 403)
      {
         Print("Authentication failed - API key may be invalid");
         SendLog("ERROR", "Authentication failed", "API key may be invalid");
         serverConnected = false;
      }
      else
      {
         SendLog("WARNING", "Heartbeat failed", StringFormat("HTTP code: %d", res));
      }
      return false;
   }
}

//+------------------------------------------------------------------+
//| Parse and update symbols from JSON response                      |
//+------------------------------------------------------------------+
void ParseAndUpdateSymbols(string response)
{
   // Parse symbols array from JSON
   int symbolsPos = StringFind(response, "\"symbols\":[");
   if(symbolsPos < 0)
      return;

   int startPos = symbolsPos + 11; // Position after "symbols":[
   int endPos = StringFind(response, "]", startPos);
   string symbolsArray = StringSubstr(response, startPos, endPos - startPos);

   // Count symbols
   int count = 1;
   for(int i = 0; i < StringLen(symbolsArray); i++)
   {
      if(StringGetCharacter(symbolsArray, i) == ',')
         count++;
   }

   // If empty array
   if(StringLen(symbolsArray) < 2)
      count = 0;

   // Check if symbol list changed
   if(count != symbolCount)
   {
      Print("Symbol list changed! Old count: ", symbolCount, ", New count: ", count);
   }

   ArrayResize(subscribedSymbols, count);
   int oldSymbolCount = symbolCount;
   symbolCount = 0;

   if(count > 0)
   {
      // Parse each symbol
      string remaining = symbolsArray;
      while(StringLen(remaining) > 0)
      {
         int quoteStart = StringFind(remaining, "\"");
         if(quoteStart == -1) break;

         int quoteEnd = StringFind(remaining, "\"", quoteStart + 1);
         if(quoteEnd == -1) break;

         string symbol = StringSubstr(remaining, quoteStart + 1, quoteEnd - quoteStart - 1);

         // Check if this is a new symbol
         bool isNew = true;
         for(int i = 0; i < oldSymbolCount; i++)
         {
            if(subscribedSymbols[i] == symbol)
            {
               isNew = false;
               break;
            }
         }

         subscribedSymbols[symbolCount] = symbol;

         if(isNew)
         {
            Print("NEW SYMBOL ADDED: ", symbol);
            SendLog("INFO", "Symbol subscribed", StringFormat("New symbol added: %s", symbol));
            // Send symbol specifications for new symbol
            SendSymbolSpecForSymbol(symbol);
            // Send historical data for new symbol
            SendHistoricalDataForSymbol(symbol);
         }

         symbolCount++;
         remaining = StringSubstr(remaining, quoteEnd + 1);
      }
   }

   if(count != oldSymbolCount)
   {
      Print("Symbol list updated. Total subscribed symbols: ", symbolCount);
   }
}

//+------------------------------------------------------------------+
//| Send symbol specification for a single symbol                    |
//+------------------------------------------------------------------+
void SendSymbolSpecForSymbol(string symbol)
{
   if(apiKey == "")
   {
      Print("Cannot send symbol spec - no API key");
      return;
   }

   Print("Sending symbol specification for: ", symbol);

   // Build JSON for single symbol
   string specsJSON = StringFormat(
      "[{\"symbol\":\"%s\",\"volume_min\":%.2f,\"volume_max\":%.2f,\"volume_step\":%.2f,\"stops_level\":%d,\"freeze_level\":%d,\"trade_mode\":%d,\"digits\":%d,\"point_value\":%.10f}]",
      symbol,
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP),
      SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
      SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL),
      SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE),
      SymbolInfoInteger(symbol, SYMBOL_DIGITS),
      SymbolInfoDouble(symbol, SYMBOL_POINT)
   );

   // Prepare request
   string url = ServerURL + "/api/symbol_specs";
   string headers = "Content-Type: application/json\r\nX-API-Key: " + apiKey + "\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"symbols\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      specsJSON
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   ResetLastError();
   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      Print("Symbol specification sent successfully for ", symbol);
   }
   else
   {
      Print("Failed to send symbol specification for ", symbol, " - HTTP ", res);
   }
}

//+------------------------------------------------------------------+
//| Send historical data for a single symbol (all timeframes)        |
//+------------------------------------------------------------------+
void SendHistoricalDataForSymbol(string symbol)
{
   Print("Sending historical data for new symbol: ", symbol);

   ENUM_TIMEFRAMES timeframes[] = {PERIOD_H1, PERIOD_H4};
   int barCounts[] = {168, 84};  // H1:7d, H4:14d - optimized for auto-optimization system

   for(int t = 0; t < ArraySize(timeframes); t++)
   {
      SendHistoricalData(symbol, timeframes[t], barCounts[t]);
      Sleep(100);  // Small delay to avoid overwhelming server
   }

   Print("Historical data sent for: ", symbol);
}

//+------------------------------------------------------------------+
//| Load subscribed symbols from server                              |
//+------------------------------------------------------------------+
void LoadSubscribedSymbols()
{
   if(apiKey == "")
   {
      Print("No API key available, cannot load symbols");
      return;
   }

   string url = ServerURL + "/api/symbols";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\"}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   ResetLastError();
   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      string response = CharArrayToString(result);
      Print("Symbols response: ", response);

      // Parse symbols array from JSON
      // Simple parser for symbols array: ["EURUSD","GBPUSD","USDJPY"]
      int symbolsPos = StringFind(response, "\"symbols\":[");
      if(symbolsPos >= 0)
      {
         int startPos = symbolsPos + 11; // Position after "symbols":[
         int endPos = StringFind(response, "]", startPos);
         string symbolsArray = StringSubstr(response, startPos, endPos - startPos);

         // Count symbols
         int count = 1;
         for(int i = 0; i < StringLen(symbolsArray); i++)
         {
            if(StringGetCharacter(symbolsArray, i) == ',')
               count++;
         }

         // If empty array
         if(StringLen(symbolsArray) < 2)
            count = 0;

         ArrayResize(subscribedSymbols, count);
         symbolCount = 0;

         if(count > 0)
         {
            // Parse each symbol
            string remaining = symbolsArray;
            while(StringLen(remaining) > 0)
            {
               int quoteStart = StringFind(remaining, "\"");
               if(quoteStart == -1) break;

               int quoteEnd = StringFind(remaining, "\"", quoteStart + 1);
               if(quoteEnd == -1) break;

               string symbol = StringSubstr(remaining, quoteStart + 1, quoteEnd - quoteStart - 1);
               subscribedSymbols[symbolCount] = symbol;
               Print("Loaded subscribed symbol: ", symbol);
               symbolCount++;

               remaining = StringSubstr(remaining, quoteEnd + 1);
            }
         }

         Print("Total subscribed symbols loaded: ", symbolCount);
      }
   }
   else
   {
      Print("Failed to load symbols from server, code: ", res);
      Print("Error: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Check if symbol is subscribed                                    |
//+------------------------------------------------------------------+
bool IsSymbolSubscribed(string symbol)
{
   for(int i = 0; i < symbolCount; i++)
   {
      if(subscribedSymbols[i] == symbol)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check if symbol is currently tradeable (within trading hours)    |
//+------------------------------------------------------------------+
bool IsSymbolTradeable(string symbol)
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   // Get symbol type to determine market hours
   string symbolType = "";
   if(StringFind(symbol, "BTC") >= 0 || StringFind(symbol, "ETH") >= 0 ||
      StringFind(symbol, "XRP") >= 0 || StringFind(symbol, "LTC") >= 0)
   {
      symbolType = "CRYPTO";
   }
   else if(StringFind(symbol, "USD") >= 0 || StringFind(symbol, "EUR") >= 0 ||
           StringFind(symbol, "GBP") >= 0 || StringFind(symbol, "JPY") >= 0 ||
           StringFind(symbol, "CHF") >= 0 || StringFind(symbol, "AUD") >= 0 ||
           StringFind(symbol, "CAD") >= 0 || StringFind(symbol, "NZD") >= 0)
   {
      symbolType = "FOREX";
   }
   else if(StringFind(symbol, "XAU") >= 0 || StringFind(symbol, "XAG") >= 0)
   {
      symbolType = "METAL";
   }
   else
   {
      symbolType = "OTHER";
   }

   // Crypto markets are 24/7
   if(symbolType == "CRYPTO")
   {
      return true;
   }

   // Forex markets are closed on weekends (Saturday and Sunday)
   if(symbolType == "FOREX")
   {
      // Saturday (6) and Sunday (0) are closed
      if(dt.day_of_week == 0 || dt.day_of_week == 6)
      {
         return false;
      }

      // Friday after 22:00 GMT is considered closed (weekend starts)
      if(dt.day_of_week == 5 && dt.hour >= 22)
      {
         return false;
      }

      // Sunday before 22:00 GMT is considered closed (weekend not over)
      if(dt.day_of_week == 0 && dt.hour < 22)
      {
         return false;
      }
   }

   // Check trade session for current weekday
   datetime from, to;
   if(SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)dt.day_of_week, 0, from, to))
   {
      datetime now = TimeCurrent();
      return (now >= from && now <= to);
   }

   return false;
}

//+------------------------------------------------------------------+
//| Add tick to buffer                                               |
//+------------------------------------------------------------------+
void AddTickToBuffer(string symbol, MqlTick &tick)
{
   int newSize = tickBufferCount + 1;
   ArrayResize(tickBuffer, newSize);

   tickBuffer[tickBufferCount].symbol = symbol;
   tickBuffer[tickBufferCount].bid = tick.bid;
   tickBuffer[tickBufferCount].ask = tick.ask;
   tickBuffer[tickBufferCount].volume = tick.volume;
   tickBuffer[tickBufferCount].timestamp = tick.time;
   tickBuffer[tickBufferCount].tradeable = IsSymbolTradeable(symbol);

   tickBufferCount++;
}

//+------------------------------------------------------------------+
//| Send tick batch to server                                        |
//+------------------------------------------------------------------+
void SendTickBatch()
{
   if(tickBufferCount == 0)
      return;

   string tickURL = "http://100.97.100.50:9901/api/ticks";  // Tick port
   string headers = "Content-Type: application/json\r\n";

   // Build JSON array of ticks
   string ticksJSON = "[";
   for(int i = 0; i < tickBufferCount; i++)
   {
      if(i > 0)
         ticksJSON += ",";

      double spread = tickBuffer[i].ask - tickBuffer[i].bid;

      ticksJSON += StringFormat(
         "{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread\":%.5f,\"volume\":%d,\"timestamp\":%d,\"tradeable\":%s}",
         tickBuffer[i].symbol,
         tickBuffer[i].bid,
         tickBuffer[i].ask,
         spread,
         tickBuffer[i].volume,
         tickBuffer[i].timestamp,
         tickBuffer[i].tradeable ? "true" : "false"
      );
   }
   ticksJSON += "]";

   // Build JSON array of open positions with MT5 profit values
   string positionsJSON = "[";
   int totalPositions = PositionsTotal();
   for(int i = 0; i < totalPositions; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(i > 0)
            positionsJSON += ",";

         double profit = PositionGetDouble(POSITION_PROFIT);
         double swap = PositionGetDouble(POSITION_SWAP);

         positionsJSON += StringFormat(
            "{\"ticket\":%llu,\"profit\":%.2f,\"swap\":%.2f}",
            ticket,
            profit,
            swap
         );
      }
   }
   positionsJSON += "]";

   // Send ALL account values in tick batches for real-time updates
   // Cached profit values are updated every 5 seconds to avoid performance issues
   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"ticks\":%s,\"positions\":%s,\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,\"profit_today\":%.2f,\"profit_week\":%.2f,\"profit_month\":%.2f,\"profit_year\":%.2f}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      ticksJSON,
      positionsJSON,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      cachedProfitToday,
      cachedProfitWeek,
      cachedProfitMonth,
      cachedProfitYear
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   int res = WebRequest(
      "POST",
      tickURL,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      // Clear buffer after successful send
      tickBufferCount = 0;
      ArrayResize(tickBuffer, 0);
   }
   else
   {
      Print("Tick batch send failed with code: ", res);
   }
}

//+------------------------------------------------------------------+
//| Send log message to server                                       |
//+------------------------------------------------------------------+
void SendLog(string level, string message, string details = "")
{
   if(apiKey == "" || !serverConnected)
      return;

   string logURL = "http://100.97.100.50:9903/api/log";  // Logging port
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"level\":\"%s\",\"message\":\"%s\",\"details\":{\"info\":\"%s\"}}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      level,
      message,
      details
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   WebRequest(
      "POST",
      logURL,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );
}

//+------------------------------------------------------------------+
//| Send trade update to Port 9902                                   |
//+------------------------------------------------------------------+
void SendTradeUpdate(ulong ticket, string action, string closeReason = "")
{
   if(apiKey == "" || !serverConnected)
      return;

   // Get position or history data
   string symbol = "";
   string direction = "";
   double volume = 0;
   double openPrice = 0;
   datetime openTime = 0;
   double closePrice = 0;
   datetime closeTime = 0;
   double sl = 0;
   double tp = 0;
   double profit = 0;
   double commission = 0;
   double swap = 0;
   string status = "";

   if(action == "OPEN" || action == "MODIFY")
   {
      // Get from open positions
      if(PositionSelectByTicket(ticket))
      {
         symbol = PositionGetString(POSITION_SYMBOL);
         direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
         volume = PositionGetDouble(POSITION_VOLUME);
         openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         openTime = (datetime)PositionGetInteger(POSITION_TIME);
         sl = PositionGetDouble(POSITION_SL);
         tp = PositionGetDouble(POSITION_TP);
         profit = PositionGetDouble(POSITION_PROFIT);
         swap = PositionGetDouble(POSITION_SWAP);

         // Get commission from deal history (not available directly from position)
         if(HistorySelectByPosition(ticket))
         {
            int totalDeals = HistoryDealsTotal();
            for(int i = 0; i < totalDeals; i++)
            {
               ulong dealTicket = HistoryDealGetTicket(i);
               if(HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID) == ticket)
               {
                  commission += HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
               }
            }
         }

         status = "open";
      }
   }
   else if(action == "CLOSE")
   {
      // Get from history
      if(HistorySelectByPosition(ticket))
      {
         int totalDeals = HistoryDealsTotal();

         // Find ENTRY_IN and ENTRY_OUT deals for this position
         for(int i = 0; i < totalDeals; i++)
         {
            ulong dealTicket = HistoryDealGetTicket(i);
            if(HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID) == ticket)
            {
               ENUM_DEAL_ENTRY dealEntry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);

               if(dealEntry == DEAL_ENTRY_IN)
               {
                  symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
                  ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE);
                  direction = (dealType == DEAL_TYPE_BUY) ? "BUY" : "SELL";
                  volume = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
                  openPrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
                  openTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
               }
               else if(dealEntry == DEAL_ENTRY_OUT)
               {
                  closePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
                  closeTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
                  profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
                  commission = HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
                  swap = HistoryDealGetDouble(dealTicket, DEAL_SWAP);
               }
            }
         }
         status = "closed";
      }
   }

   if(symbol == "")
   {
      Print("Could not retrieve trade data for ticket ", ticket);
      return;
   }

   // Build JSON
   string tradeURL = "http://100.97.100.50:9902/api/trades/update";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"ticket\":%llu,\"symbol\":\"%s\",\"direction\":\"%s\",\"volume\":%.2f,\"open_price\":%.5f,\"open_time\":%d,\"close_price\":%.5f,\"close_time\":%d,\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f,\"commission\":%.2f,\"swap\":%.2f,\"status\":\"%s\",\"source\":\"MT5\",\"close_reason\":\"%s\"}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      ticket,
      symbol,
      direction,
      volume,
      openPrice,
      openTime,
      closePrice,
      closeTime,
      sl,
      tp,
      profit,
      commission,
      swap,
      status,
      closeReason
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   int res = WebRequest(
      "POST",
      tradeURL,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      Print("Trade update sent successfully: ", action, " ticket ", ticket);
   }
   else
   {
      Print("Failed to send trade update for ticket ", ticket, " - HTTP ", res);
   }
}

//+------------------------------------------------------------------+
//| Detect close reason based on SL/TP vs close price               |
//+------------------------------------------------------------------+
string DetectCloseReason(ulong positionTicket, ulong dealTicket)
{
   // Find tracked position to get original SL/TP
   for(int i = 0; i < trackedPositionCount; i++)
   {
      if(trackedPositions[i].ticket == positionTicket)
      {
         double closePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
         double currentSL = trackedPositions[i].sl;
         double initialSL = trackedPositions[i].initialSL;
         double tp = trackedPositions[i].tp;
         long direction = trackedPositions[i].direction;
         string symbol = trackedPositions[i].symbol;
         bool slMoved = trackedPositions[i].slMoved;

         double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
         double tolerance = 10 * point;  // 10 points tolerance

         if(direction == POSITION_TYPE_BUY)
         {
            // BUY position
            if(tp > 0 && MathAbs(closePrice - tp) <= tolerance)
               return "TP_HIT";
            else if(currentSL > 0 && MathAbs(closePrice - currentSL) <= tolerance)
            {
               // Check if SL was moved in profit direction (trailing stop)
               if(slMoved && currentSL > initialSL)
                  return "TRAILING_STOP";
               else
                  return "SL_HIT";
            }
         }
         else
         {
            // SELL position
            if(tp > 0 && MathAbs(closePrice - tp) <= tolerance)
               return "TP_HIT";
            else if(currentSL > 0 && MathAbs(closePrice - currentSL) <= tolerance)
            {
               // Check if SL was moved in profit direction (trailing stop)
               if(slMoved && currentSL < initialSL)
                  return "TRAILING_STOP";
               else
                  return "SL_HIT";
            }
         }

         return "MANUAL";
      }
   }

   return "UNKNOWN";
}

//+------------------------------------------------------------------+
//| Track position for close reason detection                        |
//+------------------------------------------------------------------+
void TrackPosition(ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
      return;

   // Add to tracked positions
   int newSize = trackedPositionCount + 1;
   ArrayResize(trackedPositions, newSize);

   double currentSL = PositionGetDouble(POSITION_SL);

   trackedPositions[trackedPositionCount].ticket = ticket;
   trackedPositions[trackedPositionCount].openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
   trackedPositions[trackedPositionCount].sl = currentSL;
   trackedPositions[trackedPositionCount].tp = PositionGetDouble(POSITION_TP);
   trackedPositions[trackedPositionCount].volume = PositionGetDouble(POSITION_VOLUME);
   trackedPositions[trackedPositionCount].symbol = PositionGetString(POSITION_SYMBOL);
   trackedPositions[trackedPositionCount].direction = PositionGetInteger(POSITION_TYPE);
   trackedPositions[trackedPositionCount].initialSL = currentSL;  // Store initial SL
   trackedPositions[trackedPositionCount].slMoved = false;

   trackedPositionCount++;

   Print("Tracking position ", ticket, " SL:", trackedPositions[trackedPositionCount-1].sl, " TP:", trackedPositions[trackedPositionCount-1].tp);
}

//+------------------------------------------------------------------+
//| Update tracked position (when SL/TP modified)                    |
//+------------------------------------------------------------------+
void UpdateTrackedPosition(ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
      return;

   double newSL = PositionGetDouble(POSITION_SL);
   long direction = PositionGetInteger(POSITION_TYPE);

   for(int i = 0; i < trackedPositionCount; i++)
   {
      if(trackedPositions[i].ticket == ticket)
      {
         double oldSL = trackedPositions[i].sl;

         // Check if SL moved in profit direction
         if(direction == POSITION_TYPE_BUY && newSL > oldSL)
         {
            trackedPositions[i].slMoved = true;  // SL moved up (profit direction for BUY)
         }
         else if(direction == POSITION_TYPE_SELL && newSL < oldSL && newSL > 0)
         {
            trackedPositions[i].slMoved = true;  // SL moved down (profit direction for SELL)
         }

         trackedPositions[i].sl = newSL;
         trackedPositions[i].tp = PositionGetDouble(POSITION_TP);

         Print("Updated tracked position ", ticket, " SL:", trackedPositions[i].sl, " TP:", trackedPositions[i].tp,
               " SL moved in profit: ", trackedPositions[i].slMoved);
         return;
      }
   }
}

//+------------------------------------------------------------------+
//| Remove position from tracking                                    |
//+------------------------------------------------------------------+
void UntrackPosition(ulong ticket)
{
   for(int i = 0; i < trackedPositionCount; i++)
   {
      if(trackedPositions[i].ticket == ticket)
      {
         // Shift remaining elements
         for(int j = i; j < trackedPositionCount - 1; j++)
         {
            trackedPositions[j] = trackedPositions[j + 1];
         }

         trackedPositionCount--;
         ArrayResize(trackedPositions, trackedPositionCount);

         Print("Untracked position ", ticket);
         return;
      }
   }
}

//+------------------------------------------------------------------+
//| Sync all open positions to server (periodic)                     |
//+------------------------------------------------------------------+
void SyncAllPositions()
{
   if(apiKey == "" || !serverConnected)
      return;

   int totalPositions = PositionsTotal();

   Print("Syncing ", totalPositions, " open positions to server...");

   for(int i = 0; i < totalPositions; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         SendTradeUpdate(ticket, "OPEN");
      }
   }
}

//+------------------------------------------------------------------+
//| Check for account transactions (deposits, withdrawals, etc.)     |
//+------------------------------------------------------------------+
void CheckAccountTransactions()
{
   if(!serverConnected || apiKey == "")
      return;

   // Select history from last check to now
   if(!HistorySelect(lastTransactionCheck, TimeCurrent()))
   {
      Print("Failed to select transaction history");
      return;
   }

   int totalDeals = HistoryDealsTotal();

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket <= 0)
         continue;

      // Get deal type
      ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);

      // Check if this is a non-trading operation
      bool isTransaction = false;
      string transactionType = "";

      // Only check for deal types that exist in MT5
      switch(dealType)
      {
         case DEAL_TYPE_BALANCE:
            transactionType = "BALANCE";
            isTransaction = true;
            break;
         case DEAL_TYPE_CREDIT:
            transactionType = "CREDIT";
            isTransaction = true;
            break;
         case DEAL_TYPE_CHARGE:
            transactionType = "CHARGE";
            isTransaction = true;
            break;
         case DEAL_TYPE_CORRECTION:
            transactionType = "CORRECTION";
            isTransaction = true;
            break;
         case DEAL_TYPE_BONUS:
            transactionType = "BONUS";
            isTransaction = true;
            break;
         case DEAL_TYPE_COMMISSION:
            transactionType = "COMMISSION";
            isTransaction = true;
            break;
         case DEAL_TYPE_COMMISSION_DAILY:
            transactionType = "COMMISSION_DAILY";
            isTransaction = true;
            break;
         case DEAL_TYPE_COMMISSION_MONTHLY:
            transactionType = "COMMISSION_MONTHLY";
            isTransaction = true;
            break;
         case DEAL_TYPE_INTEREST:
            transactionType = "INTEREST";
            isTransaction = true;
            break;
      }

      if(isTransaction)
      {
         // Get transaction details
         double amount = HistoryDealGetDouble(ticket, DEAL_PROFIT);
         datetime time = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
         string comment = HistoryDealGetString(ticket, DEAL_COMMENT);

         // Send to server
         SendTransactionToServer(ticket, transactionType, amount, time, comment);

         Print("Transaction detected: ", transactionType, " ", amount, " at ", TimeToString(time));
      }
   }

   // Update last check time
   lastTransactionCheck = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Send transaction to server                                       |
//+------------------------------------------------------------------+
void SendTransactionToServer(ulong ticket, string transType, double amount, datetime timestamp, string comment)
{
   string url = ServerURL + "/api/transaction";
   string headers = "Content-Type: application/json\r\n";

   string jsonData = StringFormat(
      "{\"account\":%d,\"api_key\":\"%s\",\"ticket\":%llu,\"transaction_type\":\"%s\",\"amount\":%.2f,\"timestamp\":%d,\"comment\":\"%s\",\"balance\":%.2f}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      apiKey,
      ticket,
      transType,
      amount,
      timestamp,
      comment,
      AccountInfoDouble(ACCOUNT_BALANCE)
   );

   char post[];
   char result[];
   string resultHeaders;

   ArrayResize(post, StringToCharArray(jsonData, post, 0, WHOLE_ARRAY) - 1);

   int res = WebRequest(
      "POST",
      url,
      headers,
      ConnectionTimeout,
      post,
      result,
      resultHeaders
   );

   if(res == 200)
   {
      Print("Transaction sent to server: ", transType, " ", amount);
   }
   else
   {
      Print("Failed to send transaction to server: ", res);
   }
}

//+------------------------------------------------------------------+
//| Get human-readable error description                             |
//+------------------------------------------------------------------+
string ErrorDescription(int errorCode)
{
   string error = "";

   switch(errorCode)
   {
      case 0:     error = "Success"; break;
      case 4:     error = "Trade server is busy"; break;
      case 6:     error = "Request rejected"; break;
      case 8:     error = "Order placed"; break;
      case 9:     error = "Request completed"; break;
      case 10:    error = "Request partial fill"; break;
      case 11:    error = "Request processing error"; break;
      case 10004: error = "Requote"; break;
      case 10006: error = "Request rejected"; break;
      case 10007: error = "Request canceled"; break;
      case 10008: error = "Order placed"; break;
      case 10009: error = "Request completed"; break;
      case 10010: error = "Request partial fill"; break;
      case 10011: error = "Request processing error"; break;
      case 10012: error = "Request canceled due to timeout"; break;
      case 10013: error = "Invalid request"; break;
      case 10014: error = "Invalid volume in request"; break;
      case 10015: error = "Invalid price in request"; break;
      case 10016: error = "Invalid stops in request"; break;
      case 10017: error = "Trade disabled"; break;
      case 10018: error = "Market closed"; break;
      case 10019: error = "Not enough money"; break;
      case 10020: error = "Prices changed"; break;
      case 10021: error = "No quotes"; break;
      case 10022: error = "Invalid order expiration"; break;
      case 10023: error = "Order state changed"; break;
      case 10024: error = "Too many requests"; break;
      case 10025: error = "No changes in request"; break;
      case 10026: error = "Autotrading disabled by server"; break;
      case 10027: error = "Autotrading disabled by client"; break;
      case 10028: error = "Request locked for processing"; break;
      case 10029: error = "Order or position frozen"; break;
      case 10030: error = "Invalid fill type"; break;
      case 10031: error = "No connection"; break;
      case 10032: error = "Operation allowed only for live accounts"; break;
      case 10033: error = "Number of pending orders limit reached"; break;
      case 10034: error = "Volume limit reached"; break;
      case 10035: error = "Invalid or prohibited order type"; break;
      case 10036: error = "Position with specified ID already closed"; break;
      case 4756:  error = "Invalid filling mode / Wrong request structure"; break;
      case 4753:  error = "Order sending function not found"; break;
      case 4754:  error = "Function cannot be called"; break;
      default:    error = "Unknown error"; break;
   }

   return error;
}

//+------------------------------------------------------------------+
//| Disconnect from server                                           |
//+------------------------------------------------------------------+
void DisconnectFromServer()
{
   SendLog("INFO", "EA disconnecting", "Normal shutdown");
   Print("Disconnected from server");
}
//+------------------------------------------------------------------+

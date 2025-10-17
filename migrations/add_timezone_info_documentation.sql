-- Timezone Documentation for ngTradingBot Database
-- =================================================
--
-- CRITICAL INFORMATION FOR DATABASE TIMESTAMPS:
--
-- 1. ALL DATETIME COLUMNS IN DATABASE ARE STORED AS UTC (without timezone info)
--    - This is naive UTC (no tzinfo in Python)
--    - PostgreSQL TIMESTAMP WITHOUT TIME ZONE type
--    - Always assumed to be UTC when reading
--
-- 2. BROKER/MT5 TIMESTAMPS:
--    - Broker sends timestamps in EET (Eastern European Time = UTC+2 or UTC+3 with DST)
--    - Python code converts broker timestamps to UTC before storing in DB
--    - When sending to MT5, convert back from UTC to EET
--
-- 3. TIMEZONE CONVERSIONS:
--    - Use timezone_manager.py for all conversions
--    - Server time = UTC
--    - Broker time = EET/EEST (Europe/Bucharest timezone)
--    - Trading sessions defined in UTC
--
-- 4. IMPORTANT TABLES WITH TIMESTAMPS:
--    - trades.open_time: UTC (when trade was opened)
--    - trades.close_time: UTC (when trade was closed)
--    - trading_signals.created_at: UTC (when signal was generated)
--    - ticks.timestamp: UTC (when tick was received from broker)
--    - commands.created_at: UTC (when command was created)
--    - commands.timeout_at: UTC (when command expires)
--
-- 5. SESSION TIMES (in UTC):
--    - ASIAN: 00:00-08:00 UTC
--    - LONDON: 08:00-16:00 UTC  
--    - OVERLAP: 13:00-16:00 UTC (London + US)
--    - US: 13:00-22:00 UTC
--    - AFTER_HOURS: 22:00-00:00 UTC
--
-- 6. DEBUGGING TIMEZONE ISSUES:
--    - Check logs for "[UTC: ... | Broker: ... EET]" format
--    - Verify timezone_manager.py is being used
--    - Confirm MT5 EA sends correct timestamps
--    - Test with: SELECT NOW() AS server_time, NOW() AT TIME ZONE 'UTC' AS utc_time;
--
-- NO MIGRATION NEEDED - This is documentation only
--
-- To verify database timezone:
SELECT 
    current_setting('TIMEZONE') AS db_timezone,
    NOW() AS current_timestamp,
    NOW() AT TIME ZONE 'UTC' AS utc_timestamp,
    NOW() AT TIME ZONE 'Europe/Bucharest' AS broker_timestamp;

-- To check a sample of timestamps from trades table:
-- SELECT 
--     symbol,
--     open_time,
--     open_time AT TIME ZONE 'UTC' AS utc_time,
--     open_time AT TIME ZONE 'Europe/Bucharest' AS broker_time
-- FROM trades
-- WHERE status = 'open'
-- LIMIT 5;

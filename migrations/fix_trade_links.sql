-- Fix trade links to commands and signals
-- Step 1: Link trades to commands based on matching ticket numbers
UPDATE trades t
SET
    command_id = c.id,
    signal_id = (c.payload->>'signal_id')::integer,
    source = 'autotrade'
FROM commands c
WHERE
    t.ticket = (c.response->>'ticket')::integer
    AND c.command_type = 'OPEN_TRADE'
    AND c.status = 'completed'
    AND t.command_id IS NULL
    AND t.account_id = 3;

-- Step 2: Update entry_reason for trades that now have signal_ids
UPDATE trades t
SET entry_reason =
    COALESCE(
        (SELECT
            CASE
                WHEN s.confidence IS NOT NULL AND s.timeframe IS NOT NULL
                THEN CONCAT(ROUND(s.confidence * 100)::text, '% confidence | ', s.timeframe, ' timeframe')
                WHEN s.confidence IS NOT NULL
                THEN CONCAT(ROUND(s.confidence * 100)::text, '% confidence')
                WHEN s.timeframe IS NOT NULL
                THEN CONCAT(s.timeframe, ' timeframe')
                ELSE 'Auto-trade signal'
            END
         FROM trading_signals s
         WHERE s.id = t.signal_id),
        'Auto-trade (signal linked)'
    )
WHERE
    t.signal_id IS NOT NULL
    AND t.entry_reason = 'Manual trade (MT5)'
    AND t.account_id = 3;

-- Step 3: Update timeframe for trades from their linked signals
UPDATE trades t
SET timeframe = s.timeframe
FROM trading_signals s
WHERE
    t.signal_id = s.id
    AND t.timeframe IS NULL
    AND s.timeframe IS NOT NULL
    AND t.account_id = 3;

-- Show results
SELECT 'Trades linked to commands:' as description, COUNT(*) as count
FROM trades
WHERE command_id IS NOT NULL AND account_id = 3
UNION ALL
SELECT 'Trades with signals:', COUNT(*)
FROM trades
WHERE signal_id IS NOT NULL AND account_id = 3
UNION ALL
SELECT 'Trades with auto-trade entry reason:', COUNT(*)
FROM trades
WHERE entry_reason NOT LIKE 'Manual trade%' AND account_id = 3
UNION ALL
SELECT 'Trades with timeframe:', COUNT(*)
FROM trades
WHERE timeframe IS NOT NULL AND account_id = 3;
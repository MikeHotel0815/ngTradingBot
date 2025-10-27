#!/bin/bash

echo "===================================================================================================="
echo "📊 HANDELSWOCHE-ANALYSE (letzte 7 Tage) - MIT AKTUELLEN FEATURES & PARAMETERN"
echo "===================================================================================================="
echo ""

echo "📈 PERFORMANCE PRO SYMBOL:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    symbol AS \"Symbol\",
    COUNT(*) as \"Trades\",
    COUNT(*) FILTER (WHERE profit > 0) || '/' || COUNT(*) FILTER (WHERE profit <= 0) as \"W/L\",
    ROUND(AVG(CASE WHEN profit > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as \"WR%\",
    ROUND(SUM(profit)::numeric, 2) as \"P/L (EUR)\",
    ROUND(AVG(profit)::numeric, 2) as \"Avg\",
    ROUND(MAX(profit)::numeric, 2) as \"Best\",
    ROUND(MIN(profit)::numeric, 2) as \"Worst\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days'
GROUP BY symbol
ORDER BY SUM(profit) DESC;
"

echo ""
echo "💹 RISK/REWARD & PROFIT FACTOR:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    symbol AS \"Symbol\",
    ROUND(AVG(CASE WHEN profit > 0 THEN profit END)::numeric, 2) as \"Avg Win\",
    ROUND(AVG(CASE WHEN profit <= 0 THEN profit END)::numeric, 2) as \"Avg Loss\",
    ROUND(
        ABS(AVG(CASE WHEN profit > 0 THEN profit END)::numeric /
        NULLIF(AVG(CASE WHEN profit <= 0 THEN profit END)::numeric, 0)), 2
    ) as \"R/R\",
    ROUND(
        SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END)::numeric /
        NULLIF(ABS(SUM(CASE WHEN profit <= 0 THEN profit ELSE 0 END))::numeric, 0), 2
    ) as \"PF\",
    ROUND(AVG(hold_duration_minutes)::numeric / 60, 1) as \"Avg h\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days'
GROUP BY symbol
ORDER BY SUM(profit) DESC;
"

echo ""
echo "📅 TÄGLICHE PERFORMANCE:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    DATE(close_time) as \"Datum\",
    COUNT(*) as \"Trades\",
    ROUND(SUM(profit)::numeric, 2) as \"P/L (EUR)\",
    ROUND(AVG(CASE WHEN profit > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as \"WR%\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days'
GROUP BY DATE(close_time)
ORDER BY DATE(close_time) DESC;
"

echo ""
echo "💰 GESAMTBILANZ:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    COUNT(*) as \"Trades\",
    COUNT(*) FILTER (WHERE profit > 0) as \"Wins\",
    COUNT(*) FILTER (WHERE profit <= 0) as \"Losses\",
    ROUND(AVG(CASE WHEN profit > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as \"WR%\",
    ROUND(SUM(profit)::numeric, 2) as \"Realisiert (EUR)\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days';
"

echo ""
echo "📊 OFFENE POSITIONEN:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    symbol AS \"Symbol\",
    COUNT(*) as \"Anzahl\",
    ROUND(SUM(current_profit)::numeric, 2) as \"Unrealisiert (EUR)\"
FROM trades
WHERE status = 'open'
GROUP BY symbol
UNION ALL
SELECT
    'GESAMT' AS symbol,
    COUNT(*),
    ROUND(SUM(current_profit)::numeric, 2)
FROM trades
WHERE status = 'open';
"

echo ""
echo "🛡️  STOP-LOSS ENFORCEMENT CHECK:"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    symbol AS \"Symbol\",
    COUNT(*) as \"Trades\",
    COUNT(*) FILTER (WHERE stop_loss IS NOT NULL AND stop_loss != 0) as \"Mit SL\",
    COUNT(*) FILTER (WHERE stop_loss IS NULL OR stop_loss = 0) as \"Ohne SL\",
    ROUND(AVG(CASE WHEN stop_loss IS NOT NULL AND stop_loss != 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as \"SL Rate%\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days'
GROUP BY symbol
ORDER BY COUNT(*) DESC;
"

echo ""
echo "🔍 PROBLEM-SYMBOLE (Hohe Verluste):"
echo "----------------------------------------------------------------------------------------------------"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT
    symbol AS \"Symbol\",
    COUNT(*) FILTER (WHERE profit < -5) as \"Große Verluste (>5 EUR)\",
    ROUND(MIN(profit)::numeric, 2) as \"Schlimmster Trade\",
    close_reason AS \"Grund\"
FROM trades
WHERE status = 'closed'
AND close_time >= NOW() - INTERVAL '7 days'
AND profit < -5
GROUP BY symbol, close_reason
ORDER BY MIN(profit) ASC
LIMIT 10;
"

echo ""
echo "===================================================================================================="

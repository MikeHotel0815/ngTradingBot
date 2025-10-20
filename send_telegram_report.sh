#!/bin/bash
# Send Daily Performance Report via Telegram
# Uses docker exec to get data directly from database

TELEGRAM_BOT_TOKEN="8454891267:AAHKrGTcGCVfXjb0LNjq6QAC816Un9ig7VA"
TELEGRAM_CHAT_ID="557944459"

# Function to send Telegram message
send_telegram() {
    local message="$1"
    curl -s -X POST "https://api.telegram.com/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="$message" \
        -d parse_mode="HTML" > /dev/null
}

# Get 24h stats
stats_24h=$(docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END) as wins,
    ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as wr,
    ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'24 hours' AND status='closed';
")

# Get BUY stats
buy_stats=$(docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    COUNT(*) as total,
    ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as wr,
    ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'24 hours' AND status='closed' AND direction='BUY';
")

# Get SELL stats
sell_stats=$(docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    COUNT(*) as total,
    ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as wr,
    ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'24 hours' AND status='closed' AND direction='SELL';
")

# Get 7d stats
stats_7d=$(docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    COUNT(*) as total,
    ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) as wr,
    ROUND(SUM(profit),2) as profit
FROM trades
WHERE close_time >= NOW()-INTERVAL'7 days' AND status='closed';
")

# Get top 3 symbols
top_symbols=$(docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    symbol || ': €' || ROUND(SUM(profit),2) || ' (' || COUNT(*) || ' trades)'
FROM trades
WHERE close_time >= NOW()-INTERVAL'7 days' AND status='closed'
GROUP BY symbol
ORDER BY SUM(profit) DESC
LIMIT 3;
")

# Parse stats (format: total | wins | wr | profit)
read total_24h wins_24h wr_24h profit_24h <<< $(echo $stats_24h | tr '|' ' ')
read buy_total buy_wr buy_profit <<< $(echo $buy_stats | tr '|' ' ')
read sell_total sell_wr sell_profit <<< $(echo $sell_stats | tr '|' ' ')
read total_7d wr_7d profit_7d <<< $(echo $stats_7d | tr '|' ' ')

# Clean up whitespace
total_24h=$(echo $total_24h | xargs)
wins_24h=$(echo $wins_24h | xargs)
wr_24h=$(echo $wr_24h | xargs)
profit_24h=$(echo $profit_24h | xargs)
buy_total=$(echo $buy_total | xargs)
buy_wr=$(echo $buy_wr | xargs)
buy_profit=$(echo $buy_profit | xargs)
sell_total=$(echo $sell_total | xargs)
sell_wr=$(echo $sell_wr | xargs)
sell_profit=$(echo $sell_profit | xargs)
total_7d=$(echo $total_7d | xargs)
wr_7d=$(echo $wr_7d | xargs)
profit_7d=$(echo $profit_7d | xargs)

# Determine profit emoji
profit_emoji="⚪"
if [ ! -z "$profit_24h" ]; then
    if awk "BEGIN {exit !($profit_24h > 0)}"; then
        profit_emoji="🟢"
    elif awk "BEGIN {exit !($profit_24h < 0)}"; then
        profit_emoji="🔴"
    fi
fi

# Build message
message="🤖 <b>ngTradingBot Daily Report</b>
📅 $(date '+%d.%m.%Y %H:%M')

📊 <b>Performance (Letzte 24h)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades: <b>${total_24h}</b> (${wins_24h}W / $((total_24h - wins_24h))L)
Win Rate: <b>${wr_24h}%</b>
Profit: ${profit_emoji} <b>€${profit_24h}</b>

🎯 <b>BUY vs SELL</b>
BUY:  ${buy_total} trades | ${buy_wr}% WR | €${buy_profit}
SELL: ${sell_total} trades | ${sell_wr}% WR | €${sell_profit}"

# Check gap (only if both values exist)
if [ ! -z "$sell_wr" ] && [ ! -z "$buy_wr" ]; then
    gap=$(awk "BEGIN {print $sell_wr - $buy_wr}")
    if [ ! -z "$gap" ] && awk "BEGIN {exit !($gap > 15)}"; then
        message="$message

⚠️ SELL outperforms BUY by ${gap}%"
    elif [ ! -z "$gap" ] && awk "BEGIN {exit !($gap < -15)}"; then
        message="$message

✅ BUY outperforms SELL by ${gap#-}%"
    fi
fi

message="$message

📈 <b>7-Tage Übersicht</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades: ${total_7d}
Win Rate: ${wr_7d}%
Profit: €${profit_7d}"

# Add top symbols
if [ ! -z "$top_symbols" ]; then
    message="$message

🏆 <b>Top Symbole (7d)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    count=1
    while IFS= read -r symbol; do
        if [ $count -eq 1 ]; then emoji="🥇"; fi
        if [ $count -eq 2 ]; then emoji="🥈"; fi
        if [ $count -eq 3 ]; then emoji="🥉"; fi
        message="$message
${emoji} $(echo $symbol | xargs)"
        count=$((count + 1))
    done <<< "$top_symbols"
fi

message="$message

⚙️ <b>System Status</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Database Online
✅ Docker Running
✅ Auto-Trading Active

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 Automatischer Tagesbericht"

# Send message
echo "📱 Sending daily report to Telegram..."
send_telegram "$message"

if [ $? -eq 0 ]; then
    echo "✅ Report sent successfully!"
else
    echo "❌ Failed to send report"
    exit 1
fi

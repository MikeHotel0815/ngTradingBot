# Telegram Notifications Setup

## ✨ Features

The ngTradingBot now includes Telegram notifications for:

- 🚨 **MT5 Connection Lost** - Alerts when MT5 stops responding
- ✅ **Connection Restored** - Notifies when MT5 comes back online
- ⚠️ **Data Flow Problems** - Alerts if tick data stops flowing
- 🔄 **Auto-Trading Status** - Notifications when auto-trading is paused/resumed
- 📊 **Trade Alerts** - Optional notifications for new trades (can be enabled)

## 📋 Setup Instructions

### Step 1: Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Start a chat and send: `/newbot`
3. Follow the instructions:
   - Choose a name for your bot (e.g., "My Trading Bot")
   - Choose a username (must end in 'bot', e.g., "mytrading_bot")
4. **Copy the BOT TOKEN** you receive (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Get Your Chat ID

**Method 1 (Easy):**
1. Search for **@userinfobot** in Telegram
2. Start a chat with it
3. It will send you your Chat ID (a number like `123456789`)

**Method 2 (Alternative):**
1. Start a chat with your bot (search for the username you created)
2. Send any message to your bot
3. Open this URL in your browser (replace `<YOUR_BOT_TOKEN>`):
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
4. Look for `"chat":{"id":123456789}` in the response

### Step 3: Configure the Bot

**Option A: Using .env file (Recommended)**

1. Edit the file `/projects/ngTradingBot/.env.telegram`:
   ```bash
   nano /projects/ngTradingBot/.env.telegram
   ```

2. Replace the placeholders:
   ```bash
   TELEGRAM_BOT_TOKEN=your_actual_bot_token_here
   TELEGRAM_CHAT_ID=your_actual_chat_id_here
   ```

3. Load the environment variables:
   ```bash
   export $(cat /projects/ngTradingBot/.env.telegram | grep -v '^#' | xargs)
   ```

**Option B: Using docker-compose.yml**

1. Edit `/projects/ngTradingBot/docker-compose.yml`
2. Find the `server` service and add under `environment`:
   ```yaml
   - TELEGRAM_BOT_TOKEN=your_actual_bot_token_here
   - TELEGRAM_CHAT_ID=your_actual_chat_id_here
   ```

**Option C: Using system environment variables**

Add to your `~/.bashrc` or `~/.profile`:
```bash
export TELEGRAM_BOT_TOKEN="your_actual_bot_token_here"
export TELEGRAM_CHAT_ID="your_actual_chat_id_here"
```

### Step 4: Restart the Bot

```bash
cd /projects/ngTradingBot
docker-compose restart server
```

### Step 5: Test the Connection

```bash
cd /projects/ngTradingBot
python3 telegram_notifier.py
```

You should receive a test message in Telegram!

## 📱 What Notifications You'll Receive

### 🚨 Critical Alerts (With Sound)

**MT5 Connection Lost:**
```
⚠️ MT5 CONNECTION LOST

Account: #730630
Last Heartbeat: 2025-10-16 06:00:00
Offline for: 5 minutes

Actions taken:
• Auto-trading paused
• No new trades will be opened
• Existing trades continue to be monitored

Please check MT5 Terminal and EA status!
```

**Connection Restored:**
```
✅ MT5 CONNECTION RESTORED

Account: #730630
Offline duration: 5 minutes

Status:
• Connection re-established
• Receiving live data
• Auto-trading resumed

System back to normal operation.
```

### ℹ️ Info Notifications (Silent)

- Symbol data flow problems
- Trade opened/closed (if enabled)
- Daily performance summary (if enabled)

## 🔧 Advanced Configuration

### Customize Alert Thresholds

Edit `/projects/ngTradingBot/connection_watchdog.py`:

```python
self.heartbeat_timeout = 300  # Seconds before connection alert (default: 5 minutes)
self.tick_timeout = 180       # Seconds before data flow alert (default: 3 minutes)
self.check_interval = 60      # How often to check (default: 60 seconds)
```

### Enable Trade Notifications

In your trading code, add:

```python
from telegram_notifier import get_telegram_notifier

telegram = get_telegram_notifier()

# When opening a trade:
telegram.send_trade_alert({
    'symbol': 'EURUSD',
    'direction': 'BUY',
    'entry_price': 1.10500,
    'sl': 1.10300,
    'tp': 1.10800,
    'confidence': 75.5
})
```

### Disable Notifications Temporarily

Set environment variable:
```bash
export TELEGRAM_BOT_TOKEN=""
```

Or in code:
```python
telegram.enabled = False
```

## 🛠️ Troubleshooting

### "Telegram notifications DISABLED" in logs

**Cause:** Missing BOT_TOKEN or CHAT_ID

**Fix:** Make sure both environment variables are set correctly

### Not receiving messages

1. **Check bot token:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   ```

2. **Verify chat ID:**
   ```bash
   echo $TELEGRAM_CHAT_ID
   ```

3. **Test manually:**
   ```bash
   python3 telegram_notifier.py
   ```

4. **Check bot privacy settings:**
   - Make sure your bot can send messages to you
   - Start a conversation with your bot first

### Error: "Chat not found"

**Cause:** You haven't started a conversation with your bot yet

**Fix:** In Telegram, search for your bot and send `/start`

## 📊 Monitoring

Check if Connection Watchdog is running:

```bash
docker logs ngtradingbot_server --tail 100 | grep "Watchdog"
```

You should see:
```
🔍 Connection Watchdog started (monitors MT5 health)
```

## 🔐 Security Notes

- ⚠️ Keep your BOT_TOKEN secret! Don't share it or commit it to git
- ✅ Only you (via CHAT_ID) can receive messages from the bot
- ✅ The bot cannot be used by others without your CHAT_ID
- 🔒 Consider using a `.env` file and adding it to `.gitignore`

## 📞 Support

If you encounter issues, check the logs:

```bash
docker logs ngtradingbot_server --tail 200 | grep -i telegram
```

For more help, see the main README.md file.

---

**Created:** 2025-10-16
**Version:** 1.0
**Status:** ✅ Production Ready

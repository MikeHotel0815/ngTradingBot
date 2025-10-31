# Telegram Bot Setup - ngTradingBot

## Übersicht

Der ngTradingBot verfügt jetzt über einen interaktiven Telegram Bot, mit dem du Charts und Berichte direkt aus Telegram heraus anfordern kannst.

## Features

### Verfügbare Befehle

- **/start** - Zeigt das Hauptmenü mit Buttons
- **/charts** - Sendet alle 5 P/L Charts (1h, 12h, 24h, Woche, Jahr)
- **/report** - Sendet den täglichen Performance-Report
- **/help** - Zeigt die Hilfe

### Interaktive Buttons

Wenn du `/start` eingibst, erhältst du ein Menü mit Buttons:
- 📊 **P/L Charts** - Sendet alle Charts
- 📈 **Tagesbericht** - Sendet den 24h Report
- ❓ **Hilfe** - Zeigt verfügbare Befehle

## Setup-Anleitung

### 1. Bot-Befehle in Telegram registrieren

Öffne einen Chat mit deinem Bot in Telegram und sende:

```
/setcommands
```

Dann gib folgende Befehle ein:

```
start - Hauptmenü anzeigen
charts - P/L Charts senden
report - Tagesbericht senden
help - Hilfe anzeigen
```

### 2. Bot testen

Sende einfach einen der folgenden Befehle an deinen Bot:

- `/start` - Zeigt das Hauptmenü
- `/charts` - Lädt und sendet alle 5 P/L Charts

## Technische Details

### Container

- **Container Name**: `ngtradingbot_telegram_bot`
- **Port**: 9907
- **Image**: `ngtradingbot-telegram_bot`

### Bot-Status prüfen

```bash
# Container Status
docker ps | grep telegram_bot

# Logs anzeigen
docker logs ngtradingbot_telegram_bot --tail 50

# Health Check
curl http://localhost:9907/health
```

### Manueller Test

```bash
# /start Befehl testen
docker exec ngtradingbot_telegram_bot python3 -c "from telegram_bot import TelegramBot; bot = TelegramBot(); bot.handle_command('/start')"

# /charts Befehl testen
docker exec ngtradingbot_telegram_bot python3 -c "from telegram_bot import TelegramBot; bot = TelegramBot(); bot.handle_command('/charts')"

# /report Befehl testen
docker exec ngtradingbot_telegram_bot python3 -c "from telegram_bot import TelegramBot; bot = TelegramBot(); bot.handle_command('/report')"
```

## Webhook Setup (Optional)

Falls du einen öffentlichen Server hast und Webhook statt Polling nutzen möchtest:

```bash
# Webhook setzen
docker exec ngtradingbot_telegram_bot python3 /app/telegram_bot.py webhook https://yourdomain.com/webhook

# Webhook Info anzeigen
docker exec ngtradingbot_telegram_bot python3 /app/telegram_bot.py info
```

**Hinweis**: Für Webhook brauchst du:
- Einen öffentlich erreichbaren Server mit HTTPS
- Port 9907 muss von außen erreichbar sein
- Reverse Proxy (nginx/Caddy) mit SSL-Zertifikat

## Verwendung

### Charts anfordern

1. Öffne Telegram und gehe zu deinem Bot-Chat
2. Sende: `/charts`
3. Der Bot generiert und sendet alle 5 P/L Charts:
   - Letzte Stunde
   - Letzte 12 Stunden
   - Letzte 24 Stunden
   - Letzte Woche
   - Aktuelles Jahr (YTD)

### Tagesbericht anfordern

1. Sende: `/report`
2. Der Bot sendet einen detaillierten 24h Report mit:
   - Performance-Übersicht
   - BUY vs SELL Statistik
   - 7-Tage Zusammenfassung
   - Top Performer
   - System Status

## Troubleshooting

### Bot antwortet nicht

```bash
# Container Logs prüfen
docker logs ngtradingbot_telegram_bot --tail 100

# Container neu starten
docker compose restart telegram_bot
```

### Credentials nicht gefunden

```bash
# Environment Variables prüfen
docker exec ngtradingbot_telegram_bot env | grep TELEGRAM

# Sollte ausgeben:
# TELEGRAM_BOT_TOKEN=8454891267:AAHKrGTcGCVfXjb0LNjq6QAC816Un9ig7VA
# TELEGRAM_CHAT_ID=557944459
```

### Manuelle Tests schlagen fehl

```bash
# Test Command direkt im Container
docker exec -it ngtradingbot_telegram_bot python3 /app/telegram_bot.py test
```

## Architektur

```
Telegram User
     ↓
Telegram Bot API
     ↓
/webhook Endpoint (Port 9907)
     ↓
telegram_bot.py (Flask App)
     ↓
├── /start → _handle_start() → Menü mit Buttons
├── /charts → _handle_charts() → telegram_charts.py
└── /report → _handle_report() → telegram_daily_report.py
     ↓
Telegram User (Charts/Report)
```

## Dateistruktur

- `telegram_bot.py` - Hauptbot mit Flask Webhook Server
- `telegram_charts.py` - Chart-Generierung mit matplotlib
- `telegram_daily_report.py` - Tagesbericht-Generator
- `telegram_notifier.py` - Telegram API Client
- `docker-compose.yml` - Container-Konfiguration

## Automatische Reports

Der tägliche Report wird weiterhin automatisch um 23:00 Uhr gesendet (via `telegram_daily_worker`). Mit dem Bot kannst du Reports zusätzlich jederzeit manuell anfordern.

## Nächste Schritte

1. **Bot-Befehle registrieren**: Sende `/setcommands` an @BotFather
2. **Bot testen**: Sende `/start` an deinen Bot
3. **Charts anfordern**: Klicke auf "📊 P/L Charts" oder sende `/charts`

---

**Status**: ✅ Implementiert und getestet (2025-10-30)
**Container**: Running auf Port 9907
**Getestete Befehle**: /start, /charts, /report

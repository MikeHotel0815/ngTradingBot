# 📱 Telegram Reports - Quick Reference

## ⚡ Wichtigste Commands

```bash
# Report JETZT senden
/projects/ngTradingBot/send_telegram_report.sh

# Service Status
ps aux | grep start_monitoring.sh | grep -v grep

# Heutigen Log ansehen
cat /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log | tail -30
```

---

## ⏰ Zeitplan

**Automatischer Report:** Täglich um **8:00 Uhr** auf Telegram 📱

**Background Service:** Läuft mit PID 3228339

---

## ✅ Status Check

**Alles funktioniert wenn:**
- ✅ Service läuft (`ps aux | grep start_monitoring`)
- ✅ Docker DB läuft (`docker ps | grep ngtradingbot_db`)
- ✅ Manueller Test erfolgreich (`/projects/ngTradingBot/send_telegram_report.sh`)

---

## 📊 Was Du Bekommst

**Jeden Morgen Um 8:00 Uhr:**
- 24h Performance (Trades, WR, Profit)
- BUY vs SELL Vergleich
- 7-Tage Übersicht
- Top 3 Symbole
- System Status
- Automatische Warnungen

---

## 🔧 Quick Fixes

**Report kommt nicht?**
```bash
/projects/ngTradingBot/send_telegram_report.sh
```

**Service gestoppt?**
```bash
nohup /projects/ngTradingBot/start_monitoring.sh > /var/log/ngtradingbot/monitoring_service.log 2>&1 &
```

**Errors checken?**
```bash
tail -20 /var/log/ngtradingbot/errors.log
```

---

## 🎯 Files

| File | Location |
|------|----------|
| **Telegram Script** | `/projects/ngTradingBot/send_telegram_report.sh` |
| **Monitor Job** | `/projects/ngTradingBot/daily_monitor_job.sh` |
| **Background Service** | `/projects/ngTradingBot/start_monitoring.sh` |
| **Daily Logs** | `/var/log/ngtradingbot/daily_audit_*.log` |

---

## 📱 Bot Config

**Token:** `8454891267:AAHKrGTcGCVfXjb0LNjq6QAC816Un9ig7VA`
**Chat ID:** `557944459`

---

**Das War's! Morgen um 8:00 Uhr kommt dein erster automatischer Report! 🎉**

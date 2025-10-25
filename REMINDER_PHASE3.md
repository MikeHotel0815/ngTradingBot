# 📅 REMINDER: Phase 3 Analyse

## Wann melden?

**Datum:** 27. oder 28. Oktober 2025

**Zeitpunkt:** Beliebig (mindestens 48-72h nach 25.10.2025 15:16 UTC)

## Was sagen?

Öffne Claude Code und schreibe einfach:

```
Starte Phase 3 Analyse
```

Oder:

```
Zeige Phase 2 Status
```

Oder:

```
python check_phase_status.py
```

## Was passiert dann?

Ich werde:
1. ✅ Prüfen ob genug Daten gesammelt wurden (50-100 Trades)
2. 📊 Analysieren welche Sessions gut/schlecht performt haben
3. 🔍 Indicator-Korrelationen finden
4. 💡 Empfehlungen geben für:
   - Welche pausierten Symbole reaktivieren
   - Mit welchen Bedingungen (Session, Confidence, etc.)
   - Welche Risk-Multiplier verwenden
5. 🚀 Optional: Phase 4 Code implementieren

## Schnellcheck (ohne Claude)

```bash
# Auf dem Server:
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT COUNT(*) as total_trades
FROM trades
WHERE created_at > '2025-10-25 15:16:00'
  AND status = 'closed'
  AND session IS NOT NULL;
"

# Wenn total_trades >= 50 → BEREIT FÜR PHASE 3!
```

---

## Setup Auto-Reminder (Optional)

### Option A: Crontab (Linux/Mac)

```bash
# Öffne crontab
crontab -e

# Füge hinzu (prüft alle 6 Stunden):
0 */6 * * * cd /projects/ngTradingBot && python auto_notify_phase3.py

# Speichern und fertig!
```

### Option B: Windows Task Scheduler

1. Task Scheduler öffnen
2. "Create Basic Task"
3. Trigger: Daily, repeat every 6 hours
4. Action: Start Program
   - Program: `python`
   - Arguments: `/projects/ngTradingBot/auto_notify_phase3.py`
5. Fertig!

### Option C: Google Calendar

1. Neuer Termin: **27. Oktober 2025, 10:00**
2. Titel: "Trading Bot: Phase 3 Analyse starten"
3. Beschreibung: "Öffne Claude Code und sage: 'Starte Phase 3 Analyse'"
4. Benachrichtigung: 1 Tag vorher + am Tag selbst
5. Speichern!

---

## Kontakt-Methoden

**WICHTIG:** Ich (Claude) kann NICHT proaktiv Kontakt aufnehmen!

Du musst:
- ✅ Claude Code öffnen
- ✅ Mich ansprechen
- ✅ "Starte Phase 3" sagen

Dann läuft alles automatisch! 😊

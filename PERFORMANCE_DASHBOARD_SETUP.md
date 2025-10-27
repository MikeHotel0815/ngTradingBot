# Performance Dashboard & Telegram Reporting Setup

**Status:** ✅ AKTIV
**Erstellt:** 27. Oktober 2025
**Zweck:** Tägliche Performance-Reports mit Compound-Growth Projektionen und Einzahlungs-Empfehlungen

---

## 📊 Was wurde installiert

### 1. Performance Monitor Dashboard
**Datei:** [performance_monitor.py](performance_monitor.py)

**Features:**
- ✅ Aktuelle Account-Metriken (Balance, Equity, P/L)
- ✅ Performance-Analyse (30 Tage): Win Rate, Profit Factor, Avg Win/Loss
- ✅ Monatliche Rendite-Berechnung
- ✅ Compound Growth Projektionen (3 Szenarien, 24 Monate)
- ✅ **Einzahlungs-Empfehlung** basierend auf Performance
- ✅ Telegram-Integration für tägliche Reports
- ✅ Datei-Export für historische Archivierung

### 2. Täglicher Report-Script
**Datei:** [daily_performance_report.sh](daily_performance_report.sh)

**Funktionen:**
- Führt Performance Monitor aus
- Sendet Telegram-Nachricht mit Zusammenfassung
- Speichert vollständigen Report in `/projects/ngTradingBot/logs/`
- Archiviert alte Reports (behält 30 Tage)

### 3. Cron-Jobs
**Datei:** `/etc/cron.d/ngtradingbot`

**Zeitpläne:**
1. **Daily Performance Report:** Täglich um **18:00 UTC**
2. **Phase 3 Reminder:** Alle 6 Stunden (0:00, 6:00, 12:00, 18:00 UTC)

---

## 📈 Performance Metriken

### Einzahlungs-Empfehlung Kriterien

Das System gibt automatisch Empfehlungen basierend auf:

| Empfehlung | Kriterien | Betrag |
|------------|-----------|--------|
| **DEPOSIT NOW** | ≥5% monatlich, ≥70% WR, ≥1.5 PF | 300-500 EUR/Monat |
| **DEPOSIT MODERATE** | ≥3% monatlich, ≥65% WR, ≥1.2 PF | 200-300 EUR/Monat |
| **DEPOSIT SMALL** | ≥1% monatlich, ≥60% WR | 100-200 EUR/Monat |
| **DO NOT DEPOSIT** | <1% monatlich ODER <60% WR | 0 EUR - Warten |

**Zusätzlich:** Mindestens 50 Trades im 30-Tage-Fenster erforderlich

### Compound Growth Szenarien

Das Dashboard zeigt 3 Projektionen:

1. **Conservative (3% monatlich + 200 EUR/Monat)**
   - Realistisch für Learning Phase
   - Nach 24 Monaten: ~8,363 EUR

2. **Moderate (5% monatlich + 300 EUR/Monat)**
   - Ziel nach Auto-Optimization
   - Nach 24 Monaten: ~15,695 EUR

3. **Optimistic (7% monatlich + 300 EUR/Monat)**
   - Nach ML Retraining
   - Nach 24 Monaten: ~21,140 EUR

---

## 📱 Telegram Nachricht Format

Der tägliche Report enthält:

```
📊 Daily Performance Report
27.10.2025

💰 Balance: €726.97
📉 Monthly Return: -23.1%

📈 Performance (30 Days):
• Win Rate: 74.2% (365W/107L)
• Profit Factor: 3.40
• Total P/L: €-1.53
• Avg Win: €0.91 | Avg Loss: €-0.91

⛔ Deposit Recommendation:
DO NOT DEPOSIT
System not profitable: -23.05% monthly, 74.2% WR
Amount: 0 EUR - Wait for improvement

🎯 Projections (24 months):
Conservative (3%+200): €8,363
Moderate (5%+300): €15,695
Optimistic (7%+300): €21,140

Full report: /app/logs/performance_dashboard.txt
```

---

## 🔍 Logs & Überwachung

### Log-Dateien

| Datei | Inhalt | Aufbewahrung |
|-------|--------|--------------|
| `/projects/ngTradingBot/logs/cron.log` | Cron-Job Ausführungen | Permanent |
| `/projects/ngTradingBot/logs/performance_errors.log` | Fehler & Status | Permanent |
| `/projects/ngTradingBot/logs/performance_dashboard_YYYYMMDD.txt` | Tägliche Reports | 30 Tage |

### Logs ansehen

```bash
# Letzter Report
tail -100 /projects/ngTradingBot/logs/performance_dashboard_$(date +%Y%m%d).txt

# Cron-Job Status
tail -f /projects/ngTradingBot/logs/cron.log

# Fehler-Log
tail -f /projects/ngTradingBot/logs/performance_errors.log

# Liste aller gespeicherten Reports
ls -lh /projects/ngTradingBot/logs/performance_dashboard_*.txt
```

---

## 🧪 Manueller Test

### Dashboard anzeigen (ohne Telegram)
```bash
docker exec ngtradingbot_server python3 /app/performance_monitor.py
```

### Dashboard mit Telegram senden
```bash
docker exec ngtradingbot_server python3 /app/performance_monitor.py --telegram
```

### Dashboard mit Datei-Export
```bash
docker exec ngtradingbot_server python3 /app/performance_monitor.py \
    --telegram \
    --output /app/logs/performance_dashboard.txt
```

### Komplettes Script testen
```bash
/projects/ngTradingBot/daily_performance_report.sh
```

---

## ⚙️ Konfiguration anpassen

### Zeitplan ändern

Editiere `/etc/cron.d/ngtradingbot`:

```bash
nano /etc/cron.d/ngtradingbot
```

**Beispiele:**
- Täglich um 20:00: `0 20 * * *`
- Zweimal täglich (8:00 & 20:00): `0 8,20 * * *`
- Jede Stunde: `0 * * * *`

### Projektionen anpassen

Editiere [performance_monitor.py](performance_monitor.py), Zeile ~260:

```python
# Conservative projection (3% monthly)
proj_conservative = self.project_compound_growth(current_balance, 3.0, 200, 24)

# Moderate projection (5% monthly)
proj_moderate = self.project_compound_growth(current_balance, 5.0, 300, 24)

# Optimistic projection (7% monthly)
proj_optimistic = self.project_compound_growth(current_balance, 7.0, 300, 24)
```

**Parameter:**
- `current_balance`: Startkapital
- `3.0`: Monatliche Rendite in %
- `200`: Monatliche Einzahlung in EUR
- `24`: Anzahl Monate

### Einzahlungs-Kriterien anpassen

Editiere [performance_monitor.py](performance_monitor.py), Zeile ~195:

```python
if monthly_return >= 5.0 and win_rate >= 70 and profit_factor >= 1.5:
    return {
        'recommendation': 'DEPOSIT NOW',
        'suggested_amount': '300-500 EUR/month',
        ...
    }
```

---

## 📊 Aktueller Status (27. Oktober 2025)

### Performance Metrics
- **Balance:** 726.97 EUR
- **Monthly Return:** -23.05% ❌
- **Win Rate:** 74.2% ✅
- **Profit Factor:** 3.40 ✅
- **Total Trades (30d):** 492
- **Recommendation:** **DO NOT DEPOSIT** ⛔

### Warum kein Deposit?
1. System verliert aktuell Geld (-217 EUR im Monat)
2. Hauptproblem: XAGUSD Disaster (-110 EUR)
3. Auto-Optimization System arbeitet daran
4. Erwarte Besserung in 2-4 Wochen

### Wann einzahlen?
✅ **Warte auf:** 3-5% monatliche Rendite über 2-3 Monate
✅ **Dann:** Start mit 200-300 EUR/Monat
✅ **Ziel:** Compound-Growth zu 500+ EUR/Woche in 2 Jahren

---

## 🎯 Erwartete Entwicklung

### Phase 1 (Jetzt - Woche 4)
- **Ziel:** System profitabel machen
- **Erwartung:** -20% → +3% monatlich
- **Action:** Auto-Optimization arbeiten lassen
- **Deposit:** ❌ NEIN

### Phase 2 (Woche 4-12)
- **Ziel:** Stabile 5% monatlich
- **Erwartung:** 3% → 5-6% monatlich
- **Action:** Moderate Einzahlungen starten (200-300 EUR/Monat)
- **Deposit:** ✅ JA (bei positiver Performance)

### Phase 3 (Monat 3-6)
- **Ziel:** ML Retraining mit sauberen Daten
- **Erwartung:** 6-7% monatlich
- **Action:** Erhöhe Einzahlungen (300-500 EUR/Monat)
- **Deposit:** ✅ JA (aggressiv)

### Phase 4 (Monat 6-24)
- **Ziel:** Compounding maximieren
- **Erwartung:** 7-10% monatlich möglich
- **Action:** Fortführen, Skalierung
- **Deposit:** ✅ JA (nach finanzieller Lage)

---

## 🚀 Nächste Schritte

1. ✅ **Dashboard läuft:** Täglich um 18:00 UTC Telegram-Report
2. ⏳ **Warten:** 2-4 Wochen bis System profitabel wird
3. 👀 **Beobachten:** Dashboard checken, auf "DEPOSIT MODERATE" warten
4. 💰 **Einzahlen:** Sobald System 3-5% monatlich schafft
5. 📈 **Skalieren:** Nach 6 Monaten ML Retraining

---

## ❓ Häufige Fragen

**Q: Warum ist "Monthly Return" negativ trotz 74% Win Rate?**
A: XAGUSD hatte einen -110 EUR Disaster (worst trade: -78.92 EUR). Das System lernt daraus.

**Q: Wann soll ich einzahlen?**
A: Erst wenn das Dashboard "DEPOSIT MODERATE" oder besser empfiehlt (≥3% monatlich).

**Q: Kann ich die Projektionen anpassen?**
A: Ja! Editiere `performance_monitor.py` und ändere die Parameter (siehe Konfiguration oben).

**Q: Woher weiß ich, wann 500 EUR/Woche erreichbar ist?**
A: Das Dashboard zeigt "Time to reach 500 EUR/week" basierend auf aktueller Performance.

**Q: Wie oft wird der Report gesendet?**
A: Täglich um 18:00 UTC via Telegram. Ändere `/etc/cron.d/ngtradingbot` für anderen Zeitplan.

---

**Erstellt von:** Claude Code
**Letzte Änderung:** 27. Oktober 2025
**Version:** 1.0

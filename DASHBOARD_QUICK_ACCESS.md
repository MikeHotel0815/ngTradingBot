# Dashboard Quick Access Guide

**Letzte Aktualisierung:** 2025-10-27
**Status:** ✅ Alle Dashboards verfügbar

---

## 🚀 Dashboard-URLs

### ⚠️ WICHTIG: Unraid Netzwerk

Auf **Unraid-Systemen** ersetzen Sie `YOUR_UNRAID_IP` mit Ihrer tatsächlichen Server-IP-Adresse.

**So finden Sie Ihre IP:**
1. Unraid WebUI → Oben links im Dashboard
2. Command Line: `hostname -I | awk '{print $1}'`
3. Typische Beispiele: `192.168.1.100`, `10.0.0.50`, `unraid.local`

---

## 📱 Für Mobile Geräte (Smartphone/Tablet)

### Mobile Dashboard (Touch-optimiert)

```
http://YOUR_UNRAID_IP:9906/
```

**Features:**
- ✅ Touch-optimierte Bedienung
- ✅ Trading-Controls (Close Trade, Close All)
- ✅ Live Balance, Equity, P&L
- ✅ Open Positions mit Live P&L
- ✅ Symbol-Übersicht
- ✅ Auto-Refresh alle 15s
- ✅ Dark Theme

**Verwendung:**
- Trading unterwegs
- Schnelle Position-Checks
- Emergency Stop (Close All)
- Touch-freundliche UI

---

## 💻 Für Desktop/Laptop

### Main Dashboard (Alle Funktionen)

```
http://YOUR_UNRAID_IP:9905/
```

**Features:**
- ✅ Alle Trading-Controls
- ✅ OHLC Charts (Candlestick)
- ✅ Settings Management
- ✅ Signal Management
- ✅ Trade Analytics
- ✅ News Calendar
- ✅ AI Decision Log

**Verwendung:**
- Hauptarbeitsplatz für Trading
- Chart-Analyse
- Settings ändern
- Detaillierte Übersicht

---

### Unified Dashboard (Schnelle Übersicht)

```
http://YOUR_UNRAID_IP:9905/unified
```

**Features:**
- ✅ Live Balance & Equity
- ✅ Quick Stats
- ✅ Symbol-Tabelle
- ✅ Performance 24h
- ✅ System Health
- ❌ Keine Trading-Controls
- ❌ Keine Charts

**Verwendung:**
- Schneller Status-Check
- Überwachung ohne Trading
- Leichtgewichtig (41 KB)

---

## 📊 Dashboard-Vergleich

| Feature | Main Dashboard | Unified Dashboard | Mobile Dashboard |
|---------|----------------|-------------------|------------------|
| **Port** | 9905 | 9905 | 9906 |
| **Route** | `/` | `/unified` | `/` |
| **Trading Controls** | ✅ Umfangreich | ❌ Keine | ✅ Essential |
| **Charts** | ✅ OHLC Charts | ❌ Keine | ❌ Keine |
| **Settings** | ✅ Volle Config | ❌ Keine | ❌ Keine |
| **Touch-Optimiert** | ❌ Desktop | ❌ Desktop | ✅ Mobile |
| **Auto-Refresh** | ⚙️ Manuell | ✅ 15s | ✅ 15s |
| **Socket.IO** | ❌ Nein | ❌ Nein | ✅ Ja |
| **Size** | 358 KB | 41 KB | 35 KB |
| **Use Case** | Trading Station | Quick View | Mobile Trading |

---

## 🎯 Empfehlungen

### Für Desktop-Trader
➡️ **http://YOUR_UNRAID_IP:9905/**
- Alle Funktionen
- Charts und Analysen
- Settings Management

### Für Mobile-Trader
➡️ **http://YOUR_UNRAID_IP:9906/**
- Touch-optimierte Bedienung
- Trading-Controls verfügbar
- Unterwegs handeln

### Für schnelle Checks
➡️ **http://YOUR_UNRAID_IP:9905/unified**
- Leichtgewichtig
- Schnelles Laden
- Nur Monitoring

---

## 📱 Mobile Dashboard als App installieren (PWA)

### iOS (iPhone/iPad)

1. Safari öffnen
2. `http://YOUR_UNRAID_IP:9906/` aufrufen
3. **Teilen-Button** tippen (📤)
4. **"Zum Home-Bildschirm"** wählen
5. Name bestätigen → **"Hinzufügen"**

➡️ Dashboard erscheint als App-Icon auf dem Home-Screen!

### Android (Chrome/Edge)

1. Chrome/Edge öffnen
2. `http://YOUR_UNRAID_IP:9906/` aufrufen
3. **Menü** (⋮) → **"Zum Startbildschirm hinzufügen"**
4. Name bestätigen → **"Hinzufügen"**

➡️ Dashboard erscheint als App-Icon!

### Vorteile als App:
- ✅ Kein Browser-UI (Vollbild)
- ✅ Schneller Zugriff vom Home-Screen
- ✅ Sieht aus wie native App
- ✅ Push-Notifications (wenn implementiert)

---

## 🧪 Verbindung testen

### Test 1: Main Dashboard (Port 9905)
```bash
curl http://YOUR_UNRAID_IP:9905/ | grep "ngTradingBot Dashboard"
```
**Erwartet:** ✅ "ngTradingBot Dashboard" gefunden

### Test 2: Mobile Dashboard (Port 9906)
```bash
curl http://YOUR_UNRAID_IP:9906/ | grep "ngTradingBot Mobile"
```
**Erwartet:** ✅ "ngTradingBot Mobile" gefunden

### Test 3: Health Check (Port 9906)
```bash
curl http://YOUR_UNRAID_IP:9906/health
```
**Erwartet:**
```json
{"service":"ngTradingBot Dashboard","status":"healthy"}
```

---

## 🔧 Troubleshooting

### Problem: "Connection refused" oder "Timeout"

**Lösung 1: IP-Adresse prüfen**
```bash
# Von Unraid-Server aus:
hostname -I | awk '{print $1}'
```
Verwenden Sie diese IP in der URL.

**Lösung 2: Container prüfen**
```bash
docker ps --filter "name=ngtradingbot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```
Sollte zeigen:
- `ngtradingbot_server` (Port 9905)
- `ngtradingbot_dashboard` (Port 9906)

**Lösung 3: Firewall prüfen**
Stellen Sie sicher, dass Ports 9905 und 9906 in der Firewall freigegeben sind.

---

### Problem: Dashboard lädt, zeigt aber keine Daten

**Browser-Cache leeren:**
- **Chrome/Edge:** Ctrl+Shift+R (Windows) / Cmd+Shift+R (Mac)
- **Firefox:** Ctrl+F5 (Windows) / Cmd+Shift+R (Mac)
- **Safari:** Cmd+Option+R (Mac)

**Developer Console prüfen (F12):**
- Rote Fehler in der Console?
- Netzwerk-Tab: Zeigen API-Requests "200 OK"?

**Server-Logs prüfen:**
```bash
docker logs ngtradingbot_server --tail 50
docker logs ngtradingbot_dashboard --tail 50
```

---

### Problem: Socket.IO zeigt "Disconnected" (Mobile Dashboard)

**Ursache:** Falsche URL im JavaScript

**Lösung:**
Das Dashboard sollte automatisch die richtige URL verwenden. Falls nicht:

1. Browser Developer Tools öffnen (F12)
2. Console-Tab öffnen
3. Nach Socket.IO-Fehlern suchen
4. Prüfen: "Failed to connect to..."

**Fix:** Dashboard-Container neu starten
```bash
docker compose restart dashboard
```

---

## 📝 URLs für Lesezeichen

### Desktop-Lesezeichen
```
Name: ngTradingBot Main
URL:  http://YOUR_UNRAID_IP:9905/
```

### Mobile-Lesezeichen
```
Name: ngTradingBot Mobile
URL:  http://YOUR_UNRAID_IP:9906/
```

### Quick View
```
Name: ngTradingBot Quick View
URL:  http://YOUR_UNRAID_IP:9905/unified
```

---

## 🎉 Zusammenfassung

Sie haben jetzt **3 Dashboard-Optionen** zur Auswahl:

1. **Main Dashboard (Port 9905)** - Für Desktop mit allen Funktionen
2. **Unified Dashboard (Port 9905/unified)** - Für schnelle Übersicht
3. **Mobile Dashboard (Port 9906)** - Für Smartphone/Tablet Trading

**Nächste Schritte:**
1. Ersetzen Sie `YOUR_UNRAID_IP` mit Ihrer tatsächlichen IP
2. Testen Sie alle Dashboards im Browser
3. Installieren Sie Mobile Dashboard als App (PWA)
4. Setzen Sie Lesezeichen für schnellen Zugriff

**Viel Erfolg beim Trading!** 🚀

---

**Generated with Claude Code**
https://claude.com/claude-code

© 2025 ngTradingBot

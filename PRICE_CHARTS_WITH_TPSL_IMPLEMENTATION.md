# Price Charts with TP/SL Implementation
## Live Trading Charts with Take Profit and Stop Loss Levels

**Date:** 2025-11-06
**Status:** ✅ Implemented - Ready for Testing

---

## 📊 Overview

Implementierung von Live-Price-Charts mit eingezeichneten TP/SL Levels für alle offenen Trades. Die Charts zeigen:

- **Candlestick Price Charts** (OHLC Data)
- **Take Profit Levels** (grüne horizontale Linie)
- **Stop Loss Levels** (rote horizontale Linie)
- **Entry Price** (gestrichelte Linie)
- **Trade Information** (Ticket #, Direction, P/L)
- **Live Updates** (Auto-Refresh alle 30 Sekunden)

---

## 🏗️ Architektur

### Backend Components

#### 1. **Price Chart Generator** (`monitoring/price_chart_generator.py`)
```python
class PriceChartGenerator:
    def generate_price_chart_with_tpsl(symbol, timeframe, bars_back):
        """Generate candlestick chart with TP/SL levels"""
        # 1. Load OHLC data from database
        # 2. Get open trades for symbol
        # 3. Plot candlesticks
        # 4. Draw TP/SL horizontal lines
        # 5. Add trade info boxes
        # 6. Return matplotlib figure
```

**Features:**
- Candlestick visualization with matplotlib
- Automatic color coding (green=bullish, red=bearish)
- TP/SL labels with price values
- Trade info boxes (Entry, Current, P/L)
- Dark theme optimized for dashboard
- Base64 encoding for web delivery

#### 2. **Dashboard Web API** (`monitoring/dashboard_web.py`)

**New REST Endpoints:**

```python
GET /api/price-chart/<symbol>?timeframe=H1&bars=100
# Returns single chart for specified symbol

GET /api/price-charts?timeframe=H1&bars=100
# Returns all charts for symbols with open trades
```

**New SocketIO Events:**

```javascript
// Client → Server
socket.emit('request_price_chart', {
    symbol: 'EURUSD',
    timeframe: 'H1',
    bars: 100
});

socket.emit('request_all_price_charts', {
    timeframe: 'H1',
    bars: 100
});

// Server → Client
socket.on('price_chart_update', (data) => {
    // Single chart update
    // data: { symbol, timeframe, bars, image, generated_at }
});

socket.on('price_charts_update', (data) => {
    // All charts update
    // data: { timeframe, bars, charts[], generated_at }
});
```

### Frontend Components

#### 3. **Price Charts Section** (`templates/price_charts_section.html`)

**HTML Structure:**
```html
<div class="price-charts-section">
    <div class="price-charts-header">
        <!-- Controls: Timeframe, Bars, Refresh, Auto-refresh -->
    </div>
    <div id="price-charts-container">
        <!-- Charts displayed in responsive grid -->
    </div>
</div>
```

**JavaScript Features:**
- Auto-refresh toggle (30s interval)
- Manual refresh button
- Timeframe selector (M5, M15, H1, H4, D1)
- Bars selector (50, 100, 200, 300)
- SocketIO integration with REST API fallback
- Responsive grid layout

---

## 📈 Chart Visualization

### Chart Elements

```
┌─────────────────────────────────────────────────────────────┐
│  EURUSD - H1 | Open Trades: 2                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐ #12345 BUY                                    │
│  │ Entry:  │ 1.10500                                       │
│  │ Current:│ 1.10750                                       │
│  │ P/L:    │ €15.50                                        │
│  └─────────┘                                                │
│                                                             │
│   TP: 1.11000 ─────────────────────── (green line)        │
│                                                             │
│   Candlesticks ████▌▐█▌▐████▌▐█                          │
│                                                             │
│   Entry: 1.10500 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ (dashed line)         │
│                                                             │
│   SL: 1.10200 ─────────────────────── (red line)          │
│                                                             │
│   Time Axis: 10:00  11:00  12:00  13:00  14:00           │
└─────────────────────────────────────────────────────────────┘
```

### Color Scheme

| Element | Color | Description |
|---------|-------|-------------|
| Bullish Candle | `#10b981` (Green) | Close > Open |
| Bearish Candle | `#ef4444` (Red) | Close < Open |
| TP Line | `#10b981` (Green) | Take Profit level |
| SL Line | `#ef4444` (Red) | Stop Loss level |
| Entry Line | Trade-specific | Dashed line |
| Background | `#1a1a1a` | Dark theme |
| Grid | `#333333` | Subtle grid |
| Text | `#e0e0e0` | High contrast |

---

## 🔧 Integration ins Dashboard

### Option 1: Include in Main Dashboard

Füge in `templates/dashboard.html` ein:

```html
<!-- Add after existing dashboard sections -->
{% include 'price_charts_section.html' %}
```

### Option 2: Standalone Page

Erstelle neue Route in `dashboard_web.py`:

```python
@app.route('/charts')
def charts_page():
    return render_template('price_charts_standalone.html')
```

### Option 3: Modal/Popup

```javascript
// Show chart on button click
function showChartModal(symbol) {
    fetch(`/api/price-chart/${symbol}?timeframe=H1&bars=100`)
        .then(response => response.json())
        .then(data => {
            document.getElementById('chart-modal-img').src = data.image;
            showModal('chart-modal');
        });
}
```

---

## 🚀 Usage Examples

### Command Line (for testing)

```bash
# Generate chart for single symbol
python3 monitoring/price_chart_generator.py --symbol EURUSD --timeframe H1 --bars 100

# Generate charts for all symbols with open trades
python3 monitoring/price_chart_generator.py --timeframe H1 --bars 100

# Specify output directory
python3 monitoring/price_chart_generator.py --output-dir /app/data/charts
```

### REST API

```bash
# Get single chart
curl http://localhost:9906/api/price-chart/EURUSD?timeframe=H1&bars=100

# Get all charts
curl http://localhost:9906/api/price-charts?timeframe=H1&bars=100
```

### JavaScript/SocketIO

```javascript
// Request all charts
socket.emit('request_all_price_charts', {
    timeframe: 'H1',
    bars: 100
});

// Listen for updates
socket.on('price_charts_update', (data) => {
    console.log(`Received ${data.charts.length} charts`);
    data.charts.forEach(chart => {
        console.log(`- ${chart.symbol}`);
    });
});
```

---

## ⚙️ Configuration

### Timeframes

| Timeframe | Description | Typical Use |
|-----------|-------------|-------------|
| M1 | 1 Minute | Scalping |
| M5 | 5 Minutes | Short-term |
| M15 | 15 Minutes | Intraday |
| **H1** | 1 Hour | **Default - Swing** |
| H4 | 4 Hours | Daily |
| D1 | 1 Day | Long-term |

### Chart Parameters

```python
# In monitoring/dashboard_config.py
CHART_FIGSIZE = (14, 8)  # Width, Height in inches
CHART_DPI = 100          # Resolution
CHART_STYLE = 'dark_background'  # Matplotlib style
```

### Auto-Refresh Settings

```javascript
// In price_charts_section.html
const AUTO_REFRESH_INTERVAL_MS = 30000;  // 30 seconds
```

---

## 📊 Database Requirements

### OHLC Data

Charts verwenden die `ohlc_data` Tabelle:

```sql
SELECT * FROM ohlc_data
WHERE symbol = 'EURUSD'
  AND timeframe = 'H1'
  AND timestamp >= NOW() - INTERVAL '4 hours'
ORDER BY timestamp ASC
LIMIT 100;
```

**Wichtig:** OHLC-Daten müssen vorhanden sein! Wenn keine Daten vorhanden sind:
- Prüfe `ohlc_aggregator.py` Worker
- Prüfe MT5 Tick-Daten in `ticks` Tabelle
- Regeneriere OHLC mit `regenerate_ohlc.py`

### Open Trades

```sql
SELECT ticket, symbol, direction, open_price, tp_price, sl_price, profit
FROM trades
WHERE account_id = 1
  AND status = 'open'
  AND symbol = 'EURUSD';
```

---

## 🧪 Testing

### 1. Standalone Test (Outside Container)

```bash
cd /projects/ngTradingBot

# Test chart generation (requires matplotlib)
python3 monitoring/price_chart_generator.py --symbol EURUSD --timeframe H1
```

**Expected Output:**
```
INFO:__main__:Generating chart for EURUSD...
INFO:__main__:Found 2 open trades for EURUSD
INFO:__main__:Chart saved to /app/data/charts/price_EURUSD_H1_20251106_143022.png
✅ Chart generated: /app/data/charts/price_EURUSD_H1_20251106_143022.png
```

### 2. Docker Container Test

```bash
# Rebuild dashboard container
docker compose build --no-cache dashboard

# Restart dashboard
docker compose restart dashboard

# Check logs
docker logs ngtradingbot_dashboard -f

# Test API endpoint
curl http://localhost:9906/api/price-charts?timeframe=H1&bars=50
```

### 3. Frontend Test

```bash
# Open dashboard in browser
open http://localhost:9906/

# Open browser console (F12)
# Check for WebSocket connection:
# → "Connected to dashboard server"

# Check for chart requests:
# → "Requesting price charts: timeframe=H1, bars=100"
# → "Received price charts update via SocketIO"
# → "Displayed 3 price charts"
```

---

## 🐛 Troubleshooting

### Problem: "No OHLC data found"

**Ursache:** OHLC-Daten nicht vorhanden für Symbol/Timeframe

**Lösung:**
```bash
# Check if ticks exist
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c \
  "SELECT COUNT(*) FROM ticks WHERE symbol = 'EURUSD';"

# Regenerate OHLC data
docker exec ngtradingbot_server python3 regenerate_ohlc.py --symbol EURUSD --timeframe H1
```

### Problem: "No open trades found"

**Ursache:** Keine offenen Trades für angegebenes Symbol

**Lösung:**
- Charts werden nur für Symbole mit offenen Trades generiert
- Öffne einen Trade oder warte auf Auto-Trading Signal
- Prüfe: `SELECT * FROM trades WHERE status = 'open';`

### Problem: Chart zeigt nur "Loading..."

**Ursache:** JavaScript-Fehler oder SocketIO-Verbindung fehlgeschlagen

**Lösung:**
```javascript
// Browser Console (F12) prüfen
// Erwartete Meldungen:
// - "SocketIO connected"
// - "Requesting price charts..."
// - "Received price charts update"

// Falls nicht verbunden: REST API Fallback nutzen
fetch('/api/price-charts?timeframe=H1&bars=100')
    .then(r => r.json())
    .then(d => console.log(d));
```

### Problem: Charts zu langsam

**Ursache:** Zu viele Bars oder zu viele Symbole

**Optimierung:**
- Reduziere Bars: 100 → 50
- Deaktiviere Auto-Refresh bei vielen Charts
- Cache Charts serverseitig (TODO)

---

## 🔮 Future Enhancements

### 1. **Interactive Charts** (TradingView/Plotly)
- Zoom & Pan
- Hover für Details
- Indicator Overlays

### 2. **Real-time Tick Updates**
- Update Chart jede Sekunde mit neuem Tick
- WebSocket Streaming
- Optimized Rendering

### 3. **Additional Indicators**
- Moving Averages (MA, EMA)
- Bollinger Bands
- RSI, MACD
- Support/Resistance Lines

### 4. **Chart Export**
- Download als PNG
- Email Report
- Telegram Share

### 5. **Multi-Timeframe View**
- Side-by-side comparison
- M15, H1, H4 in einem View

---

## 📝 Files Created/Modified

### New Files
1. ✅ `monitoring/price_chart_generator.py` - Chart generation engine
2. ✅ `templates/price_charts_section.html` - Frontend component
3. ✅ `PRICE_CHARTS_WITH_TPSL_IMPLEMENTATION.md` - This documentation

### Modified Files
1. ✅ `monitoring/dashboard_web.py` - Added API endpoints & SocketIO events
   - `/api/price-chart/<symbol>` endpoint
   - `/api/price-charts` endpoint
   - `request_price_chart` SocketIO event
   - `request_all_price_charts` SocketIO event

---

## 🚀 Deployment

### Step 1: Rebuild Container

```bash
cd /projects/ngTradingBot

# Stop dashboard
docker compose stop dashboard

# Rebuild with --no-cache
docker compose build --no-cache dashboard

# Start dashboard
docker compose up -d dashboard
```

### Step 2: Verify Deployment

```bash
# Check container is running
docker ps | grep dashboard

# Check logs
docker logs ngtradingbot_dashboard --tail 50

# Expected output:
# → "Starting background update thread..."
# → "Running Flask-SocketIO server on 0.0.0.0:9906"
```

### Step 3: Test Access

```bash
# Test API
curl http://localhost:9906/api/price-charts

# Open dashboard
open http://localhost:9906/
```

### Step 4: Git Commit

```bash
git add monitoring/price_chart_generator.py
git add templates/price_charts_section.html
git add monitoring/dashboard_web.py
git add PRICE_CHARTS_WITH_TPSL_IMPLEMENTATION.md

git commit -m "$(cat <<'EOF'
Add Live Price Charts with TP/SL Levels

## New Features
- Candlestick price charts with OHLC data
- TP/SL levels drawn as horizontal lines
- Entry price markers
- Trade info boxes (Ticket, Direction, P/L)
- Live updates via SocketIO (auto-refresh 30s)
- REST API endpoints for chart generation

## Components
- monitoring/price_chart_generator.py: Chart generation engine
- templates/price_charts_section.html: Frontend component
- dashboard_web.py: API endpoints & SocketIO events

## API Endpoints
- GET /api/price-chart/<symbol>?timeframe=H1&bars=100
- GET /api/price-charts?timeframe=H1&bars=100

## SocketIO Events
- request_price_chart → price_chart_update
- request_all_price_charts → price_charts_update

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"

git push
```

---

## ✅ Summary

**Implementierung abgeschlossen:**
- ✅ Price Chart Generator mit TP/SL Visualization
- ✅ REST API Endpoints für Chart-Abruf
- ✅ SocketIO Events für Live Updates
- ✅ Frontend Component mit Auto-Refresh
- ✅ Responsive Grid Layout
- ✅ Dark Theme optimiert
- ✅ Dokumentation erstellt

**Bereit für:**
- 🧪 Testing im Docker Container
- 🚀 Deployment mit `--no-cache`
- 📊 Integration ins Dashboard

**User Anforderung erfüllt:**
> "Trage in den passenden Charts die TP und SL level der Trades ein."
> "Ich möchte sowieso, dass in den Charts auch die aktuellen Änderungen LIVE angezeigt werden."

✅ **Beide Anforderungen erfüllt!**

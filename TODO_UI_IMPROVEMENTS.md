# UI Improvements - Dashboard Enhancements

**Date:** 2025-10-06
**Priority:** High
**Requested by:** User

---

## 🎯 Missing Features

### 1. Live Trading Statistics Section
**Status:** ❌ Not Implemented
**Location:** Dashboard main page
**Priority:** High

**What's Needed:**
- Real-time Win Rate (% of winning trades)
- Profit Factor (Gross Profit / Gross Loss)
- Average Win / Average Loss
- Best Trade / Worst Trade
- Total Trades (Today / Week / Month / All Time)
- Sharpe Ratio (if possible)
- Max Drawdown (current)
- Recovery Factor

**API Endpoint:** NEW - `/api/dashboard/statistics`

**Implementation:**
```python
@app.route('/api/dashboard/statistics')
def get_trading_statistics():
    """Get live trading statistics"""
    account_id = 1  # TODO: Get from session

    # Today's stats
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
    today_trades = db.query(Trade).filter(
        Trade.account_id == account_id,
        Trade.close_time >= today_start,
        Trade.status == 'closed'
    ).all()

    # All time stats
    all_trades = db.query(Trade).filter(
        Trade.account_id == account_id,
        Trade.status == 'closed'
    ).all()

    stats = {
        'today': calculate_stats(today_trades),
        'week': calculate_stats(get_week_trades()),
        'month': calculate_stats(get_month_trades()),
        'all_time': calculate_stats(all_trades)
    }

    return jsonify(stats)
```

---

### 2. Open Trades Overview with Real-Time P&L
**Status:** ⚠️ Partially Implemented (exists but hidden/not prominent)
**Location:** Dashboard main page
**Priority:** Critical

**What's Needed:**
- Dedicated "Open Positions" section at top of dashboard
- Real-time P&L for each open trade
- Visual indicators (green/red for profit/loss)
- Distance to TP/SL
- Duration (how long trade has been open)
- Trailing Stop status (which stage if active)
- Quick actions (close position button)

**Current Status:**
- Data available via `/api/monitoring/account/{account_id}`
- Just needs better UI presentation

**UI Enhancement:**
```html
<div class="open-trades-section">
    <h2>📈 Open Positions (<span id="open-count">0</span>)</h2>
    <div class="trades-grid" id="open-trades">
        <!-- Populated by JavaScript -->
    </div>
</div>

<style>
.trades-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 15px;
}

.trade-card {
    background: #2d2d2d;
    border-radius: 8px;
    padding: 15px;
    border-left: 4px solid;
}

.trade-card.profit {
    border-left-color: #4CAF50;
}

.trade-card.loss {
    border-left-color: #f44336;
}
</style>
```

---

### 3. Trade History with Advanced Filters
**Status:** ❌ Not Implemented
**Location:** New section below Open Trades
**Priority:** High

**What's Needed:**
- Filterable table of closed trades
- Filter options:
  - ✅ All Time
  - ✅ This Year
  - ✅ This Month
  - ✅ Today
  - ✅ Custom Date Range (date picker)
  - ✅ Symbol filter
  - ✅ Direction filter (Buy/Sell)
  - ✅ Status filter (Profit/Loss)
- Sortable columns
- Pagination (20 trades per page)
- Export to CSV

**API Endpoint:** NEW - `/api/trades/history`

**Implementation:**
```python
@app.route('/api/trades/history')
def get_trade_history():
    """Get filtered trade history"""
    account_id = request.args.get('account_id', 1, type=int)
    filter_period = request.args.get('period', 'all')  # all, year, month, today, custom
    start_date = request.args.get('start_date')  # For custom range
    end_date = request.args.get('end_date')
    symbol = request.args.get('symbol')  # Optional filter
    direction = request.args.get('direction')  # BUY/SELL
    status = request.args.get('status')  # profit/loss
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = db.query(Trade).filter(
        Trade.account_id == account_id,
        Trade.status == 'closed'
    )

    # Apply period filter
    if filter_period == 'today':
        query = query.filter(Trade.close_time >= today_start())
    elif filter_period == 'month':
        query = query.filter(Trade.close_time >= month_start())
    elif filter_period == 'year':
        query = query.filter(Trade.close_time >= year_start())
    elif filter_period == 'custom' and start_date and end_date:
        query = query.filter(
            Trade.close_time >= parse_date(start_date),
            Trade.close_time <= parse_date(end_date)
        )

    # Apply optional filters
    if symbol:
        query = query.filter(Trade.symbol == symbol)
    if direction:
        query = query.filter(Trade.direction == direction)
    if status == 'profit':
        query = query.filter(Trade.profit > 0)
    elif status == 'loss':
        query = query.filter(Trade.profit < 0)

    # Pagination
    total = query.count()
    trades = query.order_by(
        Trade.close_time.desc()
    ).limit(per_page).offset((page - 1) * per_page).all()

    return jsonify({
        'trades': [trade_to_dict(t) for t in trades],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })
```

**UI:**
```html
<div class="trade-history-section">
    <h2>📊 Trade History</h2>

    <!-- Filters -->
    <div class="filters">
        <button class="filter-btn active" data-period="all">All</button>
        <button class="filter-btn" data-period="year">This Year</button>
        <button class="filter-btn" data-period="month">This Month</button>
        <button class="filter-btn" data-period="today">Today</button>
        <button class="filter-btn" data-period="custom">Custom Range</button>

        <div class="custom-date-range" style="display:none;">
            <input type="date" id="start-date">
            <input type="date" id="end-date">
            <button id="apply-custom-range">Apply</button>
        </div>

        <select id="symbol-filter">
            <option value="">All Symbols</option>
            <!-- Populated dynamically -->
        </select>

        <select id="direction-filter">
            <option value="">All Directions</option>
            <option value="BUY">Buy</option>
            <option value="SELL">Sell</option>
        </select>

        <select id="status-filter">
            <option value="">All</option>
            <option value="profit">Profitable</option>
            <option value="loss">Loss</option>
        </select>

        <button id="export-csv">Export CSV</button>
    </div>

    <!-- Table -->
    <table class="trades-table">
        <thead>
            <tr>
                <th onclick="sortBy('ticket')">Ticket</th>
                <th onclick="sortBy('symbol')">Symbol</th>
                <th onclick="sortBy('direction')">Direction</th>
                <th onclick="sortBy('open_time')">Open Time</th>
                <th onclick="sortBy('close_time')">Close Time</th>
                <th onclick="sortBy('duration')">Duration</th>
                <th onclick="sortBy('profit')">Profit</th>
                <th onclick="sortBy('pips')">Pips</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="trade-history-body">
            <!-- Populated by JavaScript -->
        </tbody>
    </table>

    <!-- Pagination -->
    <div class="pagination" id="pagination">
        <!-- Generated by JavaScript -->
    </div>
</div>
```

---

## 📋 Implementation Steps

### Step 1: Backend API Endpoints (2-3 hours)
1. ✅ Create `/api/dashboard/statistics` endpoint
2. ✅ Create `/api/trades/history` endpoint with filters
3. ✅ Add helper functions for date parsing
4. ✅ Add CSV export endpoint `/api/trades/export`

### Step 2: Frontend UI (3-4 hours)
1. ✅ Add Statistics Dashboard section
2. ✅ Enhance Open Trades display
3. ✅ Create Trade History table with filters
4. ✅ Add JavaScript for real-time updates
5. ✅ Style with existing color scheme

### Step 3: Testing (1 hour)
1. ✅ Test all filter combinations
2. ✅ Verify real-time P&L updates
3. ✅ Test pagination
4. ✅ Test CSV export

---

## 📊 Layout Proposal

```
┌─────────────────────────────────────────────────────────┐
│ ngTradingBot Dashboard                                  │
├─────────────────────────────────────────────────────────┤
│ [Connection Status] [Balance] [Profit Today] [Time]    │
├─────────────────────────────────────────────────────────┤
│ 📈 OPEN POSITIONS (2)                                   │
│ ┌──────────┬──────────┐                                │
│ │ EURUSD   │ BTCUSD   │                                │
│ │ BUY      │ SELL     │                                │
│ │ +$12.50  │ -$3.20   │                                │
│ │ [Close]  │ [Close]  │                                │
│ └──────────┴──────────┘                                │
├─────────────────────────────────────────────────────────┤
│ 📊 TRADING STATISTICS                                   │
│ ┌─────────┬─────────┬─────────┬─────────┐             │
│ │ Today   │ Week    │ Month   │ All Time │             │
│ ├─────────┼─────────┼─────────┼─────────┤             │
│ │ WR: 65% │ WR: 58% │ WR: 61% │ WR: 59%  │             │
│ │ PF: 1.8 │ PF: 1.5 │ PF: 1.6 │ PF: 1.7  │             │
│ │ +$45    │ +$320   │ +$1,240 │ +$8,540  │             │
│ └─────────┴─────────┴─────────┴─────────┘             │
├─────────────────────────────────────────────────────────┤
│ 📈 TRADE HISTORY                                        │
│ [All][Year][Month][Today][Custom] Symbol▼ Dir▼ Status▼│
│ ┌────────────────────────────────────────────────────┐ │
│ │ Ticket  Symbol Dir   Profit  Duration  Close Time │ │
│ ├────────────────────────────────────────────────────┤ │
│ │ 123456  EURUSD BUY  +$12.50  2h 15m   14:20       │ │
│ │ 123457  BTCUSD SELL -$3.20   1h 05m   13:15       │ │
│ │ ...                                                │ │
│ └────────────────────────────────────────────────────┘ │
│ [<] [1] [2] [3] [>]  (Page 1 of 5) [Export CSV]      │
└─────────────────────────────────────────────────────────┘
```

---

## 🎨 Color Scheme (Match existing)
- Background: `#1a1a1a`
- Cards: `#2d2d2d`
- Text: `#e0e0e0`
- Profit: `#4CAF50`
- Loss: `#f44336`
- Neutral: `#888`
- Accent: `#4CAF50`

---

## ⏱️ Estimated Time
**Total:** 6-8 hours
- Backend: 2-3 hours
- Frontend: 3-4 hours
- Testing: 1 hour

---

## 🚀 Priority Order
1. **High:** Open Trades Overview (most critical for monitoring)
2. **High:** Live Trading Statistics (essential for performance tracking)
3. **Medium:** Trade History with filters (nice-to-have but important)

---

**Next Steps:**
1. Start with Backend API endpoints
2. Then build Frontend UI
3. Test thoroughly
4. Commit and rebuild container

---

**Status:** ⏳ Ready to Implement
**Blocked By:** None
**Dependencies:** Existing Trade/Account models, Database

#!/usr/bin/env python3
"""
Script to wrap dashboard panels in draggable containers
"""

import re

# Read the dashboard HTML
with open('/projects/ngTradingBot/templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the sections to wrap with their panel IDs
# Format: (comment_marker, panel_id, already_wrapped)
sections = [
    ('<!-- TRADING SIGNALS -->', 'trading-signals', True),  # Already wrapped
    ('<!-- SYMBOL PERFORMANCE TRACKING -->', 'symbol-performance', False),
    ('<!-- P/L PERFORMANCE -->', 'pnl-performance', False),
    ('<!-- SPREAD LIMITS -->', 'spread-config', False),
    ('<!-- TRADING STATISTICS -->', 'trading-stats', False),
    ('<!-- AI DECISION LOG -->', 'ai-decision-log', False),
    ('<!-- ML MODELS -->', 'ml-models', False),
    ('<!-- TRADE HISTORY -->', 'trade-history', False),
    ('<!-- LIVE PRICES -->', 'live-prices', False),
    ('<!-- Backtesting Section -->', 'backtesting', False),
]

# Close Trading Signals panel
content = content.replace(
    '''                <div id="signals-list"></div>
            </div>
        </div>

        <!-- SYMBOL PERFORMANCE TRACKING -->
        <div class="grid">''',
    '''                <div id="signals-list"></div>
            </div>
        </div>
        </div>
        <!-- END TRADING SIGNALS -->

        <!-- SYMBOL PERFORMANCE TRACKING -->
        <div class="draggable-panel" data-panel-id="symbol-performance">
        <div class="grid">'''
)

# Find and wrap Symbol Performance end
content = content.replace(
    '''                    </table>
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">📊 P/L Performance</h2>''',
    '''                    </table>
                </div>
            </div>
        </div>
        </div>
        <!-- END SYMBOL PERFORMANCE -->

        <!-- P/L PERFORMANCE -->
        <div class="draggable-panel" data-panel-id="pnl-performance">
        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">📊 P/L Performance</h2>'''
)

# Find and wrap P/L Performance end (search for Spread Limits)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>⚙️ Spread Limits Configuration</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END P/L PERFORMANCE -->

        <!-- SPREAD CONFIG -->
        <div class="draggable-panel" data-panel-id="spread-config">
        <div class="grid">
            <div class="card">
                <h2>⚙️ Spread Limits Configuration</h2>'''
)

# Find and wrap Spread Config end (search for Trading Statistics)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>📈 Trading Statistics</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END SPREAD CONFIG -->

        <!-- TRADING STATS -->
        <div class="draggable-panel" data-panel-id="trading-stats">
        <div class="grid">
            <div class="card">
                <h2>📈 Trading Statistics</h2>'''
)

# Find and wrap Trading Statistics end (search for AI Decision Log)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">🤖 AI Decision Log</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END TRADING STATS -->

        <!-- AI DECISION LOG -->
        <div class="draggable-panel" data-panel-id="ai-decision-log">
        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">🤖 AI Decision Log</h2>'''
)

# Find and wrap AI Decision Log end (search for ML Models)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">🧠 Machine Learning Models</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END AI DECISION LOG -->

        <!-- ML MODELS -->
        <div class="draggable-panel" data-panel-id="ml-models">
        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="margin: 0;">🧠 Machine Learning Models</h2>'''
)

# Find and wrap ML Models end (search for Trade History)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>📜 Trade History</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END ML MODELS -->

        <!-- TRADE HISTORY -->
        <div class="draggable-panel" data-panel-id="trade-history">
        <div class="grid">
            <div class="card">
                <h2>📜 Trade History</h2>'''
)

# Find and wrap Trade History end (search for Live Prices)
content = content.replace(
    '''            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>📊 Abonnierte Symbole & Live-Kurse</h2>''',
    '''            </div>
        </div>
        </div>
        <!-- END TRADE HISTORY -->

        <!-- LIVE PRICES -->
        <div class="draggable-panel" data-panel-id="live-prices">
        <div class="grid">
            <div class="card">
                <h2>📊 Abonnierte Symbole & Live-Kurse</h2>'''
)

# Find Live Prices end and wrap Backtesting
# First, find where Live Prices ends (before the script section)
pattern = r'(</table>\s*</div>\s*</div>\s*</div>\s*</div>\s*<!-- End of Live Prices Grid -->)'
match = re.search(pattern, content)
if match:
    print("Found Live Prices end pattern")
else:
    # Try alternative pattern
    # Look for the end of Live Prices before Backtesting Section
    idx = content.find('<!-- Backtesting Section -->')
    if idx > 0:
        # Search backwards for </div> pattern
        search_start = idx - 500
        search_end = idx
        snippet = content[search_start:search_end]
        print(f"Snippet before Backtesting:\n{snippet[-200:]}")

# Different approach: find specific patterns
# Find where to close Live Prices (before </div> that precedes Backtesting)
content = content.replace(
    '''    <!-- Backtesting Section -->
    <div class="card" style="margin-top: 20px;">''',
    '''    </div>
    <!-- END LIVE PRICES -->

    <!-- BACKTESTING -->
    <div class="draggable-panel" data-panel-id="backtesting">
    <div class="card" style="margin-top: 20px;">'''
)

# Find Backtesting end (before Settings Modal)
content = content.replace(
    '''    </div>

    <!-- Settings Modal -->''',
    '''    </div>
    </div>
    <!-- END BACKTESTING -->

    </div>
    <!-- END DASHBOARD PANELS CONTAINER -->

    <!-- Settings Modal -->'''
)

# Write back
with open('/projects/ngTradingBot/templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Dashboard panels wrapped successfully!")
print("Panels wrapped:")
print("  - open-positions")
print("  - trading-signals")
print("  - symbol-performance")
print("  - pnl-performance")
print("  - spread-config")
print("  - trading-stats")
print("  - ai-decision-log")
print("  - ml-models")
print("  - trade-history")
print("  - live-prices")
print("  - backtesting")

/**
 * P/L Time Series Charts for ngTradingBot Dashboard
 *
 * Displays profit/loss charts for different time intervals:
 * - 1 hour
 * - 12 hours
 * - 24 hours
 * - 1 week
 * - 1 year
 *
 * Usage:
 *   <div id="pnl-charts-container"></div>
 *   <script src="/static/js/pnl_charts.js"></script>
 *   <script>
 *     PnLCharts.init('pnl-charts-container');
 *   </script>
 */

const PnLCharts = {
    containerId: null,
    charts: {},
    intervals: ['1h', '12h', '24h', '1w', '1y'],
    colors: {
        positive: '#10b981', // green
        negative: '#ef4444', // red
        neutral: '#6b7280'   // gray
    },

    /**
     * Initialize P/L charts
     */
    init: function(containerId) {
        this.containerId = containerId;
        this.renderContainer();
        this.loadAllCharts();

        // Auto-refresh every 5 minutes
        setInterval(() => this.loadAllCharts(), 5 * 60 * 1000);
    },

    /**
     * Render the chart container structure
     */
    renderContainer: function() {
        const container = document.getElementById(this.containerId);
        if (!container) {
            console.error(`Container #${this.containerId} not found`);
            return;
        }

        let html = `
            <div class="pnl-charts-wrapper">
                <h2>📊 P/L Performance</h2>
                <div class="pnl-summary-cards" id="pnl-summary"></div>
                <div class="pnl-charts-grid">
        `;

        this.intervals.forEach(interval => {
            html += `
                <div class="pnl-chart-card">
                    <h3>${this.getIntervalLabel(interval)}</h3>
                    <canvas id="chart-${interval}"></canvas>
                    <div class="chart-stats" id="stats-${interval}">
                        <span class="loading">Loading...</span>
                    </div>
                </div>
            `;
        });

        html += `
                </div>
            </div>
        `;

        container.innerHTML = html;
        this.injectStyles();
    },

    /**
     * Inject CSS styles
     */
    injectStyles: function() {
        if (document.getElementById('pnl-charts-styles')) return;

        const style = document.createElement('style');
        style.id = 'pnl-charts-styles';
        style.textContent = `
            .pnl-charts-wrapper {
                padding: 20px;
            }
            .pnl-charts-wrapper h2 {
                margin-bottom: 20px;
                color: #1f2937;
            }
            .pnl-summary-cards {
                display: flex;
                gap: 15px;
                margin-bottom: 30px;
                flex-wrap: wrap;
            }
            .pnl-summary-card {
                flex: 1;
                min-width: 150px;
                padding: 15px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .pnl-summary-card h4 {
                font-size: 12px;
                color: #6b7280;
                margin: 0 0 5px 0;
            }
            .pnl-summary-card .value {
                font-size: 24px;
                font-weight: bold;
                margin: 0;
            }
            .pnl-summary-card .value.positive { color: #10b981; }
            .pnl-summary-card .value.negative { color: #ef4444; }
            .pnl-summary-card .meta {
                font-size: 12px;
                color: #9ca3af;
                margin-top: 5px;
            }
            .pnl-charts-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 20px;
            }
            .pnl-chart-card {
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .pnl-chart-card h3 {
                margin: 0 0 15px 0;
                font-size: 16px;
                color: #1f2937;
            }
            .pnl-chart-card canvas {
                max-height: 250px;
            }
            .chart-stats {
                display: flex;
                justify-content: space-around;
                margin-top: 15px;
                padding-top: 15px;
                border-top: 1px solid #e5e7eb;
            }
            .chart-stats .stat {
                text-align: center;
            }
            .chart-stats .stat-label {
                font-size: 11px;
                color: #6b7280;
                display: block;
            }
            .chart-stats .stat-value {
                font-size: 16px;
                font-weight: bold;
                display: block;
                margin-top: 3px;
            }
            .chart-stats .loading {
                color: #9ca3af;
                font-style: italic;
            }
        `;
        document.head.appendChild(style);
    },

    /**
     * Get human-readable label for interval
     */
    getIntervalLabel: function(interval) {
        const labels = {
            '1h': 'Letzte Stunde',
            '12h': 'Letzte 12 Stunden',
            '24h': 'Letzte 24 Stunden',
            '1w': 'Letzte Woche',
            '1y': 'Letztes Jahr'
        };
        return labels[interval] || interval;
    },

    /**
     * Load all P/L charts
     */
    loadAllCharts: function() {
        // Load summary first
        this.loadSummary();

        // Load individual charts
        this.intervals.forEach(interval => {
            this.loadChart(interval);
        });
    },

    /**
     * Load P/L summary for all intervals
     */
    loadSummary: async function() {
        try {
            const response = await fetch('/api/pnl-summary');
            const data = await response.json();

            const summaryHtml = Object.entries(data).map(([interval, stats]) => {
                const valueClass = stats.total_pnl > 0 ? 'positive' : stats.total_pnl < 0 ? 'negative' : '';
                return `
                    <div class="pnl-summary-card">
                        <h4>${this.getIntervalLabel(interval)}</h4>
                        <p class="value ${valueClass}">$${stats.total_pnl.toFixed(2)}</p>
                        <p class="meta">${stats.trade_count} Trades • ${stats.win_rate}% WR</p>
                    </div>
                `;
            }).join('');

            document.getElementById('pnl-summary').innerHTML = summaryHtml;

        } catch (error) {
            console.error('Error loading P/L summary:', error);
        }
    },

    /**
     * Load individual P/L chart
     */
    loadChart: async function(interval) {
        try {
            const response = await fetch(`/api/pnl-timeseries/${interval}?aggregated=true`);
            const data = await response.json();

            this.renderChart(interval, data);
            this.renderStats(interval, data);

        } catch (error) {
            console.error(`Error loading chart for ${interval}:`, error);
            document.getElementById(`stats-${interval}`).innerHTML =
                '<span class="error">Error loading data</span>';
        }
    },

    /**
     * Render chart using Chart.js
     */
    renderChart: function(interval, data) {
        const canvas = document.getElementById(`chart-${interval}`);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        // Destroy existing chart
        if (this.charts[interval]) {
            this.charts[interval].destroy();
        }

        // Determine color based on final P/L
        const finalPnL = data.pnl_values[data.pnl_values.length - 1] || 0;
        const lineColor = finalPnL > 0 ? this.colors.positive :
                         finalPnL < 0 ? this.colors.negative :
                         this.colors.neutral;

        // Create new chart
        this.charts[interval] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.timestamps.map(t => this.formatTimestamp(t, interval)),
                datasets: [{
                    label: 'Cumulative P/L',
                    data: data.pnl_values,
                    borderColor: lineColor,
                    backgroundColor: lineColor + '20',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: data.pnl_values.length > 50 ? 0 : 3,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `P/L: $${context.parsed.y.toFixed(2)}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        display: true,
                        grid: {
                            display: false
                        },
                        ticks: {
                            maxTicksLimit: 8
                        }
                    },
                    y: {
                        display: true,
                        grid: {
                            color: '#e5e7eb'
                        },
                        ticks: {
                            callback: function(value) {
                                return '$' + value.toFixed(0);
                            }
                        }
                    }
                }
            }
        });
    },

    /**
     * Render statistics below chart
     */
    renderStats: function(interval, data) {
        const statsDiv = document.getElementById(`stats-${interval}`);
        if (!statsDiv) return;

        const pnlClass = data.total_pnl > 0 ? 'positive' : data.total_pnl < 0 ? 'negative' : '';

        statsDiv.innerHTML = `
            <div class="stat">
                <span class="stat-label">Total P/L</span>
                <span class="stat-value ${pnlClass}">$${data.total_pnl.toFixed(2)}</span>
            </div>
            <div class="stat">
                <span class="stat-label">Trades</span>
                <span class="stat-value">${data.trade_count}</span>
            </div>
            <div class="stat">
                <span class="stat-label">Win Rate</span>
                <span class="stat-value">${data.win_rate}%</span>
            </div>
        `;
    },

    /**
     * Format timestamp for display
     */
    formatTimestamp: function(timestamp, interval) {
        const date = new Date(timestamp);

        if (interval === '1h' || interval === '12h') {
            // Show time only
            return date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
        } else if (interval === '24h' || interval === '1w') {
            // Show date and time
            return date.toLocaleDateString('de-DE', { month: 'short', day: 'numeric', hour: '2-digit' });
        } else {
            // Show date only
            return date.toLocaleDateString('de-DE', { month: 'short', day: 'numeric' });
        }
    }
};

// Make it available globally
window.PnLCharts = PnLCharts;

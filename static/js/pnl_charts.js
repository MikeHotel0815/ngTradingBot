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
    intervals: ['1h', '12h', '24h', '1w', 'ytd'], // ytd = year to date (aktuelles Jahr)
    colors: {
        positive: '#10b981', // green
        negative: '#ef4444', // red
        neutral: '#6b7280',   // gray
        gridColor: '#333',
        textColor: '#9ca3af'
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
                padding: 0;
            }
            .pnl-charts-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
                gap: 20px;
            }
            .pnl-chart-card {
                background: #2a2a2a;
                padding: 20px;
                border-radius: 8px;
                border: 1px solid #333;
            }
            .pnl-chart-card h3 {
                margin: 0 0 15px 0;
                font-size: 15px;
                color: #e0e0e0;
                font-weight: 600;
            }
            .pnl-chart-card canvas {
                max-height: 220px;
            }
            .chart-stats {
                display: flex;
                justify-content: space-around;
                margin-top: 15px;
                padding-top: 15px;
                border-top: 1px solid #333;
            }
            .chart-stats .stat {
                text-align: center;
            }
            .chart-stats .stat-label {
                font-size: 11px;
                color: #888;
                display: block;
            }
            .chart-stats .stat-value {
                font-size: 15px;
                font-weight: 600;
                display: block;
                margin-top: 3px;
                color: #e0e0e0;
            }
            .chart-stats .stat-value.positive { color: #10b981; }
            .chart-stats .stat-value.negative { color: #ef4444; }
            .chart-stats .loading {
                color: #666;
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
            'ytd': 'Aktuelles Jahr'
        };
        return labels[interval] || interval;
    },

    /**
     * Load all P/L charts
     */
    loadAllCharts: function() {
        // Load individual charts
        this.intervals.forEach(interval => {
            this.loadChart(interval);
        });
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
                        backgroundColor: '#1a1a1a',
                        titleColor: '#e0e0e0',
                        bodyColor: '#e0e0e0',
                        borderColor: '#333',
                        borderWidth: 1,
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
                            maxTicksLimit: 8,
                            color: '#9ca3af'
                        }
                    },
                    y: {
                        display: true,
                        grid: {
                            color: '#333',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#9ca3af',
                            callback: function(value) {
                                return '$' + value.toFixed(2);
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

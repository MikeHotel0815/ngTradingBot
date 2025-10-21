/**
 * Symbol Modal Module
 *
 * Manages the symbol detail modal with timeframe-based views,
 * indicators, signals, and open trades for a specific symbol.
 *
 * Usage:
 *   SymbolModal.show('BTCUSD', 'H1');  // Show BTCUSD with H1 timeframe
 *   SymbolModal.close();                // Close the modal
 */

const SymbolModal = (function() {
    'use strict';

    // Private state
    let currentSymbol = null;
    let currentTimeframe = 'H1';
    let modalElement = null;
    let updateInterval = null;
    let chart = null;
    let candlestickSeries = null;

    // Available timeframes
    const TIMEFRAMES = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

    /**
     * Initialize the modal (called once on page load)
     */
    function init() {
        modalElement = document.getElementById('symbol-modal');
        if (!modalElement) {
            console.error('Symbol modal element not found');
            return;
        }

        // Set up event listeners
        setupEventListeners();
    }

    /**
     * Set up all event listeners for the modal
     */
    function setupEventListeners() {
        // Close button
        const closeBtn = modalElement.querySelector('.symbol-modal-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', close);
        }

        // Click outside to close
        modalElement.addEventListener('click', function(e) {
            if (e.target === modalElement) {
                close();
            }
        });

        // Escape key to close
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modalElement.style.display !== 'none') {
                close();
            }
        });

        // Timeframe tab clicks
        const timeframeTabs = modalElement.querySelectorAll('.timeframe-tab');
        timeframeTabs.forEach(tab => {
            tab.addEventListener('click', function() {
                const timeframe = this.dataset.timeframe;
                switchTimeframe(timeframe);
            });
        });
    }

    /**
     * Show the modal for a specific symbol and timeframe
     * @param {string} symbol - The symbol to display (e.g., 'BTCUSD')
     * @param {string} timeframe - The timeframe to show (e.g., 'H1')
     */
    function show(symbol, timeframe = 'H1') {
        if (!modalElement) {
            console.error('Modal not initialized');
            return;
        }

        currentSymbol = symbol;
        currentTimeframe = timeframe;

        // Show the modal
        modalElement.style.display = 'flex';

        // Update content
        updateModalContent();

        // Start auto-refresh
        startAutoRefresh();

        // Log for debugging
        console.log(`Opening symbol modal: ${symbol} (${timeframe})`);
    }

    /**
     * Close the modal
     */
    function close() {
        if (modalElement) {
            modalElement.style.display = 'none';
        }

        // Stop auto-refresh
        stopAutoRefresh();

        // Clean up chart
        if (chart) {
            chart.remove();
            chart = null;
            candlestickSeries = null;
        }

        currentSymbol = null;
        currentTimeframe = 'H1';

        console.log('Closed symbol modal');
    }

    /**
     * Switch to a different timeframe
     * @param {string} timeframe - The new timeframe
     */
    function switchTimeframe(timeframe) {
        if (!TIMEFRAMES.includes(timeframe)) {
            console.error('Invalid timeframe:', timeframe);
            return;
        }

        currentTimeframe = timeframe;

        // Update active tab
        const tabs = modalElement.querySelectorAll('.timeframe-tab');
        tabs.forEach(tab => {
            if (tab.dataset.timeframe === timeframe) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });

        // Refresh data for new timeframe
        updateModalContent();
    }

    /**
     * Update all content in the modal
     */
    async function updateModalContent() {
        if (!currentSymbol) return;

        // Update header
        updateHeader();

        // Update chart
        await updateChart();

        // Update indicators
        await updateIndicators();

        // Update signals
        await updateSignals();

        // Update open trades
        await updateOpenTrades();
    }

    /**
     * Update the modal header with symbol info and current price
     */
    async function updateHeader() {
        const headerSymbol = modalElement.querySelector('.symbol-modal-header-symbol');
        const headerPrice = modalElement.querySelector('.symbol-modal-header-price');
        const headerStatus = modalElement.querySelector('.symbol-modal-header-status');

        if (headerSymbol) {
            headerSymbol.textContent = currentSymbol;
        }

        try {
            // Fetch current symbol price
            const response = await fetch('/api/dashboard/symbols');
            const data = await response.json();

            if (data.status === 'success') {
                const symbolData = data.symbols.find(s => s.symbol === currentSymbol);

                if (symbolData) {
                    // Update price
                    if (headerPrice) {
                        headerPrice.innerHTML = `
                            <span class="bid-price">Bid: ${symbolData.bid}</span>
                            <span class="ask-price">Ask: ${symbolData.ask}</span>
                        `;
                    }

                    // Update status
                    if (headerStatus) {
                        if (symbolData.tradeable) {
                            headerStatus.innerHTML = '<span class="status-active">🟢 Handelbar</span>';
                        } else {
                            headerStatus.innerHTML = '<span class="status-inactive">🔒 Markt geschlossen</span>';
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Error fetching symbol data:', error);
        }
    }

    /**
     * Update chart with OHLC data
     */
    async function updateChart() {
        const chartContainer = document.getElementById('symbol-chart-container');
        if (!chartContainer) {
            console.error('Chart container not found');
            return;
        }

        console.log(`📊 Updating chart for ${currentSymbol} ${currentTimeframe}`);

        try {
            // Fetch OHLC data from backend
            const url = `/api/dashboard/ohlc?symbol=${currentSymbol}&timeframe=${currentTimeframe}&limit=100`;
            console.log(`Fetching from: ${url}`);

            const response = await fetch(url);
            const data = await response.json();

            console.log(`OHLC Response:`, data);

            if (data.status === 'success' && data.candles && data.candles.length > 0) {
                console.log(`✅ Received ${data.candles.length} candles`);

                // Initialize chart if not already created
                if (!chart) {
                    console.log('Creating new chart instance...');

                    // Load TradingView Lightweight Charts library if not loaded
                    if (typeof LightweightCharts === 'undefined') {
                        console.log('Loading TradingView Charts library...');
                        await loadLightweightCharts();
                        console.log('Library loaded successfully');
                    }

                    // Clear container
                    chartContainer.innerHTML = '';

                    chart = LightweightCharts.createChart(chartContainer, {
                        width: chartContainer.clientWidth,
                        height: 400,
                        layout: {
                            background: { color: '#1a1a1a' },
                            textColor: '#d1d4dc',
                        },
                        grid: {
                            vertLines: { color: '#2a2a2a' },
                            horzLines: { color: '#2a2a2a' },
                        },
                        crosshair: {
                            mode: LightweightCharts.CrosshairMode.Normal,
                        },
                        rightPriceScale: {
                            borderColor: '#3a3a3a',
                        },
                        timeScale: {
                            borderColor: '#3a3a3a',
                            timeVisible: true,
                            secondsVisible: false,
                        },
                    });

                    candlestickSeries = chart.addCandlestickSeries({
                        upColor: '#4CAF50',
                        downColor: '#f44336',
                        borderVisible: false,
                        wickUpColor: '#4CAF50',
                        wickDownColor: '#f44336',
                    });

                    console.log('Chart created successfully');

                    // Handle window resize
                    window.addEventListener('resize', () => {
                        if (chart && chartContainer) {
                            chart.applyOptions({ width: chartContainer.clientWidth });
                        }
                    });
                }

                // Convert data to TradingView format
                const candleData = data.candles.map(candle => ({
                    time: Math.floor(new Date(candle.time).getTime() / 1000),
                    open: parseFloat(candle.open),
                    high: parseFloat(candle.high),
                    low: parseFloat(candle.low),
                    close: parseFloat(candle.close),
                }));

                // Sort by time (ascending)
                candleData.sort((a, b) => a.time - b.time);

                console.log(`Setting ${candleData.length} candles to chart`);
                console.log(`First candle:`, candleData[0]);
                console.log(`Last candle:`, candleData[candleData.length - 1]);

                // Update the series (use update for real-time, setData for full refresh)
                if (candleData.length > 0) {
                    candlestickSeries.setData(candleData);

                    // Fit content to visible range
                    chart.timeScale().fitContent();

                    console.log('✅ Chart updated successfully');
                }

            } else {
                console.warn('No candle data available:', data);
                chartContainer.innerHTML = '<div style="padding: 40px; text-align: center; color: #888;">Keine Chart-Daten verfügbar</div>';
            }
        } catch (error) {
            console.error('❌ Error loading chart:', error);
            chartContainer.innerHTML = `<div style="padding: 40px; text-align: center; color: #f44336;">Fehler beim Laden des Charts: ${error.message}</div>`;
        }
    }

    /**
     * Load TradingView Lightweight Charts library dynamically
     */
    function loadLightweightCharts() {
        return new Promise((resolve, reject) => {
            if (typeof LightweightCharts !== 'undefined') {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    /**
     * Update indicators section
     */
    async function updateIndicators() {
        const indicatorsContainer = modalElement.querySelector('.symbol-modal-indicators');
        if (!indicatorsContainer) return;

        indicatorsContainer.innerHTML = '<div class="loading">Lade Indikatoren...</div>';

        try {
            // Fetch signals to get indicator data
            const response = await fetch(`/api/signals?symbol=${currentSymbol}&timeframe=${currentTimeframe}`);
            const data = await response.json();

            if (data.status === 'success' && data.signals.length > 0) {
                // Use the most recent signal for indicator data
                const signal = data.signals[0];

                indicatorsContainer.innerHTML = `
                    <div class="indicator-grid">
                        <div class="indicator-card">
                            <div class="indicator-label">RSI (14)</div>
                            <div class="indicator-value ${getRSIClass(signal.rsi)}">${signal.rsi ? signal.rsi.toFixed(2) : 'N/A'}</div>
                            <div class="indicator-interpretation">${getRSIInterpretation(signal.rsi)}</div>
                        </div>

                        <div class="indicator-card">
                            <div class="indicator-label">MACD</div>
                            <div class="indicator-value">${signal.macd_value ? signal.macd_value.toFixed(5) : 'N/A'}</div>
                            <div class="indicator-interpretation">${getMACDInterpretation(signal.macd_signal)}</div>
                        </div>

                        <div class="indicator-card">
                            <div class="indicator-label">Bollinger Bands</div>
                            <div class="indicator-value">${signal.bb_position || 'N/A'}</div>
                            <div class="indicator-interpretation">${getBBInterpretation(signal.bb_position)}</div>
                        </div>

                        <div class="indicator-card">
                            <div class="indicator-label">Trend</div>
                            <div class="indicator-value trend-${signal.signal_type ? signal.signal_type.toLowerCase() : 'neutral'}">
                                ${getTrendArrow(signal.signal_type)}
                            </div>
                            <div class="indicator-interpretation">${signal.signal_type || 'Neutral'}</div>
                        </div>
                    </div>
                `;
            } else {
                indicatorsContainer.innerHTML = '<div class="no-data">Keine Indikator-Daten verfügbar</div>';
            }
        } catch (error) {
            console.error('Error fetching indicators:', error);
            indicatorsContainer.innerHTML = '<div class="error">Fehler beim Laden der Indikatoren</div>';
        }
    }

    /**
     * Update signals section
     */
    async function updateSignals() {
        const signalsContainer = modalElement.querySelector('.symbol-modal-signals');
        if (!signalsContainer) return;

        signalsContainer.innerHTML = '<div class="loading">Lade Signale...</div>';

        try {
            const response = await fetch(`/api/signals?symbol=${currentSymbol}&timeframe=${currentTimeframe}`);
            const data = await response.json();

            if (data.status === 'success' && data.signals.length > 0) {
                signalsContainer.innerHTML = `
                    <div class="signals-list">
                        ${data.signals.map(signal => `
                            <div class="signal-card signal-${signal.signal_type.toLowerCase()}">
                                <div class="signal-card-header">
                                    <span class="signal-type">${signal.signal_type}</span>
                                    <span class="signal-confidence">${signal.confidence.toFixed(1)}%</span>
                                </div>
                                <div class="signal-card-body">
                                    <div class="signal-row">
                                        <span class="signal-label">Entry:</span>
                                        <span class="signal-value">${signal.entry_price}</span>
                                    </div>
                                    <div class="signal-row">
                                        <span class="signal-label">SL:</span>
                                        <span class="signal-value">${signal.sl_price}</span>
                                    </div>
                                    <div class="signal-row">
                                        <span class="signal-label">TP:</span>
                                        <span class="signal-value">${signal.tp_price}</span>
                                    </div>
                                    <div class="signal-row">
                                        <span class="signal-label">Lot Size:</span>
                                        <span class="signal-value">${signal.lot_size}</span>
                                    </div>
                                </div>
                                <div class="signal-card-footer">
                                    <small>Alter: ${signal.age_minutes}min | Risiko: €${signal.risk_amount.toFixed(2)}</small>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `;
            } else {
                signalsContainer.innerHTML = '<div class="no-data">Keine aktiven Signale für diesen Timeframe</div>';
            }
        } catch (error) {
            console.error('Error fetching signals:', error);
            signalsContainer.innerHTML = '<div class="error">Fehler beim Laden der Signale</div>';
        }
    }

    /**
     * Update open trades section
     */
    async function updateOpenTrades() {
        const tradesContainer = modalElement.querySelector('.symbol-modal-trades');
        if (!tradesContainer) return;

        tradesContainer.innerHTML = '<div class="loading">Lade offene Trades...</div>';

        try {
            const apiBase = window.location.protocol + '//' + window.location.hostname + ':9900';
            const monitoringResponse = await fetch(apiBase + '/api/monitoring/1');
            const monitoringData = await monitoringResponse.json();

            if (monitoringData.status === 'success' && monitoringData.open_trades) {
                // Filter trades for current symbol
                const symbolTrades = monitoringData.open_trades.filter(trade =>
                    trade.symbol === currentSymbol
                );

                if (symbolTrades.length > 0) {
                    tradesContainer.innerHTML = `
                        <div class="trades-list">
                            ${symbolTrades.map(trade => {
                                const pnl = parseFloat(trade.profit || 0);
                                const pnlClass = pnl >= 0 ? 'profit' : 'loss';

                                return `
                                    <div class="trade-card">
                                        <div class="trade-card-header">
                                            <span class="trade-direction trade-${trade.type.toLowerCase()}">${trade.type}</span>
                                            <span class="trade-pnl ${pnlClass}">€${pnl.toFixed(2)}</span>
                                        </div>
                                        <div class="trade-card-body">
                                            <div class="trade-row">
                                                <span class="trade-label">Ticket:</span>
                                                <span class="trade-value">#${trade.ticket}</span>
                                            </div>
                                            <div class="trade-row">
                                                <span class="trade-label">Entry:</span>
                                                <span class="trade-value">${trade.open_price}</span>
                                            </div>
                                            <div class="trade-row">
                                                <span class="trade-label">Current:</span>
                                                <span class="trade-value">${trade.current_price || 'N/A'}</span>
                                            </div>
                                            <div class="trade-row">
                                                <span class="trade-label">Volume:</span>
                                                <span class="trade-value">${trade.volume} lots</span>
                                            </div>
                                            ${trade.tp ? `
                                            <div class="trade-row">
                                                <span class="trade-label">TP:</span>
                                                <span class="trade-value">${trade.tp}</span>
                                            </div>
                                            ` : ''}
                                            ${trade.sl ? `
                                            <div class="trade-row">
                                                <span class="trade-label">SL:</span>
                                                <span class="trade-value">${trade.sl}</span>
                                            </div>
                                            ` : ''}
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    `;
                } else {
                    tradesContainer.innerHTML = '<div class="no-data">Keine offenen Trades für dieses Symbol</div>';
                }
            } else {
                tradesContainer.innerHTML = '<div class="no-data">Keine offenen Trades</div>';
            }
        } catch (error) {
            console.error('Error fetching open trades:', error);
            tradesContainer.innerHTML = '<div class="error">Fehler beim Laden der Trades</div>';
        }
    }

    /**
     * Start auto-refresh interval
     */
    function startAutoRefresh() {
        stopAutoRefresh(); // Clear any existing interval

        // Refresh every 2 seconds for real-time updates
        updateInterval = setInterval(() => {
            updateModalContent();
        }, 2000);

        console.log('✅ Auto-refresh started (2s interval)');
    }

    /**
     * Stop auto-refresh interval
     */
    function stopAutoRefresh() {
        if (updateInterval) {
            clearInterval(updateInterval);
            updateInterval = null;
        }
    }

    // Helper functions for indicator interpretation

    function getRSIClass(rsi) {
        if (!rsi) return '';
        if (rsi > 70) return 'rsi-overbought';
        if (rsi < 30) return 'rsi-oversold';
        return 'rsi-neutral';
    }

    function getRSIInterpretation(rsi) {
        if (!rsi) return 'N/A';
        if (rsi > 70) return 'Überkauft';
        if (rsi < 30) return 'Überverkauft';
        return 'Neutral';
    }

    function getMACDInterpretation(macdSignal) {
        if (!macdSignal) return 'N/A';
        if (macdSignal === 'bullish') return 'Bullish';
        if (macdSignal === 'bearish') return 'Bearish';
        return 'Neutral';
    }

    function getBBInterpretation(bbPosition) {
        if (!bbPosition) return 'N/A';
        if (bbPosition === 'upper') return 'Oberes Band';
        if (bbPosition === 'lower') return 'Unteres Band';
        if (bbPosition === 'middle') return 'Mittleres Band';
        return bbPosition;
    }

    function getTrendArrow(signalType) {
        if (!signalType) return '●';
        if (signalType === 'BUY') return '▲';
        if (signalType === 'SELL') return '▼';
        return '●';
    }

    // Public API
    return {
        init: init,
        show: show,
        close: close
    };
})();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', SymbolModal.init);
} else {
    SymbolModal.init();
}

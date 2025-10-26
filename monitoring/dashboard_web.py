#!/usr/bin/env python3
"""
Web Dashboard Server for ngTradingBot
Flask server with REST API and WebSocket live updates
"""

import sys
import os
import logging
from datetime import datetime
from typing import Optional
import json

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.dashboard_core import DashboardCore
from monitoring.chart_generator import ChartGenerator
from monitoring.dashboard_config import get_config

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Flask app setup
app = Flask(__name__,
            template_folder='../templates',
            static_folder='../static')
app.config['SECRET_KEY'] = 'ngtradingbot_dashboard_secret_2025'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global config
config = get_config()


class WebDashboardServer:
    """Web dashboard server with Flask and SocketIO"""

    def __init__(self, account_id: Optional[int] = None, port: int = 9906):
        self.account_id = account_id or config.DEFAULT_ACCOUNT_ID
        self.port = port
        self.running = False
        self.update_thread = None

    # =========================================================================
    # REST API Endpoints
    # =========================================================================

    def setup_routes(self):
        """Setup Flask routes"""

        @app.route('/')
        def index():
            """Serve main dashboard page"""
            return render_template('dashboard_ultimate.html')

        @app.route('/api/dashboard')
        def api_dashboard():
            """Get complete dashboard data (JSON)"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_complete_dashboard()
                return jsonify(data)
            except Exception as e:
                logger.error(f"Error getting dashboard data: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500

        @app.route('/api/trading-overview')
        def api_trading_overview():
            """Get trading overview (Section 1)"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_realtime_trading_overview()
                return jsonify(data)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @app.route('/api/risk-management')
        def api_risk_management():
            """Get risk management status (Section 3)"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_risk_management_status()
                return jsonify(data)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @app.route('/api/live-positions')
        def api_live_positions():
            """Get live positions (Section 4)"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_live_positions()
                return jsonify(data)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @app.route('/api/performance')
        def api_performance():
            """Get performance analytics (Section 8)"""
            try:
                hours = request.args.get('hours', 24, type=int)
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_performance_analytics(hours=hours)
                return jsonify(data)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @app.route('/api/system-health')
        def api_system_health():
            """Get system health (Section 7)"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_system_health()
                return jsonify(data)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @app.route('/api/charts/<chart_type>')
        def api_chart(chart_type):
            """Get chart as base64 PNG

            Args:
                chart_type: winrate|pnl_curve|symbol_performance|ml_confidence|buy_sell

            Returns:
                JSON with base64-encoded PNG
            """
            try:
                days = request.args.get('days', 7, type=int)

                with ChartGenerator(account_id=self.account_id) as generator:
                    if chart_type == 'winrate':
                        fig = generator.generate_winrate_chart(days_back=days)
                    elif chart_type == 'pnl_curve':
                        fig = generator.generate_pnl_curve(days_back=days)
                    elif chart_type == 'symbol_performance':
                        fig = generator.generate_symbol_performance_chart(days_back=days)
                    elif chart_type == 'ml_confidence':
                        fig = generator.generate_ml_confidence_histogram(days_back=days)
                    elif chart_type == 'buy_sell':
                        fig = generator.generate_buy_sell_comparison(days_back=days)
                    else:
                        return jsonify({'error': 'Invalid chart type'}), 400

                    img_base64 = generator.fig_to_base64(fig)

                return jsonify({
                    'chart_type': chart_type,
                    'image': f'data:image/png;base64,{img_base64}',
                    'generated_at': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error generating chart {chart_type}: {e}", exc_info=True)
                return jsonify({'error': str(e)}), 500

        @app.route('/health')
        def health_check():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'service': 'ngTradingBot Dashboard',
                'version': '1.0.0',
                'timestamp': datetime.utcnow().isoformat()
            })

    # =========================================================================
    # WebSocket Events
    # =========================================================================

    def setup_socketio(self):
        """Setup SocketIO event handlers"""

        @socketio.on('connect')
        def handle_connect():
            """Client connected"""
            logger.info(f"Client connected: {request.sid}")
            emit('connected', {'message': 'Connected to dashboard server'})

        @socketio.on('disconnect')
        def handle_disconnect():
            """Client disconnected"""
            logger.info(f"Client disconnected: {request.sid}")

        @socketio.on('request_dashboard_update')
        def handle_dashboard_update_request():
            """Client requests dashboard update"""
            try:
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_complete_dashboard()
                emit('dashboard_update', data)
            except Exception as e:
                logger.error(f"Error sending dashboard update: {e}")
                emit('error', {'message': str(e)})

    # =========================================================================
    # Background Update Thread
    # =========================================================================

    def broadcast_updates(self):
        """Background thread to broadcast updates to all connected clients"""
        logger.info(f"Starting background update thread (interval: {config.WEB_UPDATE_INTERVAL}s)")

        while self.running:
            try:
                # Wait for interval
                time.sleep(config.WEB_UPDATE_INTERVAL)

                # Get dashboard data
                with DashboardCore(account_id=self.account_id) as dashboard:
                    data = dashboard.get_complete_dashboard()

                # Broadcast to all connected clients
                socketio.emit('dashboard_update', data)
                logger.debug(f"Broadcasted dashboard update to all clients")

            except Exception as e:
                logger.error(f"Error in background update thread: {e}", exc_info=True)
                time.sleep(5)  # Wait before retry

        logger.info("Background update thread stopped")

    # =========================================================================
    # Server Control
    # =========================================================================

    def run(self, debug: bool = False):
        """Start the web dashboard server

        Args:
            debug: Enable Flask debug mode
        """
        logger.info("=" * 60)
        logger.info("ngTradingBot Web Dashboard Server Starting")
        logger.info("=" * 60)
        logger.info(f"Account ID: {self.account_id}")
        logger.info(f"Port: {self.port}")
        logger.info(f"Update Interval: {config.WEB_UPDATE_INTERVAL}s")
        logger.info(f"Dashboard URL: http://0.0.0.0:{self.port}")
        logger.info("=" * 60)

        # Setup routes and WebSocket
        self.setup_routes()
        self.setup_socketio()

        # Start background update thread
        self.running = True
        self.update_thread = threading.Thread(
            target=self.broadcast_updates,
            name="DashboardUpdateThread",
            daemon=True
        )
        self.update_thread.start()

        try:
            # Run Flask-SocketIO server
            socketio.run(
                app,
                host='0.0.0.0',
                port=self.port,
                debug=debug,
                allow_unsafe_werkzeug=True  # For development
            )
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        finally:
            self.running = False
            logger.info("Web dashboard server stopped")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='ngTradingBot Web Dashboard Server')
    parser.add_argument('--port', type=int, default=9906, help='Port to run server on (default: 9906)')
    parser.add_argument('--account-id', type=int, help='Account ID (defaults to config)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    server = WebDashboardServer(account_id=args.account_id, port=args.port)
    server.run(debug=args.debug)


if __name__ == '__main__':
    main()

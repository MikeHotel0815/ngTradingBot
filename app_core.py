#!/usr/bin/env python3
"""
ngTradingBot Core Server Application
=====================================
Bulletproof Multi-Port EA Communication Server

This is the CORE server - handles ONLY EA communication.
All strategy, analysis, and UI functionality is in separate modules.

Architecture:
------------
Port 9900: Command & Control (heartbeat, commands, responses)
Port 9901: Tick Data Streaming
Port 9902: Trade Synchronization
Port 9903: EA Logging
Port 9905: WebUI & API (separate from EA communication)

Key Principles:
--------------
1. EA (MT5) is the SINGLE SOURCE OF TRUTH
2. Zero data loss - all EA messages persisted immediately
3. Fast command delivery - Redis queue for instant push
4. Reliable responses - timeout tracking and retry logic
5. Connection resilience - auto-reconnect with monitoring

Usage:
------
python app_core.py

Or via Docker:
docker-compose up -d

Author: ngTradingBot
Last Modified: 2025-10-17
"""

import logging
import os
import sys
from threading import Thread
from flask import Flask
from flask_socketio import SocketIO

# Configure logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import core modules
from database import init_db
from redis_client import init_redis
from core_communication import init_core_communication, get_core_comm
from tick_batch_writer import start_batch_writer
from backup_scheduler import start_backup_scheduler

# Import API endpoint registrations
from core_api import (
    register_command_endpoints,
    register_tick_endpoints,
    register_trade_endpoints,
    register_log_endpoints
)

# Import worker status API for WebUI
from worker_status_api import worker_status_bp


# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================

def create_command_app():
    """Create Flask app for Command & Control (Port 9900)"""
    app = Flask('command')
    
    # Enable CORS
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, x-api-key'
        return response
    
    # Handle OPTIONS preflight
    @app.before_request
    def handle_preflight():
        from flask import request
        if request.method == 'OPTIONS':
            response = Flask.response_class()
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, x-api-key'
            return response
    
    # Register endpoints
    register_command_endpoints(app)
    
    logger.info("✅ Command & Control app created (Port 9900)")
    return app


def create_ticks_app():
    """Create Flask app for Tick Data (Port 9901)"""
    app = Flask('ticks')
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    
    register_tick_endpoints(app)
    
    logger.info("✅ Tick Data app created (Port 9901)")
    return app


def create_trades_app():
    """Create Flask app for Trade Sync (Port 9902)"""
    app = Flask('trades')
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    
    register_trade_endpoints(app)
    
    logger.info("✅ Trade Sync app created (Port 9902)")
    return app


def create_logs_app():
    """Create Flask app for Logging (Port 9903)"""
    app = Flask('logs')
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    
    register_log_endpoints(app)
    
    logger.info("✅ Logging app created (Port 9903)")
    return app


def create_webui_app():
    """Create Flask app for WebUI (Port 9905)"""
    app = Flask('webui', template_folder='templates')
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, x-api-key'
        return response
    
    # Register worker status API
    app.register_blueprint(worker_status_bp)
    
    # Health check endpoint
    @app.route('/health')
    def health():
        from flask import jsonify
        try:
            core_comm = get_core_comm()
            status = core_comm.get_system_status()
            return jsonify({
                'status': 'healthy',
                'connections': status['connections']['total'],
                'healthy_connections': status['connections']['healthy']
            }), 200
        except Exception as e:
            return jsonify({
                'status': 'unhealthy',
                'error': str(e)
            }), 500
    
    # System status endpoint
    @app.route('/api/system/status')
    def system_status():
        from flask import jsonify
        try:
            core_comm = get_core_comm()
            status = core_comm.get_system_status()
            return jsonify(status), 200
        except Exception as e:
            logger.error(f"System status error: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # Safety Monitor endpoint
    @app.route('/api/safety-monitor/status', methods=['GET'])
    def get_safety_monitor_status():
        """
        Get comprehensive safety monitoring status for live dashboard.

        Returns:
            - Circuit breaker status
            - Daily drawdown protection
            - SL-hit protection cooldowns
            - News filter status
            - Failed command count
            - Multi-timeframe conflicts
            - Position limits
        """
        from flask import jsonify, request
        from datetime import datetime
        from database import ScopedSession

        try:
            from auto_trader import get_auto_trader
            from daily_drawdown_protection import get_drawdown_protection
            from sl_hit_protection import get_sl_hit_protection
            from news_filter import get_news_filter
            from multi_timeframe_analyzer import MultiTimeframeAnalyzer

            account_id = request.args.get('account_id', 1, type=int)

            # Get auto-trader instance
            auto_trader = get_auto_trader()

            # 1. Circuit Breaker Status
            circuit_breaker = {
                'enabled': auto_trader.circuit_breaker_enabled,
                'tripped': auto_trader.circuit_breaker_tripped,
                'reason': auto_trader.circuit_breaker_reason,
                'failed_command_count': auto_trader.failed_command_count,
                'max_daily_loss_percent': auto_trader.max_daily_loss_percent,
                'max_total_drawdown_percent': auto_trader.max_total_drawdown_percent,
                'daily_loss_override': getattr(auto_trader, 'daily_loss_override', False)
            }

            # 2. Daily Drawdown Protection
            dd_protection = get_drawdown_protection(account_id)
            dd_status = dd_protection.get_status()

            # 3. SL-Hit Protection Cooldowns
            sl_protection = get_sl_hit_protection()
            cooldowns = sl_protection.get_all_cooldowns()

            # 4. News Filter Status
            news_filter = get_news_filter(account_id)
            upcoming_events = news_filter.get_upcoming_events(hours=2)  # Next 2 hours

            # 5. Position Limits
            db = ScopedSession()
            try:
                from models import Trade, GlobalSettings

                settings = GlobalSettings.get_settings(db)

                open_positions = db.query(Trade).filter(
                    Trade.account_id == account_id,
                    Trade.status == 'open'
                ).count()

                # Count positions by symbol
                positions_by_symbol = {}
                open_trades = db.query(Trade).filter(
                    Trade.account_id == account_id,
                    Trade.status == 'open'
                ).all()

                for trade in open_trades:
                    symbol = trade.symbol
                    if symbol not in positions_by_symbol:
                        positions_by_symbol[symbol] = 0
                    positions_by_symbol[symbol] += 1

                position_limits = {
                    'open_positions': open_positions,
                    'max_positions': settings.max_positions,
                    'max_positions_per_symbol_timeframe': settings.max_positions_per_symbol_timeframe,
                    'positions_by_symbol': positions_by_symbol,
                    'utilization_percent': round((open_positions / settings.max_positions) * 100, 1) if settings.max_positions > 0 else 0
                }

                # 6. Multi-Timeframe Conflicts
                from models import TradingSignal

                # Note: Signals are now global (no account_id)
                active_signals = db.query(TradingSignal).filter(
                    TradingSignal.status == 'active'
                ).all()

                # Group signals by symbol
                signals_by_symbol = {}
                for signal in active_signals:
                    symbol = signal.symbol
                    if symbol not in signals_by_symbol:
                        signals_by_symbol[symbol] = []
                    signals_by_symbol[symbol].append({
                        'timeframe': signal.timeframe,
                        'signal_type': signal.signal_type,
                        'confidence': float(signal.confidence or 0)
                    })

                # Detect conflicts
                mtf_conflicts = []
                for symbol, signals in signals_by_symbol.items():
                    summary = MultiTimeframeAnalyzer.get_multi_timeframe_summary(
                        symbol, account_id, db
                    )
                    if summary['conflicts']:
                        mtf_conflicts.append({
                            'symbol': symbol,
                            'conflicts': summary['conflicts'],
                            'signals': signals
                        })

                # 7. Auto-Trading Status
                auto_trading = {
                    'enabled': auto_trader.enabled,
                    'min_confidence': auto_trader.min_autotrade_confidence
                }

            finally:
                db.close()

            # Compile response
            response = {
                'status': 'success',
                'timestamp': datetime.utcnow().isoformat(),
                'account_id': account_id,
                'safety_status': {
                    'circuit_breaker': circuit_breaker,
                    'daily_drawdown': dd_status,
                    'sl_hit_cooldowns': cooldowns,
                    'news_filter': {
                        'upcoming_events': upcoming_events[:5],  # Next 5 events
                        'total_upcoming': len(upcoming_events)
                    },
                    'position_limits': position_limits,
                    'multi_timeframe_conflicts': mtf_conflicts,
                    'auto_trading': auto_trading
                },
                'overall_health': 'HEALTHY'  # Will be calculated below
            }

            # Calculate overall health status
            warnings = []
            errors = []

            if circuit_breaker['tripped']:
                errors.append(f"Circuit breaker tripped: {circuit_breaker['reason']}")

            if circuit_breaker['failed_command_count'] >= 2:
                warnings.append(f"{circuit_breaker['failed_command_count']} consecutive failed commands")

            if dd_status.get('limit_reached'):
                errors.append("Daily drawdown limit reached")

            if cooldowns:
                warnings.append(f"{len(cooldowns)} symbol(s) in cooldown")

            if mtf_conflicts:
                warnings.append(f"{len(mtf_conflicts)} multi-timeframe conflict(s)")

            if position_limits['utilization_percent'] >= 80:
                warnings.append(f"Position limit utilization: {position_limits['utilization_percent']}%")

            if not auto_trading['enabled']:
                warnings.append("Auto-trading is disabled")

            # Determine overall health
            if errors:
                response['overall_health'] = 'ERROR'
                response['health_messages'] = {'errors': errors, 'warnings': warnings}
            elif warnings:
                response['overall_health'] = 'WARNING'
                response['health_messages'] = {'warnings': warnings}
            else:
                response['overall_health'] = 'HEALTHY'
                response['health_messages'] = {'info': ['All systems operational']}

            return jsonify(response), 200

        except Exception as e:
            logger.error(f"Error getting safety monitor status: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'error': str(e),
                'overall_health': 'UNKNOWN'
            }), 500

    logger.info("✅ WebUI app created (Port 9905)")
    return app


# ============================================================================
# SERVER STARTUP
# ============================================================================

def run_app(app, port, name):
    """Run Flask app on specified port"""
    try:
        logger.info(f"🚀 Starting {name} server on port {port}...")
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"❌ Failed to start {name} server: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point"""
    logger.info("="*70)
    logger.info("🚀 ngTradingBot Core Server Starting...")
    logger.info("="*70)
    
    # Initialize database
    logger.info("📊 Initializing database...")
    try:
        init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        sys.exit(1)
    
    # Initialize Redis
    logger.info("🔴 Initializing Redis...")
    try:
        init_redis()
        logger.info("✅ Redis initialized")
    except Exception as e:
        logger.error(f"❌ Redis initialization failed: {e}", exc_info=True)
        sys.exit(1)
    
    # Initialize core communication
    logger.info("📡 Initializing core communication system...")
    try:
        init_core_communication()
        logger.info("✅ Core communication initialized")
    except Exception as e:
        logger.error(f"❌ Core communication initialization failed: {e}", exc_info=True)
        sys.exit(1)
    
    # Start tick batch writer
    logger.info("📊 Starting tick batch writer...")
    try:
        start_batch_writer()
        logger.info("✅ Tick batch writer started")
    except Exception as e:
        logger.error(f"❌ Tick batch writer failed to start: {e}", exc_info=True)
        # Non-critical, continue
    
    # Start backup scheduler
    logger.info("💾 Starting backup scheduler...")
    try:
        start_backup_scheduler()
        logger.info("✅ Backup scheduler started")
    except Exception as e:
        logger.error(f"❌ Backup scheduler failed to start: {e}", exc_info=True)
        # Non-critical, continue
    
    # Create Flask apps
    logger.info("🌐 Creating Flask applications...")
    app_command = create_command_app()
    app_ticks = create_ticks_app()
    app_trades = create_trades_app()
    app_logs = create_logs_app()
    app_webui = create_webui_app()
    
    # Create SocketIO for WebUI (for real-time updates)
    logger.info("🔌 Initializing WebSocket (SocketIO)...")
    socketio = SocketIO(app_webui, cors_allowed_origins="*", async_mode='threading')
    logger.info("✅ WebSocket initialized")
    
    # Start servers in separate threads
    logger.info("🚀 Starting multi-port servers...")
    
    threads = [
        Thread(target=run_app, args=(app_command, 9900, "Command & Control"), daemon=True, name="Port-9900"),
        Thread(target=run_app, args=(app_ticks, 9901, "Tick Data"), daemon=True, name="Port-9901"),
        Thread(target=run_app, args=(app_trades, 9902, "Trade Sync"), daemon=True, name="Port-9902"),
        Thread(target=run_app, args=(app_logs, 9903, "Logging"), daemon=True, name="Port-9903"),
    ]
    
    for thread in threads:
        thread.start()
        logger.info(f"✅ Started thread: {thread.name}")
    
    # Start WebUI with SocketIO (this blocks)
    logger.info("="*70)
    logger.info("✅ All core servers started successfully!")
    logger.info("="*70)
    logger.info("📋 Server Ports:")
    logger.info("   🎮 Command & Control: http://0.0.0.0:9900")
    logger.info("   📊 Tick Data:         http://0.0.0.0:9901")
    logger.info("   💹 Trade Sync:        http://0.0.0.0:9902")
    logger.info("   📝 Logging:           http://0.0.0.0:9903")
    logger.info("   🌐 WebUI:             http://0.0.0.0:9905")
    logger.info("="*70)
    logger.info("🔥 System ready - EA can connect now!")
    logger.info("="*70)
    
    try:
        # Run WebUI with SocketIO (blocking call)
        socketio.run(app_webui, host='0.0.0.0', port=9905, debug=False)
    except KeyboardInterrupt:
        logger.info("\n⏸️  Shutdown signal received...")
    except Exception as e:
        logger.error(f"❌ WebUI server error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("👋 ngTradingBot Core Server stopped")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⏸️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)

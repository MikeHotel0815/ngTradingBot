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

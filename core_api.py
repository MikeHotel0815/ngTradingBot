#!/usr/bin/env python3
"""
Core API Endpoints for EA Communication
========================================
Essential API endpoints for MT5 EA <-> Server communication

This module contains ONLY the core endpoints needed for EA communication.
All strategy, UI, and analysis functionality is in separate modules.

Endpoints:
----------
Port 9900 (Command & Control):
- POST /api/connect - EA initial connection
- POST /api/heartbeat - EA status updates (every 30s)
- POST /api/get_commands - Poll for pending commands
- POST /api/command_response - EA command execution results

Port 9901 (Tick Data):
- POST /api/ticks/batch - Batch tick data upload

Port 9902 (Trade Sync):
- POST /api/trades/sync - Full trade state synchronization

Port 9903 (Logging):
- POST /api/log - EA log messages

Author: ngTradingBot
Last Modified: 2025-10-25
"""

# Import trade utilities for metadata enrichment
from trade_utils import enrich_trade_metadata

from flask import request, jsonify
import logging
from datetime import datetime
from typing import Dict, List, Optional

from database import ScopedSession
from models import Account, BrokerSymbol, SubscribedSymbol, Log, Trade
from auth import require_api_key, get_or_create_account
from core_communication import (
    get_core_comm,
    CommandPriority,
    send_command_to_ea,
    get_ea_status,
    is_ea_connected
)
from tick_batch_writer import get_batch_writer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# PORT 9900: COMMAND & CONTROL ENDPOINTS
# ============================================================================

def register_command_endpoints(app):
    """Register command & control endpoints on Flask app"""
    
    @app.route('/api/connect', methods=['POST'])
    @require_api_key
    def connect(account: Account):
        """
        Initial EA connection
        
        EA calls this on startup to register with server and receive configuration
        
        Request:
        {
            "account": 12345678,
            "broker": "Pepperstone",
            "platform": "MT5",
            "timestamp": 1234567890,
            "available_symbols": ["EURUSD", "XAUUSD", ...]
        }
        
        Response:
        {
            "status": "success",
            "session_id": "session_12345678_1234567890",
            "subscribed_symbols": ["EURUSD", "XAUUSD"],
            "server_time": "2025-10-17T12:00:00"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            account_number = data.get('account')
            broker = data.get('broker')
            available_symbols = data.get('available_symbols', [])
            
            # Register connection with core communication manager
            core_comm = get_core_comm()
            conn = core_comm.register_connection(
                account_id=account.id,
                account_number=account_number,
                broker=broker
            )
            
            # Update broker symbols if provided
            if available_symbols:
                with ScopedSession() as db:
                    for symbol_data in available_symbols:
                        symbol = symbol_data.get('symbol')
                        
                        if not symbol:
                            continue
                        
                        # Check if symbol exists in broker_symbols
                        broker_sym = db.query(BrokerSymbol).filter_by(symbol=symbol).first()
                        
                        if not broker_sym:
                            # Create new broker symbol
                            broker_sym = BrokerSymbol(
                                symbol=symbol,
                                description=symbol_data.get('description', ''),
                                volume_min=symbol_data.get('volume_min', 0.01),
                                volume_max=symbol_data.get('volume_max', 100.0),
                                volume_step=symbol_data.get('volume_step', 0.01),
                                stops_level=symbol_data.get('stops_level', 0),
                                freeze_level=symbol_data.get('freeze_level', 0),
                                trade_mode=symbol_data.get('trade_mode', 7),
                                digits=symbol_data.get('digits', 5),
                                point_value=symbol_data.get('point_value', 0.00001)
                            )
                            db.add(broker_sym)
                        else:
                            # Update existing
                            broker_sym.description = symbol_data.get('description', broker_sym.description)
                            broker_sym.volume_min = symbol_data.get('volume_min', broker_sym.volume_min)
                            broker_sym.volume_max = symbol_data.get('volume_max', broker_sym.volume_max)
                            broker_sym.volume_step = symbol_data.get('volume_step', broker_sym.volume_step)
                            broker_sym.stops_level = symbol_data.get('stops_level', broker_sym.stops_level)
                            broker_sym.freeze_level = symbol_data.get('freeze_level', broker_sym.freeze_level)
                            broker_sym.trade_mode = symbol_data.get('trade_mode', broker_sym.trade_mode)
                            broker_sym.digits = symbol_data.get('digits', broker_sym.digits)
                            broker_sym.point_value = symbol_data.get('point_value', broker_sym.point_value)
                            broker_sym.last_updated = datetime.utcnow()
                    
                    db.commit()
                    logger.info(f"✅ Updated {len(available_symbols)} broker symbols for account {account_number}")
            
            # Get subscribed symbols for this account
            with ScopedSession() as db:
                subscribed = db.query(SubscribedSymbol).filter_by(
                    account_id=account.id,
                    active=True
                ).all()
                
                subscribed_symbols = [s.symbol for s in subscribed]
            
            logger.info(f"✅ EA connected: Account {account_number} from {broker}")
            
            return jsonify({
                'status': 'success',
                'session_id': f"session_{account_number}_{int(datetime.utcnow().timestamp())}",
                'subscribed_symbols': subscribed_symbols,
                'server_time': datetime.utcnow().isoformat(),
                'health_status': conn.get_status_dict()
            }), 200
        
        except Exception as e:
            logger.error(f"❌ Connection error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/heartbeat', methods=['POST'])
    @require_api_key
    def heartbeat(account: Account):
        """
        EA heartbeat - status updates every 30 seconds
        
        Request:
        {
            "account": 12345678,
            "balance": 10000.00,
            "equity": 10050.00,
            "margin": 100.00,
            "free_margin": 9950.00,
            "open_positions": 2,
            "latency_ms": 45.3
        }
        
        Response:
        {
            "status": "success",
            "commands": [...],
            "server_time": "2025-10-17T12:00:00"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            balance = float(data.get('balance', 0))
            equity = float(data.get('equity', 0))
            margin = float(data.get('margin', 0))
            free_margin = float(data.get('free_margin', 0))
            latency_ms = float(data.get('latency_ms', 0))
            
            # Process heartbeat through core communication manager
            core_comm = get_core_comm()
            response = core_comm.process_heartbeat(
                account_id=account.id,
                balance=balance,
                equity=equity,
                margin=margin,
                free_margin=free_margin,
                latency_ms=latency_ms
            )
            
            return jsonify(response), 200
        
        except Exception as e:
            logger.error(f"❌ Heartbeat error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/get_commands', methods=['POST'])
    @require_api_key
    def get_commands(account: Account):
        """
        EA polls for pending commands (every 1 second)
        
        Request:
        {
            "account": 12345678
        }
        
        Response:
        {
            "commands": [
                {
                    "id": "cmd_12345678_1697551200",
                    "type": "OPEN_TRADE",
                    "symbol": "EURUSD",
                    "order_type": "BUY",
                    "volume": 0.1,
                    "sl": 1.0850,
                    "tp": 1.0950
                }
            ]
        }
        """
        try:
            core_comm = get_core_comm()
            commands = core_comm.get_pending_commands(account.id, limit=10)
            
            return jsonify({
                'commands': commands
            }), 200
        
        except Exception as e:
            logger.error(f"❌ Get commands error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e),
                'commands': []
            }), 500
    
    @app.route('/api/command_response', methods=['POST'])
    @require_api_key
    def command_response(account: Account):
        """
        EA sends command execution result
        
        Request:
        {
            "account": 12345678,
            "command_id": "cmd_12345678_1697551200",
            "status": "completed" | "failed",
            "response": {
                "ticket": 16218652,
                "open_price": 1.0900,
                "sl": 1.0850,
                "tp": 1.0950
            }
        }
        
        Response:
        {
            "status": "success",
            "command_id": "cmd_12345678_1697551200"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            command_id = data.get('command_id')
            status = data.get('status')
            response_data = data.get('response', {})
            
            if not command_id or not status:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing command_id or status'
                }), 400
            
            # Process response through core communication manager
            core_comm = get_core_comm()
            result = core_comm.process_command_response(
                command_id=command_id,
                status=status,
                response_data=response_data
            )
            
            return jsonify(result), 200
        
        except Exception as e:
            logger.error(f"❌ Command response error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/disconnect', methods=['POST'])
    @require_api_key
    def disconnect(account: Account):
        """
        EA disconnection notification
        
        Request:
        {
            "account": 12345678,
            "reason": "Normal shutdown"
        }
        
        Response:
        {
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            reason = data.get('reason', 'Unknown') if data else 'Unknown'
            
            # Remove connection
            core_comm = get_core_comm()
            core_comm.remove_connection(account.id)
            
            logger.info(f"🔌 EA disconnected: Account {account.mt5_account_number} - {reason}")
            
            return jsonify({'status': 'success'}), 200
        
        except Exception as e:
            logger.error(f"❌ Disconnect error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/status', methods=['GET'])
    def api_status():
        """
        Get API status (no auth required for monitoring)
        
        Response:
        {
            "status": "running",
            "server_time": "2025-10-17T12:00:00",
            "connections": {...},
            "commands": {...}
        }
        """
        try:
            core_comm = get_core_comm()
            system_status = core_comm.get_system_status()
            
            return jsonify({
                'status': 'running',
                **system_status
            }), 200
        
        except Exception as e:
            logger.error(f"❌ Status error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500


# ============================================================================
# PORT 9901: TICK DATA ENDPOINTS
# ============================================================================

def register_tick_endpoints(app):
    """Register tick data endpoints on Flask app"""
    
    @app.route('/api/ticks/batch', methods=['POST'])
    @require_api_key
    def ticks_batch(account: Account):
        """
        Receive batch of ticks from EA
        
        Request:
        {
            "account": 12345678,
            "ticks": [
                {
                    "symbol": "EURUSD",
                    "bid": 1.0900,
                    "ask": 1.0902,
                    "timestamp": 1697551200
                },
                ...
            ]
        }
        
        Response:
        {
            "status": "success",
            "processed": 10,
            "server_time": "2025-10-17T12:00:00"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            ticks = data.get('ticks', [])
            
            if not ticks:
                return jsonify({'status': 'success', 'processed': 0}), 200
            
            # Process ticks through core communication manager
            core_comm = get_core_comm()
            result = core_comm.process_tick_batch(account.id, ticks)
            
            # Send ticks to batch writer for database storage
            batch_writer = get_batch_writer()
            if batch_writer:
                batch_writer.enqueue_ticks(ticks)
            
            return jsonify(result), 200
        
        except Exception as e:
            logger.error(f"❌ Tick batch error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500


# ============================================================================
# PORT 9902: TRADE SYNC ENDPOINTS
# ============================================================================

def register_trade_endpoints(app):
    """Register trade sync endpoints on Flask app"""
    
    @app.route('/api/trades/sync', methods=['POST'])
    @require_api_key
    def trades_sync(account: Account):
        """
        Sync all open trades from EA (EA is source of truth)
        
        Request:
        {
            "account": 12345678,
            "trades": [
                {
                    "ticket": 16218652,
                    "symbol": "EURUSD",
                    "direction": "BUY",
                    "volume": 0.1,
                    "open_price": 1.0900,
                    "open_time": 1697551200,
                    "sl": 1.0850,
                    "tp": 1.0950,
                    "profit": 5.50,
                    "swap": 0.00,
                    "commission": -0.50
                },
                ...
            ]
        }
        
        Response:
        {
            "status": "success",
            "reconciliation": {
                "total_ea_trades": 5,
                "total_db_trades": 6,
                "closed_trades": 1,
                "new_trades": 0,
                "updated_trades": 5
            }
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            ea_trades = data.get('trades', [])
            
            # Sync trades through core communication manager
            core_comm = get_core_comm()
            result = core_comm.sync_trades_from_ea(account.id, ea_trades)
            
            return jsonify(result), 200
        
        except Exception as e:
            logger.error(f"❌ Trade sync error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/trades/opened', methods=['POST'])
    @require_api_key
    def trade_opened(account: Account):
        """
        EA notifies server that a trade was opened
        
        Request:
        {
            "account": 12345678,
            "ticket": 16218652,
            "symbol": "EURUSD",
            "direction": "BUY",
            "volume": 0.1,
            "open_price": 1.0900,
            "sl": 1.0850,
            "tp": 1.0950,
            "comment": "Signal #123",
            "timestamp": 1697551200
        }
        
        Response:
        {
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            ticket = data.get('ticket')
            symbol = data.get('symbol')
            direction = data.get('direction')
            volume = float(data.get('volume', 0))
            open_price = float(data.get('open_price', 0))
            sl = float(data.get('sl', 0))
            tp = float(data.get('tp', 0))
            comment = data.get('comment', '')
            timestamp = data.get('timestamp')
            
            # Check if trade already exists
            with ScopedSession() as db:
                existing = db.query(Trade).filter_by(
                    account_id=account.id,
                    mt5_ticket=ticket
                ).first()
                
                if existing:
                    logger.warning(f"⚠️  Trade {ticket} already exists in database")
                    return jsonify({'status': 'success', 'message': 'Trade already exists'}), 200
                
                # Create new trade
                trade = Trade(
                    account_id=account.id,
                    mt5_ticket=ticket,
                    symbol=symbol,
                    direction=direction,
                    volume=volume,
                    open_price=open_price,
                    open_time=datetime.fromtimestamp(timestamp) if timestamp else datetime.utcnow(),
                    current_sl=sl,
                    current_tp=tp,
                    initial_sl=sl,  # Store initial SL for R:R calculation
                    initial_tp=tp,  # Store initial TP for R:R calculation
                    status='open',
                    source='ea_notification',
                    entry_reason=comment
                )

                # Enrich trade with session and other metadata
                enrich_trade_metadata(trade)

                db.add(trade)
                db.commit()
                
                logger.info(
                    f"📈 Trade opened: {symbol} {direction} {volume} @ {open_price} | "
                    f"Ticket: {ticket} | Account: {account.mt5_account_number}"
                )
            
            return jsonify({'status': 'success'}), 200
        
        except Exception as e:
            logger.error(f"❌ Trade opened error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/trades/closed', methods=['POST'])
    @require_api_key
    def trade_closed(account: Account):
        """
        EA notifies server that a trade was closed
        
        Request:
        {
            "account": 12345678,
            "ticket": 16218652,
            "close_price": 1.0920,
            "close_reason": "TP_HIT",
            "profit": 20.00,
            "swap": 0.00,
            "commission": -0.50,
            "timestamp": 1697551800
        }
        
        Response:
        {
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            ticket = data.get('ticket')
            close_price = float(data.get('close_price', 0))
            close_reason = data.get('close_reason', 'UNKNOWN')
            profit = float(data.get('profit', 0))
            swap = float(data.get('swap', 0))
            commission = float(data.get('commission', 0))
            timestamp = data.get('timestamp')
            
            # Update trade in database
            with ScopedSession() as db:
                trade = db.query(Trade).filter_by(
                    account_id=account.id,
                    mt5_ticket=ticket
                ).first()
                
                if not trade:
                    logger.error(f"❌ Trade {ticket} not found for close notification")
                    return jsonify({
                        'status': 'error',
                        'message': f'Trade {ticket} not found'
                    }), 404
                
                trade.status = 'closed'
                trade.close_price = close_price
                trade.close_time = datetime.fromtimestamp(timestamp) if timestamp else datetime.utcnow()
                trade.close_reason = close_reason
                trade.profit = profit
                trade.swap = swap
                trade.commission = commission

                # Calculate trade metrics (R:R, duration, pips)
                from trade_utils import calculate_trade_metrics_on_close
                calculate_trade_metrics_on_close(trade)

                db.commit()
                
                logger.info(
                    f"📉 Trade closed: {trade.symbol} {trade.direction} | "
                    f"Ticket: {ticket} | Profit: €{profit:.2f} | Reason: {close_reason}"
                )
            
            return jsonify({'status': 'success'}), 200
        
        except Exception as e:
            logger.error(f"❌ Trade closed error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/trades/modified', methods=['POST'])
    @require_api_key
    def trade_modified(account: Account):
        """
        EA notifies server that a trade was modified
        
        Request:
        {
            "account": 12345678,
            "ticket": 16218652,
            "sl": 1.0860,
            "tp": 1.0950,
            "timestamp": 1697551500
        }
        
        Response:
        {
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            ticket = data.get('ticket')
            sl = float(data.get('sl', 0))
            tp = float(data.get('tp', 0))
            
            # Update trade in database
            with ScopedSession() as db:
                trade = db.query(Trade).filter_by(
                    account_id=account.id,
                    mt5_ticket=ticket,
                    status='open'
                ).first()
                
                if not trade:
                    logger.error(f"❌ Trade {ticket} not found for modify notification")
                    return jsonify({
                        'status': 'error',
                        'message': f'Trade {ticket} not found'
                    }), 404
                
                old_sl = trade.current_sl
                old_tp = trade.current_tp
                
                trade.current_sl = sl
                trade.current_tp = tp
                
                db.commit()
                
                logger.info(
                    f"🔧 Trade modified: Ticket {ticket} | "
                    f"SL: {old_sl}->{sl} | TP: {old_tp}->{tp}"
                )
            
            return jsonify({'status': 'success'}), 200
        
        except Exception as e:
            logger.error(f"❌ Trade modified error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500


# ============================================================================
# PORT 9903: LOGGING ENDPOINTS
# ============================================================================

def register_log_endpoints(app):
    """Register logging endpoints on Flask app"""
    
    @app.route('/api/log', methods=['POST'])
    @require_api_key
    def log_event(account: Account):
        """
        Receive log message from EA
        
        Request:
        {
            "account": 12345678,
            "level": "INFO" | "WARNING" | "ERROR",
            "message": "Trade opened successfully",
            "details": {
                "info": "Ticket: 16218652, Symbol: EURUSD"
            }
        }
        
        Response:
        {
            "status": "success"
        }
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'status': 'error', 'message': 'No data provided'}), 400
            
            level = data.get('level', 'INFO')
            message = data.get('message', '')
            details = data.get('details', {})
            
            # Store log in database
            with ScopedSession() as db:
                log = Log(
                    account_id=account.id,
                    level=level,
                    message=message,
                    details=details,
                    timestamp=datetime.utcnow()
                )
                db.add(log)
                db.commit()
            
            # Also log to server logs
            log_func = {
                'INFO': logger.info,
                'WARNING': logger.warning,
                'ERROR': logger.error
            }.get(level, logger.info)
            
            log_func(f"[EA-{account.mt5_account_number}] {message}")
            
            return jsonify({'status': 'success'}), 200
        
        except Exception as e:
            logger.error(f"❌ Log error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500


# ============================================================================
# HELPER FUNCTIONS FOR OTHER MODULES
# ============================================================================

def send_open_trade_command(
    account_id: int,
    symbol: str,
    order_type: str,
    volume: float,
    sl: float,
    tp: float,
    comment: str = ""
) -> str:
    """
    Send OPEN_TRADE command to EA
    
    Returns:
        command_id
    """
    return send_command_to_ea(
        account_id=account_id,
        command_type="OPEN_TRADE",
        payload={
            'symbol': symbol,
            'order_type': order_type,
            'volume': volume,
            'sl': sl,
            'tp': tp,
            'comment': comment
        },
        priority=CommandPriority.NORMAL
    )


def send_modify_trade_command(
    account_id: int,
    ticket: int,
    sl: float,
    tp: float
) -> str:
    """
    Send MODIFY_TRADE command to EA
    
    Returns:
        command_id
    """
    return send_command_to_ea(
        account_id=account_id,
        command_type="MODIFY_TRADE",
        payload={
            'ticket': ticket,
            'sl': sl,
            'tp': tp
        },
        priority=CommandPriority.HIGH
    )


def send_close_trade_command(
    account_id: int,
    ticket: int
) -> str:
    """
    Send CLOSE_TRADE command to EA
    
    Returns:
        command_id
    """
    return send_command_to_ea(
        account_id=account_id,
        command_type="CLOSE_TRADE",
        payload={
            'ticket': ticket
        },
        priority=CommandPriority.HIGH
    )


def send_close_all_command(
    account_id: int,
    symbol: Optional[str] = None
) -> str:
    """
    Send CLOSE_ALL command to EA
    
    Args:
        account_id: Account ID
        symbol: Optional symbol filter (close all trades for this symbol only)
    
    Returns:
        command_id
    """
    payload = {}
    if symbol:
        payload['symbol'] = symbol
    
    return send_command_to_ea(
        account_id=account_id,
        command_type="CLOSE_ALL",
        payload=payload,
        priority=CommandPriority.CRITICAL
    )

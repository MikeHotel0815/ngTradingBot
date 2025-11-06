"""
ngTradingBot Main Server Application
Multi-Port Flask Server with PostgreSQL backend
"""

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
from sqlalchemy import text
import logging
import os
from threading import Thread
import pytz

# Import database and models
from database import init_db, ScopedSession, cleanup_old_ticks
from models import Account, SubscribedSymbol, Log, Tick, OHLCData, BrokerSymbol, Command, AccountTransaction, TradingSignal, Trade
from auth import require_api_key, get_or_create_account
from backup_scheduler import start_backup_scheduler, get_scheduler
from redis_client import init_redis, get_redis
from tick_batch_writer import start_batch_writer, get_batch_writer
from command_helper import create_command
from worker_status_api import worker_status_bp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask apps for different ports
app_command = Flask('command')  # Port 9900
app_ticks = Flask('ticks')  # Port 9901
app_trades = Flask('trades')  # Port 9902
app_logs = Flask('logs')  # Port 9903
app_webui = Flask('webui', template_folder='templates')  # Port 9905
socketio = SocketIO(app_webui, cors_allowed_origins="*")

# Register worker status API blueprint
app_webui.register_blueprint(worker_status_bp)

# Enable CORS for all apps (allow cross-port requests)
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, x-api-key'
    return response

# Handle OPTIONS preflight requests
@app_command.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = Flask.response_class()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, x-api-key'
        return response

app_command.after_request(add_cors_headers)
app_ticks.after_request(add_cors_headers)
app_trades.after_request(add_cors_headers)
app_logs.after_request(add_cors_headers)
app_webui.after_request(add_cors_headers)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_symbol_tradeable_now(symbol):
    """
    Check if a symbol is currently tradeable based on market hours.
    This is server-side validation independent of tick data.
    """
    now_utc = datetime.now(pytz.UTC)

    # Determine symbol type
    symbol_upper = symbol.upper()

    # Crypto markets are 24/7
    if any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'XRP', 'LTC', 'DOGE', 'ADA']):
        return True

    # Forex markets (closed on weekends)
    if any(curr in symbol_upper for curr in ['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD', 'NZD']):
        weekday = now_utc.weekday()  # 0=Monday, 6=Sunday
        hour = now_utc.hour

        # Saturday (5) and Sunday (6) are closed
        if weekday == 5 or weekday == 6:
            return False

        # Friday after 22:00 UTC is considered closed (weekend starts)
        if weekday == 4 and hour >= 22:
            return False

        # Sunday before 22:00 UTC is considered closed (weekend not over)
        # Note: weekday 6 is already handled above, but keeping this for clarity
        if weekday == 6 and hour < 22:
            return False

    # For other instruments, check if we have recent tick data (within last 5 minutes)
    # If ticks are old, consider it not tradeable
    return True


def validate_confidence(value, param_name='confidence'):
    """
    Validate confidence value is in valid range.

    Args:
        value: Confidence value to validate
        param_name: Name of parameter for error messages

    Returns:
        Validated float value

    Raises:
        ValueError: If value is invalid
    """
    try:
        conf = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{param_name} must be a number, got: {value}')

    if conf < 0 or conf > 100:
        raise ValueError(f'{param_name} must be between 0 and 100, got: {conf}')

    if conf < 30:
        logger.warning(f'{param_name} is very low ({conf}%) - this may generate too many signals')

    if conf > 95:
        logger.warning(f'{param_name} is very high ({conf}%) - this may miss good opportunities')

    return conf


def validate_numeric_range(value, param_name, min_val=None, max_val=None):
    """
    Validate numeric value is in valid range.

    Args:
        value: Value to validate
        param_name: Name of parameter for error messages
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)

    Returns:
        Validated float value

    Raises:
        ValueError: If value is invalid
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{param_name} must be a number, got: {value}')

    if min_val is not None and num < min_val:
        raise ValueError(f'{param_name} must be >= {min_val}, got: {num}')

    if max_val is not None and num > max_val:
        raise ValueError(f'{param_name} must be <= {max_val}, got: {num}')

    return num


def get_trade_opening_reason(trade):
    """
    Helper function to determine how a trade was opened
    Uses multiple fallback strategies to provide accurate information
    
    Args:
        trade: Trade model instance
    
    Returns:
        str: Human-readable opening reason
    """
    # Priority 1: Check if from autotrade with signal_id
    if trade.source == "autotrade" and trade.signal_id:
        reason = f"Signal #{trade.signal_id}"
        if trade.timeframe:
            reason += f" ({trade.timeframe})"
        return reason
    
    # Priority 2: Check if autotrade without signal_id (shouldn't happen but handle it)
    if trade.source == "autotrade":
        reason = "Auto-Trade Signal"
        if trade.timeframe:
            reason += f" ({trade.timeframe})"
        return reason
    
    # Priority 3: Check for entry_reason field (may contain signal info)
    if trade.entry_reason and "signal" in trade.entry_reason.lower():
        return f"Signal: {trade.entry_reason[:50]}"  # Truncate if long
    
    # Priority 4: Check source
    if trade.source == "ea_command":
        return "EA Command"
    
    # Priority 5: Check command_id (means it came from server command)
    if trade.command_id:
        return "Server Command"
    
    # Default: Manual MT5 trade
    return "Manual (MT5)"


# ============================================================================
# PORT 9900 - COMMAND & CONTROL
# ============================================================================

@app_command.route('/api/connect', methods=['POST'])
def connect():
    """
    Initial EA connection - creates account if new, returns API key
    """
    try:
        data = request.get_json()
        account_number = data.get('account')
        broker = data.get('broker', 'Unknown')
        platform = data.get('platform', 'MT5')

        if not account_number:
            return jsonify({'status': 'error', 'message': 'Missing account number'}), 400

        db = ScopedSession()
        try:
            # Get or create account
            account, api_key, is_new = get_or_create_account(db, account_number, broker)

            # Update last heartbeat
            account.last_heartbeat = datetime.utcnow()

            # Store available symbols from EA (BrokerSymbols are now global)
            available_symbols = data.get('available_symbols', [])
            if available_symbols:
                # Upsert broker symbols (no account_id - symbols are global now)
                for symbol in available_symbols:
                    # Check if symbol already exists
                    existing = db.query(BrokerSymbol).filter_by(symbol=symbol).first()
                    if existing:
                        # Update last_updated timestamp
                        existing.last_updated = datetime.utcnow()
                    else:
                        # Create new broker symbol
                        broker_symbol = BrokerSymbol(
                            symbol=symbol,
                            last_updated=datetime.utcnow()
                        )
                        db.add(broker_symbol)

                logger.info(f"Updated {len(available_symbols)} broker symbols (global)")

            db.commit()

            # Get subscribed symbols
            symbols = db.query(SubscribedSymbol).filter_by(
                account_id=account.id,
                active=True
            ).all()

            symbol_list = [
                {'symbol': s.symbol, 'mode': s.tick_mode}
                for s in symbols
            ]

            logger.info(f"{'New' if is_new else 'Existing'} account connected: {account_number} ({broker})")

            return jsonify({
                'status': 'success',
                'message': 'Connected successfully',
                'api_key': api_key,
                'is_new': is_new,
                'subscribed_symbols': symbol_list,
                'server_time': datetime.utcnow().isoformat()
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/heartbeat', methods=['POST'])
@require_api_key
def heartbeat(account, db):
    """
    Regular heartbeat from EA with account status
    """
    try:
        data = request.get_json()
        balance = data.get('balance')
        equity = data.get('equity')
        margin = data.get('margin')
        free_margin = data.get('free_margin')
        profit_today = data.get('profit_today')
        profit_week = data.get('profit_week')
        profit_month = data.get('profit_month')
        profit_year = data.get('profit_year')
        deposits_today = data.get('deposits_today')
        deposits_week = data.get('deposits_week')
        deposits_month = data.get('deposits_month')
        deposits_year = data.get('deposits_year')

        # ✅ UPDATED: Use profit values from MT5 EA (now excludes deposits/withdrawals)
        # EA's GetProfitSince() function filters out DEAL_TYPE_BALANCE operations
        # This gives us accurate trading profit without manual recalculation
        actual_profit_today = profit_today if profit_today is not None else 0.0
        actual_profit_week = profit_week if profit_week is not None else 0.0
        actual_profit_month = profit_month if profit_month is not None else 0.0
        actual_profit_year = profit_year if profit_year is not None else 0.0
        
        # Deposits/Withdrawals (separate from profit)
        actual_deposits_today = deposits_today if deposits_today is not None else 0.0
        actual_deposits_week = deposits_week if deposits_week is not None else 0.0
        actual_deposits_month = deposits_month if deposits_month is not None else 0.0
        actual_deposits_year = deposits_year if deposits_year is not None else 0.0
        # The initial balance is not a withdrawal, it's starting capital
        # Update last heartbeat and account data
        account.last_heartbeat = datetime.utcnow()
        if balance is not None:
            account.balance = balance
        if equity is not None:
            account.equity = equity
        if margin is not None:
            account.margin = margin
        if free_margin is not None:
            account.free_margin = free_margin

        # Use profits and deposits from MT5 EA
        account.profit_today = actual_profit_today
        account.profit_week = actual_profit_week
        account.profit_month = actual_profit_month
        account.profit_year = actual_profit_year
        account.deposits_today = actual_deposits_today
        account.deposits_week = actual_deposits_week
        account.deposits_month = actual_deposits_month
        account.deposits_year = actual_deposits_year
        
        db.commit()

        logger.info(f"Heartbeat from {account.mt5_account_number} - Balance: {balance}, Equity: {equity}, Profit: Today={actual_profit_today} Month={actual_profit_month}, Deposits: Month={actual_deposits_month}")

        # ✅ NEW: Auto TP/SL for manual MT5 trades without protection
        try:
            from auto_tp_sl_manager import get_auto_tpsl_manager
            auto_tpsl = get_auto_tpsl_manager()
            auto_tpsl.check_and_set_tp_sl(account.id, db)
        except Exception as e:
            logger.error(f"Error in auto TP/SL check: {e}", exc_info=True)

        # Broadcast account update via WebSocket
        socketio.emit('account_update', {
            'number': account.mt5_account_number,
            'balance': float(balance) if balance else 0.0,
            'equity': float(equity) if equity else 0.0,
            'margin': float(margin) if margin else 0.0,
            'free_margin': float(free_margin) if free_margin else 0.0
        })

        # Broadcast profit update via WebSocket (with actual values from trades)
        socketio.emit('profit_update', {
            'today': float(actual_profit_today),
            'week': float(actual_profit_week),
            'month': float(actual_profit_month),
            'year': float(actual_profit_year)
        })

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Heartbeat error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/profit_update', methods=['POST'])
@require_api_key
def profit_update(account, db):
    """
    Instant profit update from EA when trade closes (OnTrade event)
    ✅ UPDATED 2025-11-05: Always use EA data directly, no corrections
    EA already filters out deposits/withdrawals in GetProfitSince()
    """
    try:
        data = request.get_json()
        balance = data.get('balance')
        equity = data.get('equity')
        profit_today = data.get('profit_today')
        profit_week = data.get('profit_week')
        profit_month = data.get('profit_month')
        profit_year = data.get('profit_year')

        # ✅ DIRECT EA DATA: No corrections needed, EA sends accurate trading profits
        # EA's GetProfitSince() already excludes DEAL_TYPE_BALANCE operations
        actual_profit_today = profit_today if profit_today is not None else 0.0
        actual_profit_week = profit_week if profit_week is not None else 0.0
        actual_profit_month = profit_month if profit_month is not None else 0.0
        actual_profit_year = profit_year if profit_year is not None else 0.0

        # Update account data
        if balance is not None:
            account.balance = balance
        if equity is not None:
            account.equity = equity

        # Use EA profits directly
        account.profit_today = actual_profit_today
        account.profit_week = actual_profit_week
        account.profit_month = actual_profit_month
        account.profit_year = actual_profit_year

        db.commit()

        logger.info(f"Instant profit update from {account.mt5_account_number} - Profit Today: {actual_profit_today}")

        # Broadcast account update via WebSocket
        socketio.emit('account_update', {
            'number': account.mt5_account_number,
            'balance': float(balance) if balance else 0.0,
            'equity': float(equity) if equity else 0.0,
            'margin': float(account.margin) if account.margin else 0.0,
            'free_margin': float(account.free_margin) if account.free_margin else 0.0
        })

        # Broadcast profit update via WebSocket (with EA values)
        socketio.emit('profit_update', {
            'today': float(actual_profit_today),
            'week': float(actual_profit_week),
            'month': float(actual_profit_month),
            'year': float(actual_profit_year)
        })

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Profit update error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/get_commands', methods=['POST'])
@require_api_key
def get_commands(account, db):
    """
    Get pending commands for EA (Redis-based instant delivery)
    OPTIMIZED: Always check PostgreSQL first and push to Redis for instant delivery
    """
    try:
        redis = get_redis()

        # STEP 1: Check PostgreSQL for NEW pending commands and push to Redis
        # Only process commands with status='pending' (not 'executing')
        # Commands created via /api/create_command are already in Redis with status='executing'
        pending_commands = db.query(Command).filter_by(
            account_id=account.id,
            status='pending'
        ).limit(50).all()

        for cmd in pending_commands:
            # Flatten the command structure for easier EA parsing
            cmd_dict = {
                'id': cmd.id,
                'type': cmd.command_type
            }
            # Add payload fields directly (not nested)
            if cmd.payload:
                for key, value in cmd.payload.items():
                    cmd_dict[key] = value

            # Push to Redis queue for instant delivery
            redis.push_command(account.id, cmd_dict)

            # Mark as executing (retrieved from DB)
            cmd.status = 'executing'

        if pending_commands:
            db.commit()
            logger.info(f"Pushed {len(pending_commands)} pending commands to Redis queue for account {account.id}")

        # STEP 2: Pop up to 10 commands from Redis queue for delivery
        commands_data = []
        processed_command_ids = set()  # Track which commands we're sending
        
        for _ in range(10):
            cmd = redis.pop_command(account.id)
            if not cmd:
                break
            
            cmd_id = cmd.get('id')
            
            # ✅ CRITICAL: Mark command as 'processing' in database to prevent duplicate execution
            if cmd_id:
                try:
                    db_command = db.query(Command).filter_by(id=cmd_id).first()
                    if db_command:
                        # Only send if not already completed or failed
                        if db_command.status in ['pending', 'executing']:
                            # Check if we already sent this command in this batch
                            if cmd_id not in processed_command_ids:
                                db_command.status = 'processing'
                                db.commit()
                                commands_data.append(cmd)
                                processed_command_ids.add(cmd_id)
                                logger.info(f"✅ Delivering command {cmd_id} to EA (status: processing)")
                            else:
                                logger.warning(f"⚠️ Skipping duplicate command {cmd_id} in same batch")
                        else:
                            logger.warning(f"⚠️ Skipping already {db_command.status} command {cmd_id}")
                    else:
                        # Command not in DB (shouldn't happen, but send it anyway)
                        commands_data.append(cmd)
                except Exception as e:
                    logger.error(f"Error checking command {cmd_id} status: {e}")
                    # Send it anyway to avoid blocking
                    commands_data.append(cmd)
            else:
                # No ID (shouldn't happen)
                commands_data.append(cmd)

        return jsonify({
            'status': 'success',
            'commands': commands_data
        }), 200

    except Exception as e:
        logger.error(f"Get commands error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/create_command', methods=['POST'])
@require_api_key
def create_command_api(account, db):
    """
    Create a new command with instant Redis delivery
    """
    try:
        data = request.get_json()
        command_type = data.get('command_type')
        payload = data.get('payload', {})

        if not command_type:
            return jsonify({'status': 'error', 'message': 'Missing command_type'}), 400

        # Create command with Redis push for instant delivery
        command = create_command(
            db=db,
            account_id=account.id,
            command_type=command_type,
            payload=payload,
            push_to_redis=True
        )

        logger.info(f"Command {command.id} created and pushed to Redis for instant delivery")

        return jsonify({
            'status': 'success',
            'command_id': command.id,
            'command_type': command_type,
            'message': 'Command created and queued for instant execution'
        }), 201

    except Exception as e:
        logger.error(f"Create command error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/command_response', methods=['POST'])
@require_api_key
def command_response(account, db):
    """
    Receive command execution result from EA
    """
    try:
        data = request.get_json()
        command_id = data.get('command_id')
        status = data.get('status')  # 'completed' or 'failed'
        response_data = data.get('response', {})

        # Update command in database
        command = db.query(Command).filter_by(id=command_id).first()
        if command:
            command.status = status
            command.response = response_data
            command.executed_at = datetime.utcnow()
            db.commit()

            logger.info(f"Command {command_id} {status}: {response_data}")

            # Publish to Redis Pub/Sub for instant WebSocket notification
            try:
                redis = get_redis()
                redis.publish_command_response(command_id, {
                    'command_id': command_id,
                    'status': status,
                    'response': response_data,
                    'timestamp': datetime.utcnow().isoformat()
                })

                # Also broadcast to account updates channel
                socketio.emit('command_update', {
                    'command_id': command_id,
                    'status': status,
                    'response': response_data
                }, namespace='/')
            except Exception as e:
                logger.error(f"Failed to publish command response: {e}")

            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Command not found'}), 404

    except Exception as e:
        logger.error(f"Command response error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/symbols', methods=['POST'])
@require_api_key
def get_symbols(account, db):
    """
    Get subscribed symbols for this account (filtered by broker availability)
    """
    try:
        # Get subscribed symbols
        subscribed = db.query(SubscribedSymbol).filter_by(
            account_id=account.id,
            active=True
        ).all()

        # Get available broker symbols (global - no account_id)
        broker_symbols = db.query(BrokerSymbol).all()
        valid_symbols = {bs.symbol for bs in broker_symbols}

        # Filter subscribed symbols to only include valid ones
        if valid_symbols:
            symbols = [s.symbol for s in subscribed if s.symbol in valid_symbols]
        else:
            # If no broker symbols stored yet, return all subscribed
            symbols = [s.symbol for s in subscribed]

        return jsonify({
            'status': 'success',
            'symbols': symbols,
            'count': len(symbols)
        }), 200

    except Exception as e:
        logger.error(f"Get symbols error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/symbol_specs', methods=['POST'])
@require_api_key
def update_symbol_specs(account, db):
    """
    Update symbol specifications (volume limits, stops level, etc.) from EA
    Expected payload: {
        "account": 123,
        "api_key": "...",
        "symbols": [
            {
                "symbol": "DE40.c",
                "volume_min": 0.1,
                "volume_max": 500.0,
                "volume_step": 0.1,
                "stops_level": 0,
                "freeze_level": 0,
                "trade_mode": 7,
                "digits": 2,
                "point_value": 0.01
            },
            ...
        ]
    }
    """
    try:
        data = request.get_json()
        symbol_specs = data.get('symbols', [])

        if not symbol_specs:
            return jsonify({'status': 'error', 'message': 'No symbol specs provided'}), 400

        # ✅ DEBUG: Log incoming data to verify contract_size is being sent
        if symbol_specs:
            first_spec = symbol_specs[0]
            logger.info(f"📥 Receiving symbol_specs: {len(symbol_specs)} symbols, first={first_spec.get('symbol')}, has contract_size: {'contract_size' in first_spec}")

        updated_count = 0

        for spec in symbol_specs:
            symbol_name = spec.get('symbol')
            if not symbol_name:
                continue

            # Find existing broker symbol (global - no account_id)
            broker_symbol = db.query(BrokerSymbol).filter_by(
                symbol=symbol_name
            ).first()

            if broker_symbol:
                # Update specifications
                broker_symbol.volume_min = spec.get('volume_min')
                broker_symbol.volume_max = spec.get('volume_max')
                broker_symbol.volume_step = spec.get('volume_step')
                broker_symbol.stops_level = spec.get('stops_level')
                broker_symbol.freeze_level = spec.get('freeze_level')
                broker_symbol.trade_mode = spec.get('trade_mode')
                broker_symbol.digits = spec.get('digits')
                broker_symbol.point_value = spec.get('point_value')
                contract_size_value = spec.get('contract_size')
                broker_symbol.contract_size = contract_size_value  # ✅ NEW: Auto-retrieve from MT5
                broker_symbol.last_updated = datetime.utcnow()

                # ✅ DEBUG: Log contract_size value for first symbol
                if updated_count == 0:
                    logger.info(f"📊 First symbol {symbol_name}: contract_size={contract_size_value}")

                updated_count += 1

        db.commit()

        logger.info(f"Updated specifications for {updated_count} symbols")

        return jsonify({
            'status': 'success',
            'updated': updated_count
        }), 200

    except Exception as e:
        logger.error(f"Update symbol specs error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/subscribe', methods=['POST'])
@require_api_key
def subscribe(account, db):
    """
    Subscribe to symbols for monitoring
    """
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])
        mode = data.get('mode', 'default')

        if not symbols:
            return jsonify({'status': 'error', 'message': 'No symbols provided'}), 400

        # Validate symbols against broker's available symbols (global - no account_id)
        broker_symbols = db.query(BrokerSymbol).all()
        valid_symbols = {bs.symbol for bs in broker_symbols}

        added = []
        invalid = []

        for symbol_name in symbols:
            # Check if symbol is available at broker
            if valid_symbols and symbol_name not in valid_symbols:
                invalid.append(symbol_name)
                logger.warning(f"Symbol {symbol_name} not available at broker for account {account.mt5_account_number}")
                continue

            # Check if already exists
            existing = db.query(SubscribedSymbol).filter_by(
                account_id=account.id,
                symbol=symbol_name
            ).first()

            if existing:
                existing.active = True
                existing.tick_mode = mode
            else:
                new_symbol = SubscribedSymbol(
                    account_id=account.id,
                    symbol=symbol_name,
                    tick_mode=mode
                )
                db.add(new_symbol)
                added.append(symbol_name)

        db.commit()

        logger.info(f"Subscribed {account.mt5_account_number} to symbols: {added} (mode: {mode})")

        response = {
            'status': 'success' if added else 'partial' if invalid else 'error',
            'message': f'Subscribed to {len(added)} symbols',
            'added': added,
            'mode': mode
        }

        if invalid:
            response['invalid'] = invalid
            response['message'] += f', {len(invalid)} symbols not available at broker'

        return jsonify(response), 200 if added else 400

    except Exception as e:
        logger.error(f"Subscribe error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/cleanup', methods=['POST'])
@require_api_key
def manual_cleanup(account, db):
    """
    Manually trigger data cleanup
    """
    try:
        from database import cleanup_old_data

        data = request.get_json() or {}
        tick_days = data.get('tick_days', 30)
        ohlc_days = data.get('ohlc_days', 730)

        result = cleanup_old_data(db, tick_days=tick_days, ohlc_days=ohlc_days)

        logger.info(f"Manual cleanup by account {account.mt5_account_number}: {result}")

        return jsonify({
            'status': 'success',
            'result': result
        }), 200

    except Exception as e:
        logger.error(f"Manual cleanup error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/unsubscribe', methods=['POST'])
@require_api_key
def unsubscribe(account, db):
    """
    Unsubscribe from symbols
    """
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])

        if not symbols:
            return jsonify({'status': 'error', 'message': 'No symbols provided'}), 400

        # Deactivate symbols
        db.query(SubscribedSymbol).filter(
            SubscribedSymbol.account_id == account.id,
            SubscribedSymbol.symbol.in_(symbols)
        ).update({'active': False}, synchronize_session=False)

        db.commit()

        logger.info(f"Unsubscribed {account.mt5_account_number} from symbols: {symbols}")

        return jsonify({
            'status': 'success',
            'message': f'Unsubscribed from {len(symbols)} symbols'
        }), 200

    except Exception as e:
        logger.error(f"Unsubscribe error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/transaction', methods=['POST'])
@require_api_key
def receive_transaction(account, db):
    """
    Receive account transaction from EA (deposit, withdrawal, credit, etc.)
    """
    try:
        data = request.get_json()
        ticket = data.get('ticket')
        transaction_type = data.get('transaction_type')
        amount = data.get('amount')
        timestamp = data.get('timestamp')
        comment = data.get('comment', '')
        balance_after = data.get('balance')

        if not all([ticket, transaction_type, amount, timestamp]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        # Convert timestamp
        transaction_time = datetime.fromtimestamp(timestamp)

        # Check if transaction already exists
        existing = db.query(AccountTransaction).filter_by(ticket=ticket).first()
        if existing:
            logger.info(f"Transaction {ticket} already exists, skipping")
            return jsonify({'status': 'success', 'message': 'Transaction already recorded'}), 200

        # Create transaction record
        transaction = AccountTransaction(
            account_id=account.id,
            ticket=ticket,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=balance_after,
            comment=comment,
            timestamp=transaction_time
        )
        db.add(transaction)
        db.commit()

        logger.info(f"Transaction recorded: {transaction_type} {amount} for account {account.mt5_account_number}")

        # Broadcast via WebSocket
        socketio.emit('transaction_update', {
            'account': account.mt5_account_number,
            'type': transaction_type,
            'amount': float(amount),
            'balance': float(balance_after) if balance_after else None,
            'timestamp': transaction_time.isoformat(),
            'comment': comment
        })

        return jsonify({'status': 'success', 'message': 'Transaction recorded'}), 200

    except Exception as e:
        logger.error(f"Transaction receive error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/status', methods=['GET'])
def status():
    """Get server status"""
    db = ScopedSession()
    try:
        account_count = db.query(Account).count()
        active_symbols = db.query(SubscribedSymbol).filter_by(active=True).count()

        return jsonify({
            'status': 'running',
            'server_time': datetime.utcnow().isoformat(),
            'accounts': account_count,
            'active_symbols': active_symbols
        }), 200
    finally:
        db.close()


@app_command.route('/api/auto-trade/enable', methods=['POST'])
def enable_auto_trade():
    """Enable auto-trading with optional min confidence"""
    try:
        data = request.get_json() or {}
        min_confidence_raw = data.get('min_confidence', 40)  # Default 40%

        # VALIDATION: Validate confidence is in valid range
        try:
            min_confidence = validate_confidence(min_confidence_raw, 'min_confidence')
        except ValueError as ve:
            return jsonify({
                'status': 'error',
                'message': str(ve)
            }), 400

        from auto_trader import get_auto_trader
        trader = get_auto_trader()
        trader.set_min_confidence(min_confidence)
        
        # Reset circuit breaker when manually enabling
        if trader.circuit_breaker_tripped:
            trader.reset_circuit_breaker()
            logger.info("Circuit breaker was tripped - resetting it")
        
        trader.enable()

        logger.info(f"Auto-Trading ENABLED with min_confidence={min_confidence}%")
        return jsonify({
            'status': 'success',
            'message': f'Auto-Trading ENABLED (min confidence: {min_confidence}%)'
        }), 200
    except Exception as e:
        logger.error(f"Error enabling auto-trade: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/auto-trade/disable', methods=['POST'])
def disable_auto_trade():
    """Disable auto-trading (kill-switch)"""
    from auto_trader import get_auto_trader
    trader = get_auto_trader()
    trader.disable()
    return jsonify({'status': 'success', 'message': 'Auto-Trading DISABLED'}), 200


@app_command.route('/api/auto-trade/status', methods=['GET'])
def auto_trade_status():
    """Get auto-trading status"""
    from auto_trader import get_auto_trader
    trader = get_auto_trader()
    return jsonify({
        'enabled': trader.enabled,
        'min_confidence': trader.min_autotrade_confidence,
        'risk_profile': trader.risk_profile,  # ✅ NEW
        'circuit_breaker_enabled': trader.circuit_breaker_enabled,
        'circuit_breaker_tripped': trader.circuit_breaker_tripped,
        'circuit_breaker_reason': trader.circuit_breaker_reason,
        'daily_loss_override': getattr(trader, 'daily_loss_override', False),  # ✅ NEW
        'max_daily_loss_percent': trader.max_daily_loss_percent,
        'max_total_drawdown_percent': trader.max_total_drawdown_percent,
        'processed_signals': len(trader.processed_signal_hashes)
    }), 200


@app_command.route('/api/auto-trade/set-risk-profile', methods=['POST'])
def set_risk_profile():
    """Set risk profile for dynamic confidence calculation"""
    try:
        data = request.get_json() or {}
        risk_profile = data.get('risk_profile', 'normal')
        
        if risk_profile not in ['moderate', 'normal', 'aggressive']:
            return jsonify({
                'status': 'error',
                'message': 'Invalid risk profile. Must be: moderate, normal, or aggressive'
            }), 400
        
        from auto_trader import get_auto_trader
        trader = get_auto_trader()
        trader.set_risk_profile(risk_profile)
        
        # Get the new min_confidence after setting risk profile
        min_confidence = trader.min_autotrade_confidence
        
        logger.info(f"Risk Profile set to: {risk_profile} (min_confidence: {min_confidence}%)")
        return jsonify({
            'status': 'success',
            'message': f'Risk Profile set to: {risk_profile.upper()}',
            'risk_profile': risk_profile,
            'min_confidence': min_confidence
        }), 200
    except Exception as e:
        logger.error(f"Error setting risk profile: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/auto-trade/reset-circuit-breaker', methods=['POST'])
def reset_circuit_breaker():
    """Reset circuit breaker and re-enable auto-trading"""
    try:
        from auto_trader import get_auto_trader
        trader = get_auto_trader()

        # Get override parameter from request
        data = request.get_json() or {}
        override_daily_loss = data.get('override_daily_loss', False)

        # Check if circuit breaker is actually tripped
        if not trader.circuit_breaker_tripped:
            return jsonify({
                'status': 'info',
                'message': 'Circuit breaker is not tripped'
            }), 200

        # Reset circuit breaker with optional override
        trader.reset_circuit_breaker(override_daily_loss=override_daily_loss)

        # Re-enable auto-trading
        trader.enable()

        message = 'Circuit breaker reset and auto-trading re-enabled'
        if override_daily_loss:
            message += ' (Daily loss limit override ACTIVE - use with caution!)'
            logger.warning(f"⚠️ {message}")
        else:
            logger.info(message)

        return jsonify({
            'status': 'success',
            'message': message,
            'override_active': override_daily_loss
        }), 200
    except Exception as e:
        logger.error(f"Error resetting circuit breaker: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/auto-trade/confidence-requirements', methods=['GET'])
def get_confidence_requirements():
    """Get current confidence requirements for all active symbols"""
    try:
        from dynamic_confidence_calculator import get_confidence_calculator
        from session_volatility_analyzer import SessionVolatilityAnalyzer
        from auto_trader import get_auto_trader

        trader = get_auto_trader()
        calculator = get_confidence_calculator()
        analyzer = SessionVolatilityAnalyzer()
        
        # Get current session
        session_name, session_info = analyzer.get_current_session()
        
        # Get all symbols with open positions
        db = ScopedSession()
        try:
            from models import Trade
            open_trades = db.query(Trade).filter_by(status='open').all()
            symbols = list(set(t.symbol for t in open_trades))
            
            # Calculate volatility for each symbol
            volatility_map = {}
            for symbol in symbols:
                volatility_map[symbol] = analyzer.calculate_recent_volatility(db, symbol, account_id=1)
            
            # Get requirements for all symbols
            requirements = calculator.get_all_requirements(
                symbols=symbols,
                risk_profile=trader.risk_profile,
                session=session_name,
                volatility_map=volatility_map
            )
            
            return jsonify({
                'status': 'success',
                'risk_profile': trader.risk_profile,
                'session': session_name,
                'session_description': session_info.get('description', session_name),
                'requirements': requirements
            }), 200
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting confidence requirements: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# Spread Configuration API Endpoints
# ============================================================================

@app_command.route('/api/spread-config', methods=['GET'])
def get_all_spread_configs():
    """Get all symbol spread configurations"""
    try:
        from models import SymbolSpreadConfig

        db = ScopedSession()
        try:
            configs = db.query(SymbolSpreadConfig).order_by(
                SymbolSpreadConfig.asset_type,
                SymbolSpreadConfig.symbol
            ).all()

            result = []
            for config in configs:
                result.append({
                    'id': config.id,
                    'symbol': config.symbol,
                    'typical_spread': float(config.typical_spread),
                    'max_spread_multiplier': float(config.max_spread_multiplier),
                    'absolute_max_spread': float(config.absolute_max_spread) if config.absolute_max_spread else None,
                    'asian_session_spread': float(config.asian_session_spread) if config.asian_session_spread else None,
                    'weekend_spread': float(config.weekend_spread) if config.weekend_spread else None,
                    'enabled': config.enabled,
                    'use_dynamic_limits': config.use_dynamic_limits,
                    'asset_type': config.asset_type,
                    'notes': config.notes,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None
                })

            return jsonify({
                'status': 'success',
                'configs': result,
                'count': len(result)
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting spread configs: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/spread-config/<symbol>', methods=['GET'])
def get_spread_config(symbol):
    """Get spread configuration for a specific symbol"""
    try:
        from models import SymbolSpreadConfig

        db = ScopedSession()
        try:
            config = db.query(SymbolSpreadConfig).filter_by(
                symbol=symbol.upper()
            ).first()

            if not config:
                return jsonify({
                    'status': 'error',
                    'message': f'No configuration found for {symbol.upper()}'
                }), 404

            return jsonify({
                'status': 'success',
                'config': {
                    'id': config.id,
                    'symbol': config.symbol,
                    'typical_spread': float(config.typical_spread),
                    'max_spread_multiplier': float(config.max_spread_multiplier),
                    'absolute_max_spread': float(config.absolute_max_spread) if config.absolute_max_spread else None,
                    'asian_session_spread': float(config.asian_session_spread) if config.asian_session_spread else None,
                    'weekend_spread': float(config.weekend_spread) if config.weekend_spread else None,
                    'enabled': config.enabled,
                    'use_dynamic_limits': config.use_dynamic_limits,
                    'asset_type': config.asset_type,
                    'notes': config.notes,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting spread config for {symbol}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/spread-config/<symbol>', methods=['POST', 'PUT'])
def update_spread_config(symbol):
    """Create or update spread configuration for a symbol"""
    try:
        from models import SymbolSpreadConfig
        from decimal import Decimal

        data = request.get_json() or {}
        symbol_upper = symbol.upper()

        # Validate required fields for new entries
        if 'typical_spread' not in data:
            return jsonify({
                'status': 'error',
                'message': 'typical_spread is required'
            }), 400

        db = ScopedSession()
        try:
            # Check if config exists
            config = db.query(SymbolSpreadConfig).filter_by(
                symbol=symbol_upper
            ).first()

            if config:
                # Update existing
                config.typical_spread = Decimal(str(data['typical_spread']))
                config.max_spread_multiplier = Decimal(str(data.get('max_spread_multiplier', 3.0)))

                if 'absolute_max_spread' in data and data['absolute_max_spread'] is not None:
                    config.absolute_max_spread = Decimal(str(data['absolute_max_spread']))

                if 'asian_session_spread' in data and data['asian_session_spread'] is not None:
                    config.asian_session_spread = Decimal(str(data['asian_session_spread']))

                if 'weekend_spread' in data and data['weekend_spread'] is not None:
                    config.weekend_spread = Decimal(str(data['weekend_spread']))

                if 'enabled' in data:
                    config.enabled = bool(data['enabled'])

                if 'use_dynamic_limits' in data:
                    config.use_dynamic_limits = bool(data['use_dynamic_limits'])

                if 'asset_type' in data:
                    config.asset_type = data['asset_type']

                if 'notes' in data:
                    config.notes = data['notes']

                db.commit()
                action = 'updated'
            else:
                # Create new
                config = SymbolSpreadConfig(
                    symbol=symbol_upper,
                    typical_spread=Decimal(str(data['typical_spread'])),
                    max_spread_multiplier=Decimal(str(data.get('max_spread_multiplier', 3.0))),
                    absolute_max_spread=Decimal(str(data['absolute_max_spread'])) if data.get('absolute_max_spread') else None,
                    asian_session_spread=Decimal(str(data['asian_session_spread'])) if data.get('asian_session_spread') else None,
                    weekend_spread=Decimal(str(data['weekend_spread'])) if data.get('weekend_spread') else None,
                    enabled=bool(data.get('enabled', True)),
                    use_dynamic_limits=bool(data.get('use_dynamic_limits', True)),
                    asset_type=data.get('asset_type'),
                    notes=data.get('notes')
                )
                db.add(config)
                db.commit()
                action = 'created'

            logger.info(f"Spread config {action} for {symbol_upper}")

            return jsonify({
                'status': 'success',
                'message': f'Spread configuration {action} for {symbol_upper}',
                'config': {
                    'id': config.id,
                    'symbol': config.symbol,
                    'typical_spread': float(config.typical_spread),
                    'max_spread_multiplier': float(config.max_spread_multiplier),
                    'absolute_max_spread': float(config.absolute_max_spread) if config.absolute_max_spread else None,
                    'asian_session_spread': float(config.asian_session_spread) if config.asian_session_spread else None,
                    'weekend_spread': float(config.weekend_spread) if config.weekend_spread else None,
                    'enabled': config.enabled,
                    'use_dynamic_limits': config.use_dynamic_limits,
                    'asset_type': config.asset_type,
                    'notes': config.notes
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error updating spread config for {symbol}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/spread-config/<symbol>', methods=['DELETE'])
def delete_spread_config(symbol):
    """Delete spread configuration for a symbol"""
    try:
        from models import SymbolSpreadConfig

        db = ScopedSession()
        try:
            config = db.query(SymbolSpreadConfig).filter_by(
                symbol=symbol.upper()
            ).first()

            if not config:
                return jsonify({
                    'status': 'error',
                    'message': f'No configuration found for {symbol.upper()}'
                }), 404

            db.delete(config)
            db.commit()

            logger.info(f"Spread config deleted for {symbol.upper()}")

            return jsonify({
                'status': 'success',
                'message': f'Spread configuration deleted for {symbol.upper()}'
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error deleting spread config for {symbol}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/monitoring/<int:account_id>', methods=['GET'])
def get_monitoring_data(account_id):
    """Get real-time trade monitoring data"""
    redis = get_redis()
    data = redis.get(f"monitoring:account:{account_id}")

    if data:
        import json
        try:
            monitoring = json.loads(data) if isinstance(data, str) else eval(data)
            return jsonify(monitoring), 200
        except Exception as e:
            logger.error(f"Error parsing monitoring data: {e}")
            return jsonify({'error': 'Failed to parse monitoring data'}), 500
    else:
        return jsonify({
            'positions': [],
            'total_pnl': 0,
            'position_count': 0,
            'message': 'No monitoring data available'
        }), 200


# ============================================================================
# BACKTESTING & ANALYTICS ENDPOINTS
# ============================================================================

@app_command.route('/api/backtest/create', methods=['POST'])
def create_backtest():
    """Create a new backtest run"""
    try:
        # ✅ FIX BUG-003: Input validation to prevent SQL injection
        from input_validator import InputValidator, validate_timeframe
        
        data = request.get_json()
        from models import BacktestRun

        # Validate required fields
        required = ['account_id', 'name', 'start_date', 'end_date']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Validate inputs
        account_id = InputValidator.validate_integer(data['account_id'], min_value=1)
        name = InputValidator.sanitize_string(data['name'], max_length=255, allow_special_chars=False)  # Name can be free text but no SQL
        description = InputValidator.sanitize_string(data.get('description', ''), max_length=1000, allow_special_chars=False) if data.get('description') else None
        
        # Validate symbols (comma-separated list)
        symbols_raw = data.get('symbols', 'BTCUSD')
        symbols_list = [s.strip() for s in symbols_raw.split(',')]
        for sym in symbols_list:
            InputValidator.validate_symbol(sym)  # Validate each symbol
        symbols = ','.join(symbols_list)
        
        # Validate timeframes (comma-separated list)
        timeframes_raw = data.get('timeframes', 'H1')
        timeframes_list = [validate_timeframe(tf.strip()) for tf in timeframes_raw.split(',')]
        timeframes = ','.join(timeframes_list)
        
        # Validate and parse dates
        start_date = InputValidator.validate_iso_date(data['start_date'])
        end_date = InputValidator.validate_iso_date(data['end_date'])
        
        # Validate numeric parameters
        initial_balance = InputValidator.validate_float(
            data.get('initial_balance', 10000.0),
            min_value=100,
            max_value=1000000,
            default=10000.0
        )
        min_confidence = InputValidator.validate_float(
            data.get('min_confidence', 0.50),
            min_value=0,
            max_value=1,
            default=0.50
        )
        position_size_percent = InputValidator.validate_float(
            data.get('position_size_percent', 0.01),
            min_value=0.001,
            max_value=0.1,
            default=0.01
        )
        max_positions = InputValidator.validate_integer(
            data.get('max_positions', 5),
            min_value=1,
            max_value=50,
            default=5
        )

        # Validate timeframe requirements based on period length
        days = (end_date - start_date).days

        # Minimum days required for each timeframe to get enough bars
        # H4: 6 bars/day -> need 50 bars = 9 days minimum
        # D1: 1 bar/day -> need 30 bars = 30 days minimum
        if 'H4' in timeframes and days < 9:
            return jsonify({'error': 'H4 timeframe requires at least 9 days of data. Please extend the date range or remove H4.'}), 400
        if 'D1' in timeframes and days < 30:
            return jsonify({'error': 'D1 timeframe requires at least 30 days of data. Please extend the date range or remove D1.'}), 400

        db = ScopedSession()
        try:
            backtest = BacktestRun(
                account_id=account_id,
                name=name,
                description=description,
                symbols=symbols,
                timeframes=timeframes,
                start_date=start_date,
                end_date=end_date,
                initial_balance=initial_balance,
                min_confidence=min_confidence,
                position_size_percent=position_size_percent,
                max_positions=max_positions
            )

            db.add(backtest)
            db.commit()

            return jsonify({
                'status': 'success',
                'backtest_id': backtest.id,
                'message': f'Backtest "{backtest.name}" created'
            }), 201

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error creating backtest: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/<int:backtest_id>/start', methods=['POST'])
def start_backtest(backtest_id):
    """Start a backtest run in background"""
    try:
        from threading import Thread
        from backtesting_engine import run_backtest
        from models import BacktestRun
        from command_helper import create_command

        # Get backtest run details
        db = ScopedSession()
        try:
            backtest = db.query(BacktestRun).filter_by(id=backtest_id).first()
            if not backtest:
                return jsonify({'error': 'Backtest not found'}), 404

            # Request OHLC data from EA for backtest period
            symbols = backtest.symbols.split(',') if backtest.symbols else []
            timeframes = backtest.timeframes.split(',') if backtest.timeframes else ['H1']

            logger.info(f"Requesting OHLC data from EA for backtest {backtest_id}")
            logger.info(f"Period: {backtest.start_date} to {backtest.end_date}")
            logger.info(f"Symbols: {symbols}, Timeframes: {timeframes}")

            # Send OHLC request command to EA for each symbol/timeframe combination
            for symbol in symbols:
                for timeframe in timeframes:
                    # Create command to request historical OHLC data
                    command = create_command(
                        db=db,
                        account_id=backtest.account_id,
                        command_type='REQUEST_OHLC',
                        payload={
                            'symbol': symbol.strip(),
                            'timeframe': timeframe.strip(),
                            'start_date': backtest.start_date.isoformat(),
                            'end_date': backtest.end_date.isoformat(),
                            'bars': 500  # Request up to 500 bars
                        }
                    )
                    logger.info(f"Created OHLC request command {command.id} for {symbol} {timeframe}")

        finally:
            db.close()

        # Start backtest in background thread (will wait for OHLC data if needed)
        thread = Thread(target=run_backtest, args=(backtest_id,), daemon=True)
        thread.start()

        return jsonify({
            'status': 'success',
            'message': f'Backtest {backtest_id} started. Requesting historical OHLC data from EA...'
        }), 200

    except Exception as e:
        logger.error(f"Error starting backtest: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/list', methods=['GET'])
def list_backtests():
    """Get list of all backtest runs"""
    try:
        account_id = int(request.args.get('account_id', 1))
        from models import BacktestRun
        db = ScopedSession()
        try:
            backtests = db.query(BacktestRun).filter_by(
                account_id=account_id
            ).order_by(BacktestRun.id.desc()).all()

            return jsonify({
                'backtests': [{
                    'id': bt.id,
                    'name': bt.name,
                    'status': bt.status,
                    'progress_percent': float(bt.progress_percent) if bt.progress_percent else 0,
                    'current_status': bt.current_status if hasattr(bt, 'current_status') else None,
                    'symbols': bt.symbols,
                    'timeframes': bt.timeframes,
                    'start_date': bt.start_date.isoformat() if bt.start_date else None,
                    'end_date': bt.end_date.isoformat() if bt.end_date else None,
                    'total_trades': bt.total_trades,
                    'win_rate': float(bt.win_rate) if bt.win_rate else None,
                    'profit_factor': float(bt.profit_factor) if bt.profit_factor else None,
                    'net_profit': float(bt.final_balance - bt.initial_balance) if bt.final_balance and bt.initial_balance else None
                } for bt in backtests]
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error listing backtests: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/<int:backtest_id>', methods=['GET'])
def get_backtest(backtest_id):
    """Get backtest run details and results"""
    try:
        from models import BacktestRun
        db = ScopedSession()
        try:
            backtest = db.query(BacktestRun).filter_by(id=backtest_id).first()

            if not backtest:
                return jsonify({'error': 'Backtest not found'}), 404

            return jsonify({
                'id': backtest.id,
                'name': backtest.name,
                'status': backtest.status,
                'symbols': backtest.symbols,
                'timeframes': backtest.timeframes,
                'start_date': backtest.start_date.isoformat() if backtest.start_date else None,
                'end_date': backtest.end_date.isoformat() if backtest.end_date else None,
                'initial_balance': float(backtest.initial_balance) if backtest.initial_balance else None,
                'final_balance': float(backtest.final_balance) if backtest.final_balance else None,
                'total_trades': backtest.total_trades,
                'winning_trades': backtest.winning_trades,
                'losing_trades': backtest.losing_trades,
                'win_rate': float(backtest.win_rate) if backtest.win_rate else None,
                'profit_factor': float(backtest.profit_factor) if backtest.profit_factor else None,
                'total_profit': float(backtest.total_profit) if backtest.total_profit else None,
                'total_loss': float(backtest.total_loss) if backtest.total_loss else None,
                'max_drawdown': float(backtest.max_drawdown) if backtest.max_drawdown else None,
                'max_drawdown_percent': float(backtest.max_drawdown_percent) if backtest.max_drawdown_percent else None,
                'sharpe_ratio': float(backtest.sharpe_ratio) if backtest.sharpe_ratio else None,
                'started_at': backtest.started_at.isoformat() if backtest.started_at else None,
                'completed_at': backtest.completed_at.isoformat() if backtest.completed_at else None,
                'error_message': backtest.error_message,
                # Detailed progress information
                'progress_percent': float(backtest.progress_percent) if backtest.progress_percent else 0,
                'current_status': backtest.current_status if hasattr(backtest, 'current_status') else None,
                'current_processing_date': backtest.current_processing_date.isoformat() if backtest.current_processing_date else None,
                'processed_candles': backtest.processed_candles,
                'total_candles': backtest.total_candles,
                'estimated_completion': backtest.estimated_completion.isoformat() if backtest.estimated_completion else None
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting backtest: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/<int:backtest_id>/trades', methods=['GET'])
def get_backtest_trades(backtest_id):
    """Get all trades from a backtest run"""
    try:
        from models import BacktestTrade
        db = ScopedSession()
        try:
            trades = db.query(BacktestTrade).filter_by(
                backtest_run_id=backtest_id
            ).order_by(BacktestTrade.entry_time.desc()).all()

            return jsonify({
                'trades': [{
                    'id': t.id,
                    'direction': t.direction,
                    'symbol': t.symbol,
                    'timeframe': t.timeframe,
                    'volume': float(t.volume) if t.volume else None,
                    'entry_time': t.entry_time.isoformat() if t.entry_time else None,
                    'entry_price': float(t.entry_price) if t.entry_price else None,
                    'entry_reason': t.entry_reason,
                    'exit_time': t.exit_time.isoformat() if t.exit_time else None,
                    'exit_price': float(t.exit_price) if t.exit_price else None,
                    'exit_reason': t.close_reason,  # Fixed: use close_reason column
                    'profit': float(t.profit) if t.profit else None,
                    'profit_percent': float(t.profit_percent) if t.profit_percent else None,
                    'duration_minutes': t.duration_minutes,
                    'signal_confidence': float(t.signal_confidence) if t.signal_confidence else None,
                    'trailing_stop_used': t.trailing_stop_used
                } for t in trades]
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting backtest trades: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/<int:backtest_id>', methods=['DELETE'])
def delete_backtest(backtest_id):
    """Delete a backtest run and all associated data"""
    try:
        from models import BacktestRun, BacktestTrade, SymbolPerformanceTracking
        db = ScopedSession()
        try:
            backtest = db.query(BacktestRun).filter_by(id=backtest_id).first()

            if not backtest:
                return jsonify({'error': 'Backtest not found'}), 404

            # Delete all associated data in correct order (child tables first)

            # 1. Delete symbol performance tracking (references backtest_run_id)
            deleted_perf = db.query(SymbolPerformanceTracking).filter_by(backtest_run_id=backtest_id).delete()

            # 2. Delete associated trades
            deleted_trades = db.query(BacktestTrade).filter_by(backtest_run_id=backtest_id).delete()

            # 3. Delete backtest run
            db.delete(backtest)
            db.commit()

            logger.info(f"Deleted backtest {backtest_id}: {backtest.name} ({deleted_trades} trades, {deleted_perf} performance records)")
            return jsonify({'status': 'success', 'message': 'Backtest deleted'}), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error deleting backtest: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/backtest/<int:backtest_id>/learned-scores', methods=['GET'])
def get_backtest_learned_scores(backtest_id):
    """
    Get indicator scores learned during backtest
    These are ISOLATED from live scores - purely for analysis

    Returns:
        - learned_scores: Dict of symbol -> timeframe -> indicator scores
        - Can be used to seed initial scores for live system
    """
    try:
        from models import BacktestRun
        db = ScopedSession()
        try:
            backtest = db.query(BacktestRun).filter_by(id=backtest_id).first()

            if not backtest:
                return jsonify({'error': 'Backtest not found'}), 404

            if backtest.status != 'completed':
                return jsonify({
                    'status': 'error',
                    'message': f'Backtest not completed yet (status: {backtest.status})'
                }), 400

            learned_scores = backtest.learned_scores or {}

            return jsonify({
                'status': 'success',
                'backtest_id': backtest_id,
                'backtest_name': backtest.name,
                'learned_scores': learned_scores,
                'total_symbols': len(learned_scores),
                'note': 'These scores are from backtest simulation only - NOT live scores'
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting learned scores: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/analytics/overview', methods=['GET'])
def get_analytics_overview():
    """Get overall analytics for account"""
    try:
        account_id = int(request.args.get('account_id', 1))
        period_days = int(request.args.get('period_days', 30))

        from trade_analytics import TradeAnalyticsEngine
        analytics = TradeAnalyticsEngine(account_id)

        metrics = analytics.calculate_analytics(
            period_start=datetime.utcnow() - timedelta(days=period_days)
        )

        return jsonify(metrics), 200

    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/analytics/best-pairs', methods=['GET'])
def get_best_pairs():
    """Get best performing symbol/timeframe combinations"""
    try:
        account_id = int(request.args.get('account_id', 1))
        period_days = int(request.args.get('period_days', 30))
        min_trades = int(request.args.get('min_trades', 5))

        from trade_analytics import TradeAnalyticsEngine
        analytics = TradeAnalyticsEngine(account_id)

        best = analytics.get_best_pairs(period_days, min_trades)
        worst = analytics.get_worst_pairs(period_days, min_trades)

        return jsonify({
            'best_pairs': best,
            'worst_pairs': worst
        }), 200

    except Exception as e:
        logger.error(f"Error getting best/worst pairs: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# PORT 9901 - TICK STREAM
# ============================================================================

@app_ticks.route('/api/ticks', methods=['POST'])
@require_api_key
def receive_ticks(account, db):
    """
    Receive batched tick data from EA

    IMPORTANT: Account from decorator may be detached - reload from db session
    """
    try:
        from models import Tick, Account

        # CRITICAL FIX: Reload account from db session to prevent detachment errors
        account_id = account.id  # Get ID before any session operations
        account = db.query(Account).filter_by(id=account_id).first()

        if not account:
            return jsonify({'status': 'error', 'message': 'Account not found'}), 404

        data = request.get_json()
        ticks = data.get('ticks', [])

        # CRITICAL DEBUG: Log what we're receiving
        logger.info(f"🔍 /api/ticks called: ticks_count={len(ticks)}, has_positions={bool(data.get('positions'))}")

        # DEBUG: Log first tick timestamp
        if ticks and len(ticks) > 0:
            first_tick = ticks[0]
            tick_ts = first_tick.get('timestamp')
            current_ts = datetime.utcnow().timestamp()
            age = current_ts - tick_ts if tick_ts else 0
            logger.info(f"🕒 TICK BATCH: {len(ticks)} ticks, first_ts={tick_ts}, age={age:.0f}s")
        positions_from_ea = data.get('positions', [])  # Get MT5 profit values from EA

        if not ticks:
            return jsonify({'status': 'error', 'message': 'No ticks provided'}), 400

        # Extract account data if provided
        balance = data.get('balance')
        equity = data.get('equity')
        margin = data.get('margin')
        free_margin = data.get('free_margin')
        profit_today = data.get('profit_today')
        profit_week = data.get('profit_week')
        profit_month = data.get('profit_month')
        profit_year = data.get('profit_year')

        # Create a map of ticket -> EA profit values for quick lookup
        ea_profit_map = {}
        if positions_from_ea:
            for pos in positions_from_ea:
                ticket = pos.get('ticket')
                if ticket:
                    ea_profit_map[ticket] = {
                        'profit': pos.get('profit', 0.0),
                        'swap': pos.get('swap', 0.0)
                    }

        # Store account_id before commit (to prevent session detachment issues)
        account_id = account.id

        # Update account data if provided
        if balance is not None:
            account.balance = balance
        if equity is not None:
            account.equity = equity
        if margin is not None:
            account.margin = margin
        if free_margin is not None:
            account.free_margin = free_margin
        if profit_today is not None:
            account.profit_today = profit_today
        if profit_week is not None:
            account.profit_week = profit_week
        if profit_month is not None:
            account.profit_month = profit_month
        if profit_year is not None:
            account.profit_year = profit_year

        # Commit account updates to database immediately
        db.commit()

        # Cache account state in Redis for fast access
        try:
            redis = get_redis()
            redis.cache_account_state(account_id, {
                'balance': float(balance) if balance is not None else None,
                'equity': float(equity) if equity is not None else None,
                'margin': float(margin) if margin is not None else None,
                'free_margin': float(free_margin) if free_margin is not None else None,
                'profit_today': float(profit_today) if profit_today is not None else None,
                'profit_week': float(profit_week) if profit_week is not None else None,
                'profit_month': float(profit_month) if profit_month is not None else None,
                'profit_year': float(profit_year) if profit_year is not None else None,
                'last_update': datetime.utcnow().isoformat()
            }, ttl=60)  # 60 seconds TTL
        except Exception as e:
            logger.error(f"Failed to cache account state in Redis: {e}")

        # Buffer ticks in Redis instead of immediate PostgreSQL write
        latest_prices = {}  # Track latest price per symbol for WebSocket broadcast

        try:
            redis = get_redis()

            # Prepare ticks for buffering
            buffered_ticks = []
            for tick_data in ticks:
                # Calculate spread if not provided
                bid = tick_data.get('bid', 0)
                ask = tick_data.get('ask', 0)
                spread = tick_data.get('spread', ask - bid if ask and bid else None)

                # TIMEZONE OFFSET FIX: Convert EA's local time to UTC using broker's timezone offset
                # EA sends: TimeCurrent() (broker local time) + TimeGMTOffset() (seconds from GMT)
                # NOTE: MT5's TimeGMTOffset() returns NEGATIVE values for positive UTC offsets!
                #   CET (UTC+1): TimeGMTOffset() = -3600
                #   CEST (UTC+2): TimeGMTOffset() = -7200
                # We calculate: UTC = local_time + tz_offset (because MT5 uses negative convention)
                ea_local_timestamp = tick_data.get('timestamp')
                tz_offset = tick_data.get('tz_offset', 0)  # Offset in seconds (NEGATIVE for positive UTC zones)

                # BROKER-SPECIFIC CORRECTION: This broker uses GMT+2 but TimeGMTOffset() reports GMT+1
                # Apply -3600 correction to account for broker's incorrect offset reporting
                tz_offset_corrected = tz_offset - 3600  # Subtract 1 hour (broker is GMT+2, not GMT+1)

                # Convert to UTC by adding the corrected offset
                tick_timestamp = ea_local_timestamp + tz_offset_corrected

                # ALWAYS log timezone conversion for first tick of each batch
                if len(buffered_ticks) == 0:
                    logger.info(
                        f"🕒 TIMEZONE CONVERSION: {tick_data.get('symbol')} | "
                        f"EA Local: {ea_local_timestamp} ({datetime.fromtimestamp(ea_local_timestamp)}) | "
                        f"TZ Offset: {tz_offset}s ({tz_offset/3600:.1f}h) → Corrected: {tz_offset_corrected}s ({tz_offset_corrected/3600:.1f}h) | "
                        f"UTC: {tick_timestamp} ({datetime.fromtimestamp(tick_timestamp)})"
                    )

                # Prepare tick data for buffering (Ticks are global - no account_id)
                tick_buffer_data = {
                    'symbol': tick_data.get('symbol'),
                    'bid': bid,
                    'ask': ask,
                    'spread': spread,
                    'volume': tick_data.get('volume', 0),
                    'timestamp': tick_timestamp
                }
                buffered_ticks.append(tick_buffer_data)

                # Keep only the latest price per symbol for WebSocket
                symbol = tick_data.get('symbol')
                latest_prices[symbol] = {
                    'symbol': symbol,
                    'bid': float(bid),
                    'ask': float(ask),
                    'spread': float(spread) if spread else None,
                    'timestamp': tick_timestamp
                }

            # Buffer all ticks in Redis at once (fast!)
            redis.buffer_ticks_batch(account_id, buffered_ticks)

            logger.debug(f"Buffered {len(buffered_ticks)} ticks in Redis for account {account_id}")

        except Exception as e:
            logger.error(f"Failed to buffer ticks in Redis: {e}")
            # Fallback: Write directly to PostgreSQL (Ticks are global - no account_id)
            tick_objects = []
            for tick_data in ticks:
                # FIX: MT5 EA sends local time (GMT+3), convert to UTC
                tick_timestamp = tick_data.get('timestamp')
                if tick_timestamp:
                    # Subtract 3 hours to convert from GMT+3 to UTC
                    tick_dt = datetime.fromtimestamp(tick_timestamp - (3 * 3600))
                else:
                    tick_dt = datetime.utcnow()
                
                tick = Tick(
                    symbol=tick_data.get('symbol'),
                    bid=tick_data.get('bid'),
                    ask=tick_data.get('ask'),
                    volume=tick_data.get('volume', 0),
                    timestamp=tick_dt
                )
                tick_objects.append(tick)

            db.bulk_save_objects(tick_objects)
            db.commit()
            logger.warning(f"Redis buffer failed, wrote {len(tick_objects)} ticks directly to PostgreSQL")

        # Broadcast latest prices via WebSocket
        for symbol, price_data in latest_prices.items():
            socketio.emit('price_update', price_data)

        # Broadcast account update if balance/equity/margin changed
        if balance is not None or equity is not None or margin is not None or free_margin is not None:
            socketio.emit('account_update', {
                'number': account.mt5_account_number,
                'balance': float(balance) if balance is not None else 0.0,
                'equity': float(equity) if equity is not None else 0.0,
                'margin': float(margin) if margin is not None else 0.0,
                'free_margin': float(free_margin) if free_margin is not None else 0.0
            })

        # Broadcast profit update if profit values changed
        if profit_today is not None or profit_week is not None or profit_month is not None or profit_year is not None:
            socketio.emit('profit_update', {
                'today': float(profit_today) if profit_today is not None else 0.0,
                'week': float(profit_week) if profit_week is not None else 0.0,
                'month': float(profit_month) if profit_month is not None else 0.0,
                'year': float(profit_year) if profit_year is not None else 0.0
            })

        # Update shadow trades with current prices
        try:
            from shadow_trading_engine import update_shadow_trades_for_tick
            for tick_data in ticks:
                symbol = tick_data.get('symbol')
                bid = tick_data.get('bid')
                if symbol and bid:
                    update_shadow_trades_for_tick(symbol, bid)
        except Exception as e:
            logger.error(f"Error updating shadow trades: {e}")

        # REAL-TIME POSITION UPDATES: Emit directly here like price_update (works!)
        try:
            from models import Trade, Tick as TickModel
            from trade_monitor import get_trade_monitor

            # Get symbols from received ticks
            tick_symbols = set(tick_data.get('symbol') for tick_data in ticks)

            # Check ALL open trades (not just from tick_symbols) to ensure all positions update in real-time
            # GLOBAL query - trades are shared across accounts for ML learning
            open_trades = db.query(Trade).filter(
                Trade.status == 'open'
            ).all()

            # If we have open trades affected by these price updates, calculate and emit P&L
            if open_trades:
                trade_monitor = get_trade_monitor()

                # Calculate positions with EUR conversion
                positions_data = []
                total_pnl = 0

                # Get EUR/USD rate
                eurusd_rate = trade_monitor.get_eurusd_rate(db, account_id)

                for trade in open_trades:
                    # Get current price dict from latest_prices (from current tick batch) or database (last known price)
                    if trade.symbol in latest_prices:
                        current_price_dict = latest_prices[trade.symbol]
                    else:
                        # Symbol not in current tick batch - get last known price from database
                        current_price_dict = trade_monitor.get_current_price(db, account_id, trade.symbol)

                    if current_price_dict:
                        # Check if we have EA profit values for this trade
                        ea_profit_data = ea_profit_map.get(trade.ticket)

                        if ea_profit_data:
                            # USE EA-PROVIDED PROFIT VALUES (100% accurate from MT5!)
                            mt5_profit = ea_profit_data['profit']
                            mt5_swap = ea_profit_data['swap']
                            total_pnl_mt5 = mt5_profit + mt5_swap
                            total_pnl += total_pnl_mt5

                            # Calculate TP/SL distances for display (pass price DICT)
                            pnl_data = trade_monitor.calculate_position_pnl(trade, current_price_dict, eurusd_rate)

                            # Get trailing stop info (extract float price for TS)
                            trailing_stop_info = None
                            try:
                                from trailing_stop_manager import get_trailing_stop_manager
                                ts_manager = get_trailing_stop_manager()
                                # Extract float price: BID for BUY (close at BID), ASK for SELL (close at ASK)
                                close_price_float = float(current_price_dict['bid']) if trade.direction == 'buy' else float(current_price_dict['ask'])
                                trailing_stop_info = ts_manager.get_trailing_stop_info(trade, close_price_float, db)
                            except Exception as e:
                                logger.debug(f"Failed to get trailing stop info: {e}")

                            # Format opening reason using helper function
                            opening_reason = get_trade_opening_reason(trade)

                            position_info = {
                                'ticket': trade.ticket,
                                'symbol': trade.symbol,
                                'direction': trade.direction.upper() if isinstance(trade.direction, str) else ('BUY' if trade.direction == 0 else 'SELL'),
                                'volume': float(trade.volume),
                                'open_price': float(trade.open_price),
                                'current_price': pnl_data['current_price'] if pnl_data else current_price,
                                'pnl': total_pnl_mt5,  # USE MT5 PROFIT - 100% ACCURATE!
                                'tp': float(trade.tp) if trade.tp else None,
                                'sl': float(trade.sl) if trade.sl else None,
                                'distance_to_tp_eur': pnl_data.get('distance_to_tp_eur') if pnl_data else None,
                                'distance_to_sl_eur': pnl_data.get('distance_to_sl_eur') if pnl_data else None,
                                'open_time': trade.open_time.isoformat() if trade.open_time else None,
                                'opening_reason': opening_reason,
                                'trailing_stop_info': trailing_stop_info,
                            }
                            positions_data.append(position_info)
                        else:
                            # Fallback: Calculate P&L if EA didn't send profit data (shouldn't happen normally)
                            pnl_data = trade_monitor.calculate_position_pnl(trade, current_price_dict, eurusd_rate)

                            if pnl_data:
                                calculated_pnl = pnl_data.get('pnl', 0.0)
                                total_pnl += calculated_pnl

                                # Get trailing stop info (extract float price for TS)
                                trailing_stop_info = None
                                try:
                                    from trailing_stop_manager import get_trailing_stop_manager
                                    ts_manager = get_trailing_stop_manager()
                                    # Extract float price: BID for BUY, ASK for SELL
                                    close_price_float = float(current_price_dict['bid']) if trade.direction == 'buy' else float(current_price_dict['ask'])
                                    trailing_stop_info = ts_manager.get_trailing_stop_info(trade, close_price_float, db)
                                except Exception as e:
                                    logger.debug(f"Failed to get trailing stop info: {e}")

                                # Format opening reason using helper function
                                opening_reason = get_trade_opening_reason(trade)

                                position_info = {
                                    'ticket': trade.ticket,
                                    'symbol': trade.symbol,
                                    'direction': trade.direction.upper() if isinstance(trade.direction, str) else ('BUY' if trade.direction == 0 else 'SELL'),
                                    'volume': float(trade.volume),
                                    'open_price': float(trade.open_price),
                                    'current_price': pnl_data['current_price'],
                                    'pnl': calculated_pnl,
                                    'tp': float(trade.tp) if trade.tp else None,
                                    'sl': float(trade.sl) if trade.sl else None,
                                    'distance_to_tp_eur': pnl_data.get('distance_to_tp_eur'),
                                    'distance_to_sl_eur': pnl_data.get('distance_to_sl_eur'),
                                    'open_time': trade.open_time.isoformat() if trade.open_time else None,
                                    'opening_reason': opening_reason,
                                    'trailing_stop_info': trailing_stop_info,
                                }
                                positions_data.append(position_info)

                # Emit directly like price_update (same context!)
                if positions_data:
                    # DEBUG: Log first 3 positions to verify correct P/L values
                    for pos in positions_data[:3]:
                        logger.info(f"📤 WebSocket sending: {pos['symbol']} #{pos['ticket']} - P/L: €{pos['pnl']}")

                    socketio.emit('positions_update', {
                        'account_id': account_id,
                        'position_count': len(positions_data),
                        'positions': positions_data,
                        'total_pnl': round(total_pnl, 2),
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    logger.debug(f"✨ Real-time position update emitted for {len(positions_data)} trades (same as price_update)")

        except Exception as pos_error:
            logger.warning(f"Real-time position update failed (non-critical): {pos_error}")

        logger.debug(f"Received {len(ticks)} ticks from account {account_id}")

        return jsonify({
            'status': 'success',
            'received': len(ticks)
        }), 200

    except Exception as e:
        logger.error(f"Tick receive error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/ohlc/historical', methods=['POST'])
@require_api_key
def receive_historical_ohlc(account, db):
    """
    Receive historical OHLC data from EA
    """
    try:
        from models import OHLCData
        from datetime import datetime, timezone

        data = request.get_json()
        symbol = data.get('symbol')
        timeframe = data.get('timeframe')
        candles = data.get('candles', [])

        if not symbol or not timeframe or not candles:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        logger.info(f"Receiving {len(candles)} historical candles for {symbol} {timeframe}")

        # Process candles - MT5 sends timestamps in broker timezone (usually UTC or UTC+2/+3)
        # We store everything in UTC
        imported_count = 0
        skipped_count = 0

        for candle in candles:
            # Convert MT5 timestamp (seconds since 1970-01-01) to datetime
            # MT5 timestamps are in broker timezone, treat as UTC for consistency
            timestamp = datetime.fromtimestamp(candle['timestamp'], tz=timezone.utc).replace(tzinfo=None)

            # Check if candle already exists (GLOBAL - no account_id)
            existing = db.query(OHLCData).filter_by(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp
            ).first()

            if existing:
                skipped_count += 1
                continue

            # Create new OHLC entry (GLOBAL - no account_id)
            ohlc = OHLCData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=float(candle['open']),
                high=float(candle['high']),
                low=float(candle['low']),
                close=float(candle['close']),
                volume=int(candle.get('volume', 0))
            )
            db.add(ohlc)
            imported_count += 1

        db.commit()

        logger.info(f"Historical OHLC import for {symbol} {timeframe}: {imported_count} imported, {skipped_count} skipped (duplicates)")

        return jsonify({
            'status': 'success',
            'imported': imported_count,
            'skipped': skipped_count,
            'total': len(candles)
        }), 200

    except Exception as e:
        logger.error(f"Historical OHLC receive error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_command.route('/api/ohlc/coverage', methods=['POST'])
def check_ohlc_coverage():
    """
    Check OHLC data coverage for a symbol/timeframe (GLOBAL - no auth needed)
    
    Returns:
    {
        "has_data": true/false,
        "bar_count": 168,
        "expected_bars": 168,
        "coverage_percent": 100.0,
        "oldest_bar": "2025-10-09T16:00:00",
        "newest_bar": "2025-10-16T15:00:00",
        "needs_update": false
    }
    """
    db = ScopedSession()
    try:
        from datetime import datetime, timedelta
        
        data = request.get_json()
        symbol = data.get('symbol')
        timeframe = data.get('timeframe')
        required_bars = data.get('required_bars', 168)  # Default 168 (7 days H1)
        
        if not symbol or not timeframe:
            return jsonify({
                'status': 'error',
                'message': 'Missing required fields: symbol, timeframe'
            }), 400
        
        # Count existing bars (GLOBAL - no account_id)
        bar_count = db.query(OHLCData).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).count()
        
        # Get oldest and newest bar timestamps (GLOBAL - no account_id)
        oldest = db.query(OHLCData.timestamp).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).order_by(OHLCData.timestamp.asc()).first()
        
        newest = db.query(OHLCData.timestamp).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).order_by(OHLCData.timestamp.desc()).first()
        
        has_data = bar_count > 0
        coverage_percent = (bar_count / required_bars * 100) if required_bars > 0 else 0
        
        # Consider data sufficient if we have >= 90% of required bars
        # AND newest bar is less than 2x timeframe old
        timeframe_minutes = {
            'H1': 60,
            'H4': 240,
            'D1': 1440
        }.get(timeframe, 60)
        
        max_age_minutes = timeframe_minutes * 2  # Max 2 candles old
        newest_is_fresh = False
        
        if newest:
            age = datetime.utcnow() - newest[0]
            newest_is_fresh = age.total_seconds() < (max_age_minutes * 60)
        
        needs_update = not has_data or coverage_percent < 90.0 or not newest_is_fresh
        
        return jsonify({
            'status': 'success',
            'has_data': has_data,
            'bar_count': bar_count,
            'expected_bars': required_bars,
            'coverage_percent': round(coverage_percent, 1),
            'oldest_bar': oldest[0].isoformat() if oldest else None,
            'newest_bar': newest[0].isoformat() if newest else None,
            'needs_update': needs_update
        }), 200
        
    except Exception as e:
        logger.error(f"OHLC coverage check error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        db.close()


@app_command.route('/api/request_historical_data', methods=['POST'])
def request_historical_data():
    """
    Request historical OHLC data from EA for a specific date range

    Payload:
    {
        "symbol": "BTCUSD",
        "timeframe": "H4",
        "start_date": "2024-10-05",  // YYYY-MM-DD
        "end_date": "2025-10-05"     // YYYY-MM-DD
    }
    """
    db = ScopedSession()
    try:
        # ✅ FIX BUG-003: Input validation to prevent SQL injection
        from datetime import datetime
        from command_helper import create_command
        from input_validator import InputValidator, validate_timeframe

        data = request.get_json()
        
        # Get and validate inputs
        symbol_raw = data.get('symbol')
        timeframe_raw = data.get('timeframe')
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')

        # Validation
        if not symbol_raw or not timeframe_raw or not start_date_str or not end_date_str:
            return jsonify({
                'status': 'error',
                'message': 'Missing required fields: symbol, timeframe, start_date, end_date'
            }), 400

        # Validate inputs
        symbol = InputValidator.validate_symbol(symbol_raw)
        timeframe = validate_timeframe(timeframe_raw)

        # Parse and validate dates (expecting YYYY-MM-DD format)
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            
            # Additional validation: date range should be reasonable
            days_diff = (end_date - start_date).days
            if days_diff < 0:
                return jsonify({
                    'status': 'error',
                    'message': 'end_date must be after start_date'
                }), 400
            if days_diff > 365 * 2:  # Max 2 years
                return jsonify({
                    'status': 'error',
                    'message': 'Date range too large. Maximum 2 years allowed.'
                }), 400
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Invalid date format. Use YYYY-MM-DD'
            }), 400

        # Convert to Unix timestamps
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())

        # Get first account (assume single account for now)
        account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
        if not account:
            return jsonify({
                'status': 'error',
                'message': 'No account found'
            }), 404

        # Create command for EA
        command = create_command(
            db=db,
            account_id=account_id,
            command_type='REQUEST_HISTORICAL_DATA',
            payload={
                'symbol': symbol,
                'timeframe': timeframe,
                'start_date': start_timestamp,
                'end_date': end_timestamp
            },
            push_to_redis=True
        )

        logger.info(f"Created REQUEST_HISTORICAL_DATA command {command.id} for {symbol} {timeframe} from {start_date_str} to {end_date_str}")

        return jsonify({
            'status': 'success',
            'command_id': command.id,
            'message': f'Historical data request sent to EA for {symbol} {timeframe}'
        }), 200

    except Exception as e:
        logger.error(f"Request historical data error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        db.remove()


# ============================================================================
# PORT 9902 - TRADE UPDATES
# ============================================================================

@app_trades.route('/api/trades/sync', methods=['POST'])
@require_api_key
def sync_trades(account, db):
    """
    Sync all trades from MT5 EA (open positions and closed trades)
    Called periodically by EA to keep server in sync with MT5 terminal
    """
    try:
        from models import Trade
        data = request.get_json()
        trades = data.get('trades', [])

        synced_count = 0
        updated_count = 0

        for trade_data in trades:
            ticket = trade_data.get('ticket')
            if not ticket:
                continue

            # Check if trade exists - GLOBAL (not filtered by account_id for ML learning across all accounts)
            existing_trade = db.query(Trade).filter_by(
                ticket=ticket
            ).first()

            if existing_trade:
                # Update existing trade
                old_status = existing_trade.status
                new_status = trade_data.get('status', 'open')
                existing_trade.status = new_status
                existing_trade.close_price = trade_data.get('close_price')
                existing_trade.close_time = datetime.fromisoformat(trade_data['close_time']) if trade_data.get('close_time') else None
                existing_trade.profit = trade_data.get('profit')
                existing_trade.commission = trade_data.get('commission')
                existing_trade.swap = trade_data.get('swap')

                # ✅ FIX: Preserve SL/TP on close - don't overwrite with 0!
                # When trade closes, EA sends sl=0, tp=0 (position doesn't exist anymore)
                # But we need to keep the last known SL/TP for analysis
                incoming_sl = trade_data.get('sl')
                incoming_tp = trade_data.get('tp')

                # ✅ CRITICAL FIX 2025-11-05: Set initial_sl/initial_tp from Command if not set
                # This fixes trades that were created before this fix was implemented
                if (existing_trade.initial_sl is None or existing_trade.initial_tp is None or
                    existing_trade.initial_sl == 0 or existing_trade.initial_tp == 0):
                    # Try to get original values from the Command that opened this trade
                    from models import Command
                    original_command = db.query(Command).filter(
                        Command.account_id == account.id,
                        Command.command_type == 'OPEN_TRADE',
                        Command.status == 'completed',
                        Command.response['ticket'].astext == str(ticket)
                    ).order_by(Command.created_at.desc()).first()

                    if original_command:
                        cmd_sl = original_command.response.get('sl') if original_command.response else None
                        cmd_tp = original_command.response.get('tp') if original_command.response else None

                        # Fallback to payload if response doesn't have it
                        if not cmd_sl and original_command.payload:
                            cmd_sl = original_command.payload.get('sl')
                        if not cmd_tp and original_command.payload:
                            cmd_tp = original_command.payload.get('tp')

                        if cmd_sl and (existing_trade.initial_sl is None or existing_trade.initial_sl == 0):
                            existing_trade.initial_sl = cmd_sl
                            logger.info(f"🔧 Fixed initial_sl for trade #{ticket}: {cmd_sl}")

                        if cmd_tp and (existing_trade.initial_tp is None or existing_trade.initial_tp == 0):
                            existing_trade.initial_tp = cmd_tp
                            logger.info(f"🔧 Fixed initial_tp for trade #{ticket}: {cmd_tp}")

                # Only update SL/TP if trade is still OPEN
                # When closing, preserve the last known values
                if new_status == 'open':
                    # Trade is open - update SL/TP from EA heartbeat
                    if incoming_sl is not None:
                        existing_trade.sl = incoming_sl
                    if incoming_tp is not None:
                        existing_trade.tp = incoming_tp
                else:
                    # Trade is closing/closed - PRESERVE existing SL/TP, don't overwrite with 0
                    # Keep existing_trade.sl and existing_trade.tp unchanged
                    logger.debug(
                        f"Trade {existing_trade.ticket} closing - preserving SL={existing_trade.sl}, "
                        f"TP={existing_trade.tp} (EA sent: sl={incoming_sl}, tp={incoming_tp})"
                    )

                existing_trade.updated_at = datetime.utcnow()
                
                # ✅ PHASE 7: Exit Enhancement - Calculate metrics when trade closes
                if old_status == 'open' and new_status == 'closed' and existing_trade.close_price:
                    from models import Tick
                    from market_context_helper import (
                        calculate_pips, 
                        calculate_risk_reward, 
                        get_current_trading_session
                    )
                    
                    # Calculate pips_captured
                    existing_trade.pips_captured = calculate_pips(
                        existing_trade.open_price,
                        existing_trade.close_price,
                        existing_trade.direction,
                        existing_trade.symbol
                    )
                    
                    # Calculate risk_reward_realized (if initial_sl exists)
                    if existing_trade.initial_sl:
                        existing_trade.risk_reward_realized = calculate_risk_reward(
                            existing_trade.open_price,
                            existing_trade.close_price,
                            existing_trade.initial_sl,
                            existing_trade.direction
                        )
                    
                    # Calculate hold_duration_minutes
                    if existing_trade.open_time and existing_trade.close_time:
                        duration = (existing_trade.close_time - existing_trade.open_time)
                        existing_trade.hold_duration_minutes = int(duration.total_seconds() / 60)
                    
                    # Capture exit price action snapshot
                    current_tick = db.query(Tick).filter_by(
                        symbol=existing_trade.symbol
                    ).order_by(Tick.timestamp.desc()).first()
                    
                    if current_tick:
                        existing_trade.exit_bid = float(current_tick.bid)
                        existing_trade.exit_ask = float(current_tick.ask)
                        existing_trade.exit_spread = float(current_tick.spread) if current_tick.spread else None
                    
                    # Get exit session
                    existing_trade.session = get_current_trading_session()
                    
                    logger.info(
                        f"📊 Exit Metrics for #{ticket}: "
                        f"Pips={existing_trade.pips_captured:.2f if existing_trade.pips_captured else 0:.2f}, "
                        f"R:R={existing_trade.risk_reward_realized:.2f if existing_trade.risk_reward_realized else 0:.2f}, "
                        f"Duration={existing_trade.hold_duration_minutes}min, "
                        f"Session={existing_trade.session}"
                    )

                    # ✅ Send Telegram notification for closed trade
                    try:
                        from telegram_notifier import get_telegram_notifier
                        notifier = get_telegram_notifier()
                        if notifier.enabled:
                            # Calculate duration string
                            duration_str = ''
                            if existing_trade.hold_duration_minutes:
                                hours = existing_trade.hold_duration_minutes // 60
                                minutes = existing_trade.hold_duration_minutes % 60
                                if hours > 0:
                                    duration_str = f"{hours}h {minutes}m"
                                else:
                                    duration_str = f"{minutes}m"

                            trade_info = {
                                'ticket': existing_trade.ticket,
                                'symbol': existing_trade.symbol,
                                'direction': existing_trade.direction,
                                'volume': existing_trade.volume,
                                'open_price': existing_trade.open_price,
                                'close_price': existing_trade.close_price,
                                'profit': existing_trade.profit or 0,
                                'swap': existing_trade.swap or 0,
                                'commission': existing_trade.commission or 0,
                                'close_reason': existing_trade.close_reason or 'Unknown',
                                'duration': duration_str
                            }

                            # Get current account balance
                            account_balance = account.balance or 0

                            notifier.send_trade_closed_alert(trade_info, account_balance)
                            logger.info(f"📱 Telegram notification sent for closed trade #{ticket}")
                    except Exception as e:
                        logger.error(f"Failed to send Telegram notification for closed trade: {e}")

                updated_count += 1
                logger.info(f"🔄 Trade sync update: {existing_trade.symbol} #{ticket} profit={existing_trade.profit} SL={existing_trade.sl} TP={existing_trade.tp}")
            else:
                # Create new trade record
                # ✅ FIX: Find command_id by matching ticket in command responses
                entry_reason = None
                command_id = trade_data.get('command_id')  # MT5 might send it
                signal_id_from_command = None
                source = 'MT5'  # Default to MT5
                
                # If no command_id from MT5, try to find it via ticket match
                if not command_id:
                    from models import Command, TradingSignal
                    # ✅ IMPROVED: Direct JSONB query for ticket (much faster & more reliable)
                    matching_command = db.query(Command).filter(
                        Command.account_id == account.id,
                        Command.command_type == 'OPEN_TRADE',
                        Command.status == 'completed',
                        Command.response['ticket'].astext == str(ticket)  # Direct JSONB query
                    ).order_by(Command.created_at.desc()).first()

                    if matching_command:
                        command_id = matching_command.id
                        signal_id_from_command = matching_command.payload.get('signal_id') if matching_command.payload else None
                        source = 'autotrade' if signal_id_from_command else 'ea_command'
                        logger.info(f"🔗 Linked trade #{ticket} to command {matching_command.id[:12]}... (signal #{signal_id_from_command})")
                    else:
                        # ✅ Fallback: Check if trade was opened before server started tracking it
                        logger.warning(f"⚠️ No command found for trade #{ticket} - marking as MT5 manual trade")
                        matching_command = None

                # ✅ CRITICAL FIX 2025-11-05: Extract initial SL/TP from Command response
                # This ensures we always have the ORIGINAL SL/TP values for strategy evaluation
                # even if trailing stop has modified them to 0 or changed them
                initial_sl_from_command = None
                initial_tp_from_command = None

                if matching_command and matching_command.response:
                    # EA sends back actual SL/TP values in response: {"sl": 1.23, "tp": 1.45, "ticket": 123}
                    initial_sl_from_command = matching_command.response.get('sl')
                    initial_tp_from_command = matching_command.response.get('tp')

                    if initial_sl_from_command or initial_tp_from_command:
                        logger.info(f"📊 Retrieved initial SL/TP from command response: SL={initial_sl_from_command}, TP={initial_tp_from_command}")

                # Fallback: If no command response, use payload values (what we SENT to EA)
                if not initial_sl_from_command and matching_command and matching_command.payload:
                    initial_sl_from_command = matching_command.payload.get('sl')
                    initial_tp_from_command = matching_command.payload.get('tp')

                    if initial_sl_from_command or initial_tp_from_command:
                        logger.info(f"📊 Retrieved initial SL/TP from command payload: SL={initial_sl_from_command}, TP={initial_tp_from_command}")

                # Try to find linked signal to generate entry_reason and extract metadata
                timeframe_from_signal = None
                entry_confidence_from_signal = None  # ✅ NEW: Extract confidence
                if signal_id_from_command:
                    from models import TradingSignal
                    signal = db.query(TradingSignal).filter_by(id=signal_id_from_command).first()
                    if signal:
                        # Extract timeframe from signal
                        timeframe_from_signal = signal.timeframe

                        # ✅ NEW: Extract confidence as numeric value (already in percentage format!)
                        if signal.confidence:
                            entry_confidence_from_signal = float(signal.confidence)  # Already percentage (60.0 = 60%)

                        # Build entry reason from signal data
                        patterns = []
                        if signal.pattern_data:
                            patterns = [p.get('name', 'Pattern') for p in signal.pattern_data if isinstance(signal.pattern_data, list)]
                            patterns = patterns[:2]  # Limit to 2 patterns

                        reason_parts = []
                        if patterns:
                            reason_parts.append(f"Patterns: {', '.join(patterns)}")
                        if signal.confidence:
                            reason_parts.append(f"{float(signal.confidence)*100:.0f}% confidence")
                        if signal.timeframe:
                            reason_parts.append(f"{signal.timeframe} timeframe")

                        entry_reason = " | ".join(reason_parts) if reason_parts else "Auto-traded signal"

                # Fallback entry reasons based on source
                if not entry_reason:
                    if source == 'autotrade':
                        entry_reason = "Auto-trade (signal details unavailable)"
                    elif source == 'MT5':
                        entry_reason = "Manual trade (MT5)"
                    else:
                        entry_reason = f"Trade from {source}"

                # ✅ COMPREHENSIVE TRACKING: Get current market prices for entry snapshot
                from models import Tick
                from market_context_helper import get_current_trading_session
                
                symbol_for_tick = trade_data.get('symbol')
                current_tick = None
                entry_bid = None
                entry_ask = None
                entry_spread = None
                
                if symbol_for_tick:
                    # Get latest tick for this symbol (ticks are global - no account_id)
                    current_tick = db.query(Tick).filter_by(
                        symbol=symbol_for_tick
                    ).order_by(Tick.timestamp.desc()).first()
                    
                    if current_tick:
                        entry_bid = float(current_tick.bid)
                        entry_ask = float(current_tick.ask)
                        entry_spread = float(current_tick.spread) if current_tick.spread else (entry_ask - entry_bid if entry_ask and entry_bid else None)
                
                # ✅ COMPREHENSIVE TRACKING: Get current session
                session = get_current_trading_session()
                
                new_trade = Trade(
                    account_id=account.id,
                    ticket=ticket,
                    symbol=trade_data.get('symbol'),
                    type=trade_data.get('type', 'MARKET'),
                    direction=trade_data.get('direction'),
                    volume=trade_data.get('volume'),
                    open_price=trade_data.get('open_price'),
                    open_time=datetime.fromisoformat(trade_data['open_time']) if trade_data.get('open_time') else datetime.utcnow(),
                    close_price=trade_data.get('close_price'),
                    close_time=datetime.fromisoformat(trade_data['close_time']) if trade_data.get('close_time') else None,
                    sl=trade_data.get('sl'),  # Current SL (may be modified by trailing stop)
                    tp=trade_data.get('tp'),  # Current TP (may be modified)
                    original_tp=initial_tp_from_command if initial_tp_from_command is not None else trade_data.get('tp'),  # ORIGINAL TP for extension tracking
                    tp_extended_count=0,  # Initialize extension counter

                    # ✅ COMPREHENSIVE TRACKING - Initial TP/SL Snapshot
                    # Use values from Command response/payload (ORIGINAL values before any modifications)
                    # Fallback to current position values if command not found
                    initial_tp=initial_tp_from_command if initial_tp_from_command is not None else trade_data.get('tp'),
                    initial_sl=initial_sl_from_command if initial_sl_from_command is not None else trade_data.get('sl'),
                    
                    # ✅ COMPREHENSIVE TRACKING - Entry Price Action
                    entry_bid=entry_bid,
                    entry_ask=entry_ask,
                    entry_spread=entry_spread,
                    
                    # ✅ COMPREHENSIVE TRACKING - Initialize MFE/MAE
                    max_favorable_excursion=0,
                    max_adverse_excursion=0,
                    trailing_stop_active=False,
                    trailing_stop_moves=0,
                    
                    # ✅ COMPREHENSIVE TRACKING - Market Context
                    session=session,
                    
                    profit=trade_data.get('profit'),
                    commission=trade_data.get('commission'),
                    swap=trade_data.get('swap'),
                    source=source,  # Now correctly set based on command lookup
                    command_id=command_id,
                    signal_id=signal_id_from_command,  # Store signal_id!
                    timeframe=timeframe_from_signal,  # Store timeframe from signal!
                    entry_confidence=entry_confidence_from_signal,  # Store confidence!
                    entry_reason=entry_reason,
                    response_data=trade_data.get('response_data'),
                    status=trade_data.get('status', 'open'),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_trade)
                synced_count += 1

                # ✅ Send Telegram notification for new trade
                try:
                    from telegram_notifier import get_telegram_notifier
                    notifier = get_telegram_notifier()
                    if notifier.enabled:
                        trade_info = {
                            'symbol': new_trade.symbol,
                            'direction': new_trade.direction,
                            'entry_price': new_trade.open_price,
                            'sl': new_trade.sl,
                            'tp': new_trade.tp,
                            'confidence': new_trade.entry_confidence or 0,
                            'volume': new_trade.volume
                        }
                        notifier.send_trade_alert(trade_info)
                        logger.info(f"📱 Telegram notification sent for new trade #{ticket}")
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")

        # ✅ CRITICAL FIX: Close trades that are open in DB but not in MT5's list (MT5 is source of truth!)
        closed_count = 0
        if trades:  # Only reconcile if MT5 sent a trade list
            synced_tickets = set(t.get('ticket') for t in trades if t.get('ticket'))
            
            # Find all trades marked as 'open' in DB for this account
            db_open_trades = db.query(Trade).filter_by(
                account_id=account.id,
                status='open'
            ).all()
            
            for db_trade in db_open_trades:
                # If trade is open in DB but NOT in MT5's list, it must have been closed
                if db_trade.ticket not in synced_tickets:
                    db_trade.status = 'closed'
                    db_trade.close_time = datetime.utcnow()
                    db_trade.close_reason = 'SYNC_RECONCILIATION'
                    # Keep the last known profit/swap/commission
                    db_trade.updated_at = datetime.utcnow()
                    
                    # ✅ PHASE 7: Calculate exit metrics for reconciled trades
                    if db_trade.close_price and db_trade.open_price:
                        from market_context_helper import calculate_pips, calculate_risk_reward, get_current_trading_session
                        
                        db_trade.pips_captured = calculate_pips(
                            db_trade.open_price,
                            db_trade.close_price,
                            db_trade.direction,
                            db_trade.symbol
                        )
                        
                        if db_trade.initial_sl:
                            db_trade.risk_reward_realized = calculate_risk_reward(
                                db_trade.open_price,
                                db_trade.close_price,
                                db_trade.initial_sl,
                                db_trade.direction
                            )
                        
                        if db_trade.open_time:
                            duration = (db_trade.close_time - db_trade.open_time)
                            db_trade.hold_duration_minutes = int(duration.total_seconds() / 60)
                        
                        db_trade.session = get_current_trading_session()
                    
                    closed_count += 1
                    logger.warning(f"🔄 Reconciliation: Closed trade #{db_trade.ticket} (not in MT5 position list)")

        db.commit()

        logger.info(f"Trade sync for account {account.mt5_account_number}: {synced_count} new, {updated_count} updated, {closed_count} reconciled/closed")

        return jsonify({
            'status': 'success',
            'synced': synced_count,
            'updated': updated_count,
            'reconciled': closed_count
        }), 200

    except Exception as e:
        logger.error(f"Trade sync error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_trades.route('/api/trades/update', methods=['POST'])
@require_api_key
def update_trade(account, db):
    """
    Update single trade (called on OnTrade event in EA)
    """
    try:
        from models import Trade
        data = request.get_json()
        ticket = data.get('ticket')

        logger.info(f"📥 EA trade update received: ticket={ticket}, profit={data.get('profit')}, swap={data.get('swap')}, commission={data.get('commission')}, sl={data.get('sl')}, tp={data.get('tp')}")

        if not ticket:
            return jsonify({'status': 'error', 'message': 'Missing ticket'}), 400

        # Find trade - GLOBAL (not filtered by account_id for ML learning across all accounts)
        trade = db.query(Trade).filter_by(
            ticket=ticket
        ).first()

        if trade:
            # Update existing
            trade.status = data.get('status', trade.status)
            trade.close_price = data.get('close_price', trade.close_price)

            # Handle close_time - convert Unix timestamp to datetime
            if data.get('close_time'):
                close_time_val = data.get('close_time')
                if isinstance(close_time_val, int):
                    trade.close_time = datetime.utcfromtimestamp(close_time_val)
                elif isinstance(close_time_val, str):
                    trade.close_time = datetime.fromisoformat(close_time_val)

            trade.profit = data.get('profit', trade.profit)
            trade.commission = data.get('commission', trade.commission)
            trade.swap = data.get('swap', trade.swap)
            trade.sl = data.get('sl', trade.sl)
            trade.tp = data.get('tp', trade.tp)
            trade.close_reason = data.get('close_reason', trade.close_reason)
            trade.updated_at = datetime.utcnow()

            db.commit()
            logger.info(f"🔄 Trade #{ticket} updated from EA: profit={trade.profit}, swap={trade.swap}, commission={trade.commission}, total={float(trade.profit or 0) + float(trade.swap or 0) + float(trade.commission or 0):.2f}")

            # Send Telegram notification for closed trades
            if trade.status == 'closed':
                try:
                    from telegram_notifier import get_telegram_notifier
                    telegram = get_telegram_notifier()
                    
                    # Calculate trade duration
                    duration = ""
                    if trade.open_time and trade.close_time:
                        duration_delta = trade.close_time - trade.open_time
                        hours = int(duration_delta.total_seconds() // 3600)
                        minutes = int((duration_delta.total_seconds() % 3600) // 60)
                        duration = f"{hours}h {minutes}m"
                    
                    telegram.send_trade_closed_alert(
                        trade_info={
                            'ticket': ticket,
                            'symbol': trade.symbol,
                            'direction': trade.direction,
                            'volume': float(trade.volume) if trade.volume else 0,
                            'open_price': float(trade.open_price) if trade.open_price else 0,
                            'close_price': float(trade.close_price) if trade.close_price else 0,
                            'profit': float(trade.profit) if trade.profit else 0,
                            'swap': float(trade.swap) if trade.swap else 0,
                            'commission': float(trade.commission) if trade.commission else 0,
                            'close_reason': trade.close_reason or 'Unknown',
                            'duration': duration
                        },
                        account_balance=float(account.balance) if account.balance else 0.0
                    )
                    logger.info(f"📱 Telegram notification sent for closed trade #{ticket}")
                except Exception as tg_error:
                    logger.warning(f"Failed to send Telegram notification for trade #{ticket}: {tg_error}")

            # Update indicator scores if trade was closed
            if trade.status == 'closed' and trade.signal_id:
                try:
                    from models import TradingSignal
                    from indicator_scorer import IndicatorScorer

                    # Get the signal that generated this trade
                    signal = db.query(TradingSignal).filter_by(id=trade.signal_id).first()

                    if signal and signal.indicators_used:
                        # Determine if profitable
                        was_profitable = trade.profit and float(trade.profit) > 0
                        profit_amount = float(trade.profit) if trade.profit else 0.0

                        # Update scores for all indicators used
                        scorer = IndicatorScorer(account.id, trade.symbol, signal.timeframe)
                        scorer.update_multiple_scores(
                            signal.indicators_used,
                            was_profitable,
                            profit_amount
                        )

                        logger.info(
                            f"📊 Updated indicator scores for trade #{ticket}: "
                            f"{'✅ PROFIT' if was_profitable else '❌ LOSS'} ${profit_amount:+.2f}"
                        )

                except Exception as e:
                    logger.error(f"Error updating indicator scores for trade #{ticket}: {e}")

            # Update live performance tracking when trade closes
            if trade.status == 'closed':
                try:
                    from live_performance_tracker import get_live_tracker
                    tracker = get_live_tracker()
                    tracker.update_after_trade_close(trade, db)
                except Exception as e:
                    logger.error(f"Error updating live performance tracking for trade #{ticket}: {e}")

            # Set cooldown after SL hit to prevent revenge trading
            if trade.close_reason == 'SL_HIT' and trade.symbol:
                from auto_trader import get_auto_trader
                from models import GlobalSettings
                auto_trader = get_auto_trader()
                if auto_trader:
                    settings = GlobalSettings.get_settings(db)
                    if settings.sl_cooldown_minutes > 0:
                        cooldown_until = datetime.utcnow() + timedelta(minutes=settings.sl_cooldown_minutes)
                        auto_trader.symbol_cooldowns[trade.symbol] = cooldown_until
                        logger.info(f"🕐 {trade.symbol} cooldown set until {cooldown_until} after SL hit ({settings.sl_cooldown_minutes}min)")
        else:
            # Create new trade if it doesn't exist
            # Handle open_time - convert Unix timestamp to datetime
            open_time_val = data.get('open_time')
            if isinstance(open_time_val, int):
                open_time = datetime.utcfromtimestamp(open_time_val)
            elif isinstance(open_time_val, str):
                open_time = datetime.fromisoformat(open_time_val)
            else:
                open_time = datetime.utcnow()

            # Handle close_time
            close_time_val = data.get('close_time')
            if close_time_val:
                if isinstance(close_time_val, int):
                    close_time = datetime.utcfromtimestamp(close_time_val)
                elif isinstance(close_time_val, str):
                    close_time = datetime.fromisoformat(close_time_val)
                else:
                    close_time = None
            else:
                close_time = None

            # Extract signal_id and timeframe from command if available
            command_id = data.get('command_id')
            signal_id = None
            timeframe = None
            source = data.get('source', 'mt5_manual')
            entry_reason = None
            entry_confidence = None  # ✅ NEW: Track signal confidence at entry

            if command_id:
                # Get command to extract signal_id and timeframe
                command = db.query(Command).filter_by(id=command_id).first()
                if command and command.payload:
                    signal_id = command.payload.get('signal_id')
                    timeframe = command.payload.get('timeframe')
                    # If command has signal_id, this is an autotrade
                    if signal_id:
                        source = 'autotrade'
                        # Try to get signal details for entry_reason
                        from models import TradingSignal
                        signal = db.query(TradingSignal).filter_by(id=signal_id).first()
                        if signal:
                            # ✅ NEW: Store entry confidence
                            entry_confidence = float(signal.confidence) if signal.confidence else None

                            reason_parts = []
                            if signal.confidence:
                                reason_parts.append(f"{float(signal.confidence)*100:.1f}% confidence")
                            if signal.signal_type:
                                reason_parts.append(signal.signal_type)
                            if signal.timeframe:
                                reason_parts.append(signal.timeframe)
                            entry_reason = " | ".join(reason_parts) if reason_parts else "Auto-traded signal"
                        else:
                            entry_reason = "Auto-trade (signal not found)"
                    else:
                        source = 'ea_command'
                        entry_reason = "EA command"
            else:
                # ✅ NEW: No command_id provided - Try to find matching OPEN_TRADE command by ticket
                # This fixes the issue where EA doesn't send command_id in trade updates
                matching_command = db.query(Command).filter(
                    Command.account_id == account.id,
                    Command.command_type == 'OPEN_TRADE',
                    Command.status.in_(['completed', 'processing']),  # ✅ FIXED: Also check processing commands
                    Command.response['ticket'].astext == str(ticket)
                ).order_by(Command.created_at.desc()).first()

                # ✅ NEW: If no match by ticket, try to match by symbol/volume/time window
                if not matching_command:
                    # Look for recently created commands (last 30 seconds) with matching symbol and volume
                    # ✅ FIX: Extract symbol, volume, direction from data first
                    trade_symbol = data.get('symbol')
                    trade_volume = data.get('volume')
                    trade_direction = data.get('direction')
                    
                    if trade_symbol and trade_volume and trade_direction:
                        recent_threshold = datetime.utcnow() - timedelta(seconds=30)
                        
                        matching_command = db.query(Command).filter(
                            Command.account_id == account.id,
                            Command.command_type == 'OPEN_TRADE',
                            Command.created_at >= recent_threshold,
                            Command.payload['symbol'].astext == trade_symbol,
                            Command.payload['volume'].astext == str(float(trade_volume)),
                            Command.payload['order_type'].astext == trade_direction,
                            Command.response['ticket'].astext.is_(None)  # No ticket assigned yet
                        ).order_by(Command.created_at.desc()).first()
                        
                        if matching_command:
                            logger.info(f"🔗 Matched trade #{ticket} to command #{matching_command.id} by symbol/volume/time")

                if matching_command:
                    command_id = matching_command.id
                    if matching_command.payload:
                        signal_id = matching_command.payload.get('signal_id')
                        timeframe = matching_command.payload.get('timeframe')

                        if signal_id:
                            source = 'autotrade'
                            # Get signal details
                            from models import TradingSignal
                            signal = db.query(TradingSignal).filter_by(id=signal_id).first()
                            if signal:
                                entry_confidence = float(signal.confidence) if signal.confidence else None
                                reason_parts = []
                                if signal.confidence:
                                    reason_parts.append(f"{float(signal.confidence):.1f}% confidence")
                                if signal.signal_type:
                                    reason_parts.append(signal.signal_type)
                                if signal.timeframe:
                                    reason_parts.append(signal.timeframe)
                                entry_reason = " | ".join(reason_parts) if reason_parts else "Auto-traded signal"
                                logger.info(f"🔗 Linked trade #{ticket} to command #{command_id} (autotrade, signal #{signal_id})")
                            else:
                                entry_reason = "Auto-trade (signal not found)"
                                logger.info(f"🔗 Linked trade #{ticket} to command #{command_id} (autotrade, signal deleted)")
                        else:
                            source = 'ea_command'
                            entry_reason = "EA command"
                            logger.info(f"🔗 Linked trade #{ticket} to command #{command_id} (EA command)")
                else:
                    logger.info(f"⚠️ Trade #{ticket} has no matching command - classified as MT5 manual trade")

            # Fallback entry reasons
            if not entry_reason:
                if source == 'autotrade':
                    entry_reason = "Auto-trade (signal details unavailable)"
                elif source == 'mt5_manual' or source == 'MT5':
                    entry_reason = "Manual trade (MT5)"
                else:
                    entry_reason = f"Trade from {source}"

            # ✅ CRITICAL FIX 2025-11-05: Extract initial SL/TP from Command response
            # This ensures we always have the ORIGINAL SL/TP values for strategy evaluation
            # even if trailing stop has modified them to 0 or changed them
            initial_sl_from_command = None
            initial_tp_from_command = None

            if matching_command and matching_command.response:
                # EA sends back actual SL/TP values in response: {"sl": 1.23, "tp": 1.45, "ticket": 123}
                initial_sl_from_command = matching_command.response.get('sl')
                initial_tp_from_command = matching_command.response.get('tp')

                if initial_sl_from_command or initial_tp_from_command:
                    logger.info(f"📊 Retrieved initial SL/TP from command response: SL={initial_sl_from_command}, TP={initial_tp_from_command}")

            # Fallback: If no command response, use payload values (what we SENT to EA)
            if not initial_sl_from_command and matching_command and matching_command.payload:
                initial_sl_from_command = matching_command.payload.get('sl')
                initial_tp_from_command = matching_command.payload.get('tp')

                if initial_sl_from_command or initial_tp_from_command:
                    logger.info(f"📊 Retrieved initial SL/TP from command payload: SL={initial_sl_from_command}, TP={initial_tp_from_command}")

            new_trade = Trade(
                account_id=account.id,
                ticket=ticket,
                symbol=data.get('symbol'),
                type=data.get('type', 'MARKET'),
                direction=data.get('direction'),
                volume=data.get('volume'),
                open_price=data.get('open_price'),
                open_time=open_time,
                close_price=data.get('close_price'),
                close_time=close_time,
                sl=data.get('sl'),  # Current SL (may be modified by trailing stop)
                tp=data.get('tp'),  # Current TP (may be modified)
                original_tp=initial_tp_from_command if initial_tp_from_command is not None else data.get('tp'),  # ORIGINAL TP for extension tracking
                tp_extended_count=0,  # Initialize extension counter

                # ✅ COMPREHENSIVE TRACKING - Initial TP/SL Snapshot
                # Use values from Command response/payload (ORIGINAL values before any modifications)
                # Fallback to current position values if command not found
                initial_tp=initial_tp_from_command if initial_tp_from_command is not None else data.get('tp'),
                initial_sl=initial_sl_from_command if initial_sl_from_command is not None else data.get('sl'),

                profit=data.get('profit'),
                commission=data.get('commission'),
                swap=data.get('swap'),
                source=source,  # autotrade, ea_command, or mt5_manual
                command_id=command_id,
                signal_id=signal_id,  # Link to signal for autotrades
                entry_reason=entry_reason,  # ✅ NEW: Set entry reason for new trades
                entry_confidence=entry_confidence,  # ✅ NEW: Store entry confidence
                timeframe=timeframe,  # Timeframe for symbol+timeframe limiting
                close_reason=data.get('close_reason'),
                status=data.get('status', 'open'),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(new_trade)
            db.commit()
            logger.info(f"✅ Trade #{ticket} created from MT5: source={source}, signal_id={signal_id}, timeframe={timeframe}")

        # EMIT WEBSOCKET UPDATE: Send position update after trade change
        # This ensures dashboard updates even without tick streaming
        if trade or new_trade:
            actual_trade = trade if trade else new_trade
            if actual_trade.status == 'open':
                try:
                    # Get current price for the trade (fallback to open_price if no tick data)
                    from trade_monitor import get_trade_monitor
                    trade_monitor = get_trade_monitor()
                    current_price = trade_monitor.get_current_price(db, account.id, actual_trade.symbol)
                    
                    if not current_price:
                        current_price = {'bid': float(actual_trade.open_price), 'ask': float(actual_trade.open_price)}
                    
                    # Calculate P&L
                    eurusd_rate = trade_monitor.get_eurusd_rate(db, account.id)
                    pnl_data = trade_monitor.calculate_position_pnl(actual_trade, current_price, eurusd_rate)
                    
                    # Get opening reason using helper function
                    opening_reason = get_trade_opening_reason(actual_trade)
                    
                    position_info = {
                        'ticket': actual_trade.ticket,
                        'symbol': actual_trade.symbol,
                        'direction': actual_trade.direction.upper() if isinstance(actual_trade.direction, str) else ('BUY' if actual_trade.direction == 0 else 'SELL'),
                        'volume': float(actual_trade.volume),
                        'open_price': float(actual_trade.open_price),
                        'current_price': pnl_data['current_price'] if pnl_data else float(current_price['bid']),
                        'pnl': float(actual_trade.profit) if actual_trade.profit else 0.0,
                        'tp': float(actual_trade.tp) if actual_trade.tp else None,
                        'sl': float(actual_trade.sl) if actual_trade.sl else None,
                        'distance_to_tp_eur': pnl_data.get('distance_to_tp_eur') if pnl_data else None,
                        'distance_to_sl_eur': pnl_data.get('distance_to_sl_eur') if pnl_data else None,
                        'open_time': actual_trade.open_time.isoformat() if actual_trade.open_time else None,
                        'opening_reason': opening_reason,
                        'trailing_stop_info': None,
                    }
                    
                    socketio.emit('positions_update', {
                        'account_id': account.id,
                        'position_count': 1,
                        'positions': [position_info],
                        'total_pnl': float(actual_trade.profit) if actual_trade.profit else 0.0,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    logger.debug(f"📡 WebSocket: Position update emitted for trade #{ticket}")
                except Exception as ws_error:
                    logger.warning(f"WebSocket emission failed (non-critical): {ws_error}")

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Trade update error: {str(e)}")
        db.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# PORT 9903 - LOGGING
# ============================================================================

@app_logs.route('/api/log', methods=['POST'])
@require_api_key
def log_message(account, db):
    """
    Receive logs from EA
    """
    try:
        data = request.get_json()
        level = data.get('level', 'INFO')
        message = data.get('message', '')
        details = data.get('details', {})

        if not message:
            return jsonify({'status': 'error', 'message': 'No log message provided'}), 400

        # Create log entry
        log_entry = Log(
            account_id=account.id,
            level=level,
            message=message,
            details=details,
            timestamp=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()

        logger.info(f"[EA {account.mt5_account_number}] {level}: {message}")

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Log error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# BACKGROUND TASKS
# ============================================================================

def cleanup_ticks_job():
    """Background job to aggregate ticks to OHLC and cleanup old ticks"""
    import time
    from ohlc_aggregator import cleanup_ticks_with_aggregation
    from models import Account

    while True:
        try:
            time.sleep(60)  # Run every minute
            db = ScopedSession()
            try:
                # Get all accounts
                accounts = db.query(Account).all()

                for account in accounts:
                    # Aggregate and cleanup for each account
                    # Keep ticks for 5 minutes (sufficient for M5/M15 aggregation)
                    aggregated, deleted = cleanup_ticks_with_aggregation(
                        db, account.id, minutes=5
                    )

                    if aggregated > 0 or deleted > 0:
                        logger.info(
                            f"Account {account.mt5_account_number}: "
                            f"Aggregated {aggregated} M1 candles, deleted {deleted} ticks"
                        )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Tick cleanup/aggregation error: {e}")


def ohlc_cleanup_job():
    """Background job to cleanup OHLC data older than 1 year (daily)"""
    import time
    from cleanup_old_ohlc import cleanup_old_ohlc_data

    # Wait 5 minutes after startup before first run
    time.sleep(300)

    while True:
        try:
            logger.info("🗑️  Running daily OHLC cleanup...")
            cleanup_old_ohlc_data(days_to_keep=365)
            logger.info("✅ OHLC cleanup completed")

            # Run once per day (24 hours)
            time.sleep(86400)

        except Exception as e:
            logger.error(f"OHLC cleanup error: {e}")
            # Retry in 1 hour on error
            time.sleep(3600)


def retention_cleanup_job():
    """Background job for long-term data retention cleanup (daily)"""
    import time
    from database import cleanup_old_data

    while True:
        try:
            # Run once per day (86400 seconds)
            time.sleep(86400)
            db = ScopedSession()
            try:
                result = cleanup_old_data(
                    db,
                    tick_days=30,      # Keep ticks for 30 days
                    ohlc_days=730      # Keep OHLC for 2 years
                )
                logger.info(
                    f"Retention cleanup: {result['deleted_ticks']} ticks (>30d), "
                    f"{result['deleted_ohlc']} OHLC records (>2y) deleted"
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Retention cleanup error: {e}")


# ============================================================================
# PORT 9905 - WEB UI & DASHBOARD
# ============================================================================

@app_webui.route('/')
def dashboard():
    """Main dashboard view"""
    return render_template('dashboard.html')

@app_webui.route('/unified')
def dashboard_unified():
    """Unified dashboard view (alternative)"""
    return render_template('dashboard_unified.html')


@app_webui.route('/api/dashboard/status')
def dashboard_status():
    """Get account status for dashboard"""
    try:
        db = ScopedSession()
        try:
            from sqlalchemy import func, cast, Date
            from models import Trade

            # Get the most recently active account (latest heartbeat)
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()

            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Calculate profits directly from database (don't rely on heartbeat)
            now = datetime.utcnow()
            today_date = now.date()
            week_start_date = (now - timedelta(days=now.weekday())).date()  # Monday
            month_start_date = now.replace(day=1).date()
            year_start_date = now.replace(month=1, day=1).date()

            # Calculate actual profit from closed trades - GLOBAL (across all accounts for ML learning)
            profit_today = db.query(
                func.coalesce(func.sum(Trade.profit), 0)
            ).filter(
                Trade.status == 'closed',
                cast(Trade.close_time, Date) == today_date
            ).scalar() or 0.0

            profit_week = db.query(
                func.coalesce(func.sum(Trade.profit), 0)
            ).filter(
                Trade.status == 'closed',
                cast(Trade.close_time, Date) >= week_start_date
            ).scalar() or 0.0

            profit_month = db.query(
                func.coalesce(func.sum(Trade.profit), 0)
            ).filter(
                Trade.status == 'closed',
                cast(Trade.close_time, Date) >= month_start_date
            ).scalar() or 0.0

            profit_year = db.query(
                func.coalesce(func.sum(Trade.profit), 0)
            ).filter(
                Trade.status == 'closed',
                cast(Trade.close_time, Date) >= year_start_date
            ).scalar() or 0.0

            return jsonify({
                'status': 'success',
                'account': {
                    'id': account.id,  # Add account ID for monitoring endpoint
                    'number': account.mt5_account_number,
                    'broker': account.broker,
                    'balance': float(account.balance) if account.balance else 0.0,
                    'equity': float(account.equity) if account.equity else 0.0,
                    'margin': float(account.margin) if account.margin else 0.0,
                    'free_margin': float(account.free_margin) if account.free_margin else 0.0,
                    'profit_today': float(profit_today),
                    'profit_week': float(profit_week),
                    'profit_month': float(profit_month),
                    'profit_year': float(profit_year),
                    'last_heartbeat': account.last_heartbeat.isoformat() if account.last_heartbeat else None
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Dashboard status error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/info')
def dashboard_info():
    """Get dashboard info bar data (database size, time, etc.)"""
    try:
        db = ScopedSession()
        try:
            from datetime import datetime
            import pytz

            # Get database size
            result = db.execute(text("""
                SELECT
                    pg_size_pretty(pg_database_size(current_database())) as db_size,
                    (SELECT COUNT(*) FROM ticks) as tick_count,
                    (SELECT COUNT(*) FROM ohlc_data) as ohlc_count
            """))
            row = result.fetchone()

            # Get current times
            utc_now = datetime.utcnow()
            local_tz = pytz.timezone('Europe/Berlin')  # Adjust if needed
            local_now = utc_now.replace(tzinfo=pytz.utc).astimezone(local_tz)

            return jsonify({
                'status': 'success',
                'info': {
                    'db_size': row[0] if row else '-',
                    'tick_count': row[1] if row else 0,
                    'ohlc_count': row[2] if row else 0,
                    'server_time': utc_now.strftime('%H:%M:%S UTC'),
                    'local_time': local_now.strftime('%H:%M:%S'),
                    'date': local_now.strftime('%d.%m.%Y'),
                    'weekday': local_now.strftime('%A')
                }
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in dashboard_info: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/symbols')
def dashboard_symbols():
    """Get subscribed symbols with latest tick data"""
    try:
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account

            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            subscribed = db.query(SubscribedSymbol).filter_by(
                account_id=account.id,
                active=True
            ).all()

            symbols_data = []
            for sub in subscribed:
                # NOTE: Ticks are now GLOBAL (no account_id)
                latest_tick = db.query(Tick).filter_by(
                    symbol=sub.symbol
                ).order_by(Tick.timestamp.desc()).first()

                tick_count = db.query(Tick).filter_by(
                    symbol=sub.symbol
                ).count()

                # Calculate trends for different timeframes
                trends = {}
                for tf in ['M5', 'M15', 'H1', 'H4']:
                    # NOTE: OHLCData is GLOBAL (no account_id)
                    ohlc_data = db.query(OHLCData).filter_by(
                        symbol=sub.symbol,
                        timeframe=tf
                    ).order_by(OHLCData.timestamp.desc()).limit(2).all()

                    if len(ohlc_data) >= 2:
                        current = float(ohlc_data[0].close)
                        previous = float(ohlc_data[1].close)
                        diff_percent = ((current - previous) / previous) * 100

                        if diff_percent > 0.01:
                            trends[tf] = 'up'
                        elif diff_percent < -0.01:
                            trends[tf] = 'down'
                        else:
                            trends[tf] = 'neutral'
                    else:
                        trends[tf] = 'neutral'

                # ✅ Add market hours status using new MarketHours module
                from market_hours import MarketHours
                market_open = MarketHours.is_market_open(sub.symbol)
                trading_session = MarketHours.get_trading_session(sub.symbol)
                market_hours_str = MarketHours.get_market_hours_string(sub.symbol)

                symbols_data.append({
                    'symbol': sub.symbol,
                    'bid': f"{latest_tick.bid:.5f}" if latest_tick else None,
                    'ask': f"{latest_tick.ask:.5f}" if latest_tick else None,
                    'tick_count': tick_count,
                    'last_tick': latest_tick.timestamp.strftime('%H:%M:%S') if latest_tick else None,
                    'trends': trends,
                    'tradeable': latest_tick.tradeable if latest_tick else True,
                    'market_open': market_open,
                    'trading_session': trading_session,
                    'market_hours': market_hours_str
                })

            # Add account data with profit values
            account_data = {
                'number': account.mt5_account_number,
                'balance': float(account.balance) if account.balance else 0.0,
                'equity': float(account.equity) if account.equity else 0.0,
                'margin': float(account.margin) if account.margin else 0.0,
                'free_margin': float(account.free_margin) if account.free_margin else 0.0,
                'profit_today': float(account.profit_today) if account.profit_today else 0.0,
                'profit_week': float(account.profit_week) if account.profit_week else 0.0,
                'profit_month': float(account.profit_month) if account.profit_month else 0.0,
                'profit_year': float(account.profit_year) if account.profit_year else 0.0
            }

            return jsonify({
                'status': 'success',
                'symbols': symbols_data,
                'account': account_data
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Dashboard symbols error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/ohlc')
def dashboard_ohlc():
    """Get OHLC data for specified timeframe and symbol"""
    try:
        timeframe = request.args.get('timeframe', 'M1')
        symbol = request.args.get('symbol')
        limit = int(request.args.get('limit', 100))

        if not symbol:
            return jsonify({'status': 'error', 'message': 'Symbol parameter required'}), 400

        db = ScopedSession()
        try:
            # OHLC data is now global (no account_id needed)
            query = db.query(OHLCData).filter_by(
                symbol=symbol,
                timeframe=timeframe
            )

            ohlc_data = query.order_by(OHLCData.timestamp.desc()).limit(limit).all()

            candle_list = []
            for ohlc in reversed(ohlc_data):
                candle_list.append({
                    'time': ohlc.timestamp.isoformat(),
                    'open': float(ohlc.open),
                    'high': float(ohlc.high),
                    'low': float(ohlc.low),
                    'close': float(ohlc.close),
                    'volume': int(ohlc.volume) if ohlc.volume else 0
                })

            return jsonify({
                'status': 'success',
                'symbol': symbol,
                'timeframe': timeframe,
                'candles': candle_list
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Dashboard OHLC error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _get_symbol_performance():
    """Shared logic for symbol performance endpoint"""
    db = ScopedSession()
    try:
        from models import SymbolPerformanceTracking
        from datetime import datetime

        account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account

        if not account:
            return {'status': 'error', 'message': 'No account found'}, 404

        # Get today's performance tracking directly from DB
        today = datetime.utcnow().date()
        perfs = db.query(SymbolPerformanceTracking).filter(
            SymbolPerformanceTracking.account_id == account.id,
            SymbolPerformanceTracking.evaluation_date == today
        ).all()

        results = []
        for perf in perfs:
            results.append({
                'symbol': perf.symbol,
                'status': perf.status,
                'live_trades': perf.live_trades or 0,
                'live_win_rate': float(perf.live_win_rate or 0),
                'live_profit': float(perf.live_profit or 0),
                'backtest_win_rate': float(perf.backtest_win_rate or 0),
                'backtest_profit': float(perf.backtest_profit or 0),
                'auto_disabled_reason': perf.auto_disabled_reason,
                'updated_at': perf.updated_at.isoformat() if perf.updated_at else None
            })

        # Sort by profit descending
        results = sorted(results, key=lambda x: x['live_profit'], reverse=True)

        logger.info(f"📊 Returning symbol performance for {len(results)} symbols")

        return {'status': 'success', 'symbols': results}, 200

    except Exception as e:
        logger.error(f"Dashboard performance error: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}, 500
    finally:
        db.close()


@app_command.route('/api/performance/symbols', methods=['GET'])
def command_performance():
    """Get live symbol performance metrics (24h) - Port 9900"""
    result, status = _get_symbol_performance()
    return jsonify(result), status


@app_webui.route('/api/performance/symbols', methods=['GET'])
def dashboard_performance():
    """Get live symbol performance metrics (24h) - Port 9905"""
    result, status = _get_symbol_performance()
    return jsonify(result), status


@app_webui.route('/api/symbol-config/summary', methods=['GET'])
def get_symbol_config_summary():
    """Get summary of symbol configs"""
    try:
        from models import SymbolTradingConfig
        account_id = request.args.get('account_id', 3, type=int)

        db = ScopedSession()
        try:
            configs = db.query(SymbolTradingConfig).filter_by(account_id=account_id).all()

            summary = {
                'total': len(configs),
                'active': len([c for c in configs if c.status == 'active']),
                'paused': len([c for c in configs if c.status == 'paused']),
                'configs': []
            }

            for c in configs:
                summary['configs'].append({
                    'id': c.id,
                    'symbol': c.symbol,
                    'direction': c.direction,
                    'status': c.status,
                    'risk_multiplier': float(c.risk_multiplier) if c.risk_multiplier else 1.0,
                    'min_confidence': float(c.min_confidence_threshold) if c.min_confidence_threshold else 50.0,
                    'rolling_profit': float(c.rolling_profit) if c.rolling_profit else 0.0,
                    'rolling_winrate': float(c.rolling_winrate) if c.rolling_winrate else 0.0,
                    'rolling_trades': c.rolling_trades_count or 0
                })

            return jsonify({'success': True, 'summary': summary}), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Symbol config summary error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app_webui.route('/api/dashboard/storage')
def dashboard_storage():
    """Get database storage statistics"""
    try:
        db = ScopedSession()
        try:
            from sqlalchemy import text

            # Get table sizes
            result = db.execute(text("""
                SELECT
                    tablename,
                    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS size,
                    pg_total_relation_size('public.'||tablename) AS bytes
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size('public.'||tablename) DESC
            """))

            tables = []
            for row in result:
                tables.append({
                    'table': row[0],
                    'size': row[1],
                    'bytes': row[2]
                })

            # Get record counts
            tick_count = db.query(Tick).count()
            ohlc_count = db.query(OHLCData).count()

            # Get date ranges
            tick_range = db.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM ticks")).fetchone()
            ohlc_range = db.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM ohlc_data")).fetchone()

            return jsonify({
                'status': 'success',
                'tables': tables,
                'stats': {
                    'tick_count': tick_count,
                    'ohlc_count': ohlc_count,
                    'tick_range': {
                        'first': tick_range[0].isoformat() if tick_range[0] else None,
                        'last': tick_range[1].isoformat() if tick_range[1] else None
                    },
                    'ohlc_range': {
                        'first': ohlc_range[0].isoformat() if ohlc_range[0] else None,
                        'last': ohlc_range[1].isoformat() if ohlc_range[1] else None
                    }
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Storage stats error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/transactions')
def dashboard_transactions():
    """Get recent account transactions"""
    try:
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account

            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get last 50 transactions
            transactions = db.query(AccountTransaction).filter_by(
                account_id=account.id
            ).order_by(AccountTransaction.timestamp.desc()).limit(50).all()

            transactions_data = []
            for txn in transactions:
                transactions_data.append({
                    'id': txn.id,
                    'type': txn.transaction_type,
                    'amount': float(txn.amount),
                    'balance_after': float(txn.balance_after) if txn.balance_after else None,
                    'comment': txn.comment,
                    'timestamp': txn.timestamp.isoformat(),
                    'created_at': txn.created_at.isoformat()
                })

            return jsonify({
                'status': 'success',
                'transactions': transactions_data,
                'count': len(transactions_data)
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Dashboard transactions error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/statistics')
def dashboard_statistics():
    """Get live trading statistics (Win Rate, Profit Factor, etc.)"""
    try:
        from models import Trade
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Helper function to calculate stats for a set of trades
            def calculate_stats(trades):
                if not trades:
                    return {
                        'total_trades': 0,
                        'winning_trades': 0,
                        'losing_trades': 0,
                        'win_rate': 0.0,
                        'total_profit': 0.0,
                        'total_loss': 0.0,
                        'profit_factor': 0.0,
                        'avg_win': 0.0,
                        'avg_loss': 0.0,
                        'best_trade': 0.0,
                        'worst_trade': 0.0,
                        'avg_trade_duration': None
                    }

                total_trades = len(trades)
                winning_trades = [t for t in trades if t.profit and t.profit > 0]
                losing_trades = [t for t in trades if t.profit and t.profit < 0]

                total_profit = sum(t.profit for t in winning_trades)
                total_loss = abs(sum(t.profit for t in losing_trades))

                profit_factor = (total_profit / total_loss) if total_loss > 0 else 0.0
                win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0

                avg_win = (total_profit / len(winning_trades)) if winning_trades else 0.0
                avg_loss = (total_loss / len(losing_trades)) if losing_trades else 0.0

                all_profits = [t.profit for t in trades if t.profit]
                best_trade = max(all_profits) if all_profits else 0.0
                worst_trade = min(all_profits) if all_profits else 0.0

                # Calculate average trade duration
                durations = []
                for t in trades:
                    if t.open_time and t.close_time:
                        duration = (t.close_time - t.open_time).total_seconds() / 3600  # hours
                        durations.append(duration)
                avg_duration_hours = (sum(durations) / len(durations)) if durations else None

                return {
                    'total_trades': total_trades,
                    'winning_trades': len(winning_trades),
                    'losing_trades': len(losing_trades),
                    'win_rate': round(win_rate, 2),
                    'total_profit': round(total_profit, 2),
                    'total_loss': round(total_loss, 2),
                    'profit_factor': round(profit_factor, 2),
                    'avg_win': round(avg_win, 2),
                    'avg_loss': round(avg_loss, 2),
                    'best_trade': round(best_trade, 2),
                    'worst_trade': round(worst_trade, 2),
                    'avg_trade_duration_hours': round(avg_duration_hours, 2) if avg_duration_hours else None
                }

            # Get date ranges
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())  # Monday
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            # Query closed trades for different periods - GLOBAL (for ML learning across all accounts)
            base_query = db.query(Trade).filter(
                Trade.status == 'closed',
                Trade.profit != None
            )

            today_trades = base_query.filter(Trade.close_time >= today_start).all()
            week_trades = base_query.filter(Trade.close_time >= week_start).all()
            month_trades = base_query.filter(Trade.close_time >= month_start).all()
            all_trades = base_query.all()

            return jsonify({
                'status': 'success',
                'statistics': {
                    'today': calculate_stats(today_trades),
                    'week': calculate_stats(week_trades),
                    'month': calculate_stats(month_trades),
                    'all_time': calculate_stats(all_trades)
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Dashboard statistics error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/traded-symbols')
def get_traded_symbols():
    """Get list of symbols that have been traded (for filter dropdowns)"""
    try:
        from models import Trade
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get distinct symbols from trades - GLOBAL (for ML learning across all accounts)
            symbols = db.query(Trade.symbol).distinct().order_by(Trade.symbol).all()

            symbol_list = [s[0] for s in symbols if s[0]]

            return jsonify({
                'status': 'success',
                'symbols': symbol_list
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Traded symbols error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/backup/status')
def backup_status():
    """Get backup status and statistics"""
    try:
        scheduler = get_scheduler()
        stats = scheduler.get_backup_stats()
        return jsonify({'status': 'success', 'backup': stats}), 200
    except Exception as e:
        logger.error(f"Backup status error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/backup/trigger', methods=['POST'])
def trigger_backup():
    """Manually trigger a backup"""
    try:
        scheduler = get_scheduler()
        if scheduler.backup_enabled or request.json.get('force'):
            success = scheduler.run_backup()
            if success:
                return jsonify({'status': 'success', 'message': 'Backup completed'}), 200
            else:
                return jsonify({'status': 'error', 'message': 'Backup failed'}), 500
        else:
            return jsonify({'status': 'error', 'message': 'Backup is disabled'}), 400
    except Exception as e:
        logger.error(f"Manual backup error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/dashboard/tick_writer_stats', methods=['GET'])
def tick_writer_stats():
    """Get tick batch writer statistics"""
    try:
        writer = get_batch_writer()
        stats = writer.get_stats()

        # Add Redis buffer stats
        try:
            redis = get_redis()
            # Get buffer sizes for all accounts (simplified - just check account 1)
            buffer_size = redis.get_total_buffer_size(1)
            stats['redis_buffer_size'] = buffer_size
        except Exception as e:
            logger.debug(f"Redis buffer size check failed: {e}")
            stats['redis_buffer_size'] = 0

        return jsonify({'status': 'success', 'writer': stats}), 200
    except Exception as e:
        logger.error(f"Tick writer stats error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    logger.info("WebSocket client connected")
    emit('connected', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info("WebSocket client disconnected")


@socketio.on('request_price_chart')
def handle_price_chart_request(data):
    """Client requests price chart for specific symbol

    Args:
        data: dict with keys 'symbol', 'timeframe', 'bars', 'filter', 'hours'
    """
    try:
        from monitoring.price_chart_generator import PriceChartGenerator

        symbol = data.get('symbol')
        timeframe = data.get('timeframe', 'H1')
        bars = data.get('bars', 100)
        trade_filter = data.get('filter', 'open')
        hours_back = data.get('hours', 24)

        if not symbol:
            emit('error', {'message': 'Symbol is required'})
            return

        with PriceChartGenerator(account_id=3) as generator:
            fig = generator.generate_price_chart_with_tpsl(
                symbol=symbol,
                timeframe=timeframe,
                bars_back=bars,
                trade_filter=trade_filter,
                hours_back=hours_back
            )

            if not fig:
                emit('error', {'message': f'No data available for {symbol}'})
                return

            img_base64 = generator.fig_to_base64(fig)

        emit('price_chart_update', {
            'symbol': symbol,
            'timeframe': timeframe,
            'bars': bars,
            'filter': trade_filter,
            'hours': hours_back,
            'image': f'data:image/png;base64,{img_base64}',
            'generated_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error generating price chart for {symbol}: {e}", exc_info=True)
        emit('error', {'message': str(e)})


@socketio.on('request_all_price_charts')
def handle_all_price_charts_request(data):
    """Client requests price charts for all symbols with trades

    Args:
        data: dict with keys 'timeframe', 'bars', 'filter', 'hours' (all optional)
    """
    try:
        from monitoring.price_chart_generator import PriceChartGenerator
        from sqlalchemy import distinct, or_

        timeframe = data.get('timeframe', 'H1')
        bars = data.get('bars', 100)
        trade_filter = data.get('filter', 'open')
        hours_back = data.get('hours', 24)

        # Get all symbols with trades matching filter
        db = ScopedSession()
        try:
            query = db.query(distinct(Trade.symbol)).filter(
                Trade.account_id == 3
            )

            if trade_filter == 'open':
                query = query.filter(Trade.status == 'open')
            elif trade_filter == 'closed':
                since = datetime.utcnow() - timedelta(hours=hours_back)
                query = query.filter(
                    Trade.status == 'closed',
                    Trade.close_time >= since
                )
            elif trade_filter == 'all':
                since = datetime.utcnow() - timedelta(hours=hours_back)
                query = query.filter(
                    or_(
                        Trade.status == 'open',
                        (Trade.status == 'closed') & (Trade.close_time >= since)
                    )
                )

            symbols = [s[0] for s in query.all()]
        finally:
            db.close()

        charts = []
        with PriceChartGenerator(account_id=3) as generator:
            for symbol in symbols:
                try:
                    fig = generator.generate_price_chart_with_tpsl(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars_back=bars,
                        trade_filter=trade_filter,
                        hours_back=hours_back
                    )

                    if fig:
                        img_base64 = generator.fig_to_base64(fig)
                        charts.append({
                            'symbol': symbol,
                            'image': f'data:image/png;base64,{img_base64}'
                        })
                except Exception as e:
                    logger.error(f"Error generating chart for {symbol}: {e}")
                    continue

        emit('price_charts_update', {
            'timeframe': timeframe,
            'bars': bars,
            'filter': trade_filter,
            'hours': hours_back,
            'charts': charts,
            'generated_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error generating price charts: {e}", exc_info=True)
        emit('error', {'message': str(e)})


def broadcast_tick_update(symbol, bid, ask):
    """Broadcast tick update to all connected clients"""
    socketio.emit('tick_update', {
        'symbol': symbol,
        'bid': bid,
        'ask': ask,
        'timestamp': datetime.utcnow().isoformat()
    })


# ============================================================================
# TRADING SIGNALS API
# ============================================================================

@app_webui.route('/api/signals')
def get_signals():
    """Get active trading signals with filters"""
    try:
        # ✅ FIX BUG-003: Input validation to prevent SQL injection
        from input_validator import InputValidator, validate_signal_type, validate_timeframe
        
        # Get and validate query parameters
        symbol_raw = request.args.get('symbol')
        timeframe_raw = request.args.get('timeframe')
        min_confidence_raw = request.args.get('confidence', type=float, default=0)
        signal_type_raw = request.args.get('type')  # BUY or SELL
        
        # Validate inputs
        symbol = InputValidator.validate_symbol(symbol_raw) if symbol_raw else None
        timeframe = validate_timeframe(timeframe_raw) if timeframe_raw else None
        min_confidence = InputValidator.validate_float(min_confidence_raw, min_value=0, max_value=100, default=0)
        signal_type = validate_signal_type(signal_type_raw) if signal_type_raw else None

        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Expire old signals BEFORE querying (clean up on every refresh)
            # Note: Signals are now global (no account_id filter)
            now = datetime.utcnow()
            expired_count = db.query(TradingSignal).filter(
                TradingSignal.status == 'active',
                TradingSignal.expires_at <= now
            ).update({'status': 'expired'}, synchronize_session=False)

            if expired_count > 0:
                db.commit()
                logger.info(f"Expired {expired_count} old signals on /api/signals refresh")

            # Build query for active signals
            # Note: Signal validation (pattern/indicator check) is now handled automatically
            # by signal_worker when it calls generate_signal() every 10-20s
            # Note: Signals are now global (no account_id)
            query = db.query(TradingSignal).filter_by(
                status='active'
            )

            # Apply filters
            if symbol:
                query = query.filter_by(symbol=symbol)
            if timeframe:
                query = query.filter_by(timeframe=timeframe)
            if min_confidence:
                query = query.filter(TradingSignal.confidence >= min_confidence)
            if signal_type:
                query = query.filter_by(signal_type=signal_type)

            # Get signals
            signals = query.order_by(TradingSignal.created_at.desc()).limit(50).all()

            # Get tradeable status for symbols using server-side validation
            signals_data = []
            for sig in signals:
                # Use server-side market hours check
                tradeable = is_symbol_tradeable_now(sig.symbol)

                # Calculate age in minutes
                age_minutes = int((datetime.utcnow() - sig.created_at).total_seconds() / 60) if sig.created_at else None

                # Calculate risk amount (default to fixed 1% of account balance)
                risk_amount = 0.0
                lot_size = 0.01
                if sig.entry_price and sig.sl_price:
                    # Get account balance
                    if account and account.balance:
                        balance = float(account.balance)
                        risk_percent = 0.01  # 1% risk
                        risk_amount = balance * risk_percent

                        # Calculate lot size based on risk
                        pip_value = abs(float(sig.entry_price) - float(sig.sl_price))
                        if pip_value > 0:
                            # For forex pairs, 1 standard lot = $10 per pip for major pairs
                            # Adjust based on symbol type
                            if 'USD' in sig.symbol or 'EUR' in sig.symbol or 'GBP' in sig.symbol:
                                pip_value_per_lot = 10.0  # $10 per pip for 1 standard lot
                            else:
                                pip_value_per_lot = 1.0  # Conservative for other symbols

                            # Calculate lot size: risk_amount / (pip_distance * pip_value_per_lot)
                            lot_size = risk_amount / (pip_value * pip_value_per_lot * 10000)  # Convert to pips
                            lot_size = round(lot_size, 2)
                            lot_size = max(0.01, min(lot_size, 10.0))  # Clamp between 0.01 and 10 lots

                # Extract indicator values from indicators_used JSONB
                indicators = sig.indicators_used or {}

                # RSI - handle both old format (number) and new format (dict with 'value')
                rsi_data = indicators.get('RSI')
                if isinstance(rsi_data, dict):
                    rsi = rsi_data.get('value')
                elif isinstance(rsi_data, (int, float)):
                    rsi = rsi_data
                else:
                    rsi = None

                # MACD - handle dict format
                macd_data = indicators.get('MACD', {})
                macd_value = macd_data.get('macd') if isinstance(macd_data, dict) else None
                macd_signal_value = macd_data.get('signal') if isinstance(macd_data, dict) else None

                # Bollinger Bands - handle dict format
                bb_data = indicators.get('BB', {})
                bb_position = bb_data.get('position') if isinstance(bb_data, dict) else None

                signals_data.append({
                    'id': sig.id,
                    'symbol': sig.symbol,
                    'timeframe': sig.timeframe,
                    'signal_type': sig.signal_type,
                    'confidence': float(sig.confidence),
                    'entry_price': float(sig.entry_price) if sig.entry_price else None,
                    'sl_price': float(sig.sl_price) if sig.sl_price else None,
                    'tp_price': float(sig.tp_price) if sig.tp_price else None,
                    'lot_size': lot_size,
                    'risk_amount': risk_amount,
                    'age_minutes': age_minutes,
                    'rsi': rsi,
                    'macd_value': macd_value,
                    'macd_signal': macd_signal_value,
                    'bb_position': bb_position,
                    'indicators_used': sig.indicators_used,
                    'patterns_detected': sig.patterns_detected,
                    'reasons': sig.reasons,
                    'status': sig.status,
                    'tradeable': tradeable,
                    'created_at': sig.created_at.isoformat(),
                    'expires_at': sig.expires_at.isoformat() if sig.expires_at else None
                })

            # Get volatility level and interval from Redis
            from redis_client import get_redis
            redis = get_redis()
            volatility_level = redis.get('market_volatility')
            signal_interval = redis.get('signal_interval')

            if not volatility_level:
                volatility_level = 'normal'

            if signal_interval:
                signal_interval = int(signal_interval)
            else:
                signal_interval = 10

            response = jsonify({
                'status': 'success',
                'signals': signals_data,
                'count': len(signals_data),
                'volatility': volatility_level,
                'interval': signal_interval
            })
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response, 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Get signals error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/signals/<int:signal_id>')
def get_signal_details(signal_id):
    """Get detailed information about a specific signal"""
    try:
        db = ScopedSession()
        try:
            signal = db.query(TradingSignal).filter_by(id=signal_id).first()

            if not signal:
                return jsonify({'status': 'error', 'message': 'Signal not found'}), 404

            signal_data = {
                'id': signal.id,
                'symbol': signal.symbol,
                'timeframe': signal.timeframe,
                'signal_type': signal.signal_type,
                'confidence': float(signal.confidence),
                'entry_price': float(signal.entry_price) if signal.entry_price else None,
                'sl_price': float(signal.sl_price) if signal.sl_price else None,
                'tp_price': float(signal.tp_price) if signal.tp_price else None,
                'indicators_used': signal.indicators_used,
                'patterns_detected': signal.patterns_detected,
                'reasons': signal.reasons,
                'status': signal.status,
                'created_at': signal.created_at.isoformat(),
                'expires_at': signal.expires_at.isoformat() if signal.expires_at else None,
                'executed_at': signal.executed_at.isoformat() if signal.executed_at else None
            }

            return jsonify({'status': 'success', 'signal': signal_data}), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Get signal details error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/signals/<int:signal_id>/ignore', methods=['POST'])
def ignore_signal(signal_id):
    """Mark a signal as ignored"""
    try:
        db = ScopedSession()
        try:
            signal = db.query(TradingSignal).filter_by(id=signal_id).first()

            if not signal:
                return jsonify({'status': 'error', 'message': 'Signal not found'}), 404

            signal.status = 'ignored'
            db.commit()

            logger.info(f"Signal {signal_id} marked as ignored")

            return jsonify({'status': 'success', 'message': 'Signal ignored'}), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Ignore signal error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/open_trade', methods=['POST'])
def open_trade_from_dashboard():
    """
    ❌ DISABLED: Dashboard should NOT execute trades
    All trade execution is managed by server's auto_trader.py
    Dashboard is VIEW-ONLY for monitoring signals and positions
    """
    logger.warning("⚠️  Blocked manual trade execution attempt via /api/open_trade")
    return jsonify({
        'status': 'error',
        'message': 'Manual trade execution is disabled. All trades are managed by the server auto-trader.'
    }), 403


@app_webui.route('/api/close_trade/<int:ticket>', methods=['POST'])
def close_trade(ticket):
    """Close a specific trade by ticket number"""
    try:
        from command_helper import create_command

        db = ScopedSession()
        try:
            # Get first account
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Verify trade exists and is open
            trade = db.query(Trade).filter_by(ticket=ticket, status='open').first()
            if not trade:
                return jsonify({'status': 'error', 'message': f'Open trade with ticket {ticket} not found'}), 404

            # Create close command
            payload = {
                'ticket': ticket
            }

            command = create_command(
                db=db,
                account_id=account.id,
                command_type='CLOSE_TRADE',
                payload=payload
            )

            logger.info(f"Close trade command created: {command.id} - Ticket #{ticket}")

            return jsonify({
                'status': 'success',
                'message': f'Close command sent for trade #{ticket}',
                'command_id': command.id
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Close trade error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/close_all_profitable', methods=['POST'])
def close_all_profitable():
    """Close all trades that are currently in profit"""
    try:
        from command_helper import create_command

        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get all open trades
            open_trades = db.query(Trade).filter_by(status='open').all()

            if not open_trades:
                return jsonify({'status': 'info', 'message': 'No open trades to close'}), 200

            # Get current P&L from monitoring data
            from redis_client import get_redis
            import json
            redis = get_redis()
            monitoring_data = redis.get(f"monitoring:account:{account.id}")

            if not monitoring_data:
                return jsonify({'status': 'error', 'message': 'No monitoring data available'}), 400

            monitoring_data = json.loads(monitoring_data)
            positions = monitoring_data.get('positions', [])

            # Find profitable trades
            profitable_tickets = []
            for pos in positions:
                if pos.get('pnl', 0) > 0:
                    profitable_tickets.append(pos['ticket'])

            if not profitable_tickets:
                return jsonify({'status': 'info', 'message': 'No profitable trades to close'}), 200

            # Create close commands for all profitable trades
            commands_created = []
            for ticket in profitable_tickets:
                payload = {'ticket': ticket}
                command = create_command(
                    db=db,
                    account_id=account.id,
                    command_type='CLOSE_TRADE',
                    payload=payload
                )
                commands_created.append(command.id)

            logger.info(f"Close all profitable: {len(commands_created)} commands created for tickets: {profitable_tickets}")

            return jsonify({
                'status': 'success',
                'message': f'Close commands sent for {len(profitable_tickets)} profitable trades',
                'tickets': profitable_tickets,
                'commands': commands_created
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Close all profitable error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/close_all_trades', methods=['POST'])
def close_all_trades():
    """Close ALL open trades (requires confirmation from frontend)"""
    try:
        from command_helper import create_command

        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get all open trades
            open_trades = db.query(Trade).filter_by(status='open').all()

            if not open_trades:
                return jsonify({'status': 'info', 'message': 'No open trades to close'}), 200

            # Create close commands for all trades
            commands_created = []
            tickets = []
            for trade in open_trades:
                payload = {'ticket': trade.ticket}
                command = create_command(
                    db=db,
                    account_id=account.id,
                    command_type='CLOSE_TRADE',
                    payload=payload
                )
                commands_created.append(command.id)
                tickets.append(trade.ticket)

            logger.warning(f"CLOSE ALL TRADES: {len(commands_created)} commands created for tickets: {tickets}")

            return jsonify({
                'status': 'success',
                'message': f'Close commands sent for {len(tickets)} trades',
                'tickets': tickets,
                'commands': commands_created
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Close all trades error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/set_trailing_stop/<int:ticket>', methods=['POST'])
def set_trailing_stop(ticket):
    """Manually set/update trailing stop for a specific trade"""
    try:
        from command_helper import create_command

        data = request.get_json()
        trailing_stop_pips = data.get('trailing_stop_pips')

        if not trailing_stop_pips:
            return jsonify({'status': 'error', 'message': 'trailing_stop_pips required'}), 400

        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Verify trade exists and is open
            trade = db.query(Trade).filter_by(ticket=ticket, status='open').first()
            if not trade:
                return jsonify({'status': 'error', 'message': f'Open trade with ticket {ticket} not found'}), 404

            # Create MODIFY_TRADE command with trailing stop
            payload = {
                'ticket': ticket,
                'trailing_stop': float(trailing_stop_pips)
            }

            command = create_command(
                db=db,
                account_id=account.id,
                command_type='MODIFY_TRADE',
                payload=payload
            )

            logger.info(f"Set trailing stop command created: {command.id} - Ticket #{ticket}, TS: {trailing_stop_pips} pips")

            return jsonify({
                'status': 'success',
                'message': f'Trailing stop set to {trailing_stop_pips} pips for trade #{ticket}',
                'command_id': command.id
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Set trailing stop error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/set_dynamic_trailing_stop/<int:ticket>', methods=['POST'])
def set_dynamic_trailing_stop(ticket):
    """
    Set noise-adaptive trailing stop instantly for a specific trade.
    Calculates optimal TS distance based on 60s noise, session, regime, etc.
    Sets TS just below noise threshold for immediate protection.
    """
    try:
        from command_helper import create_command
        from noise_adaptive_trailing_stop import NoiseAdaptiveTrailingStop

        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Verify trade exists and is open
            trade = db.query(Trade).filter_by(ticket=ticket, status='open').first()
            if not trade:
                return jsonify({'status': 'error', 'message': f'Open trade with ticket {ticket} not found'}), 404

            # Initialize noise-adaptive TS calculator
            nas = NoiseAdaptiveTrailingStop(account_id=account.id)

            # Get current price from latest tick
            from models import Tick
            latest_tick = db.query(Tick).filter_by(
                symbol=trade.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not latest_tick:
                return jsonify({'status': 'error', 'message': f'No tick data for {trade.symbol}'}), 404

            # Use bid for BUY, ask for SELL
            current_price = float(latest_tick.bid if trade.direction == 'BUY' else latest_tick.ask)

            # Calculate dynamic trailing stop distance
            result = nas.calculate_dynamic_trail_distance(db, trade, current_price)

            if not result or 'error' in result:
                error_msg = result.get('error', 'Unknown error') if result else 'Calculation failed'
                return jsonify({'status': 'error', 'message': f'Could not calculate dynamic TS: {error_msg}'}), 500

            # Get the final distance in points
            final_distance_points = result['new_sl_distance']

            # Get symbol info for pip calculation
            from models import BrokerSymbol
            symbol_info = db.query(BrokerSymbol).filter_by(symbol=trade.symbol).first()

            if not symbol_info:
                return jsonify({'status': 'error', 'message': f'Symbol info not found for {trade.symbol}'}), 404

            # Convert points to pips (for MT5)
            # For most forex: 1 pip = 10 points (0.0001 = 0.00010)
            # For JPY pairs: 1 pip = 10 points (0.01 = 0.010)
            # For indices/commodities: 1 pip = 1 point usually
            digits = int(symbol_info.digits)

            if digits == 5 or digits == 3:  # Forex with fractional pips
                pip_multiplier = 10.0
            elif digits == 2:  # JPY pairs
                pip_multiplier = 10.0
            else:  # Indices, commodities, crypto
                pip_multiplier = 1.0

            trailing_stop_pips = final_distance_points / pip_multiplier

            # Create MODIFY_TRADE command with trailing stop
            payload = {
                'ticket': ticket,
                'trailing_stop': float(trailing_stop_pips)
            }

            command = create_command(
                db=db,
                account_id=account.id,
                command_type='MODIFY_TRADE',
                payload=payload
            )

            # Extract analysis details
            analysis = result.get('analysis', {})
            volatility_data = analysis.get('volatility', {})
            session_name = analysis.get('session', 'N/A')
            regime = analysis.get('regime', 'UNKNOWN')
            progress_to_tp = analysis.get('profit_pct_to_tp', 0)

            logger.info(
                f"🎯 Dynamic TS set for #{ticket} ({trade.symbol}): "
                f"{trailing_stop_pips:.1f} pips ({final_distance_points:.5f} points) | "
                f"60s volatility: {volatility_data.get('classification', 'N/A')} | "
                f"Session: {session_name} | "
                f"Regime: {regime} | "
                f"Progress: {progress_to_tp:.1f}%"
            )

            return jsonify({
                'status': 'success',
                'message': f'Dynamic trailing stop set to {trailing_stop_pips:.1f} pips for trade #{ticket}',
                'command_id': command.id,
                'details': {
                    'trailing_stop_pips': round(trailing_stop_pips, 1),
                    'distance_points': round(final_distance_points, 5),
                    'volatility_60s': volatility_data.get('avg_jump', 0),
                    'session': session_name,
                    'regime': regime,
                    'progress_to_tp': round(progress_to_tp, 1),
                    'noise_threshold': volatility_data.get('avg_jump', 0)
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Set dynamic trailing stop error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/signals/stats')
def get_signal_stats():
    """Get signal statistics"""
    try:
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Count active signals
            active_count = db.query(TradingSignal).filter_by(
                account_id=account.id,
                status='active'
            ).count()

            # Count by signal type
            buy_count = db.query(TradingSignal).filter_by(
                account_id=account.id,
                status='active',
                signal_type='BUY'
            ).count()

            sell_count = db.query(TradingSignal).filter_by(
                account_id=account.id,
                status='active',
                signal_type='SELL'
            ).count()

            # Get signal worker stats
            from signal_worker import get_signal_worker
            worker = get_signal_worker()
            worker_stats = worker.get_stats()

            return jsonify({
                'status': 'success',
                'stats': {
                    'active_signals': active_count,
                    'buy_signals': buy_count,
                    'sell_signals': sell_count,
                    'worker': worker_stats
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Get signal stats error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# TRADE ANALYTICS & ERROR ANALYSIS
# ============================================================================

@app_webui.route('/api/trades/analytics')
def get_trade_analytics():
    """Get comprehensive trade analytics including error analysis"""
    try:
        from models import Trade
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get all trades - GLOBAL (for ML learning analytics across all accounts)
            all_trades = db.query(Trade).all()

            # Get all commands (to analyze failures) - still account-specific as commands are account-bound
            all_commands = db.query(Command).filter_by(account_id=account.id).all()

            # Trade statistics
            total_trades = len(all_trades)
            open_trades = len([t for t in all_trades if t.status == 'open'])
            closed_trades = len([t for t in all_trades if t.status == 'closed'])

            # Profit analysis
            total_profit = sum(float(t.profit or 0) for t in all_trades if t.profit)
            winning_trades = [t for t in all_trades if t.profit and float(t.profit) > 0]
            losing_trades = [t for t in all_trades if t.profit and float(t.profit) < 0]

            win_rate = (len(winning_trades) / closed_trades * 100) if closed_trades > 0 else 0

            # Command analysis
            successful_commands = len([c for c in all_commands if c.status == 'completed'])
            failed_commands = len([c for c in all_commands if c.status == 'failed'])

            # Error analysis
            error_breakdown = {}
            for cmd in all_commands:
                if cmd.status == 'failed' and cmd.response:
                    error_msg = cmd.response.get('error', 'Unknown error')
                    error_breakdown[error_msg] = error_breakdown.get(error_msg, 0) + 1

            # Source analysis (where trades came from)
            source_breakdown = {}
            for trade in all_trades:
                source_breakdown[trade.source] = source_breakdown.get(trade.source, 0) + 1

            # Timeframe performance
            timeframe_performance = {}
            for trade in all_trades:
                if trade.timeframe and trade.profit:
                    if trade.timeframe not in timeframe_performance:
                        timeframe_performance[trade.timeframe] = {'count': 0, 'total_profit': 0, 'wins': 0, 'losses': 0}
                    timeframe_performance[trade.timeframe]['count'] += 1
                    timeframe_performance[trade.timeframe]['total_profit'] += float(trade.profit)
                    if float(trade.profit) > 0:
                        timeframe_performance[trade.timeframe]['wins'] += 1
                    else:
                        timeframe_performance[trade.timeframe]['losses'] += 1

            # Close reason analysis
            close_reasons = {}
            for trade in all_trades:
                if trade.close_reason:
                    close_reasons[trade.close_reason] = close_reasons.get(trade.close_reason, 0) + 1

            return jsonify({
                'status': 'success',
                'analytics': {
                    'trades': {
                        'total': total_trades,
                        'open': open_trades,
                        'closed': closed_trades,
                        'winning': len(winning_trades),
                        'losing': len(losing_trades),
                        'win_rate': round(win_rate, 2)
                    },
                    'profit': {
                        'total': round(total_profit, 2),
                        'average_win': round(sum(float(t.profit) for t in winning_trades) / len(winning_trades), 2) if winning_trades else 0,
                        'average_loss': round(sum(float(t.profit) for t in losing_trades) / len(losing_trades), 2) if losing_trades else 0
                    },
                    'commands': {
                        'successful': successful_commands,
                        'failed': failed_commands,
                        'success_rate': round(successful_commands / (successful_commands + failed_commands) * 100, 2) if (successful_commands + failed_commands) > 0 else 0
                    },
                    'errors': error_breakdown,
                    'sources': source_breakdown,
                    'timeframe_performance': timeframe_performance,
                    'close_reasons': close_reasons
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Trade analytics error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/trades/history')
def get_trade_history():
    """Get trade history with advanced filters and pagination"""
    try:
        # ✅ FIX BUG-003: Input validation to prevent SQL injection
        from input_validator import InputValidator, validate_trade_status
        from models import Trade
        
        db = ScopedSession()
        try:
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()  # Use active account
            if not account:
                return jsonify({'status': 'error', 'message': 'No account found'}), 404

            # Get and validate query parameters
            status_raw = request.args.get('status', 'closed')
            symbol_raw = request.args.get('symbol')
            direction_raw = request.args.get('direction')
            profit_status_raw = request.args.get('profit_status')
            
            # Validate inputs
            status = validate_trade_status(status_raw)  # ✅ FIX: validate_trade_status already has default='closed'
            symbol = InputValidator.validate_symbol(symbol_raw) if symbol_raw else None
            direction = InputValidator.validate_enum(
                direction_raw, 
                ['BUY', 'SELL'], 
                default=None
            ) if direction_raw else None
            profit_status = InputValidator.validate_enum(
                profit_status_raw,
                ['profit', 'loss'],
                default=None
            ) if profit_status_raw else None

            # Period filters: all, year, month, week, today, custom
            period_raw = request.args.get('period', 'all')
            period = InputValidator.validate_enum(
                period_raw,
                ['all', 'today', 'week', 'month', 'year', 'custom'],
                default='all'
            )
            
            start_date_raw = request.args.get('start_date')
            end_date_raw = request.args.get('end_date')
            start_date = InputValidator.validate_iso_date(start_date_raw) if start_date_raw else None
            end_date = InputValidator.validate_iso_date(end_date_raw) if end_date_raw else None

            # Pagination
            page_raw = request.args.get('page', type=int, default=1)
            per_page_raw = request.args.get('per_page', type=int, default=20)
            page = InputValidator.validate_integer(page_raw, min_value=1, default=1)
            per_page = InputValidator.validate_integer(per_page_raw, min_value=1, max_value=100, default=20)

            # Build base query - GLOBAL (for ML learning analytics across all accounts)
            query = db.query(Trade)

            # Debug logging
            logger.info(f"Trade history query (GLOBAL) - Status: {status}, Period: {period}")

            # Apply status filter
            if status:
                query = query.filter(Trade.status == status)

            # Apply period filter
            now = datetime.utcnow()
            if period == 'today':
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(Trade.close_time >= today_start)
            elif period == 'week':
                week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
                query = query.filter(Trade.close_time >= week_start)
            elif period == 'month':
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(Trade.close_time >= month_start)
            elif period == 'year':
                year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(Trade.close_time >= year_start)
            elif period == 'custom' and start_date and end_date:
                # Dates already validated by InputValidator.validate_iso_date()
                query = query.filter(Trade.close_time >= start_date, Trade.close_time <= end_date)

            # Apply optional filters
            if symbol:
                query = query.filter(Trade.symbol == symbol)

            if direction:
                # Direction already validated and converted to uppercase by validate_enum
                query = query.filter(Trade.direction == direction)

            if profit_status == 'profit':
                query = query.filter(Trade.profit > 0)
            elif profit_status == 'loss':
                query = query.filter(Trade.profit < 0)

            # Get total count before pagination
            total = query.count()
            logger.info(f"Trade history query - Total trades found: {total}")

            # Apply pagination
            offset = (page - 1) * per_page
            trades = query.order_by(Trade.close_time.desc()).limit(per_page).offset(offset).all()

            # Format trades data
            trades_data = []
            for trade in trades:
                # Calculate trade duration
                duration_hours = None
                if trade.open_time and trade.close_time:
                    duration_seconds = (trade.close_time - trade.open_time).total_seconds()
                    duration_hours = round(duration_seconds / 3600, 2)

                # Get confidence from linked signal if available
                confidence = None
                if trade.signal_id and trade.signal:
                    confidence = float(trade.signal.confidence) if trade.signal.confidence else None

                trades_data.append({
                    'id': trade.id,
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'type': trade.type,
                    'direction': trade.direction,
                    'volume': float(trade.volume),
                    'open_price': float(trade.open_price) if trade.open_price else None,
                    'open_time': trade.open_time.isoformat() if trade.open_time else None,
                    'close_price': float(trade.close_price) if trade.close_price else None,
                    'close_time': trade.close_time.isoformat() if trade.close_time else None,
                    'sl': float(trade.sl) if trade.sl else None,
                    'tp': float(trade.tp) if trade.tp else None,
                    'profit': float(trade.profit) if trade.profit else None,
                    'commission': float(trade.commission) if trade.commission else None,
                    'swap': float(trade.swap) if trade.swap else None,
                    'source': trade.source,
                    'timeframe': trade.timeframe,
                    'confidence': confidence,
                    'entry_reason': trade.entry_reason,
                    'close_reason': trade.close_reason,
                    'signal_id': trade.signal_id,
                    'status': trade.status,
                    'duration_hours': duration_hours
                })

            # Calculate total pages
            total_pages = (total + per_page - 1) // per_page

            return jsonify({
                'status': 'success',
                'trades': trades_data,
                'pagination': {
                    'total': total,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Trade history error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==================== GLOBAL SETTINGS ENDPOINTS ====================
logger.info("Registering /api/settings endpoints...")

@app_command.route('/api/settings')
def get_settings():
    """Get global settings"""
    try:
        logger.info("⚙️ GET /api/settings called - starting")
        from models import GlobalSettings
        db = ScopedSession()
        try:
            logger.info("⚙️ Loading settings from DB...")
            settings = GlobalSettings.get_settings(db)
            logger.info(f"⚙️ Settings loaded: max_positions={settings.max_positions}")
            result = jsonify({
                'max_positions': settings.max_positions,
                'max_positions_per_symbol_timeframe': settings.max_positions_per_symbol_timeframe,
                'risk_per_trade_percent': float(settings.risk_per_trade_percent),
                'position_size_percent': float(settings.position_size_percent),
                'max_drawdown_percent': float(settings.max_drawdown_percent),
                'min_signal_confidence': float(settings.min_signal_confidence),
                'signal_max_age_minutes': settings.signal_max_age_minutes,
                'sl_cooldown_minutes': settings.sl_cooldown_minutes,
                'min_bars_required': settings.min_bars_required,
                'min_bars_d1': settings.min_bars_d1,
                'realistic_profit_factor': float(settings.realistic_profit_factor),
                'autotrade_enabled': settings.autotrade_enabled,  # ✅ NEW
                'autotrade_min_confidence': float(settings.autotrade_min_confidence),  # ✅ NEW
                'updated_at': settings.updated_at.isoformat() if settings.updated_at else None
            })
            logger.info("⚙️ Returning settings JSON")
            return result, 200
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Error getting settings: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/settings', methods=['POST'])
def update_settings():
    """Update global settings"""
    try:
        from models import GlobalSettings
        data = request.get_json()

        db = ScopedSession()
        try:
            settings = GlobalSettings.get_settings(db)

            # Update fields if provided
            if 'max_positions' in data:
                settings.max_positions = int(data['max_positions'])
            if 'max_positions_per_symbol_timeframe' in data:
                settings.max_positions_per_symbol_timeframe = int(data['max_positions_per_symbol_timeframe'])
            if 'risk_per_trade_percent' in data:
                settings.risk_per_trade_percent = float(data['risk_per_trade_percent'])
            # VALIDATION: Validate all numeric inputs
            if 'position_size_percent' in data:
                settings.position_size_percent = validate_numeric_range(
                    data['position_size_percent'], 'position_size_percent', 0.001, 100.0
                )
            if 'max_drawdown_percent' in data:
                settings.max_drawdown_percent = validate_numeric_range(
                    data['max_drawdown_percent'], 'max_drawdown_percent', 0.01, 1.0
                )
            if 'min_signal_confidence' in data:
                settings.min_signal_confidence = validate_confidence(
                    data['min_signal_confidence'], 'min_signal_confidence'
                ) / 100.0  # Convert to decimal
            if 'signal_max_age_minutes' in data:
                settings.signal_max_age_minutes = int(validate_numeric_range(
                    data['signal_max_age_minutes'], 'signal_max_age_minutes', 1, 1440
                ))
            if 'sl_cooldown_minutes' in data:
                settings.sl_cooldown_minutes = int(validate_numeric_range(
                    data['sl_cooldown_minutes'], 'sl_cooldown_minutes', 0, 1440
                ))
            if 'min_bars_required' in data:
                settings.min_bars_required = int(validate_numeric_range(
                    data['min_bars_required'], 'min_bars_required', 10, 500
                ))
            if 'min_bars_d1' in data:
                settings.min_bars_d1 = int(validate_numeric_range(
                    data['min_bars_d1'], 'min_bars_d1', 10, 500
                ))
            if 'realistic_profit_factor' in data:
                settings.realistic_profit_factor = validate_numeric_range(
                    data['realistic_profit_factor'], 'realistic_profit_factor', 0.1, 10.0
                )

            settings.updated_at = datetime.utcnow()
            settings.updated_by = 'webui'

            db.commit()

            logger.info(f"Global settings updated: {data.keys()}")
            return jsonify({'status': 'success', 'message': 'Settings updated'}), 200

        finally:
            db.close()
    except ValueError as ve:
        # Validation error - return 400 Bad Request
        logger.warning(f"Validation error updating settings: {ve}")
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        # Other errors - return 500 Internal Server Error
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# TRADE P/L HISTORY API
# ============================================================================

@app_webui.route('/api/trade/<int:ticket>/pnl-history', methods=['GET'])
def get_trade_pnl_history(ticket):
    """
    Get P/L history for an open trade over time.
    Calculates P/L at each candle based on entry price vs current price.

    Args:
        ticket: Trade ticket number

    Query params:
        timeframe: H1, H4, D1, etc. (default: H1)
        limit: Number of candles (default: 100)

    Returns:
        JSON with P/L data points synchronized with OHLC candles
    """
    try:
        from models import Trade, OHLCData
        from input_validator import InputValidator, validate_timeframe

        # Validate query params
        timeframe_raw = request.args.get('timeframe', 'H1')
        limit = request.args.get('limit', 100, type=int)

        timeframe = validate_timeframe(timeframe_raw)
        limit = InputValidator.validate_integer(limit, min_value=1, max_value=500, default=100)

        db = ScopedSession()
        try:
            # Get the trade
            trade = db.query(Trade).filter(Trade.ticket == ticket).first()

            if not trade:
                return jsonify({
                    'status': 'error',
                    'message': f'Trade #{ticket} not found'
                }), 404

            if trade.status != 'open':
                return jsonify({
                    'status': 'error',
                    'message': f'Trade #{ticket} is not open (status: {trade.status})'
                }), 400

            # Get OHLC data for the symbol starting from trade open time
            ohlc_query = db.query(OHLCData).filter(
                OHLCData.symbol == trade.symbol,
                OHLCData.timeframe == timeframe,
                OHLCData.timestamp >= trade.open_time
            ).order_by(OHLCData.timestamp.asc()).limit(limit)

            candles = ohlc_query.all()

            if not candles:
                return jsonify({
                    'status': 'success',
                    'trade': {
                        'ticket': trade.ticket,
                        'symbol': trade.symbol,
                        'type': trade.type,
                        'entry_price': float(trade.open_price),
                        'lot_size': float(trade.volume),
                        'open_time': trade.open_time.isoformat(),
                    },
                    'pnl_history': [],
                    'message': 'No OHLC data available for this trade'
                }), 200

            # Calculate P/L for each candle
            entry_price = float(trade.open_price)
            lot_size = float(trade.volume)
            trade_type = trade.type  # BUY or SELL

            # Get symbol specs for pip calculation
            from models import SymbolSpec
            symbol_spec = db.query(SymbolSpec).filter(SymbolSpec.symbol == trade.symbol).first()

            # Default pip values (will be overridden by symbol specs if available)
            pip_value = 10.0  # Default: $10 per pip for 1 standard lot
            point_multiplier = 10000  # For forex pairs (0.0001 = 1 pip)

            if symbol_spec:
                # Use actual contract size for accurate P/L
                pip_value = float(symbol_spec.contract_size) / point_multiplier

            pnl_history = []

            for candle in candles:
                # Use close price for P/L calculation
                current_price = float(candle.close)

                # Calculate P/L based on trade direction
                if trade_type == 'BUY':
                    price_diff = current_price - entry_price
                elif trade_type == 'SELL':
                    price_diff = entry_price - current_price
                else:
                    price_diff = 0

                # Convert price difference to pips and then to EUR
                pips = price_diff * point_multiplier
                pnl_eur = pips * pip_value * lot_size

                pnl_history.append({
                    'time': candle.timestamp.isoformat(),
                    'timestamp': int(candle.timestamp.timestamp()),
                    'price': current_price,
                    'pnl': round(pnl_eur, 2),
                    'pips': round(pips, 1)
                })

            return jsonify({
                'status': 'success',
                'trade': {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'type': trade_type,
                    'entry_price': entry_price,
                    'tp_price': float(trade.tp) if trade.tp else None,
                    'sl_price': float(trade.sl) if trade.sl else None,
                    'lot_size': lot_size,
                    'open_time': trade.open_time.isoformat(),
                    'current_pnl': float(trade.profit) if trade.profit else 0.0
                },
                'pnl_history': pnl_history,
                'timeframe': timeframe,
                'candle_count': len(pnl_history)
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting P/L history for trade #{ticket}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# ============================================================================
# AUTO-OPTIMIZATION API
# ============================================================================

@app_webui.route('/api/auto-optimization/config', methods=['GET'])
def get_auto_optimization_config():
    """Get auto-optimization configuration for account"""
    try:
        account_id = request.args.get('account_id', 1, type=int)

        from models import AutoOptimizationConfig
        db = ScopedSession()
        try:
            config = db.query(AutoOptimizationConfig).filter_by(account_id=account_id).first()

            if not config:
                # Create default config
                config = AutoOptimizationConfig(account_id=account_id)
                db.add(config)
                db.commit()

            return jsonify({
                'status': 'success',
                'config': {
                    'enabled': config.enabled,
                    'auto_disable_enabled': config.auto_disable_enabled,
                    'auto_enable_enabled': config.auto_enable_enabled,
                    'shadow_trading_enabled': config.shadow_trading_enabled,
                    'backtest_window_days': config.backtest_window_days,
                    'backtest_schedule_time': config.backtest_schedule_time,
                    'backtest_min_confidence': float(config.backtest_min_confidence),
                    'disable_consecutive_loss_days': config.disable_consecutive_loss_days,
                    'disable_min_win_rate': float(config.disable_min_win_rate),
                    'disable_max_loss_percent': float(config.disable_max_loss_percent),
                    'disable_max_drawdown_percent': float(config.disable_max_drawdown_percent),
                    'enable_consecutive_profit_days': config.enable_consecutive_profit_days,
                    'enable_min_win_rate': float(config.enable_min_win_rate),
                    'enable_min_profit_percent': float(config.enable_min_profit_percent),
                    'email_enabled': config.email_enabled,
                    'email_recipient': config.email_recipient
                }
            }), 200
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting auto-optimization config: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/auto-optimization/status', methods=['GET'])
def get_auto_optimization_status():
    """Get current auto-optimization status for all symbols"""
    try:
        account_id = request.args.get('account_id', 1, type=int)

        from models import SymbolPerformanceTracking
        from sqlalchemy import func, desc

        db = ScopedSession()
        try:
            # Get latest performance for each symbol
            subquery = db.query(
                SymbolPerformanceTracking.symbol,
                func.max(SymbolPerformanceTracking.evaluation_date).label('max_date')
            ).filter(
                SymbolPerformanceTracking.account_id == account_id
            ).group_by(SymbolPerformanceTracking.symbol).subquery()

            performances = db.query(SymbolPerformanceTracking).join(
                subquery,
                (SymbolPerformanceTracking.symbol == subquery.c.symbol) &
                (SymbolPerformanceTracking.evaluation_date == subquery.c.max_date)
            ).all()

            symbols_data = []
            for perf in performances:
                symbols_data.append({
                    'symbol': perf.symbol,
                    'status': perf.status,
                    'evaluation_date': perf.evaluation_date.isoformat() if perf.evaluation_date else None,
                    'backtest_total_trades': perf.backtest_total_trades,
                    'backtest_win_rate': float(perf.backtest_win_rate) if perf.backtest_win_rate else 0,
                    'backtest_profit': float(perf.backtest_profit) if perf.backtest_profit else 0,
                    'backtest_profit_percent': float(perf.backtest_profit_percent) if perf.backtest_profit_percent else 0,
                    'consecutive_loss_days': perf.consecutive_loss_days,
                    'consecutive_profit_days': perf.consecutive_profit_days,
                    'shadow_trades': perf.shadow_trades,
                    'shadow_profit': float(perf.shadow_profit) if perf.shadow_profit else 0,
                    'auto_disabled_reason': perf.auto_disabled_reason
                })

            # Count by status
            status_counts = {
                'active': sum(1 for s in symbols_data if s['status'] == 'active'),
                'watch': sum(1 for s in symbols_data if s['status'] == 'watch'),
                'disabled': sum(1 for s in symbols_data if s['status'] == 'disabled')
            }

            return jsonify({
                'status': 'success',
                'symbols': symbols_data,
                'status_counts': status_counts,
                'total_symbols': len(symbols_data)
            }), 200
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting auto-optimization status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/auto-optimization/trigger', methods=['POST'])
def trigger_manual_backtest():
    """Manually trigger a daily backtest run"""
    try:
        from daily_backtest_scheduler import trigger_manual_backtest as trigger_bt

        logger.info("🔧 Manual backtest triggered via API")

        # Run in background thread
        from threading import Thread
        thread = Thread(target=trigger_bt, daemon=True)
        thread.start()

        return jsonify({
            'status': 'success',
            'message': 'Backtest triggered successfully'
        }), 200
    except Exception as e:
        logger.error(f"Error triggering manual backtest: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/auto-optimization/events', methods=['GET'])
def get_auto_optimization_events():
    """Get recent auto-optimization events"""
    try:
        account_id = request.args.get('account_id', 1, type=int)
        limit = request.args.get('limit', 50, type=int)

        from models import AutoOptimizationEvent
        from sqlalchemy import desc

        db = ScopedSession()
        try:
            events = db.query(AutoOptimizationEvent).filter(
                AutoOptimizationEvent.account_id == account_id
            ).order_by(desc(AutoOptimizationEvent.event_timestamp)).limit(limit).all()

            events_data = []
            for event in events:
                events_data.append({
                    'id': event.id,
                    'symbol': event.symbol,
                    'event_type': event.event_type,
                    'event_timestamp': event.event_timestamp.isoformat() if event.event_timestamp else None,
                    'old_status': event.old_status,
                    'new_status': event.new_status,
                    'trigger_reason': event.trigger_reason,
                    'metrics': event.metrics
                })

            return jsonify({
                'status': 'success',
                'events': events_data,
                'count': len(events_data)
            }), 200
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting auto-optimization events: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# INDICATOR SCORES API
# ============================================================================

@app_command.route('/api/indicator-scores/<symbol>/<timeframe>', methods=['GET'])
@require_api_key
def get_indicator_scores(account, symbol, timeframe):
    """
    Get indicator scores for a specific symbol and timeframe

    Query params:
    - top: int (optional) - return only top N indicators
    """
    try:
        from indicator_scorer import IndicatorScorer

        top = request.args.get('top', type=int)

        scorer = IndicatorScorer(account.id, symbol, timeframe)

        if top:
            scores = scorer.get_top_indicators(limit=top)
        else:
            scores = scorer.get_all_scores()

        return jsonify({
            'status': 'success',
            'symbol': symbol,
            'timeframe': timeframe,
            'scores': scores
        }), 200

    except Exception as e:
        logger.error(f"Error getting indicator scores: {e}")
        return jsonify({'error': str(e)}), 500


@app_command.route('/api/indicator-scores/all', methods=['GET'])
@require_api_key
def get_all_indicator_scores(account):
    """
    Get all indicator scores across all symbols/timeframes

    Returns summary statistics for each indicator
    """
    try:
        from models import IndicatorScore
        from database import ScopedSession

        db = ScopedSession()
        try:
            # Get all scores for this account
            all_scores = db.query(IndicatorScore).filter_by(
                account_id=account.id
            ).all()

            # Aggregate by indicator name
            indicator_stats = {}

            for score in all_scores:
                name = score.indicator_name

                if name not in indicator_stats:
                    indicator_stats[name] = {
                        'indicator_name': name,
                        'total_signals': 0,
                        'successful_signals': 0,
                        'failed_signals': 0,
                        'total_profit': 0.0,
                        'symbols': []
                    }

                indicator_stats[name]['total_signals'] += score.total_signals
                indicator_stats[name]['successful_signals'] += score.successful_signals
                indicator_stats[name]['failed_signals'] += score.failed_signals
                indicator_stats[name]['total_profit'] += float(score.total_profit or 0)
                indicator_stats[name]['symbols'].append({
                    'symbol': score.symbol,
                    'timeframe': score.timeframe,
                    'score': float(score.score),
                    'signals': score.total_signals
                })

            # Calculate aggregated stats
            for name, stats in indicator_stats.items():
                if stats['total_signals'] > 0:
                    stats['win_rate'] = (stats['successful_signals'] / stats['total_signals']) * 100
                    stats['avg_profit'] = stats['total_profit'] / stats['total_signals']
                else:
                    stats['win_rate'] = 0
                    stats['avg_profit'] = 0

            # Sort by total profit
            sorted_indicators = sorted(
                indicator_stats.values(),
                key=lambda x: x['total_profit'],
                reverse=True
            )

            return jsonify({
                'status': 'success',
                'indicators': sorted_indicators
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting all indicator scores: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/spread/stats', methods=['GET'])
def get_spread_stats():
    """Get spread statistics for all symbols or a specific symbol"""
    try:
        from models import Tick
        from sqlalchemy import func

        symbol = request.args.get('symbol')
        hours = request.args.get('hours', 24, type=int)

        db = ScopedSession()

        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)

            query = db.query(
                Tick.symbol,
                func.count(Tick.id).label('tick_count'),
                func.avg(Tick.spread).label('avg_spread'),
                func.min(Tick.spread).label('min_spread'),
                func.max(Tick.spread).label('max_spread'),
                func.min(Tick.timestamp).label('first_tick'),
                func.max(Tick.timestamp).label('last_tick')
            ).filter(
                Tick.spread.isnot(None),
                Tick.timestamp >= cutoff_time
            )

            if symbol:
                query = query.filter(Tick.symbol == symbol)

            stats = query.group_by(Tick.symbol).all()

            result = []
            for stat in stats:
                result.append({
                    'symbol': stat.symbol,
                    'tick_count': stat.tick_count,
                    'avg_spread': float(stat.avg_spread) if stat.avg_spread else 0,
                    'min_spread': float(stat.min_spread) if stat.min_spread else 0,
                    'max_spread': float(stat.max_spread) if stat.max_spread else 0,
                    'first_tick': stat.first_tick.isoformat() if stat.first_tick else None,
                    'last_tick': stat.last_tick.isoformat() if stat.last_tick else None,
                    'spread_volatility': float(stat.max_spread - stat.min_spread) if stat.max_spread and stat.min_spread else 0
                })

            return jsonify({
                'status': 'success',
                'hours': hours,
                'symbol_count': len(result),
                'stats': result
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting spread stats: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# SERVER STARTUP
# ============================================================================

def run_server(app, port, name):
    """Run Flask app on specific port"""
    logger.info(f"Starting {name} server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


@app_webui.route('/api/ai-decisions', methods=['GET'])
def get_ai_decisions():
    """Get recent AI decisions for transparency"""
    try:
        from ai_decision_log import get_decision_logger

        # Use account ID 3 (actual trading account)
        account_id = 3
        limit = request.args.get('limit', 50, type=int)
        decision_type = request.args.get('type')
        minutes = request.args.get('minutes', type=int)

        decision_logger = get_decision_logger()
        decisions = decision_logger.get_recent_decisions(
            account_id,
            limit=limit,
            decision_type=decision_type,
            minutes=minutes
        )

        decisions_data = []
        for d in decisions:
            decisions_data.append({
                'id': d.id,
                'timestamp': d.timestamp.isoformat() if d.timestamp else None,
                'decision_type': d.decision_type,
                'decision': d.decision,
                'symbol': d.symbol,
                'timeframe': d.timeframe,
                'primary_reason': d.primary_reason,
                'detailed_reasoning': d.detailed_reasoning,
                'impact_level': d.impact_level,
                'user_action_required': d.user_action_required,
                'confidence_score': float(d.confidence_score) if d.confidence_score else None,
                'risk_score': float(d.risk_score) if d.risk_score else None,
                'account_balance': float(d.account_balance) if d.account_balance else None,
                'open_positions': d.open_positions
            })

        return jsonify({
            'status': 'success',
            'decisions': decisions_data
        }), 200

    except Exception as e:
        logger.error(f"Error getting AI decisions: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ai-decisions/stats', methods=['GET'])
def get_ai_decision_stats():
    """Get AI decision statistics"""
    try:
        from ai_decision_log import get_decision_logger

        # Use account ID 3 (actual trading account)
        account_id = 3
        hours = request.args.get('hours', 24, type=int)

        decision_logger = get_decision_logger()
        stats = decision_logger.get_decision_stats(account_id, hours=hours)

        return jsonify({
            'status': 'success',
            'stats': stats
        }), 200

    except Exception as e:
        logger.error(f"Error getting AI decision stats: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ai-decisions/action-required', methods=['GET'])
def get_action_required_decisions():
    """Get decisions requiring user action"""
    try:
        from ai_decision_log import get_decision_logger

        # Use account ID 3 (actual trading account)
        account_id = 3

        decision_logger = get_decision_logger()
        decisions = decision_logger.get_decisions_requiring_action(account_id)

        decisions_data = []
        for d in decisions:
            decisions_data.append({
                'id': d.id,
                'timestamp': d.timestamp.isoformat() if d.timestamp else None,
                'decision_type': d.decision_type,
                'decision': d.decision,
                'symbol': d.symbol,
                'primary_reason': d.primary_reason,
                'impact_level': d.impact_level
            })

        return jsonify({
            'status': 'success',
            'decisions': decisions_data,
            'count': len(decisions_data)
        }), 200

    except Exception as e:
        logger.error(f"Error getting action-required decisions: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# DAILY DRAWDOWN PROTECTION
# ============================================================================

@app_webui.route('/api/daily-drawdown/status', methods=['GET'])
def get_daily_drawdown_status():
    """Get daily drawdown protection status"""
    try:
        from daily_drawdown_protection import get_drawdown_protection

        # Use account ID 1 (default account for dashboard)
        account_id = 1

        dd_protection = get_drawdown_protection(account_id)
        status = dd_protection.get_status()

        return jsonify({'status': 'success', 'drawdown': status}), 200

    except Exception as e:
        logger.error(f"Error getting daily drawdown status: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/daily-drawdown/config', methods=['POST'])
def update_daily_drawdown_config():
    """Update daily drawdown protection configuration"""
    try:
        from daily_drawdown_protection import get_drawdown_protection

        data = request.get_json()
        account_id = 1  # Default account

        max_daily_loss_percent = data.get('max_daily_loss_percent')
        max_daily_loss_eur = data.get('max_daily_loss_eur')

        dd_protection = get_drawdown_protection(account_id)
        dd_protection.update_config(
            max_daily_loss_percent=max_daily_loss_percent,
            max_daily_loss_eur=max_daily_loss_eur
        )

        return jsonify({
            'status': 'success',
            'message': 'Daily drawdown config updated'
        }), 200

    except Exception as e:
        logger.error(f"Error updating daily drawdown config: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# NEWS FILTER
# ============================================================================

@app_webui.route('/api/news/upcoming', methods=['GET'])
def get_upcoming_news():
    """Get upcoming high-impact news events"""
    try:
        from news_filter import get_news_filter

        account_id = 1
        hours = request.args.get('hours', 24, type=int)

        news_filter = get_news_filter(account_id)
        events = news_filter.get_upcoming_events(hours=hours)

        return jsonify({'status': 'success', 'events': events}), 200

    except Exception as e:
        logger.error(f"Error getting upcoming news: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/news/fetch', methods=['POST'])
def fetch_news_now():
    """Manually trigger news fetch"""
    try:
        from news_filter import get_news_filter

        account_id = 1
        news_filter = get_news_filter(account_id)
        count = news_filter.fetch_and_store_events()

        return jsonify({
            'status': 'success',
            'message': f'Fetched {count} news events'
        }), 200

    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/safety-monitor/status', methods=['GET'])
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
            'daily_loss_override': getattr(auto_trader, 'daily_loss_override', False)  # ✅ NEW
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

            # GLOBAL queries - trades are shared across accounts for ML learning
            open_positions = db.query(Trade).filter(
                Trade.status == 'open'
            ).count()

            # Count positions by symbol
            positions_by_symbol = {}
            open_trades = db.query(Trade).filter(
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


# ============================================================================
# Spread Configuration Proxy Endpoints (WebUI Server)
# These proxy requests to the command server (port 9900) so they work
# even when port 9900 is not directly accessible from the browser
# ============================================================================

@app_webui.route('/api/spread-config', methods=['GET'])
def proxy_get_all_spread_configs():
    """Proxy: Get all symbol spread configurations"""
    try:
        from models import SymbolSpreadConfig

        db = ScopedSession()
        try:
            configs = db.query(SymbolSpreadConfig).order_by(
                SymbolSpreadConfig.asset_type,
                SymbolSpreadConfig.symbol
            ).all()

            result = []
            for config in configs:
                result.append({
                    'id': config.id,
                    'symbol': config.symbol,
                    'typical_spread': float(config.typical_spread),
                    'max_spread_multiplier': float(config.max_spread_multiplier),
                    'absolute_max_spread': float(config.absolute_max_spread) if config.absolute_max_spread else None,
                    'asian_session_spread': float(config.asian_session_spread) if config.asian_session_spread else None,
                    'weekend_spread': float(config.weekend_spread) if config.weekend_spread else None,
                    'enabled': config.enabled,
                    'use_dynamic_limits': config.use_dynamic_limits,
                    'asset_type': config.asset_type,
                    'notes': config.notes,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None
                })

            return jsonify({
                'status': 'success',
                'configs': result,
                'count': len(result)
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting spread configs: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/spread-config/<symbol>', methods=['GET'])
def proxy_get_spread_config(symbol):
    """Proxy: Get spread configuration for a specific symbol"""
    try:
        from models import SymbolSpreadConfig

        db = ScopedSession()
        try:
            config = db.query(SymbolSpreadConfig).filter_by(
                symbol=symbol.upper()
            ).first()

            if not config:
                return jsonify({
                    'status': 'error',
                    'message': f'No configuration found for {symbol.upper()}'
                }), 404

            return jsonify({
                'status': 'success',
                'config': {
                    'id': config.id,
                    'symbol': config.symbol,
                    'typical_spread': float(config.typical_spread),
                    'max_spread_multiplier': float(config.max_spread_multiplier),
                    'absolute_max_spread': float(config.absolute_max_spread) if config.absolute_max_spread else None,
                    'asian_session_spread': float(config.asian_session_spread) if config.asian_session_spread else None,
                    'weekend_spread': float(config.weekend_spread) if config.weekend_spread else None,
                    'enabled': config.enabled,
                    'use_dynamic_limits': config.use_dynamic_limits,
                    'asset_type': config.asset_type,
                    'notes': config.notes,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None
                }
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting spread config for {symbol}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app_webui.route('/api/spread-config/<symbol>', methods=['POST', 'PUT'])
def proxy_update_spread_config(symbol):
    """Proxy: Create or update spread configuration for a symbol"""
    try:
        from models import SymbolSpreadConfig
        from decimal import Decimal

        data = request.get_json() or {}
        symbol_upper = symbol.upper()

        if 'typical_spread' not in data:
            return jsonify({
                'status': 'error',
                'message': 'typical_spread is required'
            }), 400

        db = ScopedSession()
        try:
            config = db.query(SymbolSpreadConfig).filter_by(symbol=symbol_upper).first()

            if config:
                config.typical_spread = Decimal(str(data['typical_spread']))
                config.max_spread_multiplier = Decimal(str(data.get('max_spread_multiplier', 3.0)))
                if 'absolute_max_spread' in data and data['absolute_max_spread'] is not None:
                    config.absolute_max_spread = Decimal(str(data['absolute_max_spread']))
                if 'enabled' in data:
                    config.enabled = bool(data['enabled'])
                if 'notes' in data:
                    config.notes = data['notes']
                db.commit()
                action = 'updated'
            else:
                config = SymbolSpreadConfig(
                    symbol=symbol_upper,
                    typical_spread=Decimal(str(data['typical_spread'])),
                    max_spread_multiplier=Decimal(str(data.get('max_spread_multiplier', 3.0))),
                    absolute_max_spread=Decimal(str(data['absolute_max_spread'])) if data.get('absolute_max_spread') else None,
                    enabled=bool(data.get('enabled', True)),
                    notes=data.get('notes')
                )
                db.add(config)
                db.commit()
                action = 'created'

            return jsonify({
                'status': 'success',
                'message': f'Spread configuration {action} for {symbol_upper}'
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error updating spread config for {symbol}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# GLOBAL SETTINGS API (app_webui) - Duplicate from app_command for browser access
# ============================================================================

@app_webui.route('/api/settings')
def get_settings_webui():
    """Get global settings (WebUI version on port 9905)"""
    try:
        from models import GlobalSettings
        db = ScopedSession()
        try:
            settings = GlobalSettings.get_settings(db)
            return jsonify({
                'max_positions': settings.max_positions,
                'max_positions_per_symbol_timeframe': settings.max_positions_per_symbol_timeframe,
                'risk_per_trade_percent': float(settings.risk_per_trade_percent),
                'position_size_percent': float(settings.position_size_percent),
                'max_drawdown_percent': float(settings.max_drawdown_percent),
                'min_signal_confidence': float(settings.min_signal_confidence),
                'signal_max_age_minutes': settings.signal_max_age_minutes,
                'sl_cooldown_minutes': settings.sl_cooldown_minutes,
                'min_bars_required': settings.min_bars_required,
                'min_bars_d1': settings.min_bars_d1,
                'realistic_profit_factor': float(settings.realistic_profit_factor),
                'autotrade_enabled': settings.autotrade_enabled,
                'autotrade_min_confidence': float(settings.autotrade_min_confidence),
                'updated_at': settings.updated_at.isoformat() if settings.updated_at else None
            }), 200
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Error getting settings (webui): {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/settings', methods=['POST'])
def update_settings_webui():
    """Update global settings (WebUI version on port 9905)"""
    try:
        from models import GlobalSettings
        data = request.get_json()

        db = ScopedSession()
        try:
            settings = GlobalSettings.get_settings(db)

            # Update fields if provided
            if 'max_positions' in data:
                settings.max_positions = int(data['max_positions'])
            if 'max_positions_per_symbol_timeframe' in data:
                settings.max_positions_per_symbol_timeframe = int(data['max_positions_per_symbol_timeframe'])
            if 'risk_per_trade_percent' in data:
                settings.risk_per_trade_percent = float(data['risk_per_trade_percent'])
            if 'position_size_percent' in data:
                settings.position_size_percent = validate_numeric_range(
                    data['position_size_percent'], 'position_size_percent', 0.001, 100.0
                )
            if 'max_drawdown_percent' in data:
                settings.max_drawdown_percent = validate_numeric_range(
                    data['max_drawdown_percent'], 'max_drawdown_percent', 0.01, 1.0
                )
            if 'min_signal_confidence' in data:
                settings.min_signal_confidence = validate_confidence(
                    data['min_signal_confidence'], 'min_signal_confidence'
                ) / 100.0
            if 'signal_max_age_minutes' in data:
                settings.signal_max_age_minutes = int(validate_numeric_range(
                    data['signal_max_age_minutes'], 'signal_max_age_minutes', 1, 1440
                ))
            if 'sl_cooldown_minutes' in data:
                settings.sl_cooldown_minutes = int(validate_numeric_range(
                    data['sl_cooldown_minutes'], 'sl_cooldown_minutes', 0, 1440
                ))
            if 'min_bars_required' in data:
                settings.min_bars_required = int(validate_numeric_range(
                    data['min_bars_required'], 'min_bars_required', 10, 500
                ))
            if 'min_bars_d1' in data:
                settings.min_bars_d1 = int(validate_numeric_range(
                    data['min_bars_d1'], 'min_bars_d1', 10, 500
                ))
            if 'realistic_profit_factor' in data:
                settings.realistic_profit_factor = validate_numeric_range(
                    data['realistic_profit_factor'], 'realistic_profit_factor', 0.1, 10.0
                )

            settings.updated_at = datetime.utcnow()
            settings.updated_by = 'webui'

            db.commit()

            logger.info(f"Global settings updated (webui): {data.keys()}")
            return jsonify({'status': 'success', 'message': 'Settings updated'}), 200

        finally:
            db.close()
    except ValueError as ve:
        logger.warning(f"Validation error updating settings (webui): {ve}")
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating settings (webui): {e}")
        return jsonify({'error': str(e)}), 500


# ✅ Register Unified Daily Loss Protection API
try:
    from api_protection import register_protection_endpoints
    register_protection_endpoints(app_webui)  # Register with webui app (port 9905)
    logger.info("✅ Protection API endpoints registered")
except Exception as e:
    logger.error(f"Failed to register protection API: {e}")


# ============================================================================
# P/L PERFORMANCE CHARTS API ENDPOINTS
# ============================================================================

@app_webui.route('/api/pnl-timeseries/<interval>')
def api_pnl_timeseries(interval):
    """
    Get P/L time series data for charts

    Args:
        interval: One of '1h', '12h', '24h', '1w', '1y'

    Query params:
        aggregated: 'true' to use aggregated buckets

    Returns:
        JSON with P/L time series data
    """
    try:
        from pnl_analyzer import PnLAnalyzer

        aggregated = request.args.get('aggregated', 'false').lower() == 'true'
        account_id = 3  # Default account

        with PnLAnalyzer(account_id=account_id) as analyzer:
            if aggregated:
                data = analyzer.get_aggregated_pnl(interval)
            else:
                data = analyzer.get_pnl_timeseries(interval)

        return jsonify(data)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error getting P/L timeseries for {interval}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/pnl-summary')
def api_pnl_summary():
    """
    Get P/L summary for all time intervals

    Returns:
        JSON with P/L data for 1h, 12h, 24h, 1w, 1y
    """
    try:
        from pnl_analyzer import PnLAnalyzer

        account_id = 3  # Default account

        with PnLAnalyzer(account_id=account_id) as analyzer:
            summary = analyzer.get_multi_interval_summary()

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Error getting P/L summary: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/pnl-charts/send-telegram', methods=['POST'])
def api_send_pnl_charts_telegram():
    """Send P/L charts to Telegram"""
    try:
        from telegram_charts import TelegramChartsGenerator

        account_id = request.json.get('account_id', 3) if request.is_json else 3

        generator = TelegramChartsGenerator(account_id=account_id)

        if not generator.notifier.enabled:
            return jsonify({
                'success': False,
                'error': 'Telegram not configured'
            }), 400

        success = generator.send_charts_to_telegram()

        return jsonify({
            'success': success,
            'message': 'Charts sent to Telegram' if success else 'Failed to send charts'
        })

    except Exception as e:
        logger.error(f"Error sending P/L charts to Telegram: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# ML/AI MACHINE LEARNING API ENDPOINTS
# ============================================================================

@app_webui.route('/api/ml/models')
def get_ml_models():
    """Get all trained ML models"""
    try:
        from models import MLModel
        db = ScopedSession()
        try:
            models = db.query(MLModel).order_by(MLModel.created_at.desc()).all()
            return jsonify({
                'models': [{
                    'id': m.id,
                    'model_type': m.model_type,
                    'model_name': m.model_name,
                    'symbol': m.symbol or 'GLOBAL',
                    'version': m.version,
                    'is_active': m.is_active,
                    'accuracy': float(m.accuracy) if m.accuracy else 0.0,
                    'precision': float(m.precision) if m.precision else 0.0,
                    'recall': float(m.recall) if m.recall else 0.0,
                    'f1_score': float(m.f1_score) if m.f1_score else 0.0,
                    'auc_roc': float(m.auc_roc) if m.auc_roc else 0.0,
                    'training_samples': m.training_samples,
                    'training_date': m.training_date.isoformat() if m.training_date else None,
                    'created_at': m.created_at.isoformat() if m.created_at else None
                } for m in models]
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting ML models: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/training_runs')
def get_ml_training_runs():
    """Get recent ML training runs"""
    try:
        from models import MLTrainingRun
        db = ScopedSession()
        try:
            runs = db.query(MLTrainingRun).order_by(MLTrainingRun.started_at.desc()).limit(20).all()
            return jsonify({
                'runs': [{
                    'id': r.id,
                    'model_type': r.model_type,
                    'symbol': r.symbol,
                    'status': r.status,
                    'started_at': r.started_at.isoformat() if r.started_at else None,
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None,
                    'duration_seconds': r.duration_seconds,
                    'training_samples': r.training_samples,
                    'validation_samples': r.validation_samples,
                    'validation_accuracy': float(r.validation_accuracy) if r.validation_accuracy else None,
                    'error_message': r.error_message
                } for r in runs]
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting ML training runs: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/train', methods=['POST'])
def trigger_ml_training():
    """Trigger ML model training"""
    try:
        data = request.get_json()
        symbol = data.get('symbol')  # None for global model
        days_back = data.get('days_back', 90)
        force = data.get('force', False)

        from ml.ml_training_pipeline import MLTrainingPipeline
        from models import Account

        db = ScopedSession()
        try:
            # Get the first account (or you could pass account_id from request)
            account = db.query(Account).first()
            if not account:
                return jsonify({'error': 'No account found'}), 404

            account_id = account.id

            # Train in background (async)
            import threading
            def train_async():
                db_async = ScopedSession()
                try:
                    pipeline = MLTrainingPipeline(db_async, account_id=account_id)
                    result = pipeline.train_model(symbol=symbol, days_back=days_back, force=force)
                    logger.info(f"ML training completed for {symbol or 'GLOBAL'}: {result}")
                    # Ensure changes are committed
                    db_async.commit()
                except Exception as e:
                    logger.error(f"ML training failed for {symbol or 'GLOBAL'}: {e}")
                    db_async.rollback()
                finally:
                    db_async.close()

            thread = threading.Thread(target=train_async, daemon=True)
            thread.start()

            return jsonify({
                'status': 'training_started',
                'symbol': symbol or 'GLOBAL',
                'days_back': days_back
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error triggering ML training: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/models/<int:model_id>', methods=['DELETE'])
def delete_ml_model(model_id):
    """Delete an ML model"""
    try:
        from models import MLModel
        import os
        db = ScopedSession()
        try:
            model = db.query(MLModel).filter(MLModel.id == model_id).first()
            if not model:
                return jsonify({'error': 'Model not found'}), 404

            # Don't allow deleting active models
            if model.is_active:
                return jsonify({'error': 'Cannot delete active model. Deactivate it first.'}), 400

            # Delete model file if it exists
            model_path = os.path.join('ml_models/xgboost', model.file_path)
            if os.path.exists(model_path):
                try:
                    os.remove(model_path)
                    logger.info(f"Deleted model file: {model_path}")
                except Exception as e:
                    logger.warning(f"Could not delete model file {model_path}: {e}")

            # Delete from database
            db.delete(model)
            db.commit()

            logger.info(f"Deleted ML model #{model_id}")
            return jsonify({'success': True, 'message': f'Model #{model_id} deleted'})
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error deleting ML model: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/training_runs/<int:run_id>', methods=['DELETE'])
def delete_training_run(run_id):
    """Delete a training run record"""
    try:
        from models import MLTrainingRun
        db = ScopedSession()
        try:
            run = db.query(MLTrainingRun).filter(MLTrainingRun.id == run_id).first()
            if not run:
                return jsonify({'error': 'Training run not found'}), 404

            # Delete from database
            db.delete(run)
            db.commit()

            logger.info(f"Deleted training run #{run_id}")
            return jsonify({'success': True, 'message': f'Training run #{run_id} deleted'})
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error deleting training run: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/models/<int:model_id>/export')
def export_ml_model(model_id):
    """Export ML model file"""
    try:
        from models import MLModel
        import os
        from flask import send_file

        db = ScopedSession()
        try:
            model = db.query(MLModel).filter(MLModel.id == model_id).first()
            if not model:
                return jsonify({'error': 'Model not found'}), 404

            model_path = os.path.join('ml_models/xgboost', model.file_path)
            if not os.path.exists(model_path):
                return jsonify({'error': 'Model file not found on disk'}), 404

            return send_file(
                model_path,
                as_attachment=True,
                download_name=f"ml_model_{model.symbol or 'GLOBAL'}_{model.version}.pkl"
            )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error exporting ML model: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/models/import', methods=['POST'])
def import_ml_model():
    """Import ML model file"""
    try:
        from models import MLModel
        import os
        from werkzeug.utils import secure_filename

        if 'model_file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['model_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.pkl'):
            return jsonify({'error': 'Only .pkl files are supported'}), 400

        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join('ml_models/xgboost', filename)
        file.save(filepath)

        logger.info(f"ML model imported: {filepath}")
        return jsonify({'success': True, 'message': f'Model imported: {filename}'})
    except Exception as e:
        logger.error(f"Error importing ML model: {e}")
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/ml/stats')
def get_ml_stats():
    """Get ML system statistics"""
    try:
        from models import MLModel, MLPrediction, MLTrainingRun
        db = ScopedSession()
        try:
            # Count models
            total_models = db.query(MLModel).count()
            active_models = db.query(MLModel).filter(MLModel.is_active == True).count()

            # Count predictions
            total_predictions = db.query(MLPrediction).count()

            # Get recent training runs
            recent_runs = db.query(MLTrainingRun)\
                .filter(MLTrainingRun.status == 'completed')\
                .order_by(MLTrainingRun.completed_at.desc())\
                .limit(5).all()

            # Calculate average accuracy from active models
            active_model_objs = db.query(MLModel).filter(MLModel.is_active == True).all()
            avg_accuracy = sum(float(m.accuracy) for m in active_model_objs if m.accuracy) / len(active_model_objs) if active_model_objs else 0

            return jsonify({
                'total_models': total_models,
                'active_models': active_models,
                'total_predictions': total_predictions,
                'avg_accuracy': round(avg_accuracy, 4),
                'recent_training': [{
                    'symbol': r.symbol or 'GLOBAL',
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None,
                    'duration_seconds': r.duration_seconds,
                    'samples': r.training_samples
                } for r in recent_runs]
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting ML stats: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# PRICE CHARTS WITH TP/SL LEVELS
# ============================================================================

@app_webui.route('/api/price-chart/<symbol>')
def api_price_chart(symbol):
    """Get price chart with TP/SL levels for a symbol

    Args:
        symbol: Trading symbol (e.g., EURUSD, XAUUSD)

    Query params:
        timeframe: M1, M5, M15, H1, H4, D1 (default: H1)
        bars: Number of bars to display (default: 100)
        filter: 'open', 'closed', 'all' (default: 'open')
        hours: For closed/all, hours back to look (default: 24)

    Returns:
        JSON with base64-encoded PNG
    """
    try:
        from monitoring.price_chart_generator import PriceChartGenerator

        timeframe = request.args.get('timeframe', 'H1')
        bars = request.args.get('bars', 100, type=int)
        trade_filter = request.args.get('filter', 'open')
        hours_back = request.args.get('hours', 24, type=int)

        with PriceChartGenerator(account_id=3) as generator:
            fig = generator.generate_price_chart_with_tpsl(
                symbol=symbol,
                timeframe=timeframe,
                bars_back=bars,
                trade_filter=trade_filter,
                hours_back=hours_back
            )

            if not fig:
                return jsonify({'error': f'No data available for {symbol}'}), 404

            img_base64 = generator.fig_to_base64(fig)

            return jsonify({
                'symbol': symbol,
                'timeframe': timeframe,
                'bars': bars,
                'filter': trade_filter,
                'hours': hours_back,
                'image': f'data:image/png;base64,{img_base64}',
                'generated_at': datetime.utcnow().isoformat()
            })

    except Exception as e:
        logger.error(f"Error generating price chart for {symbol}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app_webui.route('/api/price-charts')
def api_price_charts_all():
    """Get price charts for all symbols with trades

    Query params:
        timeframe: M1, M5, M15, H1, H4, D1 (default: H1)
        bars: Number of bars to display (default: 100)
        filter: 'open', 'closed', 'all' (default: 'open')
        hours: For closed/all, hours back to look (default: 24)

    Returns:
        JSON with array of charts (base64-encoded PNGs)
    """
    try:
        from monitoring.price_chart_generator import PriceChartGenerator
        from sqlalchemy import distinct, or_

        timeframe = request.args.get('timeframe', 'H1')
        bars = request.args.get('bars', 100, type=int)
        trade_filter = request.args.get('filter', 'open')
        hours_back = request.args.get('hours', 24, type=int)

        # Get all symbols with trades matching filter
        db = ScopedSession()
        try:
            query = db.query(distinct(Trade.symbol)).filter(
                Trade.account_id == 3
            )

            if trade_filter == 'open':
                query = query.filter(Trade.status == 'open')
            elif trade_filter == 'closed':
                since = datetime.utcnow() - timedelta(hours=hours_back)
                query = query.filter(
                    Trade.status == 'closed',
                    Trade.close_time >= since
                )
            elif trade_filter == 'all':
                since = datetime.utcnow() - timedelta(hours=hours_back)
                query = query.filter(
                    or_(
                        Trade.status == 'open',
                        (Trade.status == 'closed') & (Trade.close_time >= since)
                    )
                )

            symbols = [s[0] for s in query.all()]
        finally:
            db.close()

        charts = []
        with PriceChartGenerator(account_id=3) as generator:
            for symbol in symbols:
                try:
                    fig = generator.generate_price_chart_with_tpsl(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars_back=bars,
                        trade_filter=trade_filter,
                        hours_back=hours_back
                    )

                    if fig:
                        img_base64 = generator.fig_to_base64(fig)
                        charts.append({
                            'symbol': symbol,
                            'image': f'data:image/png;base64,{img_base64}'
                        })
                except Exception as e:
                    logger.error(f"Error generating chart for {symbol}: {e}")
                    continue

        return jsonify({
            'timeframe': timeframe,
            'bars': bars,
            'filter': trade_filter,
            'hours': hours_back,
            'charts': charts,
            'generated_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error generating price charts: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("ngTradingBot Server Starting...")
    logger.info("=" * 60)

    # Initialize database
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        exit(1)

    # Initialize Redis
    try:
        init_redis()
        logger.info("Redis initialized successfully")
    except Exception as e:
        logger.error(f"Redis initialization failed: {e}")
        exit(1)

    # Start background tasks
    cleanup_thread = Thread(target=cleanup_ticks_job, daemon=True)
    cleanup_thread.start()

    retention_thread = Thread(target=retention_cleanup_job, daemon=True)
    retention_thread.start()

    # Start OHLC cleanup job (runs daily to delete data older than 1 year)
    ohlc_cleanup_thread = Thread(target=ohlc_cleanup_job, daemon=True)
    ohlc_cleanup_thread.start()

    # Start backup scheduler
    start_backup_scheduler()

    # Start tick batch writer (writes buffered ticks from Redis to PostgreSQL)
    start_batch_writer(interval=5, batch_size=1000)

    # Clear all old signals on startup to force fresh generation
    from models import TradingSignal
    startup_db = ScopedSession()
    try:
        old_signals = startup_db.query(TradingSignal).filter_by(status='active').all()
        if old_signals:
            logger.info(f"Clearing {len(old_signals)} old active signals on startup")
            for sig in old_signals:
                sig.status = 'expired'
            startup_db.commit()
    except Exception as e:
        logger.error(f"Error clearing old signals: {e}")
        startup_db.rollback()
    finally:
        startup_db.close()

    # Start signal worker (generates trading signals)
    from signal_worker import start_signal_worker
    start_signal_worker(interval=10)  # Every 10 seconds

    # Start trade monitor (real-time P&L tracking)
    from trade_monitor import start_trade_monitor
    start_trade_monitor()

    # Start auto-trader (signal → trade automation) - DISABLED by default
    from auto_trader import start_auto_trader
    auto_trader = start_auto_trader(enabled=True)  # ✅ ENABLED BY DEFAULT
    logger.info("🤖 Auto-Trader initialized (ENABLED)")

    # Start connection watchdog (monitors MT5 connection health)
    from connection_watchdog import get_connection_watchdog
    watchdog = get_connection_watchdog()
    watchdog.start()
    logger.info("🔍 Connection Watchdog started (monitors MT5 health)")

    # Start daily backtest scheduler for auto-optimization
    from daily_backtest_scheduler import start_scheduler as start_backtest_scheduler
    start_backtest_scheduler()
    logger.info("📊 Daily Backtest Scheduler started (runs at 00:00 UTC daily)")

    # Request fresh account data from EA on startup
    try:
        from account_refresh import request_account_data_refresh, schedule_periodic_refresh
        startup_db2 = ScopedSession()
        try:
            count = request_account_data_refresh(startup_db2)
            if count > 0:
                logger.info(f"🔄 Requested account data refresh for {count} accounts on startup")
        except Exception as e:
            logger.error(f"Error requesting account data refresh: {e}")
        finally:
            startup_db2.close()

        # Schedule periodic refresh every 5 minutes
        schedule_periodic_refresh(interval=300)
    except ImportError:
        logger.warning("account_refresh module not found, skipping account refresh feature")

    logger.info("Background tasks started (tick aggregation + retention cleanup + backup + tick batch writer + signal worker + trade monitor + auto-trader + daily backtest scheduler + account refresh)")

    # Start all servers in separate threads
    ports = [
        (app_command, 9900, "Command & Control"),
        (app_ticks, 9901, "Tick Stream"),
        (app_trades, 9902, "Trade Updates"),
        (app_logs, 9903, "Logging")
    ]

    logger.info("All servers starting...")

    # Log app_command routes for debugging
    logger.info("=== app_command routes (port 9900) ===")
    for rule in app_command.url_map.iter_rules():
        logger.info(f"  {rule.rule} -> {rule.endpoint} {list(rule.methods)}")
    logger.info("=" * 40)

    threads = []
    for app, port, name in ports:
        thread = Thread(target=run_server, args=(app, port, name), daemon=True)
        thread.start()
        threads.append(thread)

    # Start WebUI with SocketIO (runs in main thread)
    logger.info("Starting WebUI & Dashboard server on port 9905")
    logger.info("=== app_webui routes ===")
    for rule in app_webui.url_map.iter_rules():
        logger.info(f"  {rule.rule} -> {rule.endpoint} {list(rule.methods)}")
    logger.info("=========================")
    socketio.run(app_webui, host='0.0.0.0', port=9905, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

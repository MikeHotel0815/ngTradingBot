"""
Python server for ngTradingBot
Receives connections from MT5 EA running on Windows VPS
"""

from flask import Flask, request, jsonify
from datetime import datetime
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Store connected clients
connected_clients = {}


@app.route('/api/connect', methods=['POST'])
def connect():
    """Handle MT5 EA connection requests"""
    try:
        data = request.get_json()
        account = data.get('account')
        broker = data.get('broker')
        platform = data.get('platform')
        timestamp = data.get('timestamp')

        logger.info(f"Connection request from account {account} ({broker})")

        # Store client info
        connected_clients[account] = {
            'broker': broker,
            'platform': platform,
            'connected_at': datetime.now().isoformat(),
            'last_heartbeat': datetime.now().isoformat()
        }

        return jsonify({
            'status': 'success',
            'message': 'Connected successfully',
            'session_id': f"session_{account}_{timestamp}",
            'server_time': datetime.now().isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Handle heartbeat from MT5 EA"""
    try:
        data = request.get_json()
        account = data.get('account')
        balance = data.get('balance')
        equity = data.get('equity')

        if account in connected_clients:
            connected_clients[account]['last_heartbeat'] = datetime.now().isoformat()
            connected_clients[account]['balance'] = balance
            connected_clients[account]['equity'] = equity

            logger.info(f"Heartbeat from account {account} - Balance: {balance}, Equity: {equity}")

            return jsonify({
                'status': 'success',
                'message': 'Heartbeat received'
            }), 200
        else:
            logger.warning(f"Heartbeat from unknown account {account}")
            return jsonify({
                'status': 'error',
                'message': 'Account not connected'
            }), 404

    except Exception as e:
        logger.error(f"Heartbeat error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    """Handle MT5 EA disconnection"""
    try:
        data = request.get_json()
        account = data.get('account')

        if account in connected_clients:
            del connected_clients[account]
            logger.info(f"Account {account} disconnected")

        return jsonify({
            'status': 'success',
            'message': 'Disconnected successfully'
        }), 200

    except Exception as e:
        logger.error(f"Disconnect error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/status', methods=['GET'])
def status():
    """Get server status and connected clients"""
    return jsonify({
        'status': 'running',
        'server_time': datetime.now().isoformat(),
        'connected_clients': len(connected_clients),
        'clients': connected_clients
    }), 200


if __name__ == '__main__':
    logger.info("Starting ngTradingBot server on port 9900...")
    app.run(host='0.0.0.0', port=9900, debug=True)

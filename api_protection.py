"""
API Endpoints for Unified Daily Loss Protection System

These endpoints provide a single interface to configure ALL protection mechanisms:
- Daily loss limits (percentage and absolute EUR)
- Circuit breaker settings
- Auto-pause system
- Total drawdown protection

Replaces fragmented protection logic scattered across multiple files.
"""

from flask import Blueprint, jsonify, request
import logging
from daily_drawdown_protection import DailyDrawdownLimit, get_drawdown_protection
from database import get_db

logger = logging.getLogger(__name__)

protection_bp = Blueprint('protection', __name__, url_prefix='/api/protection')


@protection_bp.route('/', methods=['GET'])
def get_protection_status():
    """
    GET /api/protection/

    Get current protection settings for an account

    Query Parameters:
        account_id (int): Account ID (default: 3)

    Returns:
        {
            "success": true,
            "protection": {
                "protection_enabled": true,
                "max_daily_loss_percent": 10.0,
                "max_daily_loss_eur": null,
                "auto_pause_enabled": false,
                "pause_after_consecutive_losses": 3,
                "max_total_drawdown_percent": 20.0,
                "circuit_breaker_tripped": false,
                "daily_pnl": -101.83,
                "limit_reached": false,
                "tracking_date": "2025-10-24",
                "last_reset_at": "2025-10-24T08:45:00",
                "notes": "Testing account - auto-pause disabled"
            }
        }
    """
    try:
        account_id = request.args.get('account_id', 3, type=int)

        db = next(get_db())
        try:
            limit = db.query(DailyDrawdownLimit).filter_by(account_id=account_id).first()

            if not limit:
                return jsonify({
                    'success': False,
                    'error': 'No protection settings found for this account'
                }), 404

            return jsonify({
                'success': True,
                'protection': {
                    'account_id': account_id,
                    'protection_enabled': bool(limit.protection_enabled),
                    'max_daily_loss_percent': float(limit.max_daily_loss_percent) if limit.max_daily_loss_percent else None,
                    'max_daily_loss_eur': float(limit.max_daily_loss_eur) if limit.max_daily_loss_eur else None,
                    'auto_pause_enabled': bool(limit.auto_pause_enabled),
                    'pause_after_consecutive_losses': int(limit.pause_after_consecutive_losses) if limit.pause_after_consecutive_losses else None,
                    'max_total_drawdown_percent': float(limit.max_total_drawdown_percent) if limit.max_total_drawdown_percent else None,
                    'circuit_breaker_tripped': bool(limit.circuit_breaker_tripped),
                    'daily_pnl': float(limit.daily_pnl) if limit.daily_pnl else 0.0,
                    'limit_reached': bool(limit.limit_reached),
                    'tracking_date': limit.tracking_date.isoformat() if limit.tracking_date else None,
                    'last_reset_at': limit.last_reset_at.isoformat() if limit.last_reset_at else None,
                    'notes': limit.notes
                }
            })

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting protection status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@protection_bp.route('/', methods=['POST'])
def update_protection_settings():
    """
    POST /api/protection/

    Update protection settings (single source of truth)

    Request Body:
        {
            "account_id": 3,
            "protection_enabled": true,
            "max_daily_loss_percent": 10.0,
            "max_daily_loss_eur": null,
            "auto_pause_enabled": false,
            "pause_after_consecutive_losses": 3,
            "max_total_drawdown_percent": 20.0,
            "notes": "Updated via Dashboard"
        }

    Returns:
        {
            "success": true,
            "message": "Protection settings updated successfully"
        }
    """
    try:
        data = request.get_json()
        account_id = data.get('account_id', 3)

        protection = get_drawdown_protection(account_id)

        result = protection.update_full_config(
            protection_enabled=data.get('protection_enabled'),
            max_daily_loss_percent=data.get('max_daily_loss_percent'),
            max_daily_loss_eur=data.get('max_daily_loss_eur'),
            auto_pause_enabled=data.get('auto_pause_enabled'),
            pause_after_consecutive_losses=data.get('pause_after_consecutive_losses'),
            max_total_drawdown_percent=data.get('max_total_drawdown_percent'),
            notes=data.get('notes')
        )

        logger.info(f"Protection settings updated via API for account {account_id}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error updating protection settings: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


@protection_bp.route('/reset', methods=['POST'])
def reset_circuit_breaker():
    """
    POST /api/protection/reset

    Reset circuit breaker manually

    Request Body:
        {
            "account_id": 3
        }

    Returns:
        {
            "success": true,
            "message": "Circuit breaker reset successfully"
        }
    """
    try:
        data = request.get_json() or {}
        account_id = data.get('account_id', 3)

        protection = get_drawdown_protection(account_id)
        protection.reset_circuit_breaker()

        logger.info(f"Circuit breaker reset via API for account {account_id}")

        return jsonify({
            'success': True,
            'message': 'Circuit breaker reset successfully'
        })

    except Exception as e:
        logger.error(f"Error resetting circuit breaker: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


@protection_bp.route('/enable', methods=['POST'])
def enable_protection():
    """
    POST /api/protection/enable

    Enable daily loss protection

    Request Body:
        {
            "account_id": 3,
            "enabled": true
        }

    Returns:
        {
            "success": true,
            "message": "Protection enabled"
        }
    """
    try:
        data = request.get_json() or {}
        account_id = data.get('account_id', 3)
        enabled = data.get('enabled', True)

        protection = get_drawdown_protection(account_id)
        protection.enable_protection(enabled=enabled)

        status = "enabled" if enabled else "disabled"
        logger.info(f"Protection {status} via API for account {account_id}")

        return jsonify({
            'success': True,
            'message': f'Protection {status}'
        })

    except Exception as e:
        logger.error(f"Error toggling protection: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


# Register blueprint helper (to be called from app.py)
def register_protection_endpoints(app):
    """Register protection blueprint with Flask app"""
    app.register_blueprint(protection_bp)
    logger.info("✅ Protection API endpoints registered")

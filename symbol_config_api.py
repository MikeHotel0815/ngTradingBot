#!/usr/bin/env python3
"""
Symbol Configuration API Endpoints
Dashboard endpoints for viewing and managing symbol-specific dynamic configs
"""

from flask import Blueprint, jsonify, request
from database import ScopedSession
from models import SymbolTradingConfig
from symbol_dynamic_manager import SymbolDynamicManager
import logging

logger = logging.getLogger(__name__)

# Create Blueprint
symbol_config_bp = Blueprint('symbol_config', __name__, url_prefix='/api/symbol-config')


@symbol_config_bp.route('/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint"""
    return jsonify({'success': True, 'message': 'API is working'})


@symbol_config_bp.route('/', methods=['GET'])
def get_all_symbol_configs():
    """
    Get all symbol trading configurations

    Query params:
    - status: Filter by status (active, paused, disabled)
    - sort_by: Sort by field (rolling_winrate, rolling_profit, symbol)
    """
    db = ScopedSession()
    try:
        account_id = request.args.get('account_id', 1, type=int)
        status_filter = request.args.get('status')
        sort_by = request.args.get('sort_by', 'rolling_profit')

        query = db.query(SymbolTradingConfig).filter_by(account_id=account_id)

        # Apply status filter
        if status_filter:
            query = query.filter_by(status=status_filter)

        # Get all configs first, then sort in Python to avoid SQL issues
        configs = query.all()

        # Apply sorting in Python
        if sort_by == 'rolling_winrate':
            configs = sorted(configs, key=lambda c: float(c.rolling_winrate) if c.rolling_winrate else -999999, reverse=True)
        elif sort_by == 'rolling_profit':
            configs = sorted(configs, key=lambda c: float(c.rolling_profit) if c.rolling_profit else -999999, reverse=True)
        elif sort_by == 'symbol':
            configs = sorted(configs, key=lambda c: (c.symbol, c.direction or ''))

        result = []
        for config in configs:
            result.append({
                'id': config.id,
                'symbol': config.symbol,
                'direction': config.direction,
                'status': config.status,
                'min_confidence_threshold': float(config.min_confidence_threshold) if config.min_confidence_threshold else None,
                'risk_multiplier': float(config.risk_multiplier) if config.risk_multiplier else None,
                'consecutive_wins': config.consecutive_wins or 0,
                'consecutive_losses': config.consecutive_losses or 0,
                'rolling_trades_count': config.rolling_trades_count or 0,
                'rolling_wins': config.rolling_wins or 0,
                'rolling_losses': config.rolling_losses or 0,
                'rolling_winrate': float(config.rolling_winrate) if config.rolling_winrate else None,
                'rolling_profit': float(config.rolling_profit) if config.rolling_profit else None,
                'preferred_regime': config.preferred_regime,
                'regime_performance_trending': float(config.regime_performance_trending) if config.regime_performance_trending else None,
                'regime_performance_ranging': float(config.regime_performance_ranging) if config.regime_performance_ranging else None,
                'paused_at': config.paused_at.isoformat() if config.paused_at else None,
                'pause_reason': config.pause_reason,
                'last_trade_at': config.last_trade_at.isoformat() if config.last_trade_at else None,
                'last_updated_at': config.last_updated_at.isoformat() if config.last_updated_at else None,
            })

        return jsonify({
            'success': True,
            'count': len(result),
            'configs': result
        })

    except Exception as e:
        logger.error(f"Error getting symbol configs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@symbol_config_bp.route('/summary', methods=['GET'])
def get_summary():
    """Get summary statistics of all symbol configs"""
    db = ScopedSession()
    try:
        account_id = request.args.get('account_id', 1, type=int)

        configs = db.query(SymbolTradingConfig).filter_by(account_id=account_id).all()

        summary = {
            'total_configs': len(configs),
            'by_status': {
                'active': 0,
                'paused': 0,
                'reduced_risk': 0,
                'disabled': 0
            },
            'top_performers': [],
            'worst_performers': [],
            'total_trades': 0,
            'avg_winrate': 0.0,
            'total_profit': 0.0
        }

        # Count by status
        for config in configs:
            summary['by_status'][config.status] = summary['by_status'].get(config.status, 0) + 1

            if config.rolling_trades_count:
                summary['total_trades'] += config.rolling_trades_count

            if config.rolling_profit:
                summary['total_profit'] += float(config.rolling_profit)

        # Calculate average winrate
        winrates = [float(c.rolling_winrate) for c in configs if c.rolling_winrate and c.rolling_trades_count >= 5]
        if winrates:
            summary['avg_winrate'] = sum(winrates) / len(winrates)

        # Top performers (min 5 trades)
        top = sorted(
            [c for c in configs if c.rolling_trades_count and c.rolling_trades_count >= 5],
            key=lambda c: float(c.rolling_profit or 0),
            reverse=True
        )[:5]

        for config in top:
            summary['top_performers'].append({
                'symbol': config.symbol,
                'direction': config.direction,
                'rolling_winrate': float(config.rolling_winrate) if config.rolling_winrate else None,
                'rolling_profit': float(config.rolling_profit) if config.rolling_profit else None,
                'rolling_trades': config.rolling_trades_count
            })

        # Worst performers (min 5 trades)
        worst = sorted(
            [c for c in configs if c.rolling_trades_count and c.rolling_trades_count >= 5],
            key=lambda c: float(c.rolling_profit or 0)
        )[:5]

        for config in worst:
            summary['worst_performers'].append({
                'symbol': config.symbol,
                'direction': config.direction,
                'rolling_winrate': float(config.rolling_winrate) if config.rolling_winrate else None,
                'rolling_profit': float(config.rolling_profit) if config.rolling_profit else None,
                'rolling_trades': config.rolling_trades_count
            })

        return jsonify({
            'success': True,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@symbol_config_bp.route('/<int:config_id>', methods=['GET'])
def get_symbol_config(config_id):
    """Get detailed info for specific symbol config"""
    db = ScopedSession()
    try:
        config = db.query(SymbolTradingConfig).filter_by(id=config_id).first()

        if not config:
            return jsonify({'success': False, 'error': 'Config not found'}), 404

        return jsonify({
            'success': True,
            'config': {
                'id': config.id,
                'symbol': config.symbol,
                'direction': config.direction,
                'status': config.status,
                'min_confidence_threshold': float(config.min_confidence_threshold),
                'risk_multiplier': float(config.risk_multiplier),
                'position_size_multiplier': float(config.position_size_multiplier),
                'sl_multiplier': float(config.sl_multiplier),
                'tp_multiplier': float(config.tp_multiplier),
                'auto_pause_enabled': config.auto_pause_enabled,
                'pause_after_consecutive_losses': config.pause_after_consecutive_losses,
                'resume_after_cooldown_hours': config.resume_after_cooldown_hours,
                'paused_at': config.paused_at.isoformat() if config.paused_at else None,
                'pause_reason': config.pause_reason,
                'consecutive_wins': config.consecutive_wins,
                'consecutive_losses': config.consecutive_losses,
                'last_trade_result': config.last_trade_result,
                'rolling_window_size': config.rolling_window_size,
                'rolling_trades_count': config.rolling_trades_count,
                'rolling_wins': config.rolling_wins,
                'rolling_losses': config.rolling_losses,
                'rolling_breakeven': config.rolling_breakeven,
                'rolling_profit': float(config.rolling_profit) if config.rolling_profit else None,
                'rolling_winrate': float(config.rolling_winrate) if config.rolling_winrate else None,
                'rolling_avg_profit': float(config.rolling_avg_profit) if config.rolling_avg_profit else None,
                'rolling_profit_factor': float(config.rolling_profit_factor) if config.rolling_profit_factor else None,
                'preferred_regime': config.preferred_regime,
                'regime_performance_trending': float(config.regime_performance_trending) if config.regime_performance_trending else None,
                'regime_performance_ranging': float(config.regime_performance_ranging) if config.regime_performance_ranging else None,
                'regime_trades_trending': config.regime_trades_trending,
                'regime_trades_ranging': config.regime_trades_ranging,
                'regime_wins_trending': config.regime_wins_trending,
                'regime_wins_ranging': config.regime_wins_ranging,
                'session_trades_today': config.session_trades_today,
                'session_profit_today': float(config.session_profit_today) if config.session_profit_today else None,
                'last_trade_at': config.last_trade_at.isoformat() if config.last_trade_at else None,
                'last_updated_at': config.last_updated_at.isoformat() if config.last_updated_at else None,
                'created_at': config.created_at.isoformat() if config.created_at else None
            }
        })

    except Exception as e:
        logger.error(f"Error getting config {config_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@symbol_config_bp.route('/<int:config_id>/resume', methods=['POST'])
def resume_symbol_config(config_id):
    """Manually resume a paused symbol config"""
    db = ScopedSession()
    try:
        manager = SymbolDynamicManager(account_id=1)
        config = db.query(SymbolTradingConfig).filter_by(id=config_id).first()

        if not config:
            return jsonify({'success': False, 'error': 'Config not found'}), 404

        # Resume
        resumed_config = manager.manually_resume_symbol(
            db, config.symbol, config.direction
        )

        return jsonify({
            'success': True,
            'message': f'Resumed {config.symbol} {config.direction}',
            'config': {
                'status': resumed_config.status,
                'paused_at': None,
                'pause_reason': None
            }
        })

    except Exception as e:
        logger.error(f"Error resuming config {config_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@symbol_config_bp.route('/paused', methods=['GET'])
def get_paused_configs():
    """Get all paused symbol configs ready for resume"""
    db = ScopedSession()
    try:
        account_id = request.args.get('account_id', 1, type=int)
        manager = SymbolDynamicManager(account_id=account_id)

        paused = manager.get_paused_symbols(db)

        result = []
        for config in paused:
            hours_paused = 0
            if config.paused_at:
                from datetime import datetime
                hours_paused = (datetime.utcnow() - config.paused_at).total_seconds() / 3600

            ready_for_resume = hours_paused >= config.resume_after_cooldown_hours

            result.append({
                'id': config.id,
                'symbol': config.symbol,
                'direction': config.direction,
                'paused_at': config.paused_at.isoformat() if config.paused_at else None,
                'pause_reason': config.pause_reason,
                'hours_paused': round(hours_paused, 1),
                'cooldown_hours': config.resume_after_cooldown_hours,
                'ready_for_resume': ready_for_resume,
                'consecutive_losses': config.consecutive_losses,
                'rolling_winrate': float(config.rolling_winrate) if config.rolling_winrate else None
            })

        return jsonify({
            'success': True,
            'count': len(result),
            'paused_configs': result
        })

    except Exception as e:
        logger.error(f"Error getting paused configs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


# Register blueprint in app.py:
# from symbol_config_api import symbol_config_bp
# app.register_blueprint(symbol_config_bp)

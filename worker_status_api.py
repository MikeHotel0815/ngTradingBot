#!/usr/bin/env python3
"""
Worker Status API

Provides endpoints to monitor health and status of all background workers
"""

import logging
import json
from flask import Blueprint, jsonify
from typing import Dict, List
from datetime import datetime
import redis
import os

logger = logging.getLogger(__name__)

# Create Blueprint
worker_status_bp = Blueprint('worker_status', __name__, url_prefix='/api/workers')

# Redis connection
redis_client = None

def get_redis_client():
    """Get or create Redis client"""
    global redis_client
    if redis_client is None:
        try:
            redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
            redis_client = redis.from_url(redis_url, decode_responses=True)
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
    return redis_client


@worker_status_bp.route('/status', methods=['GET'])
def get_workers_status():
    """
    Get status of all workers
    
    Returns:
        {
            "success": true,
            "workers": [...],
            "summary": {
                "total": 6,
                "healthy": 5,
                "unhealthy": 1,
                "total_success": 123,
                "total_errors": 2
            }
        }
    """
    try:
        redis = get_redis_client()
        if not redis:
            return jsonify({
                'success': False,
                'error': 'Redis not available'
            }), 503
        
        # Get all worker metrics from Redis
        worker_keys = redis.keys('worker:metrics:*')
        
        workers = []
        summary = {
            'total': 0,
            'healthy': 0,
            'unhealthy': 0,
            'total_success': 0,
            'total_errors': 0
        }
        
        for key in worker_keys:
            try:
                metrics_json = redis.get(key)
                if metrics_json:
                    metrics = json.loads(metrics_json)
                    workers.append(metrics)
                    
                    # Update summary
                    summary['total'] += 1
                    if metrics.get('is_healthy'):
                        summary['healthy'] += 1
                    else:
                        summary['unhealthy'] += 1
                    
                    summary['total_success'] += metrics.get('success_count', 0)
                    summary['total_errors'] += metrics.get('error_count', 0)
            
            except Exception as e:
                logger.error(f"Error parsing metrics from {key}: {e}")
        
        # Sort workers by name
        workers.sort(key=lambda w: w.get('name', ''))
        
        # Add overall health status
        if summary['total'] == 0:
            summary['status'] = 'unknown'
            summary['message'] = 'No worker metrics available'
        elif summary['unhealthy'] == 0:
            summary['status'] = 'healthy'
            summary['message'] = 'All workers running normally'
        elif summary['unhealthy'] < summary['total']:
            summary['status'] = 'degraded'
            summary['message'] = f'{summary["unhealthy"]} worker(s) unhealthy'
        else:
            summary['status'] = 'critical'
            summary['message'] = 'All workers unhealthy'
        
        return jsonify({
            'success': True,
            'timestamp': datetime.utcnow().isoformat(),
            'workers': workers,
            'summary': summary
        })
    
    except Exception as e:
        logger.error(f"Error getting worker status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@worker_status_bp.route('/status/<worker_name>', methods=['GET'])
def get_worker_status(worker_name: str):
    """
    Get detailed status of a specific worker
    
    Args:
        worker_name: Name of the worker (e.g., 'drawdown_protection')
    
    Returns:
        Worker metrics or 404 if not found
    """
    try:
        redis = get_redis_client()
        if not redis:
            return jsonify({
                'success': False,
                'error': 'Redis not available'
            }), 503
        
        key = f'worker:metrics:{worker_name}'
        metrics_json = redis.get(key)
        
        if not metrics_json:
            return jsonify({
                'success': False,
                'error': f'Worker "{worker_name}" not found'
            }), 404
        
        metrics = json.loads(metrics_json)
        
        return jsonify({
            'success': True,
            'worker': metrics
        })
    
    except Exception as e:
        logger.error(f"Error getting worker {worker_name} status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@worker_status_bp.route('/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint
    
    Returns:
        200 if all workers healthy, 503 if any unhealthy
    """
    try:
        redis = get_redis_client()
        if not redis:
            return jsonify({
                'status': 'unhealthy',
                'reason': 'Redis not available'
            }), 503
        
        # Check all workers
        worker_keys = redis.keys('worker:metrics:*')
        
        if not worker_keys:
            return jsonify({
                'status': 'unknown',
                'reason': 'No worker metrics available'
            }), 503
        
        unhealthy_workers = []
        
        for key in worker_keys:
            metrics_json = redis.get(key)
            if metrics_json:
                metrics = json.loads(metrics_json)
                if not metrics.get('is_healthy') or not metrics.get('is_alive'):
                    unhealthy_workers.append(metrics.get('name'))
        
        if unhealthy_workers:
            return jsonify({
                'status': 'unhealthy',
                'unhealthy_workers': unhealthy_workers
            }), 503
        
        return jsonify({
            'status': 'healthy',
            'workers_count': len(worker_keys)
        }), 200
    
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@worker_status_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """
    Get aggregated metrics for monitoring/alerting
    
    Returns Prometheus-style metrics
    """
    try:
        redis = get_redis_client()
        if not redis:
            return "# Redis unavailable\n", 503
        
        worker_keys = redis.keys('worker:metrics:*')
        
        metrics_lines = [
            "# HELP worker_healthy Worker health status (1=healthy, 0=unhealthy)",
            "# TYPE worker_healthy gauge",
        ]
        
        for key in worker_keys:
            metrics_json = redis.get(key)
            if metrics_json:
                metrics = json.loads(metrics_json)
                name = metrics.get('name', 'unknown')
                is_healthy = 1 if metrics.get('is_healthy') else 0
                success_count = metrics.get('success_count', 0)
                error_count = metrics.get('error_count', 0)
                uptime = metrics.get('uptime_seconds', 0)
                
                metrics_lines.extend([
                    f'worker_healthy{{worker="{name}"}} {is_healthy}',
                    f'worker_success_total{{worker="{name}"}} {success_count}',
                    f'worker_errors_total{{worker="{name}"}} {error_count}',
                    f'worker_uptime_seconds{{worker="{name}"}} {uptime}',
                ])
        
        return '\n'.join(metrics_lines) + '\n', 200, {'Content-Type': 'text/plain'}
    
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return f"# Error: {e}\n", 500

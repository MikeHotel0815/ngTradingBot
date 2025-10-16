#!/usr/bin/env python3
"""
Worker Performance Monitor

Monitors worker health and performance over 24h period
Logs metrics every 5 minutes and alerts on issues
"""

import requests
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import json
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/projects/logs/worker_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:9905')
CHECK_INTERVAL = 300  # 5 minutes
ALERT_THRESHOLD_ERRORS = 10  # Alert if >10 errors in last hour
ALERT_THRESHOLD_UNHEALTHY_MINUTES = 10  # Alert if unhealthy for >10 minutes

# State tracking
worker_states = {}  # worker_name -> {last_check, consecutive_unhealthy, ...}


class WorkerMonitor:
    """Monitors worker health and performance"""
    
    def __init__(self):
        self.start_time = datetime.utcnow()
        self.check_count = 0
        self.alerts_sent = []
    
    def get_worker_status(self) -> Dict:
        """Fetch worker status from API"""
        try:
            url = f"{API_BASE_URL}/api/workers/status"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch worker status: {e}")
            return None
    
    def check_health(self):
        """Check worker health and log metrics"""
        self.check_count += 1
        
        logger.info(f"🔍 Health check #{self.check_count} (Runtime: {self.get_runtime()})")
        
        status = self.get_worker_status()
        if not status or not status.get('success'):
            logger.error("❌ Failed to get worker status from API")
            return
        
        workers = status.get('workers', [])
        summary = status.get('summary', {})
        
        # Log summary
        logger.info(f"📊 Summary: {summary['healthy']}/{summary['total']} healthy | "
                   f"Success: {summary['total_success']} | Errors: {summary['total_errors']}")
        
        # Check each worker
        for worker in workers:
            self.check_worker(worker)
        
        # Overall system health
        if summary.get('status') == 'critical':
            self.send_alert('CRITICAL', 'All workers unhealthy!', summary)
        elif summary.get('status') == 'degraded':
            self.send_alert('WARNING', f"{summary['unhealthy']} worker(s) unhealthy", summary)
    
    def check_worker(self, worker: Dict):
        """Check individual worker health"""
        name = worker.get('name')
        is_healthy = worker.get('is_healthy')
        is_alive = worker.get('is_alive')
        error_count = worker.get('error_count', 0)
        success_count = worker.get('success_count', 0)
        last_run = worker.get('last_run')
        uptime_hours = worker.get('uptime_hours', 0)
        
        # Initialize state if first check
        if name not in worker_states:
            worker_states[name] = {
                'first_seen': datetime.utcnow(),
                'consecutive_unhealthy': 0,
                'last_error_count': error_count,
                'last_alert': None
            }
        
        state = worker_states[name]
        
        # Calculate new errors since last check
        new_errors = error_count - state['last_error_count']
        state['last_error_count'] = error_count
        
        # Status emoji
        if is_healthy and is_alive:
            status_emoji = "✅"
            state['consecutive_unhealthy'] = 0
        else:
            status_emoji = "❌"
            state['consecutive_unhealthy'] += 1
        
        # Log worker status
        logger.info(f"  {status_emoji} {name:25s} | "
                   f"Alive: {is_alive} | "
                   f"Success: {success_count:4d} | "
                   f"Errors: {error_count:3d} (+{new_errors}) | "
                   f"Uptime: {uptime_hours:.1f}h")
        
        # Alert conditions
        if not is_alive:
            self.send_alert('CRITICAL', f'Worker {name} is DEAD', worker)
        
        elif not is_healthy and state['consecutive_unhealthy'] >= 2:
            # Unhealthy for 10+ minutes (2 checks * 5 min)
            minutes_unhealthy = state['consecutive_unhealthy'] * (CHECK_INTERVAL / 60)
            self.send_alert('WARNING', 
                          f'Worker {name} unhealthy for {minutes_unhealthy:.0f} minutes', 
                          worker)
        
        elif new_errors > 5:
            self.send_alert('WARNING', 
                          f'Worker {name} had {new_errors} errors in last check', 
                          worker)
    
    def send_alert(self, level: str, message: str, data: Dict):
        """Send alert (log for now, could extend to email/Slack)"""
        alert = {
            'level': level,
            'message': message,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data
        }
        
        # Avoid duplicate alerts
        alert_key = f"{level}:{message}"
        if alert_key in [a.get('key') for a in self.alerts_sent[-10:]]:
            return
        
        alert['key'] = alert_key
        self.alerts_sent.append(alert)
        
        # Log with appropriate level
        if level == 'CRITICAL':
            logger.critical(f"🚨 {message}")
        elif level == 'WARNING':
            logger.warning(f"⚠️  {message}")
        else:
            logger.info(f"ℹ️  {message}")
        
        # Could extend to:
        # - Send email
        # - Post to Slack
        # - Create incident in monitoring system
    
    def get_runtime(self) -> str:
        """Get monitor runtime as formatted string"""
        elapsed = datetime.utcnow() - self.start_time
        hours = elapsed.total_seconds() / 3600
        return f"{hours:.1f}h"
    
    def generate_summary_report(self):
        """Generate summary report of monitoring session"""
        logger.info("=" * 80)
        logger.info("📈 WORKER MONITORING SUMMARY REPORT")
        logger.info("=" * 80)
        logger.info(f"Monitor started: {self.start_time.isoformat()}")
        logger.info(f"Total runtime: {self.get_runtime()}")
        logger.info(f"Total checks: {self.check_count}")
        logger.info(f"Total alerts: {len(self.alerts_sent)}")
        
        # Alert breakdown
        if self.alerts_sent:
            logger.info("\nAlerts sent:")
            critical_count = sum(1 for a in self.alerts_sent if a['level'] == 'CRITICAL')
            warning_count = sum(1 for a in self.alerts_sent if a['level'] == 'WARNING')
            logger.info(f"  🚨 CRITICAL: {critical_count}")
            logger.info(f"  ⚠️  WARNING: {warning_count}")
        
        # Worker statistics
        logger.info("\nWorker statistics:")
        for name, state in worker_states.items():
            first_seen = state['first_seen']
            uptime = (datetime.utcnow() - first_seen).total_seconds() / 3600
            logger.info(f"  • {name}: Monitored for {uptime:.1f}h")
        
        logger.info("=" * 80)
    
    def run(self, duration_hours: int = 24):
        """Run monitoring for specified duration"""
        logger.info(f"🚀 Starting worker monitoring for {duration_hours}h")
        logger.info(f"Check interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL/60:.0f} minutes)")
        logger.info(f"API endpoint: {API_BASE_URL}/api/workers/status")
        
        end_time = datetime.utcnow() + timedelta(hours=duration_hours)
        
        try:
            while datetime.utcnow() < end_time:
                self.check_health()
                
                # Calculate time until next check
                next_check = datetime.utcnow() + timedelta(seconds=CHECK_INTERVAL)
                remaining_seconds = (next_check - datetime.utcnow()).total_seconds()
                
                if remaining_seconds > 0:
                    logger.debug(f"💤 Sleeping for {remaining_seconds:.0f}s until next check")
                    time.sleep(remaining_seconds)
            
            logger.info("✅ Monitoring duration completed")
        
        except KeyboardInterrupt:
            logger.info("⏹️  Monitoring stopped by user")
        
        finally:
            self.generate_summary_report()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor worker health and performance')
    parser.add_argument('--duration', type=int, default=24, 
                       help='Monitoring duration in hours (default: 24)')
    parser.add_argument('--interval', type=int, default=300,
                       help='Check interval in seconds (default: 300)')
    parser.add_argument('--api-url', type=str, default='http://localhost:9905',
                       help='API base URL (default: http://localhost:9905)')
    
    args = parser.parse_args()
    
    # Update globals
    global CHECK_INTERVAL, API_BASE_URL
    CHECK_INTERVAL = args.interval
    API_BASE_URL = args.api_url
    
    # Run monitor
    monitor = WorkerMonitor()
    monitor.run(duration_hours=args.duration)


if __name__ == '__main__':
    main()

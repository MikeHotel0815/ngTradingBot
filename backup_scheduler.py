#!/usr/bin/env python3
"""
Database Backup Scheduler for ngTradingBot
Runs periodic backups and pushes to GitHub
"""

import os
import subprocess
import logging
import time
from datetime import datetime, timedelta
from threading import Thread
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackupScheduler:
    """Manages automated database backups"""

    def __init__(self):
        self.backup_script = os.getenv('BACKUP_SCRIPT', '/app/backup_to_github.sh')
        self.backup_interval_hours = int(os.getenv('BACKUP_INTERVAL_HOURS', '24'))
        self.backup_enabled = os.getenv('BACKUP_ENABLED', 'false').lower() == 'true'
        self.github_repo = os.getenv('GITHUB_BACKUP_REPO', '')
        self.github_token = os.getenv('GITHUB_TOKEN', '')
        self.backup_dir = os.getenv('BACKUP_DIR', '/app/backups')
        self.last_backup = None

    def run_backup(self):
        """Execute backup script"""
        try:
            logger.info(f"Starting database backup (interval: {self.backup_interval_hours}h)")

            # Set environment variables for backup script
            env = os.environ.copy()
            env['GITHUB_BACKUP_REPO'] = self.github_repo
            env['GITHUB_TOKEN'] = self.github_token

            # Run backup script
            result = subprocess.run(
                [self.backup_script],
                capture_output=True,
                text=True,
                env=env,
                timeout=600  # 10 minute timeout
            )

            if result.returncode == 0:
                logger.info("Backup completed successfully")
                logger.info(result.stdout)
                self.last_backup = datetime.now()
                return True
            else:
                logger.error(f"Backup failed with exit code {result.returncode}")
                logger.error(result.stderr)
                return False

        except subprocess.TimeoutExpired:
            logger.error("Backup timeout (>10 minutes)")
            return False
        except Exception as e:
            logger.error(f"Backup error: {e}")
            return False

    def get_backup_stats(self):
        """Get backup statistics"""
        try:
            backup_files = []
            if os.path.exists(self.backup_dir):
                for file in os.listdir(self.backup_dir):
                    if file.endswith('.sql.gz'):
                        filepath = os.path.join(self.backup_dir, file)
                        stat = os.stat(filepath)
                        backup_files.append({
                            'filename': file,
                            'size_bytes': stat.st_size,
                            'size_mb': round(stat.st_size / 1024 / 1024, 2),
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })

            backup_files.sort(key=lambda x: x['modified'], reverse=True)

            return {
                'enabled': self.backup_enabled,
                'interval_hours': self.backup_interval_hours,
                'last_backup': self.last_backup.isoformat() if self.last_backup else None,
                'github_configured': bool(self.github_repo and self.github_token),
                'backup_count': len(backup_files),
                'backups': backup_files[:10]  # Last 10 backups
            }
        except Exception as e:
            logger.error(f"Error getting backup stats: {e}")
            return {}

    def schedule_loop(self):
        """Main scheduling loop"""
        logger.info(f"Backup scheduler started (interval: {self.backup_interval_hours}h, enabled: {self.backup_enabled})")

        if not self.backup_enabled:
            logger.warning("Backup is DISABLED - set BACKUP_ENABLED=true to enable")
            return

        if not os.path.exists(self.backup_script):
            logger.error(f"Backup script not found: {self.backup_script}")
            return

        # Run initial backup
        logger.info("Running initial backup...")
        self.run_backup()

        # Schedule periodic backups
        while True:
            try:
                sleep_seconds = self.backup_interval_hours * 3600
                logger.info(f"Next backup in {self.backup_interval_hours} hours")
                time.sleep(sleep_seconds)

                if self.backup_enabled:
                    self.run_backup()
                else:
                    logger.info("Backup disabled, skipping")

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                time.sleep(60)  # Wait 1 minute before retry


# Singleton instance
_scheduler = None


def get_scheduler():
    """Get or create scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackupScheduler()
    return _scheduler


def start_backup_scheduler():
    """Start backup scheduler in background thread"""
    scheduler = get_scheduler()
    thread = Thread(target=scheduler.schedule_loop, daemon=True)
    thread.start()
    logger.info("Backup scheduler thread started")
    return scheduler


if __name__ == '__main__':
    # Run standalone
    scheduler = BackupScheduler()
    scheduler.schedule_loop()

#!/bin/bash
# Automated Database Backup Script for ngTradingBot
# Purpose: Creates compressed PostgreSQL backups with rotation
# Usage: Run via cron or manually

set -e

# Configuration
BACKUP_DIR="/projects/ngTradingBot/backups/database"
CONTAINER_NAME="ngtradingbot_db"
DB_USER="trader"
DB_NAME="ngtradingbot"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate backup filename with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/ngtradingbot_${TIMESTAMP}.sql.gz"

echo "🔄 Starting database backup: $BACKUP_FILE"

# Create backup using pg_dump
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

# Check if backup was successful
if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ Backup completed successfully: $BACKUP_SIZE"
else
    echo "❌ Backup failed!"
    exit 1
fi

# Clean up old backups (older than RETENTION_DAYS)
echo "🧹 Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "ngtradingbot_*.sql.gz" -type f -mtime +$RETENTION_DAYS -delete

# Count remaining backups
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "ngtradingbot_*.sql.gz" -type f | wc -l)
echo "📊 Total backups retained: $BACKUP_COUNT"

# List recent backups
echo "📁 Recent backups:"
ls -lh "$BACKUP_DIR" | tail -5

exit 0

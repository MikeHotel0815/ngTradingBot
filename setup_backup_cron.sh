#!/bin/bash
# Setup automated database backups via cron
# Purpose: Configure cron to run backups every 6 hours

SCRIPT_PATH="/projects/ngTradingBot/backup_database.sh"
CRON_SCHEDULE="0 */6 * * *"  # Every 6 hours at minute 0

echo "🔧 Setting up automated database backups..."

# Check if cron is installed
if ! command -v crontab &> /dev/null; then
    echo "⚠️  WARNING: crontab not found. You may need to install cron:"
    echo "    Ubuntu/Debian: sudo apt-get install cron"
    echo "    CentOS/RHEL: sudo yum install cronie"
    exit 1
fi

# Check if backup script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ Backup script not found at: $SCRIPT_PATH"
    exit 1
fi

# Make sure script is executable
chmod +x "$SCRIPT_PATH"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$SCRIPT_PATH"; then
    echo "⚠️  Cron job already exists. Current crontab:"
    crontab -l | grep "$SCRIPT_PATH"
    echo ""
    echo "To update, first remove the existing entry with: crontab -e"
    exit 0
fi

# Add cron job
(crontab -l 2>/dev/null; echo "$CRON_SCHEDULE $SCRIPT_PATH >> /projects/ngTradingBot/backups/backup.log 2>&1") | crontab -

if [ $? -eq 0 ]; then
    echo "✅ Cron job added successfully!"
    echo "   Schedule: Every 6 hours"
    echo "   Script: $SCRIPT_PATH"
    echo "   Log: /projects/ngTradingBot/backups/backup.log"
    echo ""
    echo "📋 Current crontab:"
    crontab -l
    echo ""
    echo "🔄 Next backup will run at the next 0th, 6th, 12th, or 18th hour"
else
    echo "❌ Failed to add cron job"
    exit 1
fi

exit 0

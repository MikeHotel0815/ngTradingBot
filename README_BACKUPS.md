# Database Backup Setup

## Automated Backup Configuration

### Option 1: Using Cron (Recommended for Linux servers)

```bash
# Make backup script executable
chmod +x /projects/ngTradingBot/backup_database.sh

# Add to crontab (every 6 hours)
crontab -e

# Add this line:
0 */6 * * * /projects/ngTradingBot/backup_database.sh >> /projects/ngTradingBot/backups/backup.log 2>&1
```

### Option 2: Using Systemd Timer (Modern Linux)

Create `/etc/systemd/system/ngtradingbot-backup.service`:
```ini
[Unit]
Description=ngTradingBot Database Backup
After=docker.service

[Service]
Type=oneshot
ExecStart=/projects/ngTradingBot/backup_database.sh
User=root
StandardOutput=append:/projects/ngTradingBot/backups/backup.log
StandardError=append:/projects/ngTradingBot/backups/backup.log
```

Create `/etc/systemd/system/ngtradingbot-backup.timer`:
```ini
[Unit]
Description=ngTradingBot Database Backup Timer
Requires=ngtradingbot-backup.service

[Timer]
OnCalendar=*-*-* 00/6:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ngtradingbot-backup.timer
sudo systemctl start ngtradingbot-backup.timer
sudo systemctl status ngtradingbot-backup.timer
```

### Option 3: Manual Docker Compose Integration

Add to your `docker-compose.yml`:
```yaml
services:
  backup:
    image: postgres:15
    depends_on:
      - db
    volumes:
      - ./backups/database:/backups
    environment:
      - PGHOST=db
      - PGUSER=trader
      - PGDATABASE=ngtradingbot
    command: >
      sh -c "while true; do
        pg_dump -U trader ngtradingbot | gzip > /backups/ngtradingbot_$$(date +%Y%m%d_%H%M%S).sql.gz
        && find /backups -name 'ngtradingbot_*.sql.gz' -mtime +30 -delete
        && sleep 21600;
      done"
```

### Option 4: Windows Task Scheduler

Create a `.bat` file:
```batch
@echo off
docker exec ngtradingbot_db pg_dump -U trader ngtradingbot > C:\backups\ngtradingbot_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.sql
```

Add to Task Scheduler:
- Trigger: Daily, repeat every 6 hours
- Action: Start a program - `C:\path\to\backup.bat`

## Manual Backup

```bash
# Create backup
/projects/ngTradingBot/backup_database.sh

# Or directly:
docker exec ngtradingbot_db pg_dump -U trader ngtradingbot | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

## Restore from Backup

```bash
# Decompress and restore
gunzip -c /projects/ngTradingBot/backups/database/ngtradingbot_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i ngtradingbot_db psql -U trader -d ngtradingbot

# Or in two steps:
gunzip /projects/ngTradingBot/backups/database/ngtradingbot_YYYYMMDD_HHMMSS.sql.gz
docker exec -i ngtradingbot_db psql -U trader -d ngtradingbot < ngtradingbot_YYYYMMDD_HHMMSS.sql
```

## Backup Configuration

- **Location**: `/projects/ngTradingBot/backups/database/`
- **Format**: Compressed SQL dumps (`.sql.gz`)
- **Retention**: 30 days (configurable in `backup_database.sh`)
- **Frequency**: Every 6 hours (recommended)
- **Size**: ~1-5 MB per backup (compressed)

## Monitoring Backups

```bash
# List all backups
ls -lh /projects/ngTradingBot/backups/database/

# Check backup log
tail -f /projects/ngTradingBot/backups/backup.log

# Verify latest backup
gunzip -t /projects/ngTradingBot/backups/database/ngtradingbot_*.sql.gz | tail -1
```

## Offsite Backup (Recommended)

For production use, sync backups to cloud storage:

```bash
# AWS S3
aws s3 sync /projects/ngTradingBot/backups/database/ s3://your-bucket/ngtradingbot-backups/

# Google Cloud Storage
gsutil rsync -r /projects/ngTradingBot/backups/database/ gs://your-bucket/ngtradingbot-backups/

# Rsync to remote server
rsync -avz /projects/ngTradingBot/backups/database/ user@remote:/backups/ngtradingbot/
```

## Emergency Recovery

In case of complete data loss:

1. Stop the containers:
   ```bash
   docker-compose down
   ```

2. Restore database:
   ```bash
   docker-compose up -d db
   gunzip -c /path/to/backup.sql.gz | docker exec -i ngtradingbot_db psql -U trader -d ngtradingbot
   ```

3. Restart all services:
   ```bash
   docker-compose up -d
   ```

4. Verify data integrity:
   ```bash
   docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "SELECT COUNT(*) FROM trades;"
   ```

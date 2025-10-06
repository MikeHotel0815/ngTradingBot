#!/bin/bash

# ngTradingBot Database Backup Script
# Backs up PostgreSQL database and pushes to GitHub

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/app/backups}"
DB_CONTAINER="ngtradingbot_db"
DB_USER="trader"
DB_NAME="ngtradingbot"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="backup_${TIMESTAMP}.sql.gz"
GITHUB_REPO="${GITHUB_BACKUP_REPO:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory
mkdir -p "$BACKUP_DIR"

log_info "Starting database backup: $BACKUP_FILE"

# Create PostgreSQL dump
if docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"; then
    log_info "Database dump created successfully"

    # Get file size
    SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
    log_info "Backup size: $SIZE"
else
    log_error "Database dump failed"
    exit 1
fi

# Create backup metadata
cat > "${BACKUP_DIR}/backup_${TIMESTAMP}.json" <<EOF
{
    "timestamp": "$(date -Iseconds)",
    "filename": "$BACKUP_FILE",
    "size_bytes": $(stat -f%z "${BACKUP_DIR}/${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_DIR}/${BACKUP_FILE}"),
    "database": "$DB_NAME",
    "compressed": true
}
EOF

# Cleanup old backups (older than RETENTION_DAYS)
log_info "Cleaning up backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f -mtime +${RETENTION_DAYS} -delete
find "$BACKUP_DIR" -name "backup_*.json" -type f -mtime +${RETENTION_DAYS} -delete

# GitHub backup (if configured)
if [ -n "$GITHUB_REPO" ] && [ -n "$GITHUB_TOKEN" ]; then
    log_info "Pushing backup to GitHub: $GITHUB_REPO"

    # Initialize git repo if needed
    cd "$BACKUP_DIR"
    if [ ! -d ".git" ]; then
        git init
        git config user.name "ngTradingBot Backup"
        git config user.email "backup@ngtradingbot.local"
        git remote add origin "https://${GITHUB_TOKEN}@${GITHUB_REPO#https://}"
    fi

    # Add and commit backup
    git add "${BACKUP_FILE}" "backup_${TIMESTAMP}.json"
    git commit -m "Automated backup: ${TIMESTAMP}" || log_warn "No changes to commit"

    # Push to GitHub
    if git push -u origin main 2>/dev/null || git push -u origin master 2>/dev/null; then
        log_info "Backup pushed to GitHub successfully"
    else
        log_error "Failed to push backup to GitHub"
    fi
else
    log_warn "GitHub backup not configured (GITHUB_REPO and GITHUB_TOKEN required)"
    log_info "Backup saved locally: ${BACKUP_DIR}/${BACKUP_FILE}"
fi

# Create latest symlink
ln -sf "$BACKUP_FILE" "${BACKUP_DIR}/latest.sql.gz"

log_info "Backup completed successfully"
log_info "Location: ${BACKUP_DIR}/${BACKUP_FILE}"

# Show backup statistics
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log_info "Total backups: $BACKUP_COUNT | Total size: $TOTAL_SIZE"

exit 0

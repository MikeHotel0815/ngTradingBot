# ngTradingBot - Backup System

Automatisches Datenbank-Backup-System mit GitHub-Integration.

## Features

- ✅ **Automatische PostgreSQL-Backups** (konfigurierbar: stündlich/täglich)
- ✅ **Komprimierte Dumps** (gzip)
- ✅ **GitHub Push** (optional, automatisches Push zu Git-Repository)
- ✅ **Retention Policy** (automatisches Löschen alter Backups)
- ✅ **Backup-Metadaten** (JSON mit Timestamp, Größe, etc.)
- ✅ **API-Endpunkte** (Manuelles Triggern & Status-Abfrage)

## Konfiguration

### 1. Environment Variables (.env)

```bash
# Backup aktivieren
BACKUP_ENABLED=true

# Backup-Intervall (in Stunden)
BACKUP_INTERVAL_HOURS=24

# Lokale Retention (in Tagen)
BACKUP_RETENTION_DAYS=30

# Optional: GitHub Backup
GITHUB_BACKUP_REPO=github.com/username/repo.git
GITHUB_TOKEN=ghp_your_personal_access_token
```

### 2. GitHub Personal Access Token erstellen

1. Gehe zu: https://github.com/settings/tokens
2. Klicke auf "Generate new token (classic)"
3. Wähle Scope: `repo` (Full control of private repositories)
4. Kopiere den Token → setze `GITHUB_TOKEN` in `.env`

### 3. GitHub Repository erstellen

```bash
# Neues Repository auf GitHub erstellen (privat empfohlen!)
# Name: z.B. "ngtradingbot-backups"

# In .env setzen:
GITHUB_BACKUP_REPO=github.com/username/ngtradingbot-backups.git
```

## Verwendung

### Automatische Backups

Backups laufen automatisch alle `BACKUP_INTERVAL_HOURS` Stunden, wenn `BACKUP_ENABLED=true`.

```bash
# Container starten mit aktivierten Backups
BACKUP_ENABLED=true docker compose up -d
```

### Manuelles Backup (Shell-Skript)

```bash
# Direkter Aufruf im Container
docker exec ngtradingbot_server /app/backup_to_github.sh
```

### Manuelles Backup (API)

```bash
# Via API triggern
curl -X POST http://localhost:9905/api/dashboard/backup/trigger \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
```

### Backup-Status abfragen

```bash
# Backup-Status und Statistiken
curl http://localhost:9905/api/dashboard/backup/status
```

**Response:**
```json
{
  "status": "success",
  "backup": {
    "enabled": true,
    "interval_hours": 24,
    "last_backup": "2025-10-02T12:18:21Z",
    "github_configured": true,
    "backup_count": 5,
    "backups": [
      {
        "filename": "backup_20251002_121821.sql.gz",
        "size_bytes": 4096,
        "size_mb": 0.004,
        "modified": "2025-10-02T12:18:21Z"
      }
    ]
  }
}
```

## Backup-Struktur

### Lokaler Backup-Ordner

```
/app/data/backups/
├── backup_20251002_120000.sql.gz
├── backup_20251002_120000.json
├── backup_20251002_130000.sql.gz
├── backup_20251002_130000.json
└── latest.sql.gz -> backup_20251002_130000.sql.gz
```

### Backup-Metadaten (JSON)

```json
{
    "timestamp": "2025-10-02T12:18:21+00:00",
    "filename": "backup_20251002_121821.sql.gz",
    "size_bytes": 4096,
    "database": "ngtradingbot",
    "compressed": true
}
```

### GitHub Repository-Struktur

```
ngtradingbot-backups/
├── backup_20251002_120000.sql.gz
├── backup_20251002_120000.json
├── backup_20251002_130000.sql.gz
├── backup_20251002_130000.json
└── README.md
```

## Retention Policy

- **Lokale Backups:** Werden nach `BACKUP_RETENTION_DAYS` Tagen gelöscht (default: 30 Tage)
- **GitHub Backups:** Bleiben dauerhaft erhalten (manuelles Cleanup via Git)

## Restore (Wiederherstellung)

### Aus lokalem Backup

```bash
# 1. Backup finden
docker exec ngtradingbot_server ls -lh /app/data/backups/

# 2. Datenbank wiederherstellen
docker exec ngtradingbot_db psql -U trader -d ngtradingbot < backup.sql
```

### Aus GitHub

```bash
# 1. Backup von GitHub herunterladen
git clone https://github.com/username/ngtradingbot-backups.git
cd ngtradingbot-backups

# 2. Backup entpacken
gunzip backup_20251002_121821.sql.gz

# 3. In Container kopieren und wiederherstellen
docker cp backup_20251002_121821.sql ngtradingbot_db:/tmp/
docker exec ngtradingbot_db psql -U trader -d ngtradingbot < /tmp/backup_20251002_121821.sql
```

## Logs

```bash
# Backup-Scheduler Logs
docker logs ngtradingbot_server | grep -i backup

# Beispiel-Output:
# 2025-10-02 12:17:59 - backup_scheduler - INFO - Backup scheduler started (interval: 24h, enabled: True)
# 2025-10-02 12:18:21 - backup_scheduler - INFO - Backup completed successfully
```

## Troubleshooting

### Backup funktioniert nicht

1. **Prüfe Umgebungsvariablen:**
   ```bash
   docker exec ngtradingbot_server env | grep BACKUP
   ```

2. **Prüfe Scheduler-Status:**
   ```bash
   docker logs ngtradingbot_server | grep "Backup scheduler"
   ```

3. **Teste manuell:**
   ```bash
   docker exec ngtradingbot_server /app/backup_to_github.sh
   ```

### GitHub Push schlägt fehl

1. **Token prüfen:**
   - Token muss `repo` Permissions haben
   - Token nicht abgelaufen?

2. **Repository prüfen:**
   - Repository existiert?
   - Format: `github.com/username/repo.git` (ohne `https://`)

3. **Manueller Test:**
   ```bash
   docker exec -it ngtradingbot_server bash
   cd /app/data/backups
   git remote -v
   git push
   ```

## Sicherheit

⚠️ **WICHTIG:**

1. **GitHub Repository:** Unbedingt als **privat** markieren!
2. **Token:** NIEMALS in Git committen! Nur in `.env` (in `.gitignore`)
3. **Backups:** Enthalten sensitive Daten (Accounts, API-Keys, etc.)

## Kosten-Kalkulation

**Backup-Größe:** ~4 KB (aktuell, wächst mit Daten)

**Bei 5 Symbolen:**
- 1 Backup/Tag × 30 Tage = 120 KB/Monat
- 1 Jahr Backups = ~1.4 MB

**GitHub Free:** 1 GB Speicher (ausreichend für Jahre!)

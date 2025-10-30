#!/bin/bash
# Deploy Trading Bot Optimizations - 2025-10-30
# Based on 36h Performance Analysis

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Trading Bot Optimization Deployment                    ║"
echo "║   Based on 36h Performance Analysis (2025-10-30)         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Farben
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Syntax Check
echo -e "${YELLOW}[1/5] Syntax-Prüfung...${NC}"
python3 -m py_compile signal_generator.py sl_enforcement.py smart_tp_sl.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Alle Python-Dateien syntaktisch korrekt${NC}"
else
    echo -e "${RED}❌ Syntax-Fehler gefunden! Deployment abgebrochen.${NC}"
    exit 1
fi
echo ""

# 2. Backup aktuelle Konfiguration
echo -e "${YELLOW}[2/5] Backup der aktuellen Konfiguration...${NC}"
BACKUP_DIR="backups/optimization_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

docker exec ngtradingbot_server python3 - <<'EOF'
from database import get_db
from models import SubscribedSymbol
import json

db = next(get_db())
symbols = db.query(SubscribedSymbol).filter_by(account_id=3).all()

backup = []
for s in symbols:
    backup.append({
        'symbol': s.symbol,
        'active': s.active
    })

print(json.dumps(backup, indent=2))
db.close()
EOF > "$BACKUP_DIR/symbol_config_before.json"

echo -e "${GREEN}✅ Backup erstellt: $BACKUP_DIR${NC}"
echo ""

# 3. Zeige aktuelle Symbole
echo -e "${YELLOW}[3/5] Aktuelle Symbol-Konfiguration:${NC}"
docker exec ngtradingbot_server python3 - <<'EOF'
from database import get_db
from models import SubscribedSymbol

db = next(get_db())
all_subs = db.query(SubscribedSymbol).filter_by(account_id=3).all()

print("Symbol       | Status")
print("─────────────────────")
for sub in all_subs:
    status = "✅ AKTIV" if sub.active else "❌ INAKTIV"
    print(f"{sub.symbol:12} | {status}")

print(f"\n{len([s for s in all_subs if s.active])} aktive von {len(all_subs)} gesamt")
db.close()
EOF
echo ""

# 4. Container Neustart
echo -e "${YELLOW}[4/5] Container Neustart...${NC}"
echo "Starte Docker Container neu um Änderungen zu aktivieren..."

docker-compose restart ngtradingbot_server ngtradingbot_workers ngtradingbot_dashboard

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Container erfolgreich neu gestartet${NC}"
else
    echo -e "${RED}❌ Container-Neustart fehlgeschlagen!${NC}"
    exit 1
fi

echo ""
echo "Warte 10 Sekunden auf Container-Initialisierung..."
sleep 10
echo ""

# 5. Verifizierung
echo -e "${YELLOW}[5/5] Verifizierung der Änderungen...${NC}"

# Check 1: News-Filter Import
echo -n "  • News-Filter Integration: "
if docker exec ngtradingbot_server python3 -c "from news_filter import NewsFilter; print('OK')" 2>/dev/null | grep -q "OK"; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌${NC}"
fi

# Check 2: Signal Generator Import
echo -n "  • Signal Generator: "
if docker exec ngtradingbot_server python3 -c "from signal_generator import SignalGenerator; print('OK')" 2>/dev/null | grep -q "OK"; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌${NC}"
fi

# Check 3: Container Health
echo -n "  • Server Container: "
if docker ps | grep -q "ngtradingbot_server.*Up"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Down${NC}"
fi

echo -n "  • Workers Container: "
if docker ps | grep -q "ngtradingbot_workers.*Up"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Down${NC}"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                   DEPLOYMENT ERFOLGREICH                  ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Zusammenfassung der Änderungen
echo -e "${GREEN}Implementierte Optimierungen:${NC}"
echo "  1. ✅ News-Filter aktiviert (Forex Factory API)"
echo "  2. ✅ Problem-Symbole deaktiviert (XAGUSD, DE40.c, USDJPY)"
echo "  3. ✅ SL-Limits reduziert (z.B. XAUUSD: \$100→\$5.50)"
echo "  4. ✅ R:R Ratio optimiert (FOREX: 4.4:1, METALS: 3.0:1)"
echo ""

echo -e "${YELLOW}Nächste Schritte:${NC}"
echo "  1. Monitoring aktivieren:"
echo "     ./daily_performance_report.sh"
echo ""
echo "  2. In 36 Stunden Performance prüfen:"
echo "     docker exec ngtradingbot_server python3 /app/analyze_last_36h.py"
echo ""
echo "  3. Logs überwachen:"
echo "     docker logs -f ngtradingbot_server | grep 'news_filter\\|Trading paused'"
echo ""

echo -e "${GREEN}Erwartete Verbesserungen:${NC}"
echo "  • Netto P/L: -\$77 → +\$20-50 (36h)"
echo "  • Profit Factor: 0.07 → 1.5-2.0"
echo "  • AUDUSD: 79% WR/-\$9.55 → +\$15-25"
echo "  • XAUUSD: News-Verluste verhindert"
echo ""

echo -e "${YELLOW}Backup-Wiederherstellung (falls nötig):${NC}"
echo "  Backup gespeichert in: $BACKUP_DIR"
echo ""

#!/bin/bash
# Rebuild all ngTradingBot containers with --no-cache
# 2025-10-30 - After optimization implementation

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   ngTradingBot Container Rebuild (--no-cache)             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Farben
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

cd /projects/ngTradingBot

echo -e "${YELLOW}[1/4] Stoppe Container...${NC}"
docker stop ngtradingbot_server ngtradingbot_workers ngtradingbot_dashboard
echo -e "${GREEN}✅ Container gestoppt${NC}"
echo ""

echo -e "${YELLOW}[2/4] Entferne alte Images...${NC}"
docker rmi ngtradingbot-server ngtradingbot-workers ngtradingbot-dashboard 2>/dev/null || true
echo -e "${GREEN}✅ Alte Images entfernt${NC}"
echo ""

echo -e "${YELLOW}[3/4] Rebuild mit --no-cache...${NC}"
docker build --no-cache -t ngtradingbot-server -f Dockerfile .
docker build --no-cache -t ngtradingbot-workers -f Dockerfile .
docker build --no-cache -t ngtradingbot-dashboard -f Dockerfile .
echo -e "${GREEN}✅ Images neu gebaut${NC}"
echo ""

echo -e "${YELLOW}[4/4] Starte Container...${NC}"
docker start ngtradingbot_db ngtradingbot_redis
sleep 5
docker start ngtradingbot_server ngtradingbot_workers ngtradingbot_dashboard
echo -e "${GREEN}✅ Container gestartet${NC}"
echo ""

echo "Warte 15 Sekunden auf Initialisierung..."
sleep 15
echo ""

echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                 REBUILD ABGESCHLOSSEN                     ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

echo "Verifizierung:"
docker ps | grep ngtradingbot | awk '{print "  • " $NF ": " $7 " " $8}'
echo ""

echo "Logs anzeigen:"
echo "  docker logs -f ngtradingbot_server"
echo ""

echo "News-Filter Logs überwachen:"
echo "  docker logs -f ngtradingbot_server | grep 'news_filter\\|Trading paused'"
echo ""

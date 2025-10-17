#!/bin/bash
# Deploy Dynamic TP Extension System

echo "═══════════════════════════════════════════════════════════"
echo "🚀 DYNAMIC TP EXTENSION - DEPLOYMENT"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Navigate to project directory
cd /projects/ngTradingBot

echo "📊 Changes Summary:"
echo "  ✅ Trailing Stop Stages more aggressive (20%/40%/60%/80%)"
echo "  ✅ Dashboard: Stage markers only shown in profit"
echo "  ✅ Dynamic TP Extension: TP raised by +50% at 80% progress"
echo "  ✅ Database: Added original_tp and tp_extended_count fields"
echo ""

# Stop containers
echo "🛑 Stopping containers..."
docker compose down

# Run database migration
echo ""
echo "🔄 Running database migration..."
docker compose run --rm server alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✅ Migration completed successfully!"
else
    echo "❌ Migration failed! Check logs."
    exit 1
fi

# Start system
echo ""
echo "🚀 Starting system..."
docker compose up -d

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Next Steps:"
echo "  1. Check logs: docker compose logs -f app"
echo "  2. Monitor dashboard for TP extensions"
echo "  3. Look for '🚀 TP EXTENDED' messages in logs"
echo ""
echo "🎯 How it works:"
echo "  - When trade reaches 80% to TP: TP is extended by +50%"
echo "  - SL becomes very tight (10 pips) for maximum protection"
echo "  - Can extend up to 5 times for strong trends!"
echo "  - Stage markers only shown when in profit"
echo ""
echo "📊 Monitoring:"
echo "  - Trade cards will show 'Extension #N' in SL info"
echo "  - original_tp field tracks starting TP"
echo "  - tp_extended_count shows how many times extended"
echo ""

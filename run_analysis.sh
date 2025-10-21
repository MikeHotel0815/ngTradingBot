#!/bin/bash
# Wrapper script to run analysis tools with proper environment

# Source environment variables
export DATABASE_URL="postgresql://trader:tradingbot_secret_2025@localhost:9904/ngtradingbot"
export REDIS_HOST="localhost"
export REDIS_PORT="9905"
export REDIS_DB="0"

# Run the requested script
case "$1" in
    performance)
        python3 analyze_current_performance.py "${@:2}"
        ;;
    monitor)
        python3 audit_monitor.py "${@:2}"
        ;;
    backtest)
        python3 run_audit_backtests.py "${@:2}"
        ;;
    *)
        echo "Usage: $0 {performance|monitor|backtest} [options]"
        echo ""
        echo "Examples:"
        echo "  $0 performance --days 30"
        echo "  $0 monitor --once"
        echo "  $0 backtest --quick"
        exit 1
        ;;
esac

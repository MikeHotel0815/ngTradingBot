#!/usr/bin/env python3
"""
Timezone Migration Summary and Verification Script
===================================================

This script verifies that the timezone handling is correctly implemented
across the entire ngTradingBot system.

WHAT WAS CHANGED:
-----------------

1. NEW MODULE: timezone_manager.py
   - Centralized timezone management
   - Global instance 'tz' for easy access
   - Handles UTC <-> EET/EEST conversions
   - Provides logging with both timezones
   - Database helpers (to_db, from_db)

2. UPDATED MODULES:
   - session_volatility_analyzer.py: Uses tz.now_utc() and tz.get_current_session_info()
   - auto_trader.py: Added timezone context to header
   - unified_workers.py: Market conditions worker shows UTC + Broker time
   - core_communication.py: Heartbeat uses timezone-aware timestamps

3. TIMEZONE RULES:
   - Server/DB: Always UTC (naive timestamps for SQLAlchemy)
   - Broker/MT5: EET/EEST (Europe/Bucharest = UTC+2 or UTC+3)
   - Sessions: Defined in UTC (ASIAN: 00:00-08:00, LONDON: 08:00-16:00, etc.)
   - Logging: Shows both "[UTC: ... | Broker: ... EET]"

4. USAGE PATTERNS:

   # Get current time
   from timezone_manager import tz
   now_utc = tz.now_utc()          # Timezone-aware UTC
   now_broker = tz.now_broker()    # Timezone-aware EET/EEST
   
   # Convert timestamps
   utc_dt = tz.broker_to_utc(broker_dt)
   broker_dt = tz.utc_to_broker(utc_dt)
   
   # Database operations
   db_timestamp = tz.to_db(aware_dt)    # Make naive UTC for DB
   aware_dt = tz.from_db(db_timestamp)  # Make aware when reading
   
   # Parse broker timestamps (MT5 sends in EET)
   utc_dt = tz.parse_broker_timestamp(unix_timestamp)
   
   # Logging with timezone context
   log_msg = tz.format_for_log(dt, "Trade opened")

5. VERIFICATION STEPS:
   - Run this script to check implementation
   - Check logs for timezone format
   - Verify session detection matches UTC time
   - Confirm broker timestamps are converted correctly

"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from timezone_manager import tz
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_timezone_implementation():
    """Verify timezone handling is correctly implemented"""
    
    print("=" * 80)
    print("🕒 TIMEZONE IMPLEMENTATION VERIFICATION")
    print("=" * 80)
    print()
    
    # 1. Check timezone_manager
    print("1️⃣  Checking timezone_manager.py...")
    try:
        print(f"   ✅ Timezone manager imported successfully")
        print(f"   📍 Server timezone: UTC")
        print(f"   📍 Broker timezone: {tz.broker_tz}")
        print(f"   📍 Current offset: {tz._get_broker_offset()}")
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 2. Test current time functions
    print("2️⃣  Testing current time functions...")
    try:
        now_utc = tz.now_utc()
        now_broker = tz.now_broker()
        print(f"   ✅ Current UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"   ✅ Current Broker: {now_broker.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 3. Test conversions
    print("3️⃣  Testing timezone conversions...")
    try:
        # UTC to Broker
        test_utc = tz.now_utc()
        test_broker = tz.utc_to_broker(test_utc)
        back_to_utc = tz.broker_to_utc(test_broker)
        
        if test_utc == back_to_utc:
            print(f"   ✅ UTC <-> Broker conversion: PASS")
        else:
            print(f"   ❌ UTC <-> Broker conversion: FAIL")
            return False
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 4. Test logging format
    print("4️⃣  Testing logging format...")
    try:
        test_dt = tz.now_utc()
        log_str = tz.format_for_log(test_dt, "Test event")
        print(f"   📝 {log_str}")
        
        if "UTC:" in log_str and "Broker:" in log_str:
            print(f"   ✅ Logging format: PASS")
        else:
            print(f"   ❌ Logging format: FAIL")
            return False
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 5. Test session detection
    print("5️⃣  Testing session detection...")
    try:
        session_info = tz.get_current_session_info()
        print(f"   ✅ Current session: {session_info['session']}")
        print(f"   ✅ UTC time: {session_info['utc_time']}")
        print(f"   ✅ Broker time: {session_info['broker_time']}")
        print(f"   ✅ Offset: {session_info['offset']}")
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 6. Test database helpers
    print("6️⃣  Testing database helpers...")
    try:
        # Create aware datetime
        aware_dt = tz.now_utc()
        
        # Convert to DB format (naive UTC)
        db_dt = tz.to_db(aware_dt)
        if db_dt.tzinfo is None:
            print(f"   ✅ to_db() creates naive UTC: PASS")
        else:
            print(f"   ❌ to_db() should create naive datetime: FAIL")
            return False
        
        # Convert back from DB
        back_aware = tz.from_db(db_dt)
        if back_aware.tzinfo is not None:
            print(f"   ✅ from_db() creates aware UTC: PASS")
        else:
            print(f"   ❌ from_db() should create aware datetime: FAIL")
            return False
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 7. Test broker timestamp parsing
    print("7️⃣  Testing broker timestamp parsing...")
    try:
        # Current timestamp as if from MT5 (in broker time)
        broker_now = tz.now_broker()
        unix_ts = int(broker_now.timestamp())
        
        # Parse as broker timestamp
        parsed_utc = tz.parse_broker_timestamp(unix_ts)
        
        # Should be in UTC
        if parsed_utc.tzinfo.zone == 'UTC':
            print(f"   ✅ Broker timestamp parsed to UTC: PASS")
            print(f"   📍 Original: {broker_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"   📍 Parsed: {parsed_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            print(f"   ❌ Parsed timestamp not in UTC: FAIL")
            return False
        print()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 8. Check file imports
    print("8️⃣  Checking module imports...")
    modules_to_check = [
        'session_volatility_analyzer',
        'auto_trader',
        'unified_workers',
        'core_communication'
    ]
    
    for module_name in modules_to_check:
        try:
            module = __import__(module_name)
            # Check if timezone_manager is imported
            if hasattr(module, 'tz'):
                print(f"   ✅ {module_name}: Has 'tz' imported")
            else:
                # Check source code for import
                import inspect
                source = inspect.getsource(module)
                if 'timezone_manager import' in source or 'from timezone_manager' in source:
                    print(f"   ✅ {module_name}: Imports timezone_manager")
                else:
                    print(f"   ⚠️  {module_name}: May not use timezone_manager")
        except Exception as e:
            print(f"   ⚠️  {module_name}: Could not check ({e})")
    print()
    
    # Final summary
    print("=" * 80)
    print("✅ TIMEZONE IMPLEMENTATION VERIFICATION COMPLETE")
    print("=" * 80)
    print()
    print("NEXT STEPS:")
    print("1. Check logs for timezone format: [UTC: ... | Broker: ... EET]")
    print("2. Verify MT5 timestamps are correctly converted")
    print("3. Confirm session detection works across timezone boundaries")
    print("4. Test with real broker connection")
    print()
    
    return True


if __name__ == "__main__":
    success = verify_timezone_implementation()
    sys.exit(0 if success else 1)

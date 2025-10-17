#!/usr/bin/env python3
"""
Timezone Manager
================
Ensures consistent timezone handling across the entire trading system.

CRITICAL CONTEXT:
-----------------
1. MT5/Broker Time: EET (Eastern European Time = UTC+2, or UTC+3 during DST)
   - This is what the EA sends in timestamps
   - Most brokers use this timezone

2. Server Time: UTC (Coordinated Universal Time)
   - Docker containers run in UTC
   - Database stores in UTC
   - All internal calculations in UTC

3. Trading Sessions: Defined in UTC
   - ASIAN: 00:00-08:00 UTC (08:00-16:00 Tokyo)
   - LONDON: 08:00-16:00 UTC (08:00-16:00 London)
   - US: 13:00-22:00 UTC (08:00-17:00 New York)
   - OVERLAP (London+US): 13:00-16:00 UTC

4. Log Display: Shows both UTC and Broker time for clarity

USAGE:
------
from timezone_manager import tz

# Get current time in all timezones
now_utc = tz.now_utc()
now_broker = tz.now_broker()

# Convert timestamps
broker_time = tz.utc_to_broker(utc_datetime)
utc_time = tz.broker_to_utc(broker_datetime)

# Format for logging
log_msg = tz.format_for_log(utc_datetime, "Trade opened")
# Output: "Trade opened [UTC: 2025-10-17 10:30:00 | Broker: 2025-10-17 12:30:00 EET]"

# Parse MT5 timestamps (usually in EET)
dt = tz.parse_broker_timestamp(timestamp_seconds)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
import pytz

logger = logging.getLogger(__name__)


class TimezoneManager:
    """
    Centralized timezone management for the trading system.
    
    Ensures all timestamps are properly handled with explicit timezone info.
    """
    
    def __init__(self):
        # Define timezones
        self.utc = pytz.UTC
        self.broker_tz = pytz.timezone('Europe/Bucharest')  # EET/EEST (UTC+2/+3)
        
        # Alternative names for the same timezone
        self.timezone_names = {
            'utc': self.utc,
            'UTC': self.utc,
            'broker': self.broker_tz,
            'BROKER': self.broker_tz,
            'EET': self.broker_tz,
            'EEST': self.broker_tz,
            'mt5': self.broker_tz,
            'MT5': self.broker_tz
        }
        
        logger.info(f"🕒 Timezone Manager initialized:")
        logger.info(f"   - Server/Database: UTC")
        logger.info(f"   - Broker/MT5: {self.broker_tz} (EET/EEST)")
        logger.info(f"   - Current UTC offset: {self._get_broker_offset()}")
    
    def _get_broker_offset(self) -> str:
        """Get current UTC offset for broker timezone (handles DST)"""
        now = datetime.now(self.broker_tz)
        offset = now.strftime('%z')
        return f"UTC{offset[:3]}:{offset[3:]}"
    
    # ==================== CURRENT TIME ====================
    
    def now_utc(self) -> datetime:
        """Get current time in UTC (timezone-aware)"""
        return datetime.now(self.utc)
    
    def now_broker(self) -> datetime:
        """Get current time in broker timezone (timezone-aware)"""
        return datetime.now(self.broker_tz)
    
    def now_naive_utc(self) -> datetime:
        """Get current UTC time without timezone (for legacy compatibility)"""
        return datetime.utcnow()
    
    # ==================== CONVERSION ====================
    
    def make_aware(self, dt: datetime, tz: Optional[Union[str, pytz.tzinfo.BaseTzInfo]] = 'utc') -> datetime:
        """
        Make a naive datetime timezone-aware.
        
        Args:
            dt: Naive datetime object
            tz: Timezone name or tzinfo object (default: 'utc')
        
        Returns:
            Timezone-aware datetime
        """
        if dt.tzinfo is not None:
            return dt  # Already aware
        
        if isinstance(tz, str):
            tz = self.timezone_names.get(tz, self.utc)
        
        return tz.localize(dt)
    
    def utc_to_broker(self, dt: datetime) -> datetime:
        """
        Convert UTC datetime to broker timezone.
        
        Args:
            dt: Datetime in UTC (aware or naive)
        
        Returns:
            Datetime in broker timezone (aware)
        """
        if dt.tzinfo is None:
            dt = self.utc.localize(dt)
        
        return dt.astimezone(self.broker_tz)
    
    def broker_to_utc(self, dt: datetime) -> datetime:
        """
        Convert broker timezone datetime to UTC.
        
        Args:
            dt: Datetime in broker timezone (aware or naive)
        
        Returns:
            Datetime in UTC (aware)
        """
        if dt.tzinfo is None:
            dt = self.broker_tz.localize(dt)
        
        return dt.astimezone(self.utc)
    
    def to_utc(self, dt: datetime, source_tz: Optional[str] = None) -> datetime:
        """
        Convert any datetime to UTC.
        
        Args:
            dt: Datetime object
            source_tz: Source timezone name if dt is naive (default: 'utc')
        
        Returns:
            Datetime in UTC (aware)
        """
        if dt.tzinfo is None:
            source_tz = source_tz or 'utc'
            dt = self.make_aware(dt, source_tz)
        
        return dt.astimezone(self.utc)
    
    # ==================== PARSING ====================
    
    def parse_broker_timestamp(self, timestamp: Union[int, float]) -> datetime:
        """
        Parse Unix timestamp from broker (assumes EET).
        
        Args:
            timestamp: Unix timestamp in seconds
        
        Returns:
            Timezone-aware datetime in UTC
        """
        # MT5 typically sends timestamps in broker time (EET)
        dt_broker = datetime.fromtimestamp(timestamp, tz=self.broker_tz)
        return dt_broker.astimezone(self.utc)
    
    def parse_utc_timestamp(self, timestamp: Union[int, float]) -> datetime:
        """
        Parse Unix timestamp as UTC.
        
        Args:
            timestamp: Unix timestamp in seconds
        
        Returns:
            Timezone-aware datetime in UTC
        """
        return datetime.fromtimestamp(timestamp, tz=self.utc)
    
    def parse_iso_string(self, iso_string: str, source_tz: str = 'utc') -> datetime:
        """
        Parse ISO format datetime string.
        
        Args:
            iso_string: ISO format string (e.g., "2025-10-17T10:30:00")
            source_tz: Source timezone if not included in string
        
        Returns:
            Timezone-aware datetime in UTC
        """
        try:
            dt = datetime.fromisoformat(iso_string)
            if dt.tzinfo is None:
                dt = self.make_aware(dt, source_tz)
            return dt.astimezone(self.utc)
        except Exception as e:
            logger.error(f"Failed to parse ISO string '{iso_string}': {e}")
            return self.now_utc()
    
    # ==================== FORMATTING ====================
    
    def format_for_log(self, dt: datetime, prefix: str = "") -> str:
        """
        Format datetime for logging with both UTC and broker time.
        
        Args:
            dt: Datetime object (aware or naive)
            prefix: Optional prefix for the log message
        
        Returns:
            Formatted string with both timezones
        """
        if dt.tzinfo is None:
            dt_utc = self.utc.localize(dt)
        else:
            dt_utc = dt.astimezone(self.utc)
        
        dt_broker = dt_utc.astimezone(self.broker_tz)
        
        utc_str = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
        broker_str = dt_broker.strftime('%Y-%m-%d %H:%M:%S')
        tz_name = dt_broker.strftime('%Z')
        
        if prefix:
            return f"{prefix} [UTC: {utc_str} | Broker: {broker_str} {tz_name}]"
        else:
            return f"[UTC: {utc_str} | Broker: {broker_str} {tz_name}]"
    
    def format_utc(self, dt: datetime) -> str:
        """Format datetime as UTC string"""
        if dt.tzinfo is None:
            dt = self.utc.localize(dt)
        return dt.astimezone(self.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def format_broker(self, dt: datetime) -> str:
        """Format datetime as broker timezone string"""
        if dt.tzinfo is None:
            dt = self.utc.localize(dt)
        dt_broker = dt.astimezone(self.broker_tz)
        return dt_broker.strftime('%Y-%m-%d %H:%M:%S %Z')
    
    # ==================== DATABASE HELPERS ====================
    
    def to_db(self, dt: datetime) -> datetime:
        """
        Prepare datetime for database storage (naive UTC).
        
        Args:
            dt: Datetime object (aware or naive)
        
        Returns:
            Naive datetime in UTC (for SQLAlchemy compatibility)
        """
        if dt.tzinfo is None:
            # Assume it's already UTC
            return dt
        
        # Convert to UTC and remove timezone info
        return dt.astimezone(self.utc).replace(tzinfo=None)
    
    def from_db(self, dt: Optional[datetime]) -> Optional[datetime]:
        """
        Load datetime from database (add UTC timezone).
        
        Args:
            dt: Naive datetime from database (assumed UTC)
        
        Returns:
            Timezone-aware datetime in UTC
        """
        if dt is None:
            return None
        
        if dt.tzinfo is not None:
            return dt  # Already aware
        
        return self.utc.localize(dt)
    
    # ==================== TRADING SESSION HELPERS ====================
    
    def get_current_session_info(self) -> dict:
        """
        Get information about current trading session.
        
        Returns:
            Dict with session info including time in all relevant timezones
        """
        now_utc = self.now_utc()
        now_broker = self.now_broker()
        
        utc_time = now_utc.time()
        
        # Determine session based on UTC time
        if time(0, 0) <= utc_time < time(8, 0):
            session = 'ASIAN'
        elif time(8, 0) <= utc_time < time(13, 0):
            session = 'LONDON'
        elif time(13, 0) <= utc_time < time(16, 0):
            session = 'OVERLAP'  # London + US
        elif time(16, 0) <= utc_time < time(22, 0):
            session = 'US'
        else:
            session = 'AFTER_HOURS'
        
        return {
            'session': session,
            'utc_time': now_utc.strftime('%H:%M:%S'),
            'broker_time': now_broker.strftime('%H:%M:%S %Z'),
            'utc_full': now_utc.isoformat(),
            'broker_full': now_broker.isoformat(),
            'offset': self._get_broker_offset()
        }


# ==================== GLOBAL INSTANCE ====================

# Create global instance for easy import
tz = TimezoneManager()


# ==================== UTILITY FUNCTIONS ====================

def log_with_timezone(message: str, dt: Optional[datetime] = None, level: str = 'info'):
    """
    Log a message with timezone context.
    
    Args:
        message: Log message
        dt: Optional datetime to include (uses current time if None)
        level: Log level (debug, info, warning, error)
    """
    dt = dt or tz.now_utc()
    formatted = tz.format_for_log(dt, message)
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(formatted)


# Import guard for backwards compatibility
from datetime import time

__all__ = [
    'TimezoneManager',
    'tz',
    'log_with_timezone'
]

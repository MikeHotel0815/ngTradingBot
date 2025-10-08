"""
Input Validation Module
Centralized input validation for API endpoints to prevent SQL injection and other attacks
"""

import re
from typing import Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class InputValidator:
    """Centralized input validation"""
    
    # Allowed values for enum-like fields
    ALLOWED_SIGNAL_TYPES = ['BUY', 'SELL', 'HOLD', 'CLOSE']
    ALLOWED_TRADE_STATUS = ['open', 'closed', 'pending', 'cancelled']
    ALLOWED_TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1']
    ALLOWED_PERIODS = ['all', 'today', 'week', 'month', 'year', 'custom']
    ALLOWED_PROFIT_STATUS = ['profit', 'loss', 'breakeven']
    ALLOWED_DECISION_TYPES = [
        'TRADE_OPEN', 'TRADE_CLOSE', 'TRADE_RETRY', 'TRADE_FAILED', 'CIRCUIT_BREAKER',
        'SIGNAL_SKIP', 'SIGNAL_GENERATED', 'SIGNAL_EXPIRED',
        'SYMBOL_DISABLE', 'SYMBOL_ENABLE', 'SHADOW_TRADE', 'SYMBOL_RECOVERY',
        'RISK_LIMIT', 'CORRELATION_BLOCK', 'DD_LIMIT', 'SPREAD_REJECTED', 'TICK_STALE',
        'NEWS_PAUSE', 'NEWS_RESUME', 'VOLATILITY_HIGH', 'LIQUIDITY_LOW',
        'SUPERTREND_SL', 'MTF_CONFLICT', 'MTF_ALIGNMENT', 'TRAILING_STOP',
        'BACKTEST_START', 'BACKTEST_COMPLETE', 'OPTIMIZATION_RUN', 'PERFORMANCE_ALERT',
        'MT5_DISCONNECT', 'MT5_RECONNECT', 'AUTOTRADING_ENABLED', 'AUTOTRADING_DISABLED'
    ]
    
    # Pattern for valid symbols (alphanumeric + common symbols)
    SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,12}$')
    
    # Pattern for ISO date format
    ISO_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
    
    @staticmethod
    def validate_integer(
        value: Any,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        default: Optional[int] = None
    ) -> Optional[int]:
        """
        Validate and sanitize integer input
        
        Args:
            value: Input value to validate
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            default: Default value if validation fails
            
        Returns:
            Validated integer or default
        """
        try:
            if value is None:
                return default
            
            result = int(value)
            
            if min_value is not None and result < min_value:
                logger.warning(f"Integer value {result} below minimum {min_value}, using minimum")
                return min_value
            
            if max_value is not None and result > max_value:
                logger.warning(f"Integer value {result} above maximum {max_value}, using maximum")
                return max_value
            
            return result
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid integer value '{value}': {e}, using default {default}")
            return default
    
    @staticmethod
    def validate_float(
        value: Any,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        default: Optional[float] = None
    ) -> Optional[float]:
        """Validate and sanitize float input"""
        try:
            if value is None:
                return default
            
            result = float(value)
            
            if min_value is not None and result < min_value:
                logger.warning(f"Float value {result} below minimum {min_value}, using minimum")
                return min_value
            
            if max_value is not None and result > max_value:
                logger.warning(f"Float value {result} above maximum {max_value}, using maximum")
                return max_value
            
            return result
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid float value '{value}': {e}, using default {default}")
            return default
    
    @staticmethod
    def validate_enum(
        value: Any,
        allowed_values: List[str],
        default: Optional[str] = None,
        case_sensitive: bool = True
    ) -> Optional[str]:
        """
        Validate enum-like input against allowed values
        
        Args:
            value: Input value
            allowed_values: List of allowed values
            default: Default if value not in allowed
            case_sensitive: Whether comparison is case-sensitive
            
        Returns:
            Validated value or default
        """
        if value is None:
            return default
        
        str_value = str(value)
        
        if not case_sensitive:
            str_value = str_value.upper()
            allowed_values = [v.upper() for v in allowed_values]
        
        if str_value in allowed_values:
            return str_value
        
        logger.warning(f"Invalid enum value '{value}', allowed: {allowed_values}, using default {default}")
        return default
    
    @staticmethod
    def validate_symbol(value: Any, default: Optional[str] = None) -> Optional[str]:
        """
        Validate trading symbol format
        
        Args:
            value: Symbol string to validate
            default: Default value if invalid
            
        Returns:
            Validated symbol or default
        """
        if value is None:
            return default
        
        str_value = str(value).upper().strip()
        
        if InputValidator.SYMBOL_PATTERN.match(str_value):
            return str_value
        
        logger.warning(f"Invalid symbol format '{value}', using default {default}")
        return default
    
    @staticmethod
    def validate_iso_date(value: Any) -> Optional[datetime]:
        """
        Validate and parse ISO date string
        
        Args:
            value: Date string in ISO format
            
        Returns:
            Parsed datetime or None if invalid
        """
        if value is None:
            return None
        
        str_value = str(value)
        
        try:
            # Handle both formats: with and without 'Z'
            dt = datetime.fromisoformat(str_value.replace('Z', '+00:00'))
            return dt
        except (ValueError, AttributeError) as e:
            logger.warning(f"Invalid ISO date '{value}': {e}")
            return None
    
    @staticmethod
    def sanitize_string(
        value: Any,
        max_length: int = 255,
        allow_special_chars: bool = False
    ) -> Optional[str]:
        """
        Sanitize string input
        
        Args:
            value: String to sanitize
            max_length: Maximum allowed length
            allow_special_chars: Whether to allow special characters
            
        Returns:
            Sanitized string or None
        """
        if value is None:
            return None
        
        str_value = str(value).strip()
        
        # Limit length
        if len(str_value) > max_length:
            logger.warning(f"String too long ({len(str_value)} chars), truncating to {max_length}")
            str_value = str_value[:max_length]
        
        # Remove potentially dangerous characters if not allowed
        if not allow_special_chars:
            # Remove SQL injection attempts
            dangerous_patterns = [
                r"';", r'";', r'--', r'/\*', r'\*/', 
                r'xp_', r'sp_', r'DROP\s+TABLE', r'DELETE\s+FROM',
                r'INSERT\s+INTO', r'UPDATE\s+.+SET', r'UNION\s+SELECT'
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, str_value, re.IGNORECASE):
                    logger.error(f"Potential SQL injection detected in input: {str_value}")
                    return None
        
        return str_value


# Convenience functions
def validate_signal_type(value: Any) -> Optional[str]:
    """Validate signal type (BUY/SELL/etc)"""
    return InputValidator.validate_enum(
        value, 
        InputValidator.ALLOWED_SIGNAL_TYPES,
        case_sensitive=False
    )


def validate_trade_status(value: Any) -> Optional[str]:
    """Validate trade status"""
    return InputValidator.validate_enum(
        value,
        InputValidator.ALLOWED_TRADE_STATUS,
        default='closed',
        case_sensitive=False
    )


def validate_timeframe(value: Any) -> Optional[str]:
    """Validate timeframe"""
    return InputValidator.validate_enum(
        value,
        InputValidator.ALLOWED_TIMEFRAMES,
        case_sensitive=False
    )


def validate_period(value: Any) -> Optional[str]:
    """Validate period"""
    return InputValidator.validate_enum(
        value,
        InputValidator.ALLOWED_PERIODS,
        default='all',
        case_sensitive=False
    )


def validate_decision_type(value: Any) -> Optional[str]:
    """Validate AI decision type"""
    return InputValidator.validate_enum(
        value,
        InputValidator.ALLOWED_DECISION_TYPES,
        case_sensitive=False
    )

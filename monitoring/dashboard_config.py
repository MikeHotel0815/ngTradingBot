"""
Dashboard Configuration
Central configuration for all dashboard components
"""

from dataclasses import dataclass
from typing import Dict, List

@dataclass
class DashboardConfig:
    """Configuration for dashboard components"""

    # Update intervals (seconds)
    WEB_UPDATE_INTERVAL: int = 15
    TELEGRAM_LIGHTWEIGHT_INTERVAL: int = 14400  # 4 hours
    TELEGRAM_FULL_INTERVAL: int = 86400  # 24 hours
    TERMINAL_UPDATE_INTERVAL: int = 5
    CHART_GENERATION_INTERVAL: int = 3600  # 1 hour

    # Alert thresholds
    DRAWDOWN_WARNING_THRESHOLD: float = -20.0  # EUR
    DRAWDOWN_CRITICAL_THRESHOLD: float = -30.0  # EUR
    DRAWDOWN_EMERGENCY_THRESHOLD: float = -50.0  # EUR
    MAX_POSITION_WARNING_PCT: float = 0.8  # 80% of max
    LOW_WIN_RATE_THRESHOLD: float = 50.0  # %

    # Chart settings
    CHART_DPI: int = 100
    CHART_FIGSIZE: tuple = (12, 6)
    CHART_STYLE: str = 'dark_background'
    CHART_COLORS: Dict[str, str] = None

    # Feature toggles
    ENABLE_WEB_DASHBOARD: bool = True
    ENABLE_TELEGRAM_REPORTS: bool = True
    ENABLE_TERMINAL_DASHBOARD: bool = True
    ENABLE_CHART_GENERATION: bool = True
    ENABLE_SHADOW_TRADING_SECTION: bool = True

    # Shadow trading re-activation criteria (XAGUSD)
    SHADOW_MIN_TRADES: int = 100
    SHADOW_MIN_WIN_RATE: float = 70.0  # %
    SHADOW_MIN_PROFIT: float = 0.0  # EUR

    # Performance metrics
    ROLLING_WINDOW_TRADES: int = 20
    SIGNAL_LATENCY_TARGET_MS: int = 200

    # Database account ID (default)
    DEFAULT_ACCOUNT_ID: int = 3

    def __post_init__(self):
        if self.CHART_COLORS is None:
            self.CHART_COLORS = {
                'profit': '#4CAF50',
                'loss': '#F44336',
                'neutral': '#888888',
                'buy': '#2196F3',
                'sell': '#FF9800',
                'background': '#1a1a1a',
                'grid': '#333333',
                'text': '#e0e0e0'
            }


# Singleton instance
_config = DashboardConfig()

def get_config() -> DashboardConfig:
    """Get dashboard configuration"""
    return _config

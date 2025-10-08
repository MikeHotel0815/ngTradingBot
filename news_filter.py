"""
News & Economic Calendar Filter

Prevents trading during high-impact news events:
1. Fetches economic calendar from API (e.g., Forex Factory, Investing.com)
2. Pauses trading X minutes before/after high-impact events
3. Configurable per event impact level (HIGH, MEDIUM, LOW)
4. Logs all trading pauses via AI Decision Log

Configuration:
- pause_before_minutes: Minutes to pause before event (default: 15)
- pause_after_minutes: Minutes to pause after event (default: 15)
- impact_levels: Which impact levels to filter ['HIGH', 'MEDIUM', 'LOW']
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from database import get_db, Base
from ai_decision_log import log_risk_limit

logger = logging.getLogger(__name__)


class NewsEvent(Base):
    """Economic Calendar Event"""
    __tablename__ = 'news_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_time = Column(DateTime, nullable=False, index=True)
    currency = Column(String(3), nullable=False)  # USD, EUR, GBP, etc.
    event_name = Column(String(200), nullable=False)
    impact = Column(String(10), nullable=False)  # HIGH, MEDIUM, LOW
    previous = Column(String(50))
    forecast = Column(String(50))
    actual = Column(String(50))
    fetched_at = Column(DateTime, default=datetime.utcnow)


class NewsFilterConfig(Base):
    """News Filter Configuration"""
    __tablename__ = 'news_filter_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, unique=True)

    enabled = Column(Boolean, default=True)
    pause_before_minutes = Column(Integer, default=15)
    pause_after_minutes = Column(Integer, default=15)

    # Impact levels to filter (comma-separated: HIGH,MEDIUM)
    filter_impact_levels = Column(String(50), default='HIGH')

    # Currencies to monitor (comma-separated: USD,EUR,GBP)
    filter_currencies = Column(String(100), default='USD,EUR,GBP,JPY')


class NewsFilter:
    """News & Economic Calendar Filter"""

    # Forex Factory API (alternative: use web scraping or paid API)
    # For production: use ForexFactory API, Investing.com API, or Econoday
    CALENDAR_API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, account_id: int):
        self.account_id = account_id
        self._ensure_table_exists()
        self._ensure_config_exists()

    def _ensure_table_exists(self):
        """Create tables if not exists"""
        import os
        from sqlalchemy import create_engine

        # Use environment variable or default to Docker service name
        db_host = os.getenv('DB_HOST', 'postgres')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'ngtradingbot')
        db_user = os.getenv('DB_USER', 'trader')
        db_pass = os.getenv('DB_PASSWORD', 'tradingbot_secret_2025')

        database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_engine(database_url)
        Base.metadata.create_all(engine, tables=[NewsEvent.__table__, NewsFilterConfig.__table__])

    def _ensure_config_exists(self):
        """Ensure config exists for account"""
        db = next(get_db())

        try:
            config = db.query(NewsFilterConfig).filter_by(
                account_id=self.account_id
            ).first()

            if not config:
                config = NewsFilterConfig(
                    account_id=self.account_id,
                    enabled=True,
                    pause_before_minutes=15,
                    pause_after_minutes=15,
                    filter_impact_levels='HIGH',
                    filter_currencies='USD,EUR,GBP,JPY'
                )
                db.add(config)
                db.commit()
                logger.info(f"✅ Created news filter config for account {self.account_id}")

        except Exception as e:
            logger.error(f"Error ensuring news filter config: {e}")
            db.rollback()
        finally:
            db.close()

    def fetch_and_store_events(self) -> int:
        """
        Fetch economic calendar events and store in database

        Returns:
            Number of events stored
        """
        db = next(get_db())

        try:
            # Fetch from Forex Factory (free API)
            response = requests.get(self.CALENDAR_API_URL, timeout=10)

            if response.status_code != 200:
                logger.error(f"Failed to fetch news calendar: {response.status_code}")
                return 0

            events = response.json()
            stored_count = 0

            for event_data in events:
                try:
                    # Parse event
                    event_time = datetime.fromisoformat(event_data['date'].replace('Z', '+00:00'))

                    # Skip past events
                    if event_time < datetime.utcnow():
                        continue

                    # Check if already exists
                    existing = db.query(NewsEvent).filter_by(
                        event_time=event_time,
                        event_name=event_data['title']
                    ).first()

                    if existing:
                        continue

                    # Map impact
                    impact_map = {
                        'Non-Economic': 'LOW',
                        'Low Impact': 'LOW',
                        'Medium Impact': 'MEDIUM',
                        'High Impact': 'HIGH'
                    }
                    impact = impact_map.get(event_data.get('impact', ''), 'MEDIUM')

                    # Create event
                    news_event = NewsEvent(
                        event_time=event_time,
                        currency=event_data.get('country', 'USD'),
                        event_name=event_data['title'],
                        impact=impact,
                        previous=event_data.get('previous'),
                        forecast=event_data.get('forecast'),
                        actual=event_data.get('actual'),
                        fetched_at=datetime.utcnow()
                    )

                    db.add(news_event)
                    stored_count += 1

                except Exception as e:
                    logger.debug(f"Error parsing event: {e}")
                    continue

            db.commit()

            if stored_count > 0:
                logger.info(f"📰 Fetched {stored_count} news events")

            return stored_count

        except Exception as e:
            logger.error(f"Error fetching news events: {e}")
            return 0
        finally:
            db.close()

    def check_trading_allowed(self, symbol: str) -> Dict:
        """
        Check if trading is allowed based on upcoming news

        Args:
            symbol: Trading symbol (e.g., EURUSD, GBPUSD)

        Returns:
            Dict with:
                - allowed: bool
                - reason: str (if not allowed)
                - upcoming_event: Dict (if event nearby)
        """
        db = next(get_db())

        try:
            config = db.query(NewsFilterConfig).filter_by(
                account_id=self.account_id
            ).first()

            if not config or not config.enabled:
                return {'allowed': True}

            # Extract currencies from symbol
            symbol_currencies = self._extract_currencies_from_symbol(symbol)

            # Get filter settings
            filter_currencies = config.filter_currencies.split(',')
            filter_impacts = config.filter_impact_levels.split(',')

            # Time window to check
            now = datetime.utcnow()
            check_start = now - timedelta(minutes=config.pause_after_minutes)
            check_end = now + timedelta(minutes=config.pause_before_minutes)

            # Query upcoming events
            upcoming_events = db.query(NewsEvent).filter(
                NewsEvent.event_time >= check_start,
                NewsEvent.event_time <= check_end,
                NewsEvent.currency.in_(filter_currencies),
                NewsEvent.impact.in_(filter_impacts)
            ).all()

            # Filter events affecting this symbol
            for event in upcoming_events:
                if event.currency in symbol_currencies:
                    time_to_event = (event.event_time - now).total_seconds() / 60

                    # Event is upcoming
                    if time_to_event > 0:
                        reason = f"High-impact {event.currency} news in {int(time_to_event)}min: {event.event_name}"
                    else:
                        reason = f"High-impact {event.currency} news just occurred ({int(abs(time_to_event))}min ago): {event.event_name}"

                    # Log decision
                    log_risk_limit(
                        account_id=self.account_id,
                        limit_type='NEWS_PAUSE',
                        reason=reason,
                        details={
                            'symbol': symbol,
                            'event_name': event.event_name,
                            'event_time': event.event_time.isoformat(),
                            'event_currency': event.currency,
                            'event_impact': event.impact,
                            'time_to_event_minutes': time_to_event
                        }
                    )

                    return {
                        'allowed': False,
                        'reason': reason,
                        'upcoming_event': {
                            'name': event.event_name,
                            'time': event.event_time.isoformat(),
                            'currency': event.currency,
                            'impact': event.impact,
                            'minutes_to_event': int(time_to_event)
                        }
                    }

            return {'allowed': True}

        except Exception as e:
            logger.error(f"Error checking news filter: {e}")
            return {'allowed': True, 'error': str(e)}
        finally:
            db.close()

    def _extract_currencies_from_symbol(self, symbol: str) -> List[str]:
        """Extract currency codes from symbol (e.g., EURUSD -> ['EUR', 'USD'])"""
        # Remove common suffixes
        clean_symbol = symbol.replace('.c', '').replace('_', '')

        # Forex pairs
        if len(clean_symbol) == 6:
            return [clean_symbol[:3], clean_symbol[3:6]]

        # Crypto pairs
        if 'USD' in clean_symbol:
            return ['USD', clean_symbol.replace('USD', '')]

        # Commodities/Indices
        if clean_symbol.startswith('XAU'):
            return ['USD']  # Gold typically in USD
        if clean_symbol.startswith('US') or clean_symbol.startswith('DE'):
            return ['USD', 'EUR']

        return []

    def get_upcoming_events(self, hours: int = 24) -> List[Dict]:
        """Get upcoming high-impact events"""
        db = next(get_db())

        try:
            config = db.query(NewsFilterConfig).filter_by(
                account_id=self.account_id
            ).first()

            if not config:
                return []

            filter_impacts = config.filter_impact_levels.split(',')
            filter_currencies = config.filter_currencies.split(',')

            cutoff = datetime.utcnow() + timedelta(hours=hours)

            events = db.query(NewsEvent).filter(
                NewsEvent.event_time >= datetime.utcnow(),
                NewsEvent.event_time <= cutoff,
                NewsEvent.currency.in_(filter_currencies),
                NewsEvent.impact.in_(filter_impacts)
            ).order_by(NewsEvent.event_time).all()

            return [{
                'time': e.event_time.isoformat(),
                'currency': e.currency,
                'name': e.event_name,
                'impact': e.impact,
                'forecast': e.forecast,
                'previous': e.previous
            } for e in events]

        except Exception as e:
            logger.error(f"Error getting upcoming events: {e}")
            return []
        finally:
            db.close()

    def update_config(self, **kwargs):
        """Update news filter configuration"""
        db = next(get_db())

        try:
            config = db.query(NewsFilterConfig).filter_by(
                account_id=self.account_id
            ).first()

            if not config:
                self._ensure_config_exists()
                config = db.query(NewsFilterConfig).filter_by(
                    account_id=self.account_id
                ).first()

            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            db.commit()
            logger.info(f"✅ Updated news filter config for account {self.account_id}")

        except Exception as e:
            logger.error(f"Error updating news filter config: {e}")
            db.rollback()
        finally:
            db.close()


def get_news_filter(account_id: int) -> NewsFilter:
    """Get news filter instance"""
    return NewsFilter(account_id)

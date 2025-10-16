#!/usr/bin/env python3
"""
Connection Watchdog for ngTradingBot
Monitors MT5 connection health and sends alerts when connection is lost
"""

import logging
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, Set
import pytz
from database import ScopedSession
from models import Account, Tick
from telegram_notifier import get_telegram_notifier
from trading_hours_config import is_market_open, get_next_open_time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConnectionWatchdog:
    """Monitors MT5 connection health via heartbeats and tick flow"""

    def __init__(self):
        self.check_interval = 60  # Check every 60 seconds
        self.heartbeat_timeout = 300  # 5 minutes without heartbeat = connection lost
        self.tick_timeout = 180  # 3 minutes without ticks = data flow problem
        self.running = False

        # Track connection states
        self.connection_states = {}  # account_id -> {'online': bool, 'alerted': bool}
        self.tick_flow_states = {}  # symbol -> {'flowing': bool, 'alerted': bool}

        # Telegram notifier
        self.telegram = get_telegram_notifier()

        logger.info("Connection Watchdog initialized")

    def start(self):
        """Start the watchdog in background thread"""
        if self.running:
            logger.warning("Watchdog already running")
            return

        self.running = True
        thread = Thread(target=self._run, daemon=True)
        thread.start()
        logger.info("Connection Watchdog started")

    def stop(self):
        """Stop the watchdog"""
        self.running = False
        logger.info("Connection Watchdog stopped")

    def _run(self):
        """Main watchdog loop"""
        logger.info("Watchdog monitoring loop started")

        while self.running:
            try:
                self._check_heartbeats()
                self._check_tick_flow()

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Error in watchdog loop: {e}", exc_info=True)
                time.sleep(self.check_interval)

    def _check_heartbeats(self):
        """Check MT5 account heartbeats"""
        db = ScopedSession()
        try:
            now = datetime.utcnow()
            accounts = db.query(Account).all()

            for account in accounts:
                account_id = account.id
                mt5_number = account.mt5_account_number

                # Initialize state if not exists
                if account_id not in self.connection_states:
                    self.connection_states[account_id] = {
                        'online': True,
                        'alerted': False,
                        'last_offline': None
                    }

                state = self.connection_states[account_id]

                # Check heartbeat age
                if account.last_heartbeat:
                    age = (now - account.last_heartbeat).total_seconds()

                    # Connection is healthy
                    if age < self.heartbeat_timeout:
                        if not state['online']:
                            # Connection was restored!
                            offline_duration = (now - state['last_offline']).total_seconds()

                            logger.info(
                                f"✅ MT5 #{mt5_number} CONNECTION RESTORED "
                                f"(was offline for {offline_duration:.0f}s)"
                            )

                            self.telegram.send_connection_restored(
                                mt5_number,
                                int(offline_duration)
                            )

                            state['online'] = True
                            state['alerted'] = False
                            state['last_offline'] = None

                    # Connection is lost
                    else:
                        if state['online']:
                            # Connection just lost
                            logger.warning(
                                f"⚠️ MT5 #{mt5_number} CONNECTION LOST "
                                f"(last heartbeat {age:.0f}s ago)"
                            )

                            state['online'] = False
                            state['last_offline'] = now

                        # Send alert only once
                        if not state['alerted']:
                            logger.error(
                                f"🚨 MT5 #{mt5_number} OFFLINE FOR {age:.0f}s - SENDING ALERT"
                            )

                            self.telegram.send_connection_alert(
                                mt5_number,
                                account.last_heartbeat,
                                int(age)
                            )

                            state['alerted'] = True

                            # Pause auto-trading for this account
                            self._pause_auto_trading(account_id, f"Connection lost for {age:.0f}s")

                else:
                    # No heartbeat ever received
                    logger.warning(f"MT5 #{mt5_number} has never sent a heartbeat")

        except Exception as e:
            logger.error(f"Error checking heartbeats: {e}", exc_info=True)
        finally:
            db.close()

    def _check_tick_flow(self):
        """Check if tick data is flowing for subscribed symbols"""
        db = ScopedSession()
        try:
            from models import SubscribedSymbol

            now = datetime.utcnow()

            # Get subscribed symbols for active accounts
            subscribed = db.query(SubscribedSymbol).filter_by(active=True).all()

            for sub in subscribed:
                symbol = sub.symbol

                # Initialize state
                if symbol not in self.tick_flow_states:
                    self.tick_flow_states[symbol] = {
                        'flowing': True,
                        'alerted': False
                    }

                state = self.tick_flow_states[symbol]

                # Get latest tick (ticks are now global, no account_id)
                latest_tick = db.query(Tick).filter_by(
                    symbol=symbol
                ).order_by(Tick.timestamp.desc()).first()

                if latest_tick:
                    # Ensure timezone aware for market hours check
                    tick_time = latest_tick.timestamp
                    if tick_time.tzinfo is None:
                        tick_time = pytz.UTC.localize(tick_time)

                    age = (now - tick_time).total_seconds()

                    # Check if market should be open right now
                    now_utc = pytz.UTC.localize(now) if now.tzinfo is None else now
                    market_open, close_reason = is_market_open(symbol, now_utc)

                    # Tick flow is healthy
                    if age < self.tick_timeout:
                        if not state['flowing']:
                            logger.info(f"✅ Tick flow restored for {symbol}")
                            state['flowing'] = True
                            state['alerted'] = False

                    # Tick flow is stale
                    else:
                        if state['flowing']:
                            if market_open:
                                # Market should be open - this is a problem
                                logger.warning(
                                    f"⚠️ No ticks for {symbol} for {age:.0f}s (market should be open)"
                                )
                            else:
                                # Market is closed - this is normal
                                logger.debug(
                                    f"ℹ️  No ticks for {symbol} for {age:.0f}s ({close_reason})"
                                )
                            state['flowing'] = False

                        # Send alert only if market should be open
                        if not state['alerted'] and age > 600 and market_open:  # 10 minutes + market open
                            logger.error(f"🚨 {symbol} tick data STALE for {age:.0f}s (MARKET SHOULD BE OPEN)")

                            next_open = get_next_open_time(symbol, now_utc)

                            self.telegram.send_alert(
                                title=f"{symbol} Data Flow Problem",
                                message=f"⚠️ No tick data received for {age // 60:.0f} minutes.\n\n"
                                       f"Market should currently be OPEN.\n"
                                       f"This may indicate a connection or data feed issue.",
                                level='WARNING'
                            )

                            state['alerted'] = True
                        elif not state['alerted'] and age > 600 and not market_open:
                            # Market is closed - just log, don't alert
                            logger.info(
                                f"ℹ️  {symbol} no ticks for {age // 60:.0f} min - Market closed: {close_reason}"
                            )
                            # Mark as alerted to prevent repeated logging
                            state['alerted'] = True

        except Exception as e:
            logger.error(f"Error checking tick flow: {e}", exc_info=True)
        finally:
            db.close()

    def _pause_auto_trading(self, account_id: int, reason: str):
        """Pause auto-trading for an account"""
        from models import GlobalSettings

        db = ScopedSession()
        try:
            settings = GlobalSettings.get_settings(db)

            if settings.autotrade_enabled:
                logger.warning(f"⏸️  PAUSING AUTO-TRADING: {reason}")

                # Note: This pauses globally
                # In production, you might want per-account control
                settings.autotrade_enabled = False
                db.commit()

                self.telegram.send_alert(
                    title="Auto-Trading Paused",
                    message=f"Auto-trading has been paused due to:\n\n{reason}\n\n"
                           f"Existing positions will continue to be monitored.\n"
                           f"Please check MT5 connection and resume manually.",
                    level='CRITICAL'
                )

        except Exception as e:
            logger.error(f"Error pausing auto-trading: {e}")
            db.rollback()
        finally:
            db.close()

    def get_status(self) -> Dict:
        """Get current watchdog status"""
        return {
            'running': self.running,
            'connection_states': self.connection_states,
            'tick_flow_states': self.tick_flow_states,
            'heartbeat_timeout': self.heartbeat_timeout,
            'tick_timeout': self.tick_timeout
        }


# Singleton instance
_watchdog_instance = None


def get_connection_watchdog() -> ConnectionWatchdog:
    """Get or create connection watchdog singleton"""
    global _watchdog_instance

    if _watchdog_instance is None:
        _watchdog_instance = ConnectionWatchdog()

    return _watchdog_instance


if __name__ == '__main__':
    # Test the watchdog
    print("Starting Connection Watchdog test...")

    watchdog = get_connection_watchdog()
    watchdog.start()

    print("Watchdog running. Press Ctrl+C to stop...")

    try:
        while True:
            time.sleep(10)
            status = watchdog.get_status()
            print(f"\nStatus: {status}")
    except KeyboardInterrupt:
        print("\nStopping watchdog...")
        watchdog.stop()
        print("Done!")

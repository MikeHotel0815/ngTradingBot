"""
SL Hit Protection - Automatische Pause nach mehreren Stop-Loss Hits

Verhindert "Revenge Trading" durch:
- Cooldown nach 2 SL-Hits innerhalb von 4 Stunden
- Symbol-spezifische Pausierung
- Automatische Wiederaktivierung nach Cooldown-Period
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy.orm import Session
from models import Trade
from sqlalchemy import and_

logger = logging.getLogger(__name__)


class SLHitProtection:
    """Schutz vor aufeinanderfolgenden SL-Hits"""

    def __init__(self):
        self.symbol_cooldowns: Dict[str, datetime] = {}

    def check_sl_hits(self, db: Session, account_id: int, symbol: str,
                      max_hits: int = 2, timeframe_hours: int = 4) -> Dict:
        """
        Prüfe ob Symbol pausiert werden sollte nach mehreren SL-Hits

        Args:
            db: Database session
            account_id: Account ID
            symbol: Symbol (z.B. 'XAUUSD')
            max_hits: Maximale SL-Hits bevor Pause (default: 2)
            timeframe_hours: Zeitfenster in Stunden (default: 4)

        Returns:
            Dict mit 'should_pause', 'sl_hits_count', 'cooldown_until'
        """
        # Prüfe ob bereits in Cooldown
        if symbol in self.symbol_cooldowns:
            cooldown_until = self.symbol_cooldowns[symbol]
            if datetime.utcnow() < cooldown_until:
                remaining = (cooldown_until - datetime.utcnow()).total_seconds() / 60
                logger.warning(
                    f"🕐 {symbol} ist noch {remaining:.0f}min in Cooldown "
                    f"(bis {cooldown_until.strftime('%H:%M:%S')})"
                )
                return {
                    'should_pause': True,
                    'sl_hits_count': 0,
                    'cooldown_until': cooldown_until,
                    'reason': f'Symbol in Cooldown für {remaining:.0f} Minuten'
                }
            else:
                # Cooldown abgelaufen
                del self.symbol_cooldowns[symbol]
                logger.info(f"✅ {symbol} Cooldown beendet - Trading wieder aktiv")

        # Zähle SL-Hits im Zeitfenster
        cutoff_time = datetime.utcnow() - timedelta(hours=timeframe_hours)

        sl_hits = db.query(Trade).filter(
            and_(
                Trade.account_id == account_id,
                Trade.symbol == symbol,
                Trade.status == 'closed',
                Trade.close_reason == 'SL_HIT',
                Trade.close_time >= cutoff_time
            )
        ).count()

        logger.debug(f"📊 {symbol}: {sl_hits} SL-Hits in den letzten {timeframe_hours}h")

        if sl_hits >= max_hits:
            # Setze Cooldown
            cooldown_minutes = 60  # 1 Stunde Pause
            cooldown_until = datetime.utcnow() + timedelta(minutes=cooldown_minutes)
            self.symbol_cooldowns[symbol] = cooldown_until

            logger.warning(
                f"🚨 {symbol} PAUSIERT: {sl_hits} SL-Hits in {timeframe_hours}h! "
                f"Cooldown bis {cooldown_until.strftime('%H:%M:%S')} ({cooldown_minutes}min)"
            )

            return {
                'should_pause': True,
                'sl_hits_count': sl_hits,
                'cooldown_until': cooldown_until,
                'reason': f'{sl_hits} SL-Hits in {timeframe_hours}h - Automatische Pause'
            }

        return {
            'should_pause': False,
            'sl_hits_count': sl_hits,
            'cooldown_until': None,
            'reason': None
        }

    def is_symbol_paused(self, symbol: str) -> bool:
        """Prüfe ob Symbol aktuell pausiert ist"""
        if symbol in self.symbol_cooldowns:
            if datetime.utcnow() < self.symbol_cooldowns[symbol]:
                return True
            else:
                del self.symbol_cooldowns[symbol]
        return False

    def get_cooldown_remaining(self, symbol: str) -> Optional[float]:
        """Gibt verbleibende Cooldown-Zeit in Minuten zurück"""
        if symbol in self.symbol_cooldowns:
            cooldown_until = self.symbol_cooldowns[symbol]
            if datetime.utcnow() < cooldown_until:
                return (cooldown_until - datetime.utcnow()).total_seconds() / 60
            else:
                del self.symbol_cooldowns[symbol]
        return None

    def clear_cooldown(self, symbol: str):
        """Manuelles Entfernen des Cooldowns für ein Symbol"""
        if symbol in self.symbol_cooldowns:
            del self.symbol_cooldowns[symbol]
            logger.info(f"✅ {symbol} Cooldown manuell entfernt")

    def get_all_cooldowns(self) -> Dict[str, dict]:
        """Gibt alle aktiven Cooldowns zurück"""
        result = {}
        now = datetime.utcnow()

        for symbol, cooldown_until in list(self.symbol_cooldowns.items()):
            if now < cooldown_until:
                remaining_minutes = (cooldown_until - now).total_seconds() / 60
                result[symbol] = {
                    'cooldown_until': cooldown_until.isoformat(),
                    'remaining_minutes': round(remaining_minutes, 1)
                }
            else:
                del self.symbol_cooldowns[symbol]

        return result


# Global instance
_protection_instance: Optional[SLHitProtection] = None


def get_sl_hit_protection() -> SLHitProtection:
    """Get global SL hit protection instance"""
    global _protection_instance
    if _protection_instance is None:
        _protection_instance = SLHitProtection()
    return _protection_instance

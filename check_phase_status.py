#!/usr/bin/env python3
"""
Phase 2 Data Collection Status Monitor
Zeigt an, wann Phase 3 (Analyse) bereit ist

Usage:
    python check_phase_status.py
"""

from datetime import datetime, timedelta
from database import get_db
from models import Trade
from sqlalchemy import func, and_

def check_phase_2_status():
    """Prüft Status der Datensammlung (Phase 2)"""

    db = next(get_db())

    # Zeitpunkt des Quick Wins Deployments
    phase2_start = datetime(2025, 10, 25, 15, 16)  # UTC
    now = datetime.utcnow()
    hours_running = (now - phase2_start).total_seconds() / 3600

    print("=" * 70)
    print("📊 PHASE 2: DATA COLLECTION STATUS")
    print("=" * 70)
    print(f"Start: {phase2_start.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Jetzt: {now.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Laufzeit: {hours_running:.1f} Stunden ({hours_running/24:.1f} Tage)")
    print()

    # Zähle Trades mit vollständigen Daten (seit Phase 2)
    trades_with_data = db.query(Trade).filter(
        and_(
            Trade.created_at >= phase2_start,
            Trade.session.isnot(None),  # Hat Session-Tracking
        )
    ).count()

    # Zähle geschlossene Trades mit Metriken
    closed_with_metrics = db.query(Trade).filter(
        and_(
            Trade.created_at >= phase2_start,
            Trade.status == 'closed',
            Trade.session.isnot(None),
            Trade.risk_reward_realized.isnot(None),
            Trade.hold_duration_minutes.isnot(None),
            Trade.pips_captured.isnot(None)
        )
    ).count()

    # Offene Trades (noch keine Metriken)
    open_trades = db.query(Trade).filter(
        and_(
            Trade.created_at >= phase2_start,
            Trade.status == 'open'
        )
    ).count()

    # Ziel: 50-100 geschlossene Trades mit Daten
    target_min = 50
    target_max = 100

    progress_pct = min(100, (closed_with_metrics / target_min) * 100)

    print(f"📈 DATENSAMMLUNG:")
    print(f"   Total Trades (seit Phase 2): {trades_with_data}")
    print(f"   Geschlossen (mit Metriken):  {closed_with_metrics}")
    print(f"   Offen (Metriken folgen):     {open_trades}")
    print()
    print(f"🎯 ZIEL: {target_min}-{target_max} geschlossene Trades")
    print(f"   Progress: [{('█' * int(progress_pct/5)).ljust(20, '░')}] {progress_pct:.1f}%")
    print()

    # Berechne geschätzte Zeit bis Phase 3
    if closed_with_metrics > 0:
        hours_per_trade = hours_running / closed_with_metrics
        trades_needed = max(0, target_min - closed_with_metrics)
        hours_remaining = trades_needed * hours_per_trade
        eta = now + timedelta(hours=hours_remaining)

        print(f"⏱️  SCHÄTZUNG:")
        print(f"   Trades pro Stunde: {1/hours_per_trade:.1f}")
        print(f"   Noch benötigt: {trades_needed} Trades")
        print(f"   ETA für Phase 3: {eta.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"   (in {hours_remaining:.1f} Stunden / {hours_remaining/24:.1f} Tagen)")
        print()

    # Status-Bewertung
    if closed_with_metrics >= target_max:
        print("✅ STATUS: BEREIT FÜR PHASE 3!")
        print("   → Genug Daten gesammelt")
        print("   → Sage mir Bescheid, dann starte ich die Analyse")
        return "READY"
    elif closed_with_metrics >= target_min:
        print("⚠️  STATUS: MINIMUM ERREICHT")
        print("   → Basis-Analyse möglich")
        print("   → Mehr Daten = bessere Erkenntnisse")
        print(f"   → Optimal bei {target_max} Trades")
        return "MINIMUM_REACHED"
    else:
        print("⏳ STATUS: SAMMELT NOCH DATEN...")
        print(f"   → Noch {target_min - closed_with_metrics} Trades bis Minimum")
        print("   → Warte 2-3 Tage, dann melde dich")
        return "COLLECTING"

    print()

    # Session-Breakdown (wenn genug Daten)
    if closed_with_metrics >= 10:
        print("=" * 70)
        print("📊 SESSION BREAKDOWN (Preview):")
        print("=" * 70)

        session_stats = db.query(
            Trade.session,
            func.count(Trade.id).label('count'),
            func.avg(Trade.profit).label('avg_profit'),
            func.sum(func.case((Trade.profit > 0, 1), else_=0)).label('wins')
        ).filter(
            and_(
                Trade.created_at >= phase2_start,
                Trade.status == 'closed',
                Trade.session.isnot(None)
            )
        ).group_by(Trade.session).all()

        for stat in session_stats:
            session, count, avg_profit, wins = stat
            win_rate = (wins / count * 100) if count > 0 else 0
            print(f"   {session:8s}: {count:3d} Trades | WR: {win_rate:5.1f}% | Avg: €{avg_profit:.2f}")
        print()

    # Pausierte Symbole Status
    print("=" * 70)
    print("🚫 PAUSIERTE SYMBOLE:")
    print("=" * 70)

    from models import SymbolTradingConfig
    paused = db.query(SymbolTradingConfig).filter(
        SymbolTradingConfig.status == 'paused'
    ).all()

    for config in paused:
        print(f"   {config.symbol:8s} ({config.direction:4s}): {config.pause_reason[:50]}")

    print()
    print("=" * 70)

    db.close()

    return "COLLECTING"


if __name__ == "__main__":
    check_phase_2_status()

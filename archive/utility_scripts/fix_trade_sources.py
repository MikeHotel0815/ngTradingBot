#!/usr/bin/env python3
"""
Fix existing trades: Link them to commands and update source/signal_id
Dieses Script geht durch alle Trades ohne command_id und versucht sie mit Commands zu verlinken
"""

from database import SessionLocal
from models import Trade, Command
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_trade_sources():
    """Update existing trades with correct source and signal_id"""
    db = SessionLocal()
    try:
        # Get all trades without command_id
        trades_without_command = db.query(Trade).filter(
            Trade.command_id.is_(None),
            Trade.source == 'MT5'
        ).all()
        
        logger.info(f"Found {len(trades_without_command)} trades without command link")
        
        # Get all recent OPEN_TRADE commands
        commands = db.query(Command).filter(
            Command.command_type == 'OPEN_TRADE',
            Command.status == 'completed',
            Command.response.isnot(None)
        ).all()
        
        logger.info(f"Found {len(commands)} completed OPEN_TRADE commands")
        
        # Build ticket -> command mapping
        ticket_to_command = {}
        for cmd in commands:
            if cmd.response and 'ticket' in cmd.response:
                ticket = cmd.response['ticket']
                ticket_to_command[ticket] = cmd
        
        logger.info(f"Built mapping for {len(ticket_to_command)} tickets")
        
        # Update trades
        updated_count = 0
        autotrade_count = 0
        ea_command_count = 0
        
        for trade in trades_without_command:
            if trade.ticket in ticket_to_command:
                cmd = ticket_to_command[trade.ticket]
                signal_id = cmd.payload.get('signal_id') if cmd.payload else None
                
                # Update trade
                trade.command_id = cmd.id
                trade.signal_id = signal_id
                
                if signal_id:
                    trade.source = 'autotrade'
                    autotrade_count += 1
                    
                    # Update entry_reason
                    from models import TradingSignal
                    signal = db.query(TradingSignal).filter_by(id=signal_id).first()
                    if signal:
                        reason_parts = []
                        if signal.confidence:
                            reason_parts.append(f"{float(signal.confidence)*100:.0f}% confidence")
                        if signal.timeframe:
                            reason_parts.append(f"{signal.timeframe} timeframe")
                        
                        trade.entry_reason = " | ".join(reason_parts) if reason_parts else "Auto-traded signal"
                    else:
                        trade.entry_reason = "Auto-trade signal"
                else:
                    trade.source = 'ea_command'
                    trade.entry_reason = "EA Command"
                    ea_command_count += 1
                
                updated_count += 1
                logger.info(f"✅ Updated trade #{trade.ticket}: source={trade.source}, signal_id={signal_id}")
        
        # Commit changes
        db.commit()
        
        logger.info(f"\n" + "="*80)
        logger.info(f"UPDATE COMPLETE")
        logger.info(f"="*80)
        logger.info(f"Total updated: {updated_count}")
        logger.info(f"  - AutoTrade: {autotrade_count}")
        logger.info(f"  - EA Command: {ea_command_count}")
        logger.info(f"  - Still MT5: {len(trades_without_command) - updated_count}")
        
        return updated_count
        
    except Exception as e:
        logger.error(f"Error fixing trade sources: {e}", exc_info=True)
        db.rollback()
        return 0
    finally:
        db.close()

if __name__ == '__main__':
    print("🔧 Fixing trade sources...")
    count = fix_trade_sources()
    print(f"\n✅ Fixed {count} trades")

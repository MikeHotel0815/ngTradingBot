"""
MFE/MAE Tracking Worker
Maximum Favorable Excursion / Maximum Adverse Excursion
Tracks the maximum profit and maximum drawdown during each open trade
"""

import logging
import time
from datetime import datetime
from database import ScopedSession
from models import Trade, Tick
from market_context_helper import calculate_pips

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MFEMAETracker:
    """Tracks Maximum Favorable/Adverse Excursion for all open trades"""
    
    def __init__(self):
        self.name = "MFE/MAE Tracker"
        self.interval = 10  # Update every 10 seconds
        self.last_update = {}  # Track last update time per trade
    
    def run(self):
        """Main loop - update MFE/MAE for all open trades"""
        logger.info(f"🚀 {self.name} started (interval: {self.interval}s)")
        
        while True:
            try:
                self.update_all_trades()
                time.sleep(self.interval)
            except KeyboardInterrupt:
                logger.info(f"⛔ {self.name} stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Error in {self.name}: {e}", exc_info=True)
                time.sleep(self.interval)
    
    def update_all_trades(self):
        """Update MFE/MAE for all open trades"""
        db = ScopedSession()
        try:
            # Get all open trades
            open_trades = db.query(Trade).filter_by(status='open').all()
            
            if not open_trades:
                return
            
            updated_count = 0
            
            for trade in open_trades:
                try:
                    updated = self.update_trade_mfe_mae(db, trade)
                    if updated:
                        updated_count += 1
                except Exception as e:
                    logger.error(f"Error updating MFE/MAE for trade #{trade.ticket}: {e}")
            
            if updated_count > 0:
                db.commit()
                logger.debug(f"📊 Updated MFE/MAE for {updated_count}/{len(open_trades)} trades")
        
        except Exception as e:
            logger.error(f"Error in update_all_trades: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    
    def update_trade_mfe_mae(self, db, trade):
        """
        Update MFE/MAE for a single trade
        
        Args:
            db: Database session
            trade: Trade object
        
        Returns:
            bool: True if updated, False otherwise
        """
        # Get current price for this symbol
        current_tick = db.query(Tick).filter_by(
            symbol=trade.symbol
        ).order_by(Tick.timestamp.desc()).first()
        
        if not current_tick:
            return False
        
        # Use appropriate price (bid for BUY close, ask for SELL close)
        if trade.direction.upper() == 'BUY':
            current_price = float(current_tick.bid)
        else:  # SELL
            current_price = float(current_tick.ask)
        
        # Calculate current P&L in pips
        entry_price = float(trade.open_price)
        current_pnl_pips = calculate_pips(
            entry_price,
            current_price,
            trade.direction,
            trade.symbol
        )
        
        # Initialize MFE/MAE if not set
        if trade.max_favorable_excursion is None:
            trade.max_favorable_excursion = 0
        if trade.max_adverse_excursion is None:
            trade.max_adverse_excursion = 0
        
        mfe_before = float(trade.max_favorable_excursion)
        mae_before = float(trade.max_adverse_excursion)
        
        updated = False
        
        # Update MFE (max profit)
        if current_pnl_pips > trade.max_favorable_excursion:
            trade.max_favorable_excursion = current_pnl_pips
            updated = True
            logger.info(f"📈 MFE Update #{trade.ticket}: {mfe_before:.2f} -> {current_pnl_pips:.2f} pips")
        
        # Update MAE (max drawdown) - MAE is stored as negative value
        if current_pnl_pips < trade.max_adverse_excursion:
            trade.max_adverse_excursion = current_pnl_pips
            updated = True
            logger.info(f"📉 MAE Update #{trade.ticket}: {mae_before:.2f} -> {current_pnl_pips:.2f} pips")
        
        return updated


def main():
    """Entry point for MFE/MAE tracker worker"""
    tracker = MFEMAETracker()
    tracker.run()


if __name__ == '__main__':
    main()

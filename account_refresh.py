"""
Account Data Refresh for ngTradingBot
Requests fresh account data from EA on server startup or manually
"""

import logging
from datetime import datetime
from models import Account
from command_helper import create_command

logger = logging.getLogger(__name__)

def request_account_data_refresh(db, account_id=None):
    """
    Request account data refresh from EA
    
    This sends a GET_ACCOUNT_INFO command to the EA which will respond
    with current balance, equity, margin, etc. and trigger a heartbeat.
    
    Args:
        db: Database session
        account_id: Optional account ID. If None, refreshes all accounts.
    
    Returns:
        Number of refresh commands created
    """
    try:
        if account_id:
            accounts = db.query(Account).filter_by(id=account_id).all()
        else:
            accounts = db.query(Account).all()
        
        if not accounts:
            logger.warning("No accounts found for refresh")
            return 0
        
        count = 0
        for account in accounts:
            # Create GET_ACCOUNT_INFO command
            # This will trigger the EA to send back current account data
            command = create_command(
                db=db,
                account_id=account.id,
                command_type='GET_ACCOUNT_INFO',
                payload={},
                push_to_redis=True
            )
            
            logger.info(f"✅ Requested account data refresh for account {account.mt5_account_number} (command {command.id})")
            count += 1
        
        return count
        
    except Exception as e:
        logger.error(f"Error requesting account data refresh: {e}")
        return 0


def schedule_periodic_refresh(interval=300):
    """
    Schedule periodic account data refresh (default: every 5 minutes)
    
    Args:
        interval: Refresh interval in seconds (default 300 = 5 minutes)
    """
    import threading
    import time
    from database import ScopedSession
    
    def refresh_job():
        # Wait for the interval BEFORE the first execution
        # to avoid immediate refresh after startup
        time.sleep(interval)
        
        while True:
            try:
                db = ScopedSession()
                try:
                    count = request_account_data_refresh(db)
                    if count > 0:
                        logger.info(f"🔄 Periodic account refresh: {count} accounts updated")
                finally:
                    db.close()
                    
                # Wait for next interval
                time.sleep(interval)
                    
            except Exception as e:
                logger.error(f"Error in periodic refresh job: {e}")
                time.sleep(60)  # Wait 1 minute on error before retry
    
    thread = threading.Thread(target=refresh_job, daemon=True)
    thread.start()
    logger.info(f"📅 Periodic account refresh scheduled (every {interval}s)")

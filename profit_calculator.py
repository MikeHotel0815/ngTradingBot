"""
Profit Calculator for ngTradingBot
Calculates accurate profits excluding deposits/withdrawals
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from models import AccountTransaction

logger = logging.getLogger(__name__)

def get_deposits_withdrawals_sum(db, account_id, since_date):
    """
    Calculate sum of deposits and withdrawals since a given date
    
    Args:
        db: Database session
        account_id: Account ID
        since_date: Calculate from this date onwards
    
    Returns:
        Decimal: Total deposits (positive) + withdrawals (negative)
    """
    try:
        transactions = db.query(AccountTransaction).filter(
            AccountTransaction.account_id == account_id,
            AccountTransaction.timestamp >= since_date,
            AccountTransaction.transaction_type.in_(['BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'CREDIT'])
        ).all()
        
        total = Decimal('0.0')
        for trans in transactions:
            # BALANCE/DEPOSIT = money in (positive)
            # WITHDRAWAL = money out (negative, already negative in DB)
            total += Decimal(str(trans.amount))
        
        return total
        
    except Exception as e:
        logger.error(f"Error calculating deposits/withdrawals: {e}")
        return Decimal('0.0')


def calculate_corrected_profits(db, account_id, raw_profit_today, raw_profit_week, raw_profit_month, raw_profit_year):
    """
    Calculate corrected profits by subtracting deposits/withdrawals
    
    Args:
        db: Database session
        account_id: Account ID
        raw_profit_today: Raw profit from EA (includes deposits)
        raw_profit_week: Raw week profit from EA
        raw_profit_month: Raw month profit from EA
        raw_profit_year: Raw year profit from EA
    
    Returns:
        tuple: (corrected_today, corrected_week, corrected_month, corrected_year)
    """
    now = datetime.utcnow()
    
    # Calculate start of periods
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    
    # Get deposits/withdrawals for each period
    deposits_today = get_deposits_withdrawals_sum(db, account_id, today_start)
    deposits_week = get_deposits_withdrawals_sum(db, account_id, week_start)
    deposits_month = get_deposits_withdrawals_sum(db, account_id, month_start)
    deposits_year = get_deposits_withdrawals_sum(db, account_id, year_start)
    
    # Subtract deposits from raw profits
    corrected_today = float(Decimal(str(raw_profit_today or 0)) - deposits_today)
    corrected_week = float(Decimal(str(raw_profit_week or 0)) - deposits_week)
    corrected_month = float(Decimal(str(raw_profit_month or 0)) - deposits_month)
    corrected_year = float(Decimal(str(raw_profit_year or 0)) - deposits_year)
    
    logger.debug(f"Profit correction for account {account_id}:")
    logger.debug(f"  Today: {raw_profit_today} - {deposits_today} = {corrected_today}")
    logger.debug(f"  Week: {raw_profit_week} - {deposits_week} = {corrected_week}")
    logger.debug(f"  Month: {raw_profit_month} - {deposits_month} = {corrected_month}")
    logger.debug(f"  Year: {raw_profit_year} - {deposits_year} = {corrected_year}")
    
    return corrected_today, corrected_week, corrected_month, corrected_year


def get_initial_balance(db, account_id):
    """
    Get the initial balance for an account (first deposit/balance transaction)
    
    Args:
        db: Database session
        account_id: Account ID
    
    Returns:
        Decimal: Initial balance or 0
    """
    try:
        first_trans = db.query(AccountTransaction).filter(
            AccountTransaction.account_id == account_id,
            AccountTransaction.transaction_type.in_(['BALANCE', 'DEPOSIT'])
        ).order_by(AccountTransaction.timestamp.asc()).first()
        
        if first_trans:
            return Decimal(str(first_trans.amount))
        return Decimal('0.0')
        
    except Exception as e:
        logger.error(f"Error getting initial balance: {e}")
        return Decimal('0.0')

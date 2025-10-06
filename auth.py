"""
Authentication utilities
"""

from functools import wraps
from flask import request, jsonify
from models import Account
from database import ScopedSession
import logging

logger = logging.getLogger(__name__)


def require_api_key(f):
    """
    Decorator to require API key authentication
    Expects: account (int) and api_key (string) in request JSON OR X-API-Key header
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.get_json()

        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        account_number = data.get('account')
        api_key = data.get('api_key')

        # Check for API key in header if not in body
        if not api_key:
            api_key = request.headers.get('X-API-Key')

        if not account_number or not api_key:
            return jsonify({'status': 'error', 'message': 'Missing account or api_key'}), 401

        # Verify API key
        db = ScopedSession()
        try:
            account = db.query(Account).filter_by(
                mt5_account_number=account_number,
                api_key=api_key
            ).first()

            if not account:
                logger.warning(f"Invalid API key attempt for account {account_number}")
                return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 403

            # Pass account object to the route
            kwargs['account'] = account
            kwargs['db'] = db

            return f(*args, **kwargs)
        finally:
            db.close()

    return decorated_function


def get_or_create_account(db, mt5_account_number, broker):
    """
    Get existing account or create new one with API key
    Returns: (account, api_key, is_new)
    """
    account = db.query(Account).filter_by(mt5_account_number=mt5_account_number).first()

    if account:
        # Existing account
        return account, account.api_key, False
    else:
        # Create new account
        api_key = Account.generate_api_key()
        account = Account(
            mt5_account_number=mt5_account_number,
            api_key=api_key,
            broker=broker
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        logger.info(f"New account created: {mt5_account_number} ({broker})")
        return account, api_key, True

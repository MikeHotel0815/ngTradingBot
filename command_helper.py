"""
Command Helper for ngTradingBot
Handles command creation with Redis + PostgreSQL
"""

import uuid
from datetime import datetime
import logging
from models import Command
from redis_client import get_redis

logger = logging.getLogger(__name__)

def create_command(db, account_id, command_type, payload, push_to_redis=True):
    """
    Create command in PostgreSQL and optionally push to Redis queue

    Args:
        db: Database session
        account_id: Account ID
        command_type: Command type (OPEN_TRADE, CLOSE_TRADE, etc.)
        payload: Command payload dict
        push_to_redis: If True, also push to Redis for instant delivery

    Returns:
        Command object
    """
    # Generate UUID
    command_id = str(uuid.uuid4())

    # Create command in PostgreSQL
    # If pushing to Redis, set status to 'executing' immediately to avoid double-push
    initial_status = 'executing' if push_to_redis else 'pending'

    command = Command(
        id=command_id,
        account_id=account_id,
        command_type=command_type,
        status=initial_status,
        payload=payload,
        created_at=datetime.utcnow()
    )
    db.add(command)
    db.commit()

    logger.info(f"Created command {command_id} type={command_type} for account {account_id}")

    # Push to Redis for instant delivery
    if push_to_redis:
        try:
            redis = get_redis()

            # Flatten command for EA parsing
            cmd_dict = {
                'id': command_id,
                'type': command_type
            }

            # Add payload fields directly
            if payload:
                for key, value in payload.items():
                    cmd_dict[key] = value

            # Push to Redis queue
            redis.push_command(account_id, cmd_dict)

            logger.info(f"Pushed command {command_id} to Redis queue for instant delivery")
        except Exception as e:
            logger.error(f"Failed to push command to Redis: {e}")
            # Continue - command is still in PostgreSQL as fallback

    return command


def update_command_status(db, command_id, status, response=None):
    """
    Update command status and response

    Args:
        db: Database session
        command_id: Command ID
        status: New status (pending, executing, completed, failed)
        response: Response dict (optional)
    """
    command = db.query(Command).filter_by(id=command_id).first()

    if not command:
        logger.error(f"Command {command_id} not found")
        return False

    command.status = status
    if response:
        command.response = response
    command.updated_at = datetime.utcnow()

    db.commit()

    logger.info(f"Updated command {command_id} status={status}")

    # Publish update via Redis Pub/Sub for WebSocket
    try:
        redis = get_redis()
        redis.publish_command_response(command_id, {
            'command_id': command_id,
            'status': status,
            'response': response,
            'updated_at': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to publish command update: {e}")

    return True

#!/usr/bin/env python3
"""
Add database indexes for performance optimization
Run this script to add missing indexes on existing tables
"""

from database import init_db, ScopedSession, engine
from sqlalchemy import text, Index
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_indexes():
    """Add missing indexes to improve query performance"""

    db = ScopedSession()

    try:
        # Initialize database schema first
        init_db()

        indexes_to_add = [
            # Ticks table - compound index for time-series queries
            ("idx_ticks_symbol_timestamp", "ticks", ["symbol", "timestamp DESC"]),
            ("idx_ticks_account_timestamp", "ticks", ["account_id", "timestamp DESC"]),

            # Pattern detections - compound indexes
            ("idx_patterns_symbol_detected", "pattern_detections", ["symbol", "detected_at DESC"]),
            ("idx_patterns_account_detected", "pattern_detections", ["account_id", "detected_at DESC"]),

            # Trading signals - time-based queries
            ("idx_signals_symbol_created", "trading_signals", ["symbol", "created_at DESC"]),
            ("idx_signals_account_created", "trading_signals", ["account_id", "created_at DESC"]),

            # OHLC data - already has unique index, add account-based
            ("idx_ohlc_account_timestamp", "ohlc_data", ["account_id", "timestamp DESC"]),

            # Logs - account-based queries
            ("idx_logs_account_timestamp", "logs", ["account_id", "timestamp DESC"]),

            # Trades - account-based queries
            ("idx_trades_account_opentime", "trades", ["account_id", "open_time DESC"]),
            ("idx_trades_account_closetime", "trades", ["account_id", "close_time DESC"]),

            # Commands - account and status
            ("idx_commands_account_status", "commands", ["account_id", "status"]),
        ]

        for index_name, table_name, columns in indexes_to_add:
            try:
                # Check if index exists
                check_sql = text(f"""
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = :index_name
                """)
                result = db.execute(check_sql, {"index_name": index_name}).fetchone()

                if result:
                    logger.info(f"Index {index_name} already exists, skipping")
                    continue

                # Create index
                columns_str = ", ".join(columns)
                create_sql = text(f"""
                    CREATE INDEX {index_name} ON {table_name} ({columns_str})
                """)

                logger.info(f"Creating index {index_name} on {table_name}({columns_str})")
                db.execute(create_sql)
                db.commit()
                logger.info(f"✓ Created index {index_name}")

            except Exception as e:
                logger.error(f"Error creating index {index_name}: {e}")
                db.rollback()

        logger.info("Index creation completed")

        # Show index statistics
        stats_sql = text("""
            SELECT
                schemaname,
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_stat_user_indexes
            WHERE schemaname = 'public'
            ORDER BY pg_relation_size(indexrelid) DESC
            LIMIT 20
        """)

        logger.info("\nTop 20 indexes by size:")
        result = db.execute(stats_sql)
        for row in result:
            logger.info(f"  {row[1]}.{row[2]}: {row[3]}")

    except Exception as e:
        logger.error(f"Error adding indexes: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    logger.info("Starting index creation...")
    add_indexes()
    logger.info("Done!")

"""add dynamic tp fields

Revision ID: add_dynamic_tp_001
Revises: 
Create Date: 2025-10-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_dynamic_tp_001'
down_revision = None  # Set this to your latest migration
branch_labels = None
depends_on = None


def upgrade():
    """Add original_tp and tp_extended_count fields to trades table"""
    
    # Add original_tp column (nullable, will be populated for new trades)
    op.add_column('trades', sa.Column('original_tp', sa.Numeric(precision=20, scale=5), nullable=True))
    
    # Add tp_extended_count column (default 0)
    op.add_column('trades', sa.Column('tp_extended_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Backfill original_tp with current tp for existing trades
    op.execute("""
        UPDATE trades 
        SET original_tp = tp 
        WHERE original_tp IS NULL AND tp IS NOT NULL
    """)


def downgrade():
    """Remove dynamic TP fields"""
    op.drop_column('trades', 'tp_extended_count')
    op.drop_column('trades', 'original_tp')

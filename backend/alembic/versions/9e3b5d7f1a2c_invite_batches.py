"""邀请码按批次管理

- 新建 invite_batches 表：一次生成的一批邀请码，带备注
- invite_codes 增加 batch_id（NOT NULL，FK→invite_batches）
- 已有邀请码按「创建人 + 创建时间」归批：同一次生成的码创建时间完全相同；备注为空

Revision ID: 9e3b5d7f1a2c
Revises: 7c2d4e6f8a1b
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e3b5d7f1a2c'
down_revision: Union[str, None] = '7c2d4e6f8a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('invite_batches',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('note', sa.String(length=100), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.add_column('invite_codes', sa.Column('batch_id', sa.BigInteger(), nullable=True))
    op.execute(
        "INSERT INTO invite_batches (note, created_by, created_at) "
        "SELECT '', created_by, created_at FROM invite_codes "
        "GROUP BY created_by, created_at ORDER BY MIN(id)"
    )
    op.execute(
        "UPDATE invite_codes c JOIN invite_batches b "
        "ON b.created_by = c.created_by AND b.created_at = c.created_at "
        "SET c.batch_id = b.id"
    )
    op.alter_column('invite_codes', 'batch_id', existing_type=sa.BigInteger(), nullable=False)
    op.create_index('ix_invite_codes_batch_id', 'invite_codes', ['batch_id'], unique=False)
    op.create_foreign_key('fk_invite_codes_batch_id', 'invite_codes', 'invite_batches', ['batch_id'], ['id'])


def downgrade() -> None:
    # 降级会丢失所有批次备注
    op.drop_constraint('fk_invite_codes_batch_id', 'invite_codes', type_='foreignkey')
    op.drop_index('ix_invite_codes_batch_id', table_name='invite_codes')
    op.drop_column('invite_codes', 'batch_id')
    op.drop_table('invite_batches')

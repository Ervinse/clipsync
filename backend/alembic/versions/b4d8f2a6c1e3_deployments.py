"""部署记录表

- 新建 deployments 表：后端启动时登记运行的版本（版本号、提交号、分支、构建时间），超管可写备注

Revision ID: b4d8f2a6c1e3
Revises: 9e3b5d7f1a2c
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d8f2a6c1e3'
down_revision: Union[str, None] = '9e3b5d7f1a2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('deployments',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('app_version', sa.String(length=128), nullable=False),
    sa.Column('commit_sha', sa.String(length=40), nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('built_at', sa.DateTime(), nullable=True),
    sa.Column('deployed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # 降级会丢失所有部署记录与备注
    op.drop_table('deployments')

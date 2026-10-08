"""clipboard content 改为 MEDIUMTEXT

TEXT 上限 64KB，而 ClipboardUpdate 允许 16MB（16777215 字符），超过 64KB 的文本写库会失败。
按 README 第 5 节的设计改为 MEDIUMTEXT（上限 16MB）。

Revision ID: 3f1c2a9d7b4e
Revises: 278c88a5f21f
Create Date: 2026-10-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = '3f1c2a9d7b4e'
down_revision: Union[str, None] = '278c88a5f21f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'clipboard', 'content',
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        'clipboard_history', 'content',
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # 注意：已有超过 64KB 的内容时，降级会失败或截断（取决于 sql_mode）
    op.alter_column(
        'clipboard_history', 'content',
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        'clipboard', 'content',
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
    )

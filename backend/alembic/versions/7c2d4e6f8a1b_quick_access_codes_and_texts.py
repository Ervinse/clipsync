"""快速访问码改为挂在内容上，新增文本栏目

- 删除 access_codes 表：访问码改为 clipboard / texts / files 上的 access_code + access_expires_at 两列
- clipboard 增加 version（保存冲突检测）
- 新建 texts 表（文本栏目，每人多条）

Revision ID: 7c2d4e6f8a1b
Revises: 3f1c2a9d7b4e
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = '7c2d4e6f8a1b'
down_revision: Union[str, None] = '3f1c2a9d7b4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_access_codes_code', table_name='access_codes')
    op.drop_table('access_codes')

    op.add_column('clipboard', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('clipboard', sa.Column('access_code', sa.String(length=32), nullable=True))
    op.add_column('clipboard', sa.Column('access_expires_at', sa.DateTime(), nullable=True))

    op.add_column('files', sa.Column('access_code', sa.String(length=32), nullable=True))
    op.add_column('files', sa.Column('access_expires_at', sa.DateTime(), nullable=True))
    op.create_index('ix_files_user_access_code', 'files', ['user_id', 'access_code'], unique=False)

    op.create_table('texts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('access_code', sa.String(length=32), nullable=True),
    sa.Column('access_expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_texts_user_access_code', 'texts', ['user_id', 'access_code'], unique=False)


def downgrade() -> None:
    # 降级会丢失文本栏目的全部内容与所有访问码
    op.drop_index('ix_texts_user_access_code', table_name='texts')
    op.drop_table('texts')

    op.drop_index('ix_files_user_access_code', table_name='files')
    op.drop_column('files', 'access_expires_at')
    op.drop_column('files', 'access_code')

    op.drop_column('clipboard', 'access_expires_at')
    op.drop_column('clipboard', 'access_code')
    op.drop_column('clipboard', 'version')

    op.create_table('access_codes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('target_type', sa.Enum('TEXT', 'FILE', name='accesscodetargettype'), nullable=False),
    sa.Column('file_id', sa.BigInteger(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('is_revoked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['files.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_access_codes_code', 'access_codes', ['code'], unique=True)

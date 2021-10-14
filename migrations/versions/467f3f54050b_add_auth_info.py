"""add auth info

Revision ID: 467f3f54050b
Revises: e79878137634
Create Date: 2021-10-14 13:08:48.909834

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '467f3f54050b'
down_revision = 'e79878137634'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('auth_info',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('auth_provider', sa.Enum('GOOGLE', 'VK', 'SNAPCHAT', 'APPLE_ID', name='authprovider'), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('users', sa.Column('auth_info_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(None, 'users', 'auth_info', ['auth_info_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'users', type_='foreignkey')
    op.drop_column('users', 'auth_info_id')
    op.drop_table('auth_info')
    # ### end Alembic commands ###

"""add account_status field to User

Revision ID: c5ff22481065
Revises: 9d8c960823ba
Create Date: 2022-01-18 17:03:03.230363

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c5ff22481065'
down_revision = '9d8c960823ba'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    enum_def = postgresql.ENUM('REGISTRATION', 'ACTIVE', 'DEACTIVATED',
                               name='account_status')
    enum_def.create(op.get_bind())
    op.add_column('users', sa.Column(
        'account_status',
        sa.Enum('REGISTRATION', 'ACTIVE', 'DEACTIVATED',
                name='account_status'), nullable=True))
    op.execute(text("UPDATE users SET account_status = 'ACTIVE'"))
    op.alter_column('users', 'account_status', nullable=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'account_status')
    enum_def = postgresql.ENUM('REGISTRATION', 'ACTIVE', 'DEACTIVATED',
                               name='account_status')
    enum_def.drop(op.get_bind())
    # ### end Alembic commands ###

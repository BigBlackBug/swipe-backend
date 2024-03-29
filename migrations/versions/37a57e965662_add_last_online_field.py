"""add last_online field

Revision ID: 37a57e965662
Revises: fdecaec44dc9
Create Date: 2021-11-29 15:53:53.261232

"""
import datetime

import sqlalchemy as sa
from alembic import op
# revision identifiers, used by Alembic.
from sqlalchemy import text

revision = '37a57e965662'
down_revision = 'fdecaec44dc9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('last_online', sa.DateTime()))
    op.execute(text("UPDATE users SET last_online = :d").bindparams(
        d=datetime.datetime.utcnow(), ))
    op.alter_column('users', 'last_online', nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'last_online')
    # ### end Alembic commands ###

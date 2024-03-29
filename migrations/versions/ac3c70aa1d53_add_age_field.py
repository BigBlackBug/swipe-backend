"""add age field

Revision ID: ac3c70aa1d53
Revises: f87217fd9f12
Create Date: 2021-11-27 19:48:27.071309

"""
import datetime

import sqlalchemy as sa
from alembic import op
# revision identifiers, used by Alembic.
from sqlalchemy import text

revision = 'ac3c70aa1d53'
down_revision = 'f87217fd9f12'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('age', sa.Integer(), nullable=True))
    op.execute(text("""
        UPDATE users 
        SET age = DATE_PART('year', AGE(CURRENT_DATE::date, date_of_birth::date))
    """))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'age')
    # ### end Alembic commands ###

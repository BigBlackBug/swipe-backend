"""add birth_date and zodic_sign fields

Revision ID: 535fab273fdd
Revises: 977a0e5f2b44
Create Date: 2021-10-15 16:51:56.402815

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '535fab273fdd'
down_revision = '977a0e5f2b44'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('date_of_birth', sa.Date(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'date_of_birth')
    # ### end Alembic commands ###

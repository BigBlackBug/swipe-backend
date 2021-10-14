"""update auth info

Revision ID: 977a0e5f2b44
Revises: 8384bea8614b
Create Date: 2021-10-14 16:10:09.989835

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '977a0e5f2b44'
down_revision = '8384bea8614b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('auth_info', 'access_token',
               existing_type=sa.VARCHAR(),
               nullable=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('auth_info', 'access_token',
               existing_type=sa.VARCHAR(),
               nullable=False)
    # ### end Alembic commands ###

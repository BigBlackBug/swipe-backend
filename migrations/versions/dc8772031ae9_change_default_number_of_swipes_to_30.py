"""change default number of swipes to 30

Revision ID: dc8772031ae9
Revises: e30e42ae38b4
Create Date: 2021-12-02 19:41:27.164808

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'dc8772031ae9'
down_revision = 'e30e42ae38b4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('users', 'swipes', default=30,
                    type_=sa.Integer, nullable=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###

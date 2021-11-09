"""add ChatStatus.OPENED

Revision ID: eb2655479cbf
Revises: 3d9a63ece08e
Create Date: 2021-11-09 13:22:45.743777

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'eb2655479cbf'
down_revision = '3d9a63ece08e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("""
        ALTER TYPE chatstatus ADD value 'OPENED' after 'ACCEPTED' 
    """)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # TODO gonna break
    # ### end Alembic commands ###

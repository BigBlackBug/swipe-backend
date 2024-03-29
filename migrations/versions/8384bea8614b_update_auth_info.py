"""update auth info

Revision ID: 8384bea8614b
Revises: 467f3f54050b
Create Date: 2021-10-14 16:01:22.518319

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '8384bea8614b'
down_revision = '467f3f54050b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('auth_info', sa.Column('access_token', sa.String(), nullable=False))
    op.add_column('auth_info', sa.Column('provider_user_id', sa.String(), nullable=False))
    op.drop_column('auth_info', 'payload')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('auth_info', sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False))
    op.drop_column('auth_info', 'provider_user_id')
    op.drop_column('auth_info', 'access_token')
    # ### end Alembic commands ###

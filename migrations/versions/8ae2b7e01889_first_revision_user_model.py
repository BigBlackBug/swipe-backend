"""first revision: User model

Revision ID: 8ae2b7e01889
Revises: 
Create Date: 2021-10-13 18:10:30.199913

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '8ae2b7e01889'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('users',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('name', sa.String(length=20), nullable=False),
    sa.Column('bio', sa.String(length=200), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('interests', sa.ARRAY(sa.Enum('WORK', 'FRIENDSHIP', 'FLIRTING', 'NETWORKING', 'CHAT', 'LOVE', name='userinterests')), nullable=False),
    sa.Column('photos', sa.ARRAY(sa.String(length=50)), nullable=False),
    sa.Column('gender', sa.Enum('MALE', 'FEMALE', 'ATTACK_HELICOPTER', name='gender'), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('is_premium', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('users')
    # ### end Alembic commands ###

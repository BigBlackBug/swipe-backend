"""add chat and chat messages

Revision ID: 1bc8c29f42be
Revises: f27b7d4742e4
Create Date: 2021-10-22 13:06:49.691386

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1bc8c29f42be'
down_revision = 'f27b7d4742e4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('chats',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('status', sa.Enum('REQUESTED', 'ACCEPTED', name='chatstatus'), nullable=False),
    sa.Column('initiator_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('the_other_person_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.ForeignKeyConstraint(['initiator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['the_other_person_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('initiator_id', 'the_other_person_id', name='one_chat_per_pair')
    )
    op.create_table('chat_messages',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('status', sa.Enum('SENT', 'RECEIVED', 'READ', name='messagestatus'), nullable=True),
    sa.Column('message', sa.String(length=256), nullable=True),
    sa.Column('image_id', sa.String(length=50), nullable=True),
    sa.Column('sender_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('chat_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('chat_messages')
    op.drop_table('chats')
    # ### end Alembic commands ###

"""add on_delete cascade to chat_message

Revision ID: ac720e5024cb
Revises: 8112872402ab
Create Date: 2021-10-31 23:27:29.825439

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ac720e5024cb'
down_revision = '8112872402ab'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('chat_messages_chat_id_fkey', 'chat_messages', type_='foreignkey')
    op.create_foreign_key(None, 'chat_messages', 'chats', ['chat_id'], ['id'], ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'chat_messages', type_='foreignkey')
    op.create_foreign_key('chat_messages_chat_id_fkey', 'chat_messages', 'chats', ['chat_id'], ['id'])
    # ### end Alembic commands ###
import os

from swipe.database import SessionLocal

# temporary junk
if os.environ.get('RECREATE_DB_ON_DEPLOY', None):
    print("Dropping schema 'public'")
    with SessionLocal() as db:
        db.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')

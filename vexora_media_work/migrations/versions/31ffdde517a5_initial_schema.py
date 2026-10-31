"""Baseline the current VEXORA schema.

Revision ID: 31ffdde517a5
Revises:
Create Date: 2026-10-23

This baseline is intentionally idempotent so it can initialize a fresh database
or be stamped onto a database already created by the earlier MVP's create_all.
Future schema changes should be generated as normal Alembic revisions.
"""
from alembic import op
from app.database import Base
from app import models  # noqa: F401 - registers mapped tables

revision = "31ffdde517a5"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)

def downgrade() -> None:
    # Baseline downgrade is destructive; back up the database before running it.
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)

"""unique constraint on source_stars.source_id

Revision ID: 88bb7f366038
Revises: 17c559a7a685
Create Date: 2026-05-15

"""

from alembic import op

revision = "88bb7f366038"
down_revision = "17c559a7a685"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete duplicate rows, keeping the one with the highest id (most recent).
    op.execute(
        """
        DELETE FROM source_stars
        WHERE id NOT IN (
            SELECT MAX(id) FROM source_stars GROUP BY source_id
        )
        """
    )
    with op.batch_alter_table("source_stars") as batch_op:
        batch_op.create_unique_constraint("uq_source_stars_source_id", ["source_id"])


def downgrade() -> None:
    with op.batch_alter_table("source_stars") as batch_op:
        batch_op.drop_constraint("uq_source_stars_source_id", type_="unique")

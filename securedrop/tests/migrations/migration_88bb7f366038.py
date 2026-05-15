import uuid

from db import db
from journalist_app import create_app
from sqlalchemy import exc, text


def _insert_source(app, designation):
    with app.app_context():
        db.engine.execute(
            text(
                "INSERT INTO sources (uuid, filesystem_id, journalist_designation,"
                " interaction_count) VALUES (:uuid, :filesystem_id, :designation, :count)"
            ),
            uuid=str(uuid.uuid4()),
            filesystem_id=str(uuid.uuid4()),
            designation=designation,
            count=0,
        )
        return db.engine.execute("SELECT MAX(id) FROM sources").scalar()


class UpgradeTester:
    """The upgrade deletes duplicate source_stars rows (keeping the one with the
    highest id per source_id), then enforces uniqueness on source_id."""

    def __init__(self, config):
        self.config = config
        self.app = create_app(config)
        self.source_ids = []

    def load_data(self):
        self.source_ids = [
            _insert_source(self.app, "brave marmot"),
            _insert_source(self.app, "quiet badger"),
        ]
        with self.app.app_context():
            # Two duplicate stars for source 0; older starred=True, newer starred=False.
            # The migration should keep the newer one (highest id).
            for starred in (True, False):
                db.engine.execute(
                    text(
                        "INSERT INTO source_stars (source_id, starred)" " VALUES (:sid, :starred)"
                    ),
                    sid=self.source_ids[0],
                    starred=starred,
                )
            # One star for source 1 — should survive untouched.
            db.engine.execute(
                text("INSERT INTO source_stars (source_id, starred)" " VALUES (:sid, :starred)"),
                sid=self.source_ids[1],
                starred=True,
            )

    def check_upgrade(self):
        with self.app.app_context():
            rows = db.engine.execute(
                "SELECT source_id, starred FROM source_stars ORDER BY id"
            ).fetchall()
            # Only one row per source_id remains.
            assert len(rows) == 2
            # The duplicate for source 0 was culled, keeping the newer row (starred=False).
            assert rows[0] == (self.source_ids[0], False)
            assert rows[1] == (self.source_ids[1], True)

            # Unique constraint is now enforced.
            try:
                db.engine.execute(
                    text(
                        "INSERT INTO source_stars (source_id, starred)" " VALUES (:sid, :starred)"
                    ),
                    sid=self.source_ids[0],
                    starred=True,
                )
                raise AssertionError("Expected a unique constraint violation")
            except exc.IntegrityError:
                pass


class DowngradeTester:
    """Downgrading drops the unique constraint but leaves existing data intact."""

    def __init__(self, config):
        self.config = config
        self.app = create_app(config)
        self.source_ids = []

    def load_data(self):
        self.source_ids = [
            _insert_source(self.app, "bold sparrow"),
            _insert_source(self.app, "dim walrus"),
        ]
        with self.app.app_context():
            for sid in self.source_ids:
                db.engine.execute(
                    text(
                        "INSERT INTO source_stars (source_id, starred)" " VALUES (:sid, :starred)"
                    ),
                    sid=sid,
                    starred=True,
                )

    def check_downgrade(self):
        with self.app.app_context():
            rows = db.engine.execute("SELECT source_id FROM source_stars ORDER BY id").fetchall()
            # Existing rows are still present.
            assert len(rows) == 2

            # After downgrade, the unique constraint is gone — duplicates are allowed again.
            db.engine.execute(
                text("INSERT INTO source_stars (source_id, starred)" " VALUES (:sid, :starred)"),
                sid=self.source_ids[0],
                starred=False,
            )
            duplicates = db.engine.execute(
                text("SELECT id FROM source_stars WHERE source_id = :sid"),
                sid=self.source_ids[0],
            ).fetchall()
            assert len(duplicates) == 2

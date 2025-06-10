# This is a prototype for demonstration only.  Co-written with ChatGPT.

import logging
import time

import requests
from sqlalchemy import Column, String, create_engine
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

Base = declarative_base()


class Source(Base):
    __tablename__ = "sources"
    uuid = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    data = Column(SQLiteJSON, nullable=True)


class Submission(Base):
    __tablename__ = "submissions"
    uuid = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    data = Column(SQLiteJSON, nullable=True)


class Reply(Base):
    __tablename__ = "replies"
    uuid = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    data = Column(SQLiteJSON, nullable=True)


# Set up SQLAlchemy engine and session
engine = create_engine("sqlite:///sources.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()


def sync_entity(entity_cls, endpoint, key_name):
    logging.info(f"Syncing {key_name}")
    start_time = time.time()

    # GET current state
    response = requests.get(endpoint)
    response.raise_for_status()
    data = response.json()

    items = data.get(key_name, {})
    if not isinstance(items, dict):
        raise ValueError(f"Expected '{key_name}' to be a dictionary of uuid: version pairs")

    incoming_uuids = set(items)
    added, updated, deleted = 0, 0, 0
    changed_uuids = set()

    local_versions = {e.uuid: e.version for e in session.query(entity_cls).all()}

    for uuid, version in items.items():
        local_version = local_versions.get(uuid)
        if local_version is None:
            session.add(entity_cls(uuid=uuid, version=version))
            added += 1
            changed_uuids.add(uuid)
        elif local_version != version:
            entity = session.get(entity_cls, uuid)
            entity.version = version
            updated += 1
            changed_uuids.add(uuid)

    for uuid in set(local_versions) - incoming_uuids:
        entity = session.get(entity_cls, uuid)
        if entity:
            session.delete(entity)
            deleted += 1

    session.commit()

    if changed_uuids:
        post_payload = {key_name: list(changed_uuids)}
        post_response = requests.post(endpoint, json=post_payload)
        post_response.raise_for_status()
        logging.info(f"Posted {len(changed_uuids)} changed {key_name} UUIDs back to API")

        post_data = post_response.json()
        enriched_items = post_data.get(key_name, [])
        for item in enriched_items:
            uuid = item.get("uuid")
            if uuid:
                entity = session.get(entity_cls, uuid)
                if entity:
                    entity.data = item

    session.commit()
    elapsed = time.time() - start_time
    logging.info(
        f"{key_name.capitalize()} - Added: {added}, Updated: {updated}, Removed: {deleted}, Time: {elapsed:.2f}s"
    )


# Run sync for all entities
sync_entity(Source, "http://localhost:8081/api/v1/sources2", "sources")
sync_entity(Submission, "http://localhost:8081/api/v1/submissions2", "submissions")
sync_entity(Reply, "http://localhost:8081/api/v1/replies2", "replies")

session.close()

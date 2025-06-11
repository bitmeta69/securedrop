# This is a prototype for demonstration only.  Co-written with ChatGPT.

import logging
import os
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

api_host = os.getenv("SD_JOURNALIST_API", "localhost:8081")
base_url = f"http://{api_host}/api/v1"

# Single GET to collect all entity versions
logging.info("Fetching all versions from API")
start_all = time.time()
get_versions = requests.get(f"{base_url}/index")
get_versions.raise_for_status()
all_versions = get_versions.json()
fetch_all_elapsed = time.time() - start_all

# Dictionary of entity classes
entity_map = {
    "sources": Source,
    "submissions": Submission,
    "replies": Reply,
}

# Collect UUIDs to POST per table
uuids_to_fetch = {}
sync_total_start = time.time()

for key_name, entity_cls in entity_map.items():
    logging.info(f"Syncing {key_name}")
    items = all_versions.get(key_name, {})
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

    uuids_to_fetch[key_name] = list(changed_uuids)
    session.commit()
    logging.info(
        f"{key_name.capitalize()} - Added: {added}, Updated: {updated}, Removed: {deleted}"
    )

# POST once with all UUIDs, if any
post_payload = {k: v for k, v in uuids_to_fetch.items() if v}
if post_payload:
    logging.info("Fetching enriched data for changed entities")
    post_response = requests.post(f"{base_url}/index", json=post_payload)
    post_response.raise_for_status()
    post_data = post_response.json()

    # Save enriched data
    for key_name, records in post_data.items():
        entity_cls = entity_map.get(key_name)
        if not entity_cls:
            continue
        for item in records:
            uuid = item.get("uuid")
            if uuid:
                entity = session.get(entity_cls, uuid)
                if entity:
                    entity.data = item
    session.commit()

sync_total_elapsed = time.time() - sync_total_start

# Naive GET to old endpoint for comparison
naive_total_start = time.time()
for key in entity_map:
    naive_url = f"{base_url}/{key}"
    r = requests.get(naive_url)
    r.raise_for_status()
naive_total_elapsed = time.time() - naive_total_start

# Close session
session.close()

# Print summary
print("\nSummary Table")
print(f"{'Total Sync Time (s)':<25}: {sync_total_elapsed:.2f}")
print(f"{'Total Naive GET Time (s)':<25}: {naive_total_elapsed:.2f}")
print(f"{'Overall Speed-up':<25}: {naive_total_elapsed / sync_total_elapsed:.2f}")

# This is a prototype for demonstration only.  Co-written with ChatGPT.

import hashlib
import json
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

# Dictionary of entity classes
entity_map = {
    "sources": Source,
    "submissions": Submission,
    "replies": Reply,
}

# Construct local {entity: {uuid: version}} dict
local_versions_by_entity = {
    key_name: {e.uuid: e.version for e in session.query(entity_cls)}
    for key_name, entity_cls in entity_map.items()
}

# Compute SHA-256 digest of local versions JSON
local_versions_json = json.dumps(local_versions_by_entity, sort_keys=True)
version_hash = hashlib.sha256(local_versions_json.encode()).hexdigest()

# Start total sync timing from the beginning of GET /head/<version>
sync_total_start = time.time()

# GET from /head/<version>
logging.info("Fetching version comparison from API")
head_response = requests.get(f"{base_url}/head/{version_hash}")

if head_response.status_code == 304:
    logging.info("Client is current with server. Skipping data POST.")
    sync_total_elapsed = time.time() - sync_total_start
else:
    head_response.raise_for_status()
    all_versions = head_response.json()

    # Collect UUIDs to POST per table
    uuids_to_fetch = {}

    for key_name, entity_cls in entity_map.items():
        logging.info(f"Syncing {key_name}")
        items = all_versions.get(key_name, {})
        if not isinstance(items, dict):
            raise ValueError(f"Expected '{key_name}' to be a dictionary of uuid: version pairs")

        incoming_uuids = set(items)
        added, updated, deleted = 0, 0, 0
        changed_uuids = set()

        local_versions = local_versions_by_entity[key_name]

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

        uuids_to_fetch[key_name] = list(sorted(changed_uuids))
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

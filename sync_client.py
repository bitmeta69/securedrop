# This is a prototype for demonstration only.  Co-written with ChatGPT.

import logging
import sys
import time

import requests
from sqlalchemy import Column, String, create_engine
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# URL to fetch from
url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8081/api/v1/sources2"
start_time = time.time()

# GET the URL
response = requests.get(url)
response.raise_for_status()
data = response.json()

# Extract sources
sources = data.get("sources", {})

# Define ORM base and model
Base = declarative_base()


class Source(Base):
    __tablename__ = "sources"
    uuid = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    data = Column(SQLiteJSON, nullable=True)


# Set up SQLAlchemy engine and session
engine = create_engine("sqlite:///sources.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Track UUIDs from the response
incoming_uuids = set(sources)

# Insert or update entries
added, updated = 0, 0
changed_uuids = []
for uuid, version in sources.items():
    source = session.get(Source, uuid)
    if source:
        if source.version != version:
            source.version = version
            updated += 1
            changed_uuids.append(uuid)
    else:
        source = Source(uuid=uuid, version=version)
        session.add(source)
        added += 1
        changed_uuids.append(uuid)

# Remove sources not present in the response
existing_sources = session.query(Source).all()
deleted = 0
for source in existing_sources:
    if source.uuid not in incoming_uuids:
        session.delete(source)
        deleted += 1

# Commit current session before POST
session.commit()

# POST changed UUIDs back to API and update data
if changed_uuids:
    post_payload = {"sources": changed_uuids}
    post_response = requests.post(url, json=post_payload)
    post_response.raise_for_status()
    logging.info(f"Posted {len(changed_uuids)} changed UUIDs back to API")

    post_data = post_response.json()
    enriched_sources = post_data.get("sources", [])
    for item in enriched_sources:
        uuid = item.get("uuid")
        if uuid:
            source = session.get(Source, uuid)
            if source:
                source.data = item

# Final commit and close
session.commit()
session.close()

# Log summary
elapsed_time = time.time() - start_time
logging.info(f"Added: {added}, Updated: {updated}, Removed: {deleted}")
logging.info(f"Processing completed in {elapsed_time:.3f} seconds")

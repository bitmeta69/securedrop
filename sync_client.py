# This is a prototype for demonstration only.  Co-written with ChatGPT.

import logging
import sys
import time

import requests
from sqlalchemy import Column, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8081/api/v1/sources2"
start_time = time.time()

# GET the URL
response = requests.get(url)
response.raise_for_status()
data = response.json()

# Extract sources
dict_items = data.get("sources", {})

# Define ORM base and model
Base = declarative_base()


class Source(Base):
    __tablename__ = "sources"
    uuid = Column(String, primary_key=True)
    version = Column(String, nullable=False)


# Set up SQLAlchemy engine and session
engine = create_engine("sqlite:///sources.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Track UUIDs from the response
incoming_uuids = set(dict_items.keys())

# Insert or update entries
added, updated = 0, 0
for uuid, version in dict_items.items():
    source = session.get(Source, uuid)
    if source:
        if source.version != version:
            source.version = version
            updated += 1
    else:
        source = Source(uuid=uuid, version=version)
        session.add(source)
        added += 1

# Remove sources not present in the response
existing_sources = session.query(Source).all()
deleted = 0
for source in existing_sources:
    if source.uuid not in incoming_uuids:
        session.delete(source)
        deleted += 1

# Commit and close
session.commit()
session.close()

# Log summary
elapsed_time = time.time() - start_time
logging.info(f"Added: {added}, Updated: {updated}, Removed: {deleted}")
logging.info(f"Processing completed in {elapsed_time:.2f} seconds")

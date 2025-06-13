# This is a proof of concept for demonstration only.  Co-written with ChatGPT.

import argparse
import gzip
import hashlib
import io
import json
import logging
import os
import time
from collections import defaultdict

import requests
from sqlalchemy import Column, String, create_engine
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import declarative_base, sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

Base = declarative_base()


def json_version(d: dict) -> str:
    j = json.dumps(d, sort_keys=True)
    s = j.encode("utf-8")
    h = hashlib.sha256(s).hexdigest()
    return h


def gzipped_size(data: bytes) -> int:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as f:
        f.write(data)
    return len(buf.getvalue())


def log_json_preview(label: str, b: bytes):
    try:
        parsed = json.loads(b.decode("utf-8"))
        pretty = json.dumps(parsed, indent=2)[:1024]
        logging.debug(f"{label} preview (pretty-printed):\n{pretty}")
    except Exception:
        logging.debug(f"{label} preview (raw): {b[:1024]!r}")


class Source(Base):
    __tablename__ = "sources"
    uuid = Column(String, primary_key=True)
    data = Column(SQLiteJSON, nullable=True)


class Item(Base):
    __tablename__ = "items"
    uuid = Column(String, primary_key=True)
    data = Column(SQLiteJSON, nullable=True)


# Set up SQLAlchemy engine and session
engine = create_engine("sqlite:///sources.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Command-line argument parsing
parser = argparse.ArgumentParser()
parser.add_argument("--prefix", type=int, help="Group source UUIDs by prefix of given length")
parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
args = parser.parse_args()

if args.verbose:
    logging.getLogger().setLevel(logging.DEBUG)

if args.prefix is not None:
    grouped = defaultdict(int)
    for source in session.query(Source):
        prefix = source.uuid[: args.prefix]
        grouped[prefix] += 1
    for prefix, count in sorted(grouped.items()):
        print(f"{prefix}: {count}")
    session.close()
    exit()

api_host = os.getenv("SD_JOURNALIST_API", "localhost:8081")
base_url = f"http://{api_host}/api/v1"

# Construct local {uuid: version} for sources
local_source_versions = {
    # TODO: We should derive a fresh Source.collection_version, so that any
    # discrepancy below the source level will trigger a refresh of the entire
    # source.
    e.uuid: json_version(e.data)
    for e in session.query(Source)
    if e.data is not None
}

# Compute version hash
version_hash = json_version({"sources": local_source_versions})

# Start total sync timing from the beginning of GET /head
sync_total_start = time.time()
sync_bytes_sent = 0
sync_bytes_received = 0

# GET from /head using If-None-Match header
logging.info("Fetching version comparison from API")
headers = {
    "If-None-Match": version_hash,
    "Accept-Encoding": "gzip",
}
head_response = requests.get(f"{base_url}/head", headers=headers)
compressed_request_size = 0
compressed_response_size = gzipped_size(head_response.content)
sync_bytes_sent += compressed_request_size
sync_bytes_received += compressed_response_size
logging.info(
    f"GET /head - Sent: {compressed_request_size} bytes, Received: {compressed_response_size} bytes"
)
if args.verbose:
    log_json_preview("HEAD response", head_response.content)

if head_response.status_code == 304:
    logging.info("Client is current with server. Skipping data POST.")
    sync_total_elapsed = time.time() - sync_total_start
else:
    head_response.raise_for_status()
    all_versions = head_response.json().get("sources", {})

    incoming_uuids = set(all_versions)
    added, updated, deleted = 0, 0, 0
    changed_uuids = set()

    for uuid, remote_version in all_versions.items():
        entity = session.get(Source, uuid)
        local_data = entity.data if entity else None
        local_version = json_version(local_data) if local_data is not None else None
        if entity is None:
            session.add(Source(uuid=uuid))
            added += 1
            changed_uuids.add(uuid)
        elif local_version != remote_version:
            updated += 1
            changed_uuids.add(uuid)

    for uuid in set(local_source_versions) - incoming_uuids:
        entity = session.get(Source, uuid)
        if entity:
            session.delete(entity)
            deleted += 1

    session.commit()
    logging.info(f"Sources - Added: {added}, Updated: {updated}, Removed: {deleted}")

    # POST once with only sources
    post_payload = {"sources": list(sorted(changed_uuids))}
    if post_payload["sources"]:
        logging.info("Fetching enriched data for changed sources")
        post_headers = {
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json",
        }
        post_data = json.dumps(post_payload).encode("utf-8")
        if args.verbose:
            log_json_preview("POST request", post_data)
        post_response = requests.post(f"{base_url}/index", data=post_data, headers=post_headers)
        if args.verbose:
            log_json_preview("POST response", post_response.content)
        compressed_request_size = gzipped_size(post_data)
        compressed_response_size = gzipped_size(post_response.content)
        sync_bytes_sent += compressed_request_size
        sync_bytes_received += compressed_response_size
        logging.info(
            f"POST /index - Sent: {compressed_request_size} bytes, Received: {compressed_response_size} bytes"
        )

        post_response.raise_for_status()
        post_data = post_response.json()

        for item in post_data.get("sources", []):
            uuid = item.get("uuid")
            if uuid:
                entity = session.get(Source, uuid)
                if entity:
                    entity.data = item

        for item in post_data.get("items", []):
            uuid = item.get("uuid")
            if uuid:
                entity = session.get(Item, uuid)
                if entity is None:
                    entity = Item(uuid=uuid)
                    session.add(entity)
                entity.data = item

        session.commit()

    sync_total_elapsed = time.time() - sync_total_start

# Naive GET to old endpoint for comparison
naive_total_start = time.time()
naive_bytes_sent = 0
naive_bytes_received = 0
naive_headers = {"Accept-Encoding": "gzip"}
for key in ["sources", "submissions", "replies"]:
    naive_url = f"{base_url}/{key}"
    r = requests.get(naive_url, headers=naive_headers)
    compressed_request_size = 0
    compressed_response_size = gzipped_size(r.content)
    naive_bytes_sent += compressed_request_size
    naive_bytes_received += compressed_response_size
    logging.info(
        f"GET {naive_url} - Sent: {compressed_request_size} bytes, Received: {compressed_response_size} bytes"
    )
    if args.verbose:
        log_json_preview(f"{key.upper()} response", r.content)
    r.raise_for_status()
naive_total_elapsed = time.time() - naive_total_start

# Close session
session.close()

# Print summary
print("\nSummary Table")
print(f"{'Total Sync Time (s)':<30}: {sync_total_elapsed:.2f}")
print(f"{'Total Sync Bytes':<30}: {sync_bytes_sent + sync_bytes_received}")
print(f"{'Total Naive GET Time (s)':<30}: {naive_total_elapsed:.2f}")
print(f"{'Total Naive GET Bytes':<30}: {naive_bytes_sent + naive_bytes_received}")
print(f"{'Overall Speed-up (time)':<30}: {naive_total_elapsed / sync_total_elapsed:.2f}")
print(
    f"{'Overall Speed-up (bytes)':<30}: {(naive_bytes_sent + naive_bytes_received) / max(sync_bytes_sent + sync_bytes_received, 1):.2f}"
)

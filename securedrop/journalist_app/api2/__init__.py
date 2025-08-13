import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, NewType, Optional, Set

from flask import Blueprint, abort, json, jsonify, request
from models import Journalist, Reply, Source, Submission
from sqlalchemy.inspection import inspect
from sqlalchemy.orm.exc import MultipleResultsFound
from werkzeug.wrappers.response import Response

blp = Blueprint("api2", __name__, url_prefix="/api/v2")

PREFIX_MAX_LEN = inspect(Source).columns["uuid"].type.length


Version = NewType("Version", str)


def json_version(d: Mapping) -> Version:
    """
    Calculate the version (BLAKE2s digest) of the normalized JSON representation
    of the dictionary ``d``.

    We use BLAKE2s here because SHA-256 is too slow (we don't care about
    cryptographic security) and CRC-32 is too collision-prone (we're not merely
    checksumming for transmission integrity).
    """
    s = json.dumps(d, separators=[",", ":"], sort_keys=True)
    b = s.encode("utf-8")
    return Version(hashlib.blake2s(b).hexdigest())


# TODO: generic UUID[T] in Python 3.12
SourceUUID = NewType("SourceUUID", str)
ItemUUID = NewType("ItemUUID", str)
JournalistUUID = NewType("JournalistUUID", str)


@dataclass
class Index:
    # Source metadata, optionally filtered by `source_prefix`:
    sources: Dict[SourceUUID, Version] = field(default_factory=dict)
    items: Dict[ItemUUID, Version] = field(default_factory=dict)

    # Non-source metadata (always returned):
    journalists: Dict[JournalistUUID, Version] = field(default_factory=dict)


@blp.get("/index")
@blp.get("/index/<string:source_prefix>")
def index(source_prefix: Optional[str] = None) -> Response:
    """
    By default, return the ETag-versioned ``Index`` of all metadata unless the
    client provides the ETag of the current index.

    Given a ``source_prefix``, return the sub-index of source metadata for all
    sources whose UUIDs begin with that prefix, plus all non-source metadata,
    unless the client provides the ETag of the current sub-index for that
    prefix.  The client MAY choose an arbitrary prefix with each request: e.g.,
    a series of requests with the prefixes ``{0...f}`` will effectively shard
    the source index into 16 shards.  (Non-source metadata is not filtered by
    the prefix and is always returned.)
    """
    index = Index()

    source_query = Source.query
    if source_prefix is not None:
        if len(source_prefix) >= PREFIX_MAX_LEN:
            abort(
                422,
                f"malformed request; source prefix must be shorter than {PREFIX_MAX_LEN} "
                f"characters",
            )

        source_query = Source.query.filter(Source.uuid.startswith(source_prefix))

    for source in source_query.all():
        index.sources[source.uuid] = json_version(source.to_api_v2())
        for item in source.collection:
            index.items[item.uuid] = json_version(item.to_api_v2())

    for journalist in Journalist.query.all():
        index.journalists[journalist.uuid] = json_version(journalist.to_api_v2())

    version = json_version(asdict(index))
    response = jsonify(asdict(index))

    # If the request's `If-None-Match` header matches the version,
    # return HTTP 304 with an empty response.
    response.set_etag(version)
    return response.make_conditional(request)


@dataclass
class MetadataRequest:
    # Source metadata:
    sources: Set[SourceUUID] = field(default_factory=set)
    items: Set[ItemUUID] = field(default_factory=set)

    # Non-source metadata:
    journalists: Set[JournalistUUID] = field(default_factory=set)


@dataclass
class MetadataResponse:
    # Source metadata:
    sources: Dict[SourceUUID, Any] = field(default_factory=dict)
    items: Dict[ItemUUID, Any] = field(default_factory=dict)

    # Non-source metadata:
    journalists: Dict[JournalistUUID, Any] = field(default_factory=dict)


@blp.post("/metadata")
def metadata() -> Response:
    """
    Return the ``MetadataResponse`` requested in the ``MetadataRequest``.  The
    client MAY choose an arbitrary list of objects with each request, e.g. from
    a shard retrieved from ``/index/<source_prefix>``.
    """
    try:
        requested = MetadataRequest(**request.json)  # type: ignore
    except (TypeError, ValueError) as exc:
        abort(422, f"malformed request; {exc}")

    response = MetadataResponse()

    if requested.sources:
        for source in Source.query.filter(Source.uuid.in_(str(uuid) for uuid in requested.sources)):
            response.sources[source.uuid] = source.to_api_v2()

    if requested.items:
        for item in Submission.query.filter(
            Submission.uuid.in_(str(uuid) for uuid in requested.items)
        ):
            response.items[item.uuid] = item.to_api_v2()

        for item in Reply.query.filter(Reply.uuid.in_(str(uuid) for uuid in requested.items)):
            if item.uuid in response.items:
                # Fail if we get unlucky and hit a UUID collision between the
                # `Submission` and `Reply` tables.  This is vanishingly unlikely,
                # but SQLite can't enforce uniqueness between them.
                raise MultipleResultsFound(f"found {item.uuid} in both submissions and replies")
            response.items[item.uuid] = item.to_api_v2()

    if requested.journalists:
        for journalist in Journalist.query.filter(
            Journalist.uuid.in_(str(uuid) for uuid in requested.journalists)
        ):
            response.journalists[journalist.uuid] = journalist.to_api_v2()

    return jsonify(asdict(response))

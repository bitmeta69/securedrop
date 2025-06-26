# This file is a lightweight specification of a v2 Journalist API that
# implements the synchronization strategy proposed in `PROPOSAL.md`, including:
#
# 1. A semi-[literate] reference implementation in Python of the structures and
#    algorithms for versioning and diffing resources, which can be easily
#    replicated in another language (e.g., TypeScript).  You can view this
#    documentation inside the development shell with:
#
#        $ python -m pydoc journalist_app/api2.py
#
# 2. An initial set of test vectors.  To keep this file self-contained and
#    self-testing, these are implemented here as doctests, but they should also
#    be easily replicated in another language.  You can run these tests inside
#    the development shell with:
#
#        $ python -m doctest journalist_app/api2.py`
#
# 3. A scaffold (i.e., schemas and stubs) for the endpoints the new API
#    provides.  Most raise `NotImplementedError`; a few are implemented for
#    demonstration.  You can view the OpenAPI specification that flask-smorest
#    generates from this scaffold by running `make dev`, logging into the
#    Journalist Interface, and navigating to <http://localhost:8081/docs>.
#
#    The OpenAPI specification can also be used to generate TypeScript types
#    including JSON Schema validation (via openapi-typescript) and/or full API
#    clients (via openapi-generator).
#
#
# [literate]: https://en.wikipedia.org/wiki/Literate_programming

import hashlib
from typing import Dict, List, Protocol

import flask
from flask.views import MethodView

# FIXME: If flask-smorest is too heavy-weight a dependency for us to add in
# production, we can probably get away with [apispec]---or do more of this
# manually.
#
# [apispec]: https://apispec.readthedocs.io/en/latest/using_plugins.html#example-flask-and-marshmallow-plugins
from flask_smorest import Blueprint
from marshmallow import Schema, fields

# --- SECTION 1: REFERENCE IMPLEMENTATIONS ---


def json_version(d: dict) -> str:
    """
    Calculate the version (BLAKE2s digest) of the normalized JSON representation
    of the dictionary `d`.

    We use BLAKE2s here because SHA-256 is too slow (we don't care about
    cryptographic security) and CRC-32 is too collision-prone (we're not merely
    checksumming for transmission integrity).

    >>> d = {"foo": "bar", "baz": "biz"}
    >>> json_version(d)
    '593ffee39176ea092546a7df8247c9b3936102abf539ed212492d817ccdeb19a'
    >>> d2 = {"baz": "biz", "foo": "bar"}
    >>> json_version(d2) == json_version(d)
    True
    """
    s = flask.json.dumps(d, sort_keys=True)
    b = s.encode("utf-8")
    return hashlib.blake2s(b).hexdigest()


class VersionedItem(Protocol):
    """
    A versioned item has a canonical JSON representation that can be hashed to
    version that item.

    The `Submission` and `Reply` models MUST implement the `VersionedItem`
    protocol.
    """

    uuid: str

    @property
    def version(self) -> str:
        """
        This property SHOULD be cached.  A number of caching strategies are
        possible (on read, on server start-up, etc.), but the cached value for a
        given model instance MUST be either updated or invalidated on write.
        """
        return json_version(self.to_json())

    def to_json(self) -> Dict[str, object]:
        """
        The existing `to_json()` method.  Since the return value is derived from
        a given model instance, this should be a property, but it's left as a
        method here to minimize extraneous changes.
        """
        ...


class VersionedCollection(VersionedItem, Protocol):
    """
    A versioned collection is a `VersionedItem` that has a collection of other
    `VersionedItems` and provides an index of their IDs and versions.

    The `Source` model MUST implement the `VersionedCollection` protocol.
    """

    @property
    def collection(self) -> List[VersionedItem]:
        """The existing `collection` property."""
        ...

    @property
    def collection_index(self) -> Dict[str, str]:
        """
        This property SHOULD be cached.  A number of caching strategies are
        possible (on read, on server start-up, etc.), but the cached value for a
        given model instance and its colleciton MUST be either updated or
        invalidated on write.
        """
        return {item.uuid: item.version for item in self.collection}

    def to_json(self) -> Dict[str, str]:
        """
        The existing `to_json()` method.  Since the return value is derived from
        a given model instance, this should be a property, but it's left as a
        method here to minimize extraneous changes.

        The return value MUST include a `collection_version` key like:

            {
                ...,
                "collection_version": json_version(self.collection_index),
            }
        """
        ...


# --- SECTION 2: TEST VECTORS ---


class SubmissionStub(VersionedItem):
    """
    Example implementation of a `VersionedItem`---i.e., how `Submission` and
    `Reply` will implement the `VersionedItem` protocol.

    >>> submission = SubmissionStub("9ca2e0bf-fe06-4407-89eb-fdfd144df72d")
    >>> submission.to_json()
    {'uuid': '9ca2e0bf-fe06-4407-89eb-fdfd144df72d'}
    >>> submission.version
    '91332efd8e5592f40a7d306eb3d8cd87382e2804c6ab56bd763c1360975d6ce8'
    """

    def __init__(self, uuid: str):
        self.uuid = uuid

    @property
    def version(self):
        return json_version(self.to_json())

    def to_json(self):
        return {"uuid": self.uuid}


class SourceStub(VersionedCollection):
    """
    Example implementation of a `VersionedCollection`---i.e., how `Source` will implement
    the `VersionedCollection` protocol.

    >>> submission = SubmissionStub("9ca2e0bf-fe06-4407-89eb-fdfd144df72d")
    >>> source = SourceStub(
    ...     "b3ef45e6-7e49-4d6e-b039-14870dd870ab",
    ...     [submission],
    ... )
    >>> source.collection_index
    {'9ca2e0bf-fe06-4407-89eb-fdfd144df72d': '91332efd8e5592f40a7d306eb3d8cd87382e2804c6ab56bd763c1360975d6ce8'}
    >>> source.to_json()
    {'uuid': 'b3ef45e6-7e49-4d6e-b039-14870dd870ab', 'collection_version': 'e3016b32ba827e59a8ce525d08c01ff8f742e3b74000b8b07f9f655979c327e3'}
    >>> source.version
    '41f366630fb697afc0b55145d43b776a92b98d0c4ce9ae45797c0ee844b52a45'
    """

    def __init__(self, uuid: str, collection: List[VersionedItem]):
        self.uuid = uuid
        self._collection = collection

    @property
    def collection(self):
        return self._collection

    @property
    def collection_index(self):
        return {item.uuid: item.version for item in self.collection}

    @property
    def version(self):
        return json_version(self.to_json())

    def to_json(self):
        return {"uuid": self.uuid, "collection_version": json_version(self.collection_index)}


class IndexSchema(Schema):
    """
    An index lists all sources by `{uuid: version}`.  Sources may appear in any
    order; normalization (e.g. for versioning) is the responsibility of the
    consumer.
    """

    sources = fields.Dict(keys=fields.UUID, values=fields.String)


class SourceDeltaSchema(Schema):
    """
    A source delta lists the UUIDs of sources for which to return a source
    metadata set.
    """

    sources = fields.List(fields.UUID)


class SourceMetadataSetSchema(Schema):
    """
    A source metadata set contains the metadata for a set of sources and the
    items in the union of their collections.
    """

    sources = fields.Dict(keys=fields.UUID, values=fields.Raw)
    items = fields.Dict(keys=fields.UUID, values=fields.Raw)


# --- 3. API SCAFFOLD/STUBS ---

blp = Blueprint("v2", __name__, url_prefix="/api/v2")


@blp.route("/index")
@blp.etag
class Index(MethodView):
    @blp.response(200, IndexSchema)
    def get():
        """
        Return the index of all sources.

        If the request's `If-None-Match` header matches the new ETag, this view
        MUST return HTTP 304 with an empty response.
        """
        # These values SHOULD be cached:
        index = {"sources": {}}  # TODO: {uuid: version}
        version = json_version(index)

        # This is all flask-smorest requires to set the new (and implicitly
        # check it against the request's) ETag.
        blp.set_etag(version)

        return index


@blp.route("/index/<string:prefix>")
@blp.etag
class PrefixIndex(MethodView):
    @blp.response(200, IndexSchema)
    def get(prefix: str):
        """
        OPTIONAL: Return the index of all sources whose UUIDs begin with
        `prefix`.  The client MAY choose an arbitrary prefix with each request:
        e.g., a series of requests with the prefixes {0...f} will effectively
        shard the index into 16 shards.

        If the request's `If-None-Match` header matches the new ETag, this view MUST
        return HTTP 304 with an empty response.
        """
        raise NotImplementedError


@blp.route("/sources")
class Sources(MethodView):
    @blp.response(200, SourceMetadataSetSchema)
    def get():
        """Return the source metadata for all sources."""
        raise NotImplementedError

    @blp.arguments(SourceDeltaSchema)
    @blp.response(200, SourceMetadataSetSchema)
    def post():
        """
        Return the source metadata for the sources listed in the source delta.
        The client MAY choose an arbitrary source delta with each request, e.g.
        from a shard retrieved from `/index/<prefix>`.
        """
        raise NotImplementedError


# TODO: authentication

# TODO: operations

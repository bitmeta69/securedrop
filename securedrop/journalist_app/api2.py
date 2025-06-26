# This file is a lightweight specification of a v2 Journalist API that
# implements the synchronization strategy proposed in `PROPOSAL.md`, including:
#
# 1. A semi-[literate] reference implementation in Python of the structures and
#    algorithms for versioning and diffing resources, which can be easily
#    replicated in another language (e.g., TypeScript).
#
# 2. An initial set of test vectors.  To keep this file self-contained,
#    self-documenting, and self-testing, these are implemented here as doctests,
#    but they should also be easily replicated in another language.
#
# 3. Stubs (i.e., signatures that raise `NotImplementedError``) for the
#    endpoints the new API provides.
#
# "Semi-literate" means that this file is (a) be self-sufficient for
# understanding the API's synchronization strategy and (b) produce reasonable
# output under a documentation generator like Doxygen or Sphinx.  As a stretch
# goal, this file MAY also produce an OpenAPI specification that can be consumed
# by a client (or its code-generation toolchain), including for typing and
# validating requests and responses.
# - TODO: document
#
#
# [^1]: https://en.wikipedia.org/wiki/Literate_programming

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


class IndexSchema(Schema):
    """
    An index lists all sources by `{uuid: version}`.  Sources may appear in any
    order; normalization (e.g. for versioning) is the responsibility of the
    consumer.
    """

    sources = fields.Dict(keys=fields.UUID, values=fields.String)


# --- 3. API SCAFFOLD/STUBS ---

# TODO: app.register_blueprint() in "__init__.py"
blp = Blueprint("v2", "v2", url_prefix="/api/v2", description="Journalist API")


@blp.route("/index")
@blp.etag
class Index(MethodView):
    """
    Return the index of all sources.

    If the request's `If-None-Match` header matches the new ETag, this view
    MUST return HTTP 304 with an empty response.
    """

    @blp.response(200, IndexSchema)
    def get():
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
    """
    OPTIONAL: Return the index of all sources whose UUIDs begin with `prefix`.

    If the request's `If-None-Match` header matches the new ETag, this view MUST
    return HTTP 304 with an empty response.
    """

    @blp.response(200, IndexSchema)
    def get(prefix: str):
        raise NotImplementedError


# TODO: /sources

# TODO: authentication

# TODO: operations

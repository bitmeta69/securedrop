# Journalist API v2

This package specifies the synchronization strategy for the v2 Journalist API,
including:

1.  A semi-[literate] reference implementation in Python of the structures and
    algorithms for versioning and diffing resources, which can be easily
    replicated in another language (e.g., TypeScript). You can view this
    documentation in the development shell with:

        $ python -m pydoc journalist_app/api2/__init__.py

2.  An initial set of test vectors. To keep this file self-contained and
    self-testing, these are implemented here as doctests, but they should also
    be easily replicated in another language. You can run these tests inside the
    development shell with:

        $ python -m doctest journalist_app/api2/__init__.py

3.  A scaffold (i.e., schemas and stubs) for the endpoints the new API provides.
    Most raise `NotImplementedError`; a few are implemented for demonstration.
    You can view the OpenAPI specification that flask-smorest generates from
    this scaffold by running `make dev`, logging into the Journalist Interface,
    and navigating to <http://localhost:8081/docs>.

    The OpenAPI specification can also be used to generate TypeScript types
    including JSON Schema validation (via openapi-typescript) and/or full API
    clients (via openapi-generator).

[literate]: https://en.wikipedia.org/wiki/Literate_programming

## Overview

### Initial synchronization

```mermaid

sequenceDiagram
participant Client
participant Server

alt Global
    Client -->> Server: GET /index
else Sharded by UUID prefix
    Client -->> Server: GET/index/<prefix>
end
Server ->> Client: Index<br>ETag: abcdef

Note over Client: Index.sources.keys()<br>→ SourceDelta.sources
Client -->> Server: POST /sources SourceDelta
Server ->> Client: SourceMetadataSet

Note over Client: Fetch new and changed items in SourceMetadataSet.items...
```

### Incremental synchronization

```mermaid
sequenceDiagram
participant Client
participant Server

Note over Client: Global version abcdef
Note over Client: Shard <prefix> version uvwxyz

alt Global
    Client -->> Server: GET /index<br>If-None-Match: abcdef
else Sharded by UUID prefix
    Client -->> Server: GET/index/<prefix><br>If-None-Match: uvwxyz
end

alt Up to date
    Server ->> Client: HTTP 304
else Out of date
    Server ->> Client: Index<br>ETag: ghjkli
    Note over Client: Index.sources.keys() ‒ LocalIndex.sources.keys()<br>→ SourceDelta.sources
    Client -->> Server: POST /sources SourceDelta
    Server ->> Client: SourceMetadataSet
end

Note over Client: Fetch new and changed items in SourceMetadataSet.items...
```

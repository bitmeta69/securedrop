# This file is a lightweight specification of a v2 Journalist API that
# implements the synchronization strategy proposed in "PROPOSAL.md".  The
# specification SHOULD include:
#
# 1. a semi-[literate] reference implementation in Python of the algorithms for
#    versioning and diffing resources;
#
# 2. an initial set of test vectors that MAY be used to test another
#    implementation in another language (e.g., TypeScript :-); and
#
# 3. stubs (i.e., signatures that raise NotImplementedError) for the endpoints
#    the new API provides.
#
# By "semi-literate" I mean that this file should (a) be self-sufficient for
# understanding the API's synchronization strategy and (b) produce reasonable
# output under a documentation generator like Doxygen or Sphinx.  As a stretch
# goal, this file MAY also produce an OpenAPI specification that can be consumed
# by a client (or its code-generation toolchain), including for typing and
# validating requests and responses.
#
#
# [^1]: https://en.wikipedia.org/wiki/Literate_programming

# FIXME: If flask_smorest is too heavy-weight a dependency for us to add in
# production, we can probably get away with [apispec]---or do more of this
# manually.
#
# [apispec]: https://apispec.readthedocs.io/en/latest/using_plugins.html#example-flask-and-marshmallow-plugins
import marshmallow as ma
from flask_smorest import Api, Blueprint, abort

# TODO: app.register_blueprint() in "__init__.py"
blp = Blueprint("v2", "v2", url_prefix="/api/v2", description="Journalist API")
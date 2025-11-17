"""End-to-end infrastructure for client-side write tests.

Phase 1 introduces helpers and fixtures shared by the forthcoming
single-round-trip consistency scenarios described in PLAN.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Collection

import pytest
from flask import Flask, url_for
from flask.testing import FlaskClient
from journalist_app.api2.shared import json_version
from models import Source, Submission
import loadfixeddata
from tests.utils.api_helper import get_api_headers
from werkzeug.test import TestResponse


def verify_single_round_trip_consistency(
    app: FlaskClient,
    journalist_api_token: str,
    initial_index: TestResponse,
    response: TestResponse,
    expected_changed_sources: Collection[str],
    expected_changed_items: Collection[str],
) -> None:
    """Ensure server responses contain enough metadata for one-shot convergence."""

    def _as_index_payload(resp: TestResponse) -> dict[str, dict[str, str]]:
        data = resp.json or {}
        return {
            "sources": dict(data.get("sources", {})),
            "items": dict(data.get("items", {})),
            "journalists": dict(data.get("journalists", {})),
        }

    client_index = _as_index_payload(initial_index)
    response_payload = response.json or {}

    for source_uuid, source_metadata in response_payload.get("sources", {}).items():
        if source_metadata is None:
            client_index["sources"].pop(source_uuid, None)
        else:
            client_index["sources"][source_uuid] = json_version(source_metadata)

    for item_uuid, item_metadata in response_payload.get("items", {}).items():
        if item_metadata is None:
            client_index["items"].pop(item_uuid, None)
        else:
            client_index["items"][item_uuid] = json_version(item_metadata)

    server_index = app.get(
        url_for("api2.index"),
        headers=get_api_headers(journalist_api_token),
    )
    assert server_index.status_code == 200

    client_projected_version = json_version(client_index)
    server_etag = server_index.headers.get("ETag")
    assert server_etag, "Server index response is missing an ETag"
    server_version = server_etag.strip('"')

    assert client_projected_version == server_version, (
        "Client projection does not match server index ETag"
    )

    response_sources = set(response_payload.get("sources", {}))
    for source_uuid in expected_changed_sources:
        assert source_uuid in response_sources, (
            f"Expected source {source_uuid} in BatchResponse but it was missing"
        )

    response_items = set(response_payload.get("items", {}))
    for item_uuid in expected_changed_items:
        assert item_uuid in response_items, (
            f"Expected item {item_uuid} in BatchResponse but it was missing"
        )


def load_test_data(yaml_filename: str) -> None:
    """Load canned YAML fixtures via securedrop/loadfixeddata.py."""

    yaml_path = Path(__file__).resolve().parent / "data" / yaml_filename
    if not yaml_path.exists():
        raise FileNotFoundError(f"Test data file does not exist: {yaml_path}")

    loadfixeddata.load_fixed_data(yaml_path=yaml_path, skip_empty_check=True)


@pytest.fixture
def source_for_reply_test(journalist_app: Flask) -> Source:
    """Provide a reply-ready source loaded from reply_test.yaml."""

    load_test_data("reply_test.yaml")
    with journalist_app.app_context():
        return Source.query.filter_by(journalist_designation="test reply source").one()


@pytest.fixture
def source_for_star_test(journalist_app: Flask) -> Source:
    """Provide a source ready for star/unstar workflows."""

    load_test_data("star_test.yaml")
    with journalist_app.app_context():
        return Source.query.filter_by(journalist_designation="test star source").one()


@pytest.fixture
def source_for_seen_test(journalist_app: Flask) -> Source:
    """Provide a source with unseen items for ITEM_SEEN scenarios."""

    load_test_data("seen_test.yaml")
    with journalist_app.app_context():
        return Source.query.filter_by(journalist_designation="test seen source").one()


@pytest.fixture
def source_for_item_deletion_test(journalist_app: Flask) -> tuple[Source, list[Submission]]:
    """Provide a source plus its submissions for ITEM_DELETED scenarios."""

    load_test_data("item_deletion_test.yaml")
    with journalist_app.app_context():
        source = Source.query.filter_by(journalist_designation="test delete item source").one()
        submissions = Submission.query.filter_by(source_id=source.id).all()
        return source, submissions


@pytest.fixture
def source_for_source_deletion_test(journalist_app: Flask) -> Source:
    """Provide a deletable source and its metadata for SOURCE_DELETED scenarios."""

    load_test_data("source_deletion_test.yaml")
    with journalist_app.app_context():
        return Source.query.filter_by(journalist_designation="test delete source").one()


@pytest.fixture
def source_for_conversation_deletion_test(journalist_app: Flask) -> Source:
    """Provide a source whose conversation can be deleted independently."""

    load_test_data("conversation_deletion_test.yaml")
    with journalist_app.app_context():
        return Source.query.filter_by(journalist_designation="test conversation delete").one()


def test_reply_fixture_is_visible_in_index(
    journalist_app: Flask,
    journalist_api_token: str,
    source_for_reply_test: Source,
):
    """Ensure YAML-loaded reply fixture appears in the API v2 index response."""

    source_uuid = source_for_reply_test.uuid

    with journalist_app.app_context():
        submission_uuid = (
            Submission.query.filter_by(source_id=source_for_reply_test.id)
            .with_entities(Submission.uuid)
            .scalar()
        )
        assert submission_uuid is not None

    with journalist_app.test_client() as app:
        index_response = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )

        assert index_response.status_code == 200
        assert source_uuid in index_response.json["sources"]
        assert submission_uuid in index_response.json["items"]

"""End-to-end infrastructure for client-side write tests.

Phase 1 introduces helpers and fixtures shared by the forthcoming
single-round-trip consistency scenarios described in PLAN.md.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Collection

import loadfixeddata
import pytest
from flask import Flask, url_for
from flask.testing import FlaskClient
from journalist_app.api2.shared import json_version
from journalist_app.api2.types import (
    Event,
    EventID,
    EventType,
    ItemTarget,
    ItemUUID,
    ReplyUUID,
    SourceTarget,
    SourceUUID,
    Version,
)
from models import Reply, Source, SourceStar, Submission
from tests.utils import ascii_armor, decrypt_as_journalist
from tests.utils.api_helper import get_api_headers
from werkzeug.test import TestResponse

import redwood

JOURNALIST_PUBLIC_KEY = (
    Path(__file__).resolve().parent / "files" / "test_journalist_key.pub"
).read_text()


def verify_single_round_trip_consistency(
    app: FlaskClient,
    journalist_api_token: str,
    initial_index: TestResponse,
    response: TestResponse,
    expected_changed_sources: Collection[str],
    expected_changed_items: Collection[str],
) -> None:
    """Ensure server responses contain enough metadata for single-round-trip consistency."""

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

    assert (
        client_projected_version == server_version
    ), "Client projection does not match server index ETag"

    response_sources = set(response_payload.get("sources", {}))
    for source_uuid in expected_changed_sources:
        assert (
            source_uuid in response_sources
        ), f"Expected source {source_uuid} in BatchResponse but it was missing"

    response_items = set(response_payload.get("items", {}))
    for item_uuid in expected_changed_items:
        assert (
            item_uuid in response_items
        ), f"Expected item {item_uuid} in BatchResponse but it was missing"


def load_test_data(yaml_filename: str) -> None:
    """Load canned YAML fixtures via securedrop/loadfixeddata.py."""

    yaml_path = Path(__file__).resolve().parent / "data" / yaml_filename
    if not yaml_path.exists():
        raise FileNotFoundError(f"Test data file does not exist: {yaml_path}")

    loadfixeddata.load_fixed_data(yaml_path=yaml_path, skip_empty_check=True)


def encrypt_reply_for_source(source: Source, plaintext: str) -> bytes:
    """Encrypt a reply for both the source and journalist keys."""

    destination = Path(tempfile.gettempdir()) / f"reply-{uuid.uuid4()}.gpg"
    redwood.encrypt_message(  # type: ignore[attr-defined]
        recipients=[source.public_key, JOURNALIST_PUBLIC_KEY],
        plaintext=plaintext,
        destination=destination,
    )
    ciphertext = destination.read_bytes()
    destination.unlink(missing_ok=True)
    return ciphertext


def make_source_target(source_uuid: str, version: str) -> SourceTarget:
    return SourceTarget(source_uuid=SourceUUID(source_uuid), version=Version(version))


def make_item_target(item_uuid: str, version: str) -> ItemTarget:
    return ItemTarget(item_uuid=ItemUUID(item_uuid), version=Version(version))


def make_event_id(value: str) -> EventID:
    return EventID(value)


def make_source_event(
    event_id: str,
    event_type: EventType,
    source_uuid: str,
    version: str,
    data: dict | None = None,
) -> Event:
    return Event(
        id=make_event_id(event_id),
        target=make_source_target(source_uuid, version),
        type=event_type,
        data=data,
    )


def make_item_event(
    event_id: str,
    event_type: EventType,
    item_uuid: str,
    version: str,
) -> Event:
    return Event(
        id=make_event_id(event_id),
        target=make_item_target(item_uuid, version),
        type=event_type,
    )


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


def test_reply_sent_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    test_journo: dict,
    source_for_reply_test: Source,
) -> None:
    """Ensure reply_sent events create replies and satisfy single-round-trip consistency."""

    plaintext = "the quick brown fox jumped over the lazy dog"
    with journalist_app.test_client() as app:
        source_uuid = source_for_reply_test.uuid

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200
        assert initial_index.json is not None
        source_version = initial_index.json["sources"][source_uuid]

        with journalist_app.app_context():
            initial_interaction_count = (
                Source.query.filter_by(uuid=source_uuid)
                .with_entities(Source.interaction_count)
                .scalar()
                or 0
            )
            db_source = Source.query.filter_by(uuid=source_uuid).one()

        ciphertext = encrypt_reply_for_source(db_source, plaintext)
        reply_uuid = str(uuid.uuid4())
        event = make_source_event(
            event_id="123456789",
            event_type=EventType.REPLY_SENT,
            source_uuid=source_uuid,
            version=source_version,
            data={"uuid": ReplyUUID(reply_uuid), "reply": ascii_armor(ciphertext)},
        )

        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200
        assert response.json is not None
        assert response.json["events"][event.id] == [200, None]
        assert reply_uuid in response.json["items"]
        assert source_uuid in response.json["sources"]

        with journalist_app.app_context():
            reply = Reply.query.filter_by(uuid=reply_uuid).one()
            assert reply.source.uuid == source_uuid
            assert reply.journalist.uuid == test_journo["uuid"]
            updated_interaction_count = (
                Source.query.filter_by(uuid=source_uuid)
                .with_entities(Source.interaction_count)
                .scalar()
            )
            assert updated_interaction_count == initial_interaction_count + 1

        download = app.get(
            url_for("api.download_reply", source_uuid=source_uuid, reply_uuid=reply_uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert download.status_code == 200
        assert decrypt_as_journalist(download.data).decode() == plaintext

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=response,
            expected_changed_sources={source_uuid},
            expected_changed_items={reply_uuid},
        )

        duplicate = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert duplicate.json is not None
        assert duplicate.json["events"][event.id] == [208, None]


def test_source_star_unstar_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    source_for_star_test: Source,
) -> None:
    """Starring toggles metadata and surfaces updates for single-round-trip consistency."""

    with journalist_app.test_client() as app:
        source_uuid = source_for_star_test.uuid
        source_id = source_for_star_test.id

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200
        assert initial_index.json is not None
        source_version = initial_index.json["sources"][source_uuid]

        star_event = make_source_event(
            event_id="111111111",
            event_type=EventType.SOURCE_STARRED,
            source_uuid=source_uuid,
            version=source_version,
        )
        star_response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(star_event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert star_response.status_code == 200
        assert star_response.json is not None
        assert star_response.json["events"][star_event.id] == [200, None]
        assert star_response.json["sources"][source_uuid]["is_starred"] is True

        with journalist_app.app_context():
            star_row = SourceStar.query.filter_by(source_id=source_id).one()
            assert star_row.starred is True

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=star_response,
            expected_changed_sources={source_uuid},
            expected_changed_items=set(),
        )

        refreshed_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert refreshed_index.status_code == 200
        assert refreshed_index.json is not None
        refreshed_version = refreshed_index.json["sources"][source_uuid]

        unstar_event = make_source_event(
            event_id="222222222",
            event_type=EventType.SOURCE_UNSTARRED,
            source_uuid=source_uuid,
            version=refreshed_version,
        )
        unstar_response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(unstar_event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert unstar_response.status_code == 200
        assert unstar_response.json is not None
        assert unstar_response.json["events"][unstar_event.id] == [200, None]
        assert unstar_response.json["sources"][source_uuid]["is_starred"] is False

        with journalist_app.app_context():
            star_row = SourceStar.query.filter_by(source_id=source_id).one()
            assert star_row.starred is False

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=refreshed_index,
            response=unstar_response,
            expected_changed_sources={source_uuid},
            expected_changed_items=set(),
        )


def test_batch_item_seen_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    test_journo: dict,
    source_for_seen_test: Source,
) -> None:
    """Marking a batch of items as seen updates metadata in a single response."""

    with journalist_app.test_client() as app:
        source_uuid = source_for_seen_test.uuid

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200

        with journalist_app.app_context():
            source = Source.query.filter_by(uuid=source_uuid).one()
            submissions = Submission.query.filter_by(source_id=source.id).all()
            replies = Reply.query.filter_by(source_id=source.id).all()
            for submission in submissions:
                assert submission.downloaded is False
            for reply in replies:
                assert not reply.seen_replies
            submission_uuids = [submission.uuid for submission in submissions]

        all_items = submissions + replies
        item_uuids = [item.uuid for item in all_items]

        events = []
        assert initial_index.json is not None
        for offset, item_uuid in enumerate(item_uuids):
            item_version = initial_index.json["items"][item_uuid]
            events.append(
                make_item_event(
                    event_id=str(333000000 + offset),
                    event_type=EventType.ITEM_SEEN,
                    item_uuid=item_uuid,
                    version=item_version,
                )
            )

        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event) for event in events]},
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200
        assert response.json is not None
        for event in events:
            assert response.json["events"][event.id] == [200, None]

        assert source_uuid in response.json["sources"]
        for item_uuid in item_uuids:
            payload = response.json["items"][item_uuid]
            assert payload is not None
            assert test_journo["uuid"] in payload.get("seen_by", [])

        with journalist_app.app_context():
            for submission_uuid in submission_uuids:
                submission = Submission.query.filter_by(uuid=submission_uuid).one()
                assert submission.downloaded is True

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=response,
            expected_changed_sources={source_uuid},
            expected_changed_items=set(item_uuids),
        )

        duplicate = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event) for event in events]},
            headers=get_api_headers(journalist_api_token),
        )
        assert duplicate.json is not None
        for event in events:
            assert duplicate.json["events"][event.id][0] in {208, 410}


def test_item_deleted_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    source_for_item_deletion_test: tuple[Source, list[Submission]],
) -> None:
    """Deleting a single item returns a tombstone for that item."""

    with journalist_app.test_client() as app:
        source, submissions = source_for_item_deletion_test
        item_uuid = submissions[0].uuid

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200
        assert initial_index.json is not None
        item_version = initial_index.json["items"][item_uuid]

        event = make_item_event(
            event_id="333333333",
            event_type=EventType.ITEM_DELETED,
            item_uuid=item_uuid,
            version=item_version,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200
        assert response.json is not None
        assert response.json["events"][event.id] == [200, None]
        assert response.json["items"][item_uuid] is None

        with journalist_app.app_context():
            assert Submission.query.filter_by(uuid=item_uuid).one_or_none() is None

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=response,
            expected_changed_sources=set(),
            expected_changed_items={item_uuid},
        )

        duplicate = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert duplicate.json is not None
        assert duplicate.json["events"][event.id][0] in {208, 410}


def test_source_deleted_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    source_for_source_deletion_test: Source,
) -> None:
    """Deleting a source returns tombstones for the source and its items."""

    with journalist_app.test_client() as app:
        source_uuid = source_for_source_deletion_test.uuid

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200
        assert initial_index.json is not None
        source_version = initial_index.json["sources"][source_uuid]

        with journalist_app.app_context():
            source = Source.query.filter_by(uuid=source_uuid).one()
            submissions = Submission.query.filter_by(source_id=source.id).all()
            item_uuids = {submission.uuid for submission in submissions}

        wrong_event = make_source_event(
            event_id="444444444",
            event_type=EventType.SOURCE_DELETED,
            source_uuid=source_uuid,
            version="wrong-version",
        )
        wrong_response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(wrong_event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert wrong_response.json is not None
        assert wrong_response.json["events"][wrong_event.id][0] == 409

        event = make_source_event(
            event_id="555555555",
            event_type=EventType.SOURCE_DELETED,
            source_uuid=source_uuid,
            version=source_version,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200
        assert response.json is not None
        assert response.json["events"][event.id] == [200, None]
        assert response.json["sources"][source_uuid] is None
        for item_uuid in item_uuids:
            assert response.json["items"][item_uuid] is None

        with journalist_app.app_context():
            assert Source.query.filter_by(uuid=source_uuid).one_or_none() is None
            for item_uuid in item_uuids:
                assert Submission.query.filter_by(uuid=item_uuid).one_or_none() is None

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=response,
            expected_changed_sources={source_uuid},
            expected_changed_items=item_uuids,
        )

        duplicate = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert duplicate.json is not None
        assert duplicate.json["events"][event.id][0] in {208, 410}


def test_source_conversation_deleted_single_round_trip(
    journalist_app: Flask,
    journalist_api_token: str,
    source_for_conversation_deletion_test: Source,
) -> None:
    """Deleting a conversation purges items while preserving the source record."""

    with journalist_app.test_client() as app:
        source_uuid = source_for_conversation_deletion_test.uuid

        initial_index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert initial_index.status_code == 200
        assert initial_index.json is not None
        source_version = initial_index.json["sources"][source_uuid]

        with journalist_app.app_context():
            source = Source.query.filter_by(uuid=source_uuid).one()
            submissions = Submission.query.filter_by(source_id=source.id).all()
            replies = Reply.query.filter_by(source_id=source.id).all()
            star_record = SourceStar.query.filter_by(source_id=source.id).one_or_none()
            was_starred = star_record.starred if star_record else False
            designation = source.journalist_designation
            item_uuids = {submission.uuid for submission in submissions}.union(
                {reply.uuid for reply in replies}
            )

        event = make_source_event(
            event_id="666666666",
            event_type=EventType.SOURCE_CONVERSATION_DELETED,
            source_uuid=source_uuid,
            version=source_version,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200
        assert response.json is not None
        assert response.json["events"][event.id] == [200, None]
        assert response.json["sources"][source_uuid] is not None
        for item_uuid in item_uuids:
            assert response.json["items"][item_uuid] is None

        with journalist_app.app_context():
            source = Source.query.filter_by(uuid=source_uuid).one()
            assert source.journalist_designation == designation
            star_record = SourceStar.query.filter_by(source_id=source.id).one_or_none()
            if was_starred:
                assert star_record is not None
                assert star_record.starred is True
            else:
                assert star_record is None
            for item_uuid in item_uuids:
                assert Submission.query.filter_by(uuid=item_uuid).one_or_none() is None
                assert Reply.query.filter_by(uuid=item_uuid).one_or_none() is None

        verify_single_round_trip_consistency(
            app=app,
            journalist_api_token=journalist_api_token,
            initial_index=initial_index,
            response=response,
            expected_changed_sources={source_uuid},
            expected_changed_items=item_uuids,
        )

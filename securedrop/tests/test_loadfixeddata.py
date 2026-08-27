from types import SimpleNamespace
from unittest import mock

import loadfixeddata


def test_import_reply_without_pre_encrypted_file_uses_reply_filename(tmp_path, mocker, capsys):
    source = SimpleNamespace(
        filesystem_id="source-fs-id",
        interaction_count=0,
        journalist_filename="source-name",
    )
    journalist = mock.sentinel.journalist
    storage = mocker.patch.object(loadfixeddata.Storage, "get_default").return_value
    storage.path.return_value = str(tmp_path / "encrypted-reply.gpg")
    encryption_manager = mocker.patch.object(
        loadfixeddata.EncryptionManager, "get_default"
    ).return_value
    reply_class = mocker.patch.object(loadfixeddata, "Reply")
    mocker.patch.object(loadfixeddata.db, "session")
    sources_data = [
        {
            "uuid": "source-uuid",
            "items": [
                {
                    "uuid": "reply-uuid",
                    "kind": "reply",
                    "journalist_uuid": "journalist-uuid",
                    "content": "reply content",
                    "deleted_by_source": False,
                }
            ],
        }
    ]

    submissions, replies = loadfixeddata.import_submissions_and_replies(
        sources_data=sources_data,
        uuid_to_source={"source-uuid": source},
        uuid_to_journalist={"journalist-uuid": journalist},
        yaml_dir=tmp_path,
    )

    expected_filename = "1-source-name-reply.gpg"
    output = capsys.readouterr().out
    assert f"Warning: no pre-encrypted file for reply: {expected_filename}" in output
    assert f"Imported reply: {expected_filename}" in output
    assert submissions == {}
    assert replies == {"reply-uuid": reply_class.return_value}
    encryption_manager.encrypt_journalist_reply.assert_called_once_with(
        for_source=source,
        reply_in="reply content",
        encrypted_reply_path_out=tmp_path / "encrypted-reply.gpg",
    )
    reply_class.assert_called_once_with(journalist, source, expected_filename, storage)

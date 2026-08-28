import loadfixeddata
import pytest


def test_import_rejects_unsupported_item_kind_before_side_effects(mocker, tmp_path):
    source = object()
    record_source_interaction = mocker.patch.object(loadfixeddata, "record_source_interaction")
    get_storage = mocker.patch.object(loadfixeddata.Storage, "get_default")
    get_encryption_manager = mocker.patch.object(loadfixeddata.EncryptionManager, "get_default")
    sources_data = [
        {
            "uuid": "source-uuid",
            "items": [{"uuid": "item-uuid", "kind": "unsupported"}],
        }
    ]

    expected_error = "Unsupported item kind 'unsupported' for item 'item-uuid'"
    with pytest.raises(ValueError, match=expected_error):
        loadfixeddata.import_submissions_and_replies(
            sources_data=sources_data,
            uuid_to_source={"source-uuid": source},
            uuid_to_journalist={},
            yaml_dir=tmp_path,
        )

    record_source_interaction.assert_not_called()
    get_storage.assert_not_called()
    get_encryption_manager.assert_not_called()

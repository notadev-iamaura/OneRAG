from app.lib.weaviate_setup import _document_schema_properties


def test_document_schema_contains_upload_and_management_contract_fields() -> None:
    property_names = {prop.name for prop in _document_schema_properties()}

    assert {
        "content",
        "embedding",
    } - property_names == {"embedding"}
    assert {
        "document_id",
        "source_file",
        "file_type",
        "file_size",
        "chunk_index",
        "total_chunks",
        "load_timestamp",
        "metadata_json",
        "page_number",
        "keys",
        "created_at",
    }.issubset(property_names)

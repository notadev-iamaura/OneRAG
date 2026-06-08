import pytest
from pydantic import ValidationError

from app.api.documents import BulkDeleteAllRequest


def test_bulk_delete_all_request_requires_confirm_code() -> None:
    with pytest.raises(ValidationError):
        BulkDeleteAllRequest()


def test_bulk_delete_all_request_rejects_empty_confirm_code() -> None:
    with pytest.raises(ValidationError):
        BulkDeleteAllRequest(confirm_code="")


def test_bulk_delete_all_request_accepts_exact_confirm_code() -> None:
    request = BulkDeleteAllRequest(confirm_code="DELETE_ALL_DOCUMENTS")

    assert request.confirm_code == "DELETE_ALL_DOCUMENTS"

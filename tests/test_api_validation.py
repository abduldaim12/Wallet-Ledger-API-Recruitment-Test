import pytest
from pydantic import ValidationError

from api import BalanceRequest, _invalid_request_response


@pytest.mark.parametrize("amount", ["10", 10.0, 10.5, True])
def test_credit_model_rejects_non_integer_json_amounts(amount):
    with pytest.raises(ValidationError):
        BalanceRequest.model_validate({"user_id": "u123", "amount": amount})


def test_credit_model_accepts_integer_amount_and_ignores_unknown_fields():
    payload = BalanceRequest.model_validate(
        {"user_id": "u123", "amount": 10, "unused": "ignored"}
    )

    assert payload.amount == 10
    assert payload.user_id == "u123"


def test_request_validation_errors_use_contract_shape():
    response = _invalid_request_response()

    assert response.status_code == 400
    assert response.body == b'{"error":"invalid_request","message":"malformed JSON or invalid input"}'

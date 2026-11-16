import os
from types import SimpleNamespace

import pytest

from api import LedgerError, require_auth


def test_missing_auth_header_raises_unauthorized():
    request = SimpleNamespace(headers={})
    os.environ["API_TOKEN"] = "recruitment-test-token"
    with pytest.raises(LedgerError) as exc:
        require_auth(request)
    assert exc.value.status_code == 401
    assert exc.value.code == "unauthorized"


def test_wrong_scheme_raises_unauthorized():
    request = SimpleNamespace(headers={"authorization": "Basic abc"})
    os.environ["API_TOKEN"] = "recruitment-test-token"
    with pytest.raises(LedgerError) as exc:
        require_auth(request)
    assert exc.value.status_code == 401


def test_valid_bearer_token_is_accepted():
    request = SimpleNamespace(headers={"authorization": "Bearer recruitment-test-token"})
    os.environ["API_TOKEN"] = "recruitment-test-token"
    require_auth(request)


def test_valid_bearer_token_with_extra_whitespace_is_accepted():
    request = SimpleNamespace(headers={"authorization": "  bearer\t\trecruitment-test-token  "})
    os.environ["API_TOKEN"] = "recruitment-test-token"
    require_auth(request)

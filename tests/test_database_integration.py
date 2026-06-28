import pytest

from tests.conftest import ClientFactory
from tests.database_helpers import get_database_url


@pytest.mark.integration
def test_database_connection(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            res = client.get("/ready")

            assert res.status_code == 200
            assert res.json() == {"status": "ready", "database": "ok"}

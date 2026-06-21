import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from testcontainers.postgres import PostgresContainer

POSTGRES_IMAGE = "postgres:16-alpine"
DOCKER_UNAVAILABLE_MESSAGE = (
    'Docker is required for this integration test; run pytest -m "not integration" to skip it'
)


def docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False

    result = subprocess.run(
        ["docker", "info"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.returncode == 0


@contextmanager
def get_database_url() -> Iterator[str]:
    if not docker_is_available():
        pytest.fail(DOCKER_UNAVAILABLE_MESSAGE)

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield str(postgres.get_connection_url())

from pathlib import Path
import pytest

from powerapps_sim.web import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "projects")
    app.config.update(TESTING=True)
    yield app
    app.extensions["workspace"].runtime.close()


@pytest.fixture
def runtime(app):
    return app.extensions["workspace"].runtime


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def post(client):
    return lambda path, body: client.post(path, json=body, headers={"X-Emulator-Request": "1"})

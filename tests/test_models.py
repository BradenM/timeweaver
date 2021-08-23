import shutil
from pathlib import Path
from tempfile import mkdtemp

from tinydb import Query
from ward import fixture, test

from twtw.db import TableState
from twtw.models.config import Config


@fixture
def tmp_path():
    _tmp_path = Path(mkdtemp())
    yield _tmp_path
    shutil.rmtree(_tmp_path, ignore_errors=True)


@fixture
def tmp_db(p: Path = tmp_path) -> Path:
    db_path = p / "db.json"
    TableState.db_path = db_path
    return db_path


@fixture
def tmp_cfg(p=tmp_db):
    config = Config()
    yield config


@test("creates config defaults")
def _(cfg: Config = tmp_cfg):
    cfg.save()
    results = cfg.table.all()
    assert results
    assert cfg.table
    default_prof = cfg.table.get(Query().PROFILE == "default")
    assert default_prof
    for key in (
        "TEAMWORK_HOST",
        "API_KEY",
        "GIT_USER",
    ):
        assert key in default_prof
    assert isinstance(default_prof["GIT_USER"], str)

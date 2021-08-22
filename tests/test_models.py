import shutil
from pathlib import Path
from tempfile import mkdtemp

from tinydb import Query
from ward import fixture, test

from twtw.models.config import Config


@fixture
def tmp_path():
    _tmp_path = Path(mkdtemp())
    yield _tmp_path
    shutil.rmtree(_tmp_path, ignore_errors=True)


@fixture
def config(p: Path = tmp_path):
    db_path = p / "db.json"
    config = Config(db_path=db_path)
    yield config


@test("sets db up")
def _(p: Path = tmp_path):
    db_path = p / "db.json"
    config = Config(db_path=db_path)
    assert config.db_path == db_path
    assert config.db is not None
    assert config.table is not None


@test("creates config defaults")
def _ca(cfg: Config = config):
    cfg.save()
    results = cfg.table.all()
    assert results
    assert len(results) >= 2
    for key in (
        "API_KEY",
        "GIT_USER",
    ):
        assert cfg.table.contains(Query().key == key)

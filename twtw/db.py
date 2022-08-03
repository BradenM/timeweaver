from pathlib import Path

import attr
import git
from click import get_app_dir
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb_serialization import SerializationMiddleware, Serializer
from tinydb_serialization.serializers import DateTimeSerializer


class PathSerializer(Serializer):
    OBJ_CLASS = Path

    def encode(self, obj: Path) -> str:
        return str(obj)

    def decode(self, s: str) -> Path:
        return Path(s)


class CommitSerializer(Serializer):
    OBJ_CLASS = git.Commit

    def encode(self, obj: git.Commit) -> str:
        _repo_dir = str(obj.repo.working_dir)
        _commit_hash = "@".join([_repo_dir, str(obj)])
        return _commit_hash

    def decode(self, s: str) -> git.Commit:
        _repo_dir, commit_sha = s.split("@")
        _repo_path = Path(_repo_dir)
        repo = git.Repo(_repo_path)
        print("getting commit from repo:", s, repo, commit_sha)
        return repo.commit(commit_sha)


def create_db_storage() -> SerializationMiddleware:
    storage = SerializationMiddleware(JSONStorage)
    storage.register_serializer(PathSerializer(), "TinyPath")
    storage.register_serializer(DateTimeSerializer(), "TinyDate")
    storage.register_serializer(CommitSerializer(), "TinyCommit")
    return storage


def _create_db(db_path: Path) -> TinyDB:
    storage = create_db_storage()
    return TinyDB(str(db_path), storage=storage, sort_keys=True, indent=4, separators=(",", ": "))


def _on_update_path(instance: "_TableState", attrib: attr.Attribute, new_value: Path) -> Path:
    new_value.parent.mkdir(exist_ok=True)
    instance.db = _create_db(new_value)
    return new_value


@attr.s(auto_attribs=True, collect_by_mro=True)
class _TableState:
    db_path: Path = attr.ib(
        factory=lambda: Path(get_app_dir("twtw")) / "db.json", on_setattr=_on_update_path
    )
    db: TinyDB = attr.ib()

    @db.default
    def setup_db(self) -> TinyDB:
        self.db_path.parent.mkdir(exist_ok=True)
        return _create_db(self.db_path)


TableState = _TableState()

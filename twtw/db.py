from pathlib import Path

import attr
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


def create_db_storage() -> SerializationMiddleware:
    storage = SerializationMiddleware(JSONStorage)
    storage.register_serializer(PathSerializer(), "TinyPath")
    storage.register_serializer(DateTimeSerializer(), "TinyDate")
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

from pathlib import Path

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

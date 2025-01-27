from pathlib import Path

import git
import orjson
from sqlalchemy import JSON, String, TypeDecorator



class PathType(TypeDecorator):
    """SQLAlchemy type for storing Path objects."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, Path):
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return Path(value)
        return value


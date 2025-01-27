from __future__ import annotations

from pathlib import Path

from click import get_app_dir
from sqlmodel import SQLModel, create_engine

from twtw.models.models import *  # noqa


DB_PATH = Path(get_app_dir("timeweaver")) / "timeweaver.db"
DB_URI = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URI)


def create_db_and_tables():
    DB_PATH.parent.mkdir(exist_ok=True, parents=True)
    SQLModel.metadata.create_all(engine)


if __name__ == "__main__":
    create_db_and_tables()

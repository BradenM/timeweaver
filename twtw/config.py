# -*- coding: utf-8 -*-

"""TWTW Config."""

import json
from dataclasses import dataclass
from pathlib import Path

import click

CONFIG_ROOT = Path(click.get_app_dir("twtw"))
CONFIG_PATH = CONFIG_ROOT / "config.json"


@dataclass
class TWTWConfig:
    api_key: str

    @classmethod
    def default_config(cls) -> "TWTWConfig":
        return cls(api_key="")

    @classmethod
    def from_path(cls, path: Path) -> "TWTWConfig":
        data = json.loads(path.read_text())
        return cls(**data)

    def save(self):
        data = self.__dict__
        CONFIG_PATH.write_text(json.dumps(data))


def load_config() -> TWTWConfig:
    if not CONFIG_PATH.exists():
        CONFIG_ROOT.mkdir(exist_ok=True)
        CONFIG_PATH.touch()
        return TWTWConfig.default_config()
    return TWTWConfig.from_path(CONFIG_PATH)

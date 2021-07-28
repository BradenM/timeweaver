#!/usr/bin/env python3
import re
from pathlib import Path
from typing import Optional, List

import git
import typer
from rich import print

from twtw import (
    aggregate as twaggregate,
    config as twconfig,
    csv as twcsv,
    recent as twrecent,
    tw,
)
from twtw.teamwork import load_entries

app = typer.Typer()


@app.callback()
def cli():
    """ArroyoDev Timewarrior Integration Entrypoint"""


@app.command()
def recent(days: Optional[float] = 3):
    """Preview recent entries."""
    twrecent.get_recent(days=days)


@app.command()
def aggregate():
    """Aggregate time entries.."""
    twaggregate.get_aggregates()


@app.command()
def sync(commit: bool = False):
    """arroyoDev Timewarrior Integration Entrypoint"""
    load_entries(commit=commit)


@app.command()
def csv(csv_path: Path, commit: bool = False):
    """arroyoDev CSV Teamwork integration entrypoint."""
    csv_path = Path(csv_path)
    twcsv.load_entries(csv_path, commit=commit)


@app.command()
def set_key(api_key: str):
    """Set Api Key."""
    config = twconfig.load_config()
    config.api_key = api_key
    config.save()


if __name__ == "__main__":
    app()

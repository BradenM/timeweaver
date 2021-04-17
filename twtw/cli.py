from pathlib import Path

import click

from . import aggregate as twaggregate
from . import config as twconfig
from . import csv as twcsv
from . import recent as twrecent
from .teamwork import load_entries


@click.group()
def cli():
    """ArroyoDev Timewarrior Integration Entrypoint"""


@cli.command()
def recent():
    """Preview recent entries."""
    twrecent.get_recent()


@cli.command()
def aggregate():
    """Aggregate time entries.."""
    twaggregate.get_aggregates()


@click.option("-c", "--commit", is_flag=True, default=False)
@cli.command()
def sync(commit=False):
    """arroyoDev Timewarrior Integration Entrypoint"""
    load_entries(commit=commit)


@click.option("-c", "--commit", is_flag=True, default=False)
@click.argument(
    "csv_path", type=click.Path(file_okay=True, dir_okay=False, exists=True)
)
@cli.command()
def csv(csv_path, commit=False):
    """arroyoDev CSV Teamwork integration entrypoint."""
    csv_path = Path(csv_path)
    twcsv.load_entries(csv_path, commit=commit)


@click.argument("api_key")
@cli.command()
def set_key(api_key: str):
    """Set Api Key."""
    config = twconfig.load_config()
    config.api_key = api_key
    config.save()


if __name__ == "__main__":
    cli()

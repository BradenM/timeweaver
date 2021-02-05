import click
from .teamwork import load_entries
from pathlib import Path
from . import recent as twrecent, aggregate as twaggregate, csv as twcsv


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


if __name__ == "__main__":
    cli()

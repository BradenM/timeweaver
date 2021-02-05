import click
from .teamwork import load_entries
from . import recent as twrecent
from . import aggregate as twaggregate


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
    """ArroyoDev Timewarrior Integration Entrypoint"""
    load_entries(commit=commit)


if __name__ == "__main__":
    cli()

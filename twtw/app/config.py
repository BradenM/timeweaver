import typer
from rich import print

from twtw.models.config import config

app = typer.Typer()


@app.callback()
def config():  # noqa: F811
    """Manage TWTW config."""


@app.command(name="list")
def do_list():
    """List current config."""
    print(config)


@app.command(name="set")
def do_set(key: str, value: str):
    """Set config values."""
    _config = config.copy(update={key: value}, deep=True)
    _config.save()
    print(f"[b bright_green]Set {key} => {value}")
    print(_config)

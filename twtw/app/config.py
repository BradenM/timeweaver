import typer
from rich import print

from twtw.db import TableState
from twtw.models.config import config as app_config

app = typer.Typer()


@app.callback()
def config(ctx: typer.Context):  # noqa: F811
    """Manage TWTW config."""
    
    def _close_db():
        print("Closing database...")
        TableState.db.close()

    ctx.call_on_close(_close_db)


@app.command(name="list")
def do_list():
    """List current config."""
    print(app_config)


@app.command(name="set")
def do_set(key: str, value: str):
    """Set config values."""
    _config = app_config.copy(update={key: value}, deep=True)
    _config.save()
    print(f"[b bright_green]Set {key} => {value}")
    print(_config)

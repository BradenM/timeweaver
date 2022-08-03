import typer
from rich import print

from twtw.models.config import config

app = typer.Typer()


@app.command(name="list")
def do_list():
    print(config)


@app.command(name="set")
def do_set(key: str, value: str):
    _config = config.copy(update={key: value}, deep=True)
    _config.save()
    print("[b bright_green]Set {} => {}".format(key, value))
    print(_config)

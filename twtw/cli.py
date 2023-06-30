#!/usr/bin/env python3

import typer
from rich.traceback import install

from twtw.app.config import app as config_app
from twtw.app.log import app as log_app
from twtw.app.project import app as project_app
from twtw.app.recent import app as recent_app
from twtw.logger import VerbosityLevel, configure_log

install(show_locals=True, suppress=["typer", "click", "transitions"])

app = typer.Typer()
app.add_typer(config_app, name="config")
app.add_typer(project_app, name="project")
app.add_typer(log_app, name="log")
app.add_typer(recent_app, name="recent")


@app.callback(no_args_is_help=True)
def cli(
    verbosity: int = typer.Option(
        VerbosityLevel.ERROR,
        "--verbose",
        "-v",
        callback=configure_log,
        count=True,
        max=VerbosityLevel.ALL,
    )
):
    """TimeWarrior TeamWork CLI"""


if __name__ == "__main__":
    app()

import click
from textread import __version__


@click.group()
@click.version_option(__version__)
def main():
    """Context-aware link reader."""

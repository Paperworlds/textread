import click
from textread import __version__
from textread.cache import cache_group
from textread.context import context_group


@click.group()
@click.version_option(__version__)
def main():
    """Context-aware link reader."""


main.add_command(cache_group)
main.add_command(context_group)

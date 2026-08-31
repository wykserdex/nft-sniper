"""CLI: разбор аргументов и команда version."""

import pytest

from nftsniper import __version__
from nftsniper.entrypoints.cli.main import main


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["version"])
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_unknown_command_exits_with_error() -> None:
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def test_serve_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])

from pathlib import Path
from subprocess import call

from . import src_path, source_path

pyproject_path = source_path / "pyproject.toml"
pyproject_path = pyproject_path.resolve()


def lint():
    call(f"python -m flakehell lint {src_path}".split(" "))


def fix_black():
    call(f"python -m black {src_path} --config {pyproject_path}".split(" "))


def fix_isort():
    call(f"python -m isort -rc {src_path}".split(" "))


def fix():
    fix_black()
    fix_isort()

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

venv := ".venv/bin"

default:
    @just --list

install:
    poetry sync --with dev
    {{venv}}/pre-commit install

lock:
    poetry lock

test:
    {{venv}}/pytest

typecheck:
    {{venv}}/pyright

lint:
    {{venv}}/ruff check src/

fix:
    {{venv}}/ruff check --fix src/

release version:
    ./scripts/release_checks.sh {{version}}
    poetry lock
    poetry version {{version}}
    just install
    just test
    git add pyproject.toml poetry.lock
    git commit -m "release: v{{version}}"
    git tag -a v{{version}} -m "v{{version}}"
    git push --follow-tags

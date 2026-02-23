set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    @just --list

install:
    poetry sync --with dev

lock:
    poetry lock

test:
    poetry run pytest

typecheck:
    poetry run pyright

release version:
    ./scripts/release_checks.sh {{version}}
    poetry lock
    poetry version {{version}}
    just install
    poetry run pytest
    git add pyproject.toml poetry.lock
    git commit -m "release: v{{version}}"
    git tag -a v{{version}} -m "v{{version}}"
    git push --follow-tags

"""Online backup guarantees against an exclusively fictional, file-backed database."""

import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import StringIO
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from wealth.management.commands import backup


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE fictional (amount INTEGER)")
        db.execute("INSERT INTO fictional VALUES (12345)")
        db.commit()
    monkeypatch.setattr(backup, "settings", SimpleNamespace(DATABASES={"default": {"NAME": path}}))
    return path


def run_backup(path):
    call_command("backup", str(path), stdout=StringIO())


def test_private_before_copy_and_restorable(source, tmp_path, monkeypatch):
    connect = sqlite3.connect
    connections = []

    def inspect(path, **kwargs):
        if not kwargs.get("uri"):
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        connection = connect(path, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(backup.sqlite3, "connect", inspect)
    destination = tmp_path / "backup.sqlite3"
    previous = os.umask(0o022)
    try:
        run_backup(destination)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    with closing(connect(destination)) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert restored.execute("SELECT * FROM fictional").fetchall() == [(12345,)]
    assert not list(tmp_path.glob(".tally-backup-*"))


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling"])
def test_collisions_preserve_destination(source, tmp_path, kind):
    destination = tmp_path / "existing"
    if kind == "file":
        destination.write_bytes(b"keep me")
    elif kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(source if kind == "symlink" else tmp_path / "absent")
    before = source.read_bytes()
    with pytest.raises(CommandError, match="already exists"):
        run_backup(destination)
    assert source.read_bytes() == before
    if kind == "file":
        assert destination.read_bytes() == b"keep me"
    elif kind == "directory":
        assert destination.is_dir()
    else:
        assert destination.is_symlink()
    assert not list(tmp_path.glob(".tally-backup-*"))


def test_concurrent_creation_has_one_winner(source, tmp_path, monkeypatch):
    destination = tmp_path / "winner.sqlite3"
    ready = Barrier(2)
    link = os.link

    def race(*args):
        ready.wait(timeout=5)
        return link(*args)

    monkeypatch.setattr(backup.os, "link", race)

    def attempt(_):
        try:
            run_backup(destination)
            return "created"
        except CommandError:
            return "collision"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["collision", "created"]
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert not list(tmp_path.glob(".tally-backup-*"))


@pytest.mark.parametrize("stage", ["copy", "publish"])
def test_failure_cleans_private_partial(source, tmp_path, monkeypatch, stage):
    if stage == "copy":
        connect = sqlite3.connect

        class BrokenSource:
            def backup(self, destination):
                destination.execute("CREATE TABLE partial (value INTEGER)")
                destination.commit()
                raise sqlite3.OperationalError("injected copy failure")

            def close(self):
                self.closed = True

        broken = BrokenSource()
        monkeypatch.setattr(backup.sqlite3, "connect", lambda path, **kw: broken if kw.get("uri") else connect(path))
    else:
        def fail(*args):
            raise OSError("injected publish failure")

        monkeypatch.setattr(backup.os, "link", fail)
    destination = tmp_path / "failed.sqlite3"
    with pytest.raises(CommandError, match="Backup failed"):
        run_backup(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".tally-backup-*"))
    if stage == "copy":
        assert broken.closed


def test_missing_source_is_not_created(source, tmp_path):
    source.unlink()
    with pytest.raises(CommandError, match="Backup failed"):
        run_backup(tmp_path / "backup.sqlite3")
    assert not source.exists()
    assert not list(tmp_path.glob(".tally-backup-*"))

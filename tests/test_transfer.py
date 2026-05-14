from pathlib import Path

import pytest

from src.utils.transfer import copy_files, delete_sources, move_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file(parent: Path, name: str, content: str = "data") -> Path:
    p = parent / name
    p.write_text(content)
    return p


def make_dir(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# copy_files
# ---------------------------------------------------------------------------

class TestCopyFiles:
    def test_copy_single_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        f = make_file(src, "hello.txt", "world")

        result = copy_files([f], dst)
        assert len(result) == 1
        assert result[0] == dst / "hello.txt"
        assert result[0].read_text() == "world"

    def test_copy_multiple_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        files = [make_file(src, f"f{i}.txt", str(i)) for i in range(3)]

        result = copy_files(files, dst)
        assert len(result) == 3
        for i, p in enumerate(result):
            assert p.read_text() == str(i)

    def test_copy_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        d = make_dir(src, "sub")
        make_file(d, "nested.txt", "deep")

        result = copy_files([d], dst)
        assert len(result) == 1
        assert (dst / "sub" / "nested.txt").read_text() == "deep"

    def test_copy_non_existent_source(self, tmp_path: Path) -> None:
        dst = tmp_path / "dst"
        dst.mkdir()
        result = copy_files([tmp_path / "nonexistent.txt"], dst)
        assert result == []

    def test_copy_creates_dest_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"  # doesn't exist yet
        src.mkdir()
        f = make_file(src, "a.txt", "hello")

        result = copy_files([f], dst)
        assert dst.is_dir()
        assert len(result) == 1

    def test_progress_callback(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        files = [make_file(src, f"f{i}.txt") for i in range(3)]

        calls: list[tuple[int, int]] = []

        def progress(current: int, total: int) -> None:
            calls.append((current, total))

        copy_files(files, dst, progress=progress)
        assert calls == [(1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# move_files
# ---------------------------------------------------------------------------

class TestMoveFiles:
    def test_move_single_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        f = make_file(src, "hello.txt", "world")

        result = move_files([f], dst)
        assert len(result) == 1
        assert result[0] == dst / "hello.txt"
        assert result[0].read_text() == "world"
        assert not f.exists()  # source gone

    def test_move_multiple_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        files = [make_file(src, f"f{i}.txt") for i in range(3)]

        result = move_files(files, dst)
        assert len(result) == 3
        assert all(p.exists() for p in result)
        assert all(not p.exists() for p in files)  # all sources gone

    def test_move_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        d = make_dir(src, "sub")
        make_file(d, "nested.txt", "deep")

        result = move_files([d], dst)
        assert len(result) == 1
        assert (dst / "sub" / "nested.txt").read_text() == "deep"
        assert not d.exists()  # dir moved

    def test_move_non_existent_source(self, tmp_path: Path) -> None:
        dst = tmp_path / "dst"
        dst.mkdir()
        result = move_files([tmp_path / "nonexistent.txt"], dst)
        assert result == []

    def test_move_creates_dest_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        f = make_file(src, "a.txt", "hello")

        result = move_files([f], dst)
        assert dst.is_dir()
        assert len(result) == 1

    def test_progress_callback(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        files = [make_file(src, f"f{i}.txt") for i in range(3)]

        calls: list[tuple[int, int]] = []

        def progress(current: int, total: int) -> None:
            calls.append((current, total))

        move_files(files, dst, progress=progress)
        assert calls == [(1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# delete_sources
# ---------------------------------------------------------------------------

class TestDeleteSources:
    def test_delete_file(self, tmp_path: Path) -> None:
        f = make_file(tmp_path, "to_delete.txt", "bye")
        result = delete_sources([f])
        assert result == [f]
        assert not f.exists()

    def test_delete_directory(self, tmp_path: Path) -> None:
        d = make_dir(tmp_path, "sub")
        make_file(d, "inner.txt", "data")
        result = delete_sources([d])
        assert result == [d]
        assert not d.exists()

    def test_delete_non_existent(self, tmp_path: Path) -> None:
        """Non-existent files should be skipped without error."""
        result = delete_sources([tmp_path / "nonexistent.txt"])
        assert result == []

    def test_delete_mixed(self, tmp_path: Path) -> None:
        f = make_file(tmp_path, "exists.txt", "hello")
        result = delete_sources([f, tmp_path / "missing.txt"])
        assert result == [f]  # only the existing one
        assert not f.exists()

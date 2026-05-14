from pathlib import Path

import pytest

from src.utils.file_basket import FileBasket


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def basket() -> FileBasket:
    return FileBasket()


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    paths = []
    for name in ("a.txt", "b.txt", "c.txt"):
        p = tmp_path / name
        p.write_text(name * 100)
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_new_files(self, basket: FileBasket, files: list[Path]) -> None:
        assert basket.add(files) == 3
        assert basket.count == 3
        assert all(p.resolve() in basket._paths for p in files)

    def test_add_deduplicates(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.add(files) == 0
        assert basket.count == 3

    def test_add_partial_duplicates(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files[:2])
        assert basket.add(files) == 1
        assert basket.count == 3

    def test_add_resolves_paths(self, basket: FileBasket, tmp_path: Path) -> None:
        nested = tmp_path / "sub" / ".." / "a.txt"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("data")
        resolved = nested.resolve()
        basket.add([nested])
        assert resolved in basket._paths

    def test_add_empty_list(self, basket: FileBasket) -> None:
        assert basket.add([]) == 0
        assert basket.is_empty


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

class TestRemove:
    def test_remove_existing(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.remove(files[0]) is True
        assert basket.count == 2

    def test_remove_non_existing(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.remove(Path("/nonexistent/file.txt")) is False
        assert basket.count == 3

    def test_remove_unknown_empty(self, basket: FileBasket) -> None:
        assert basket.remove(Path("/nonexistent/file.txt")) is False


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_removes_all(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        basket.clear()
        assert basket.count == 0
        assert basket.is_empty

    def test_clear_empty_basket(self, basket: FileBasket) -> None:
        basket.clear()
        assert basket.is_empty


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_files_returns_copy(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        result = basket.files
        result.append(Path("/fake"))
        assert len(basket.files) == 3

    def test_is_empty_initially(self, basket: FileBasket) -> None:
        assert basket.is_empty

    def test_is_empty_after_add(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files[:1])
        assert not basket.is_empty

    def test_count(self, basket: FileBasket, files: list[Path]) -> None:
        assert basket.count == 0
        basket.add(files)
        assert basket.count == 3

    def test_total_size_with_files(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.total_size == 1500  # each "name.txt"*100 = 500 bytes

    def test_total_size_with_directory(self, basket: FileBasket, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "f1.txt").write_text("a" * 50)
        (sub / "f2.txt").write_text("b" * 30)
        basket.add([sub])
        assert basket.total_size == 80

    def test_total_size_non_existent(self, basket: FileBasket) -> None:
        basket.add([Path("/tmp/_courier_test_nonexistent_")])
        assert basket.total_size == 0

    def test_len(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert len(basket) == 3

    def test_bool_empty(self, basket: FileBasket) -> None:
        assert not basket

    def test_bool_non_empty(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files[:1])
        assert basket


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_all_exist(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.validate() == []

    def test_some_stale(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        files[0].unlink()
        stale = basket.validate()
        assert len(stale) == 1
        assert stale[0] == files[0].resolve()

    def test_all_stale(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        for f in files:
            f.unlink()
        assert len(basket.validate()) == 3

    def test_no_files(self, basket: FileBasket) -> None:
        assert basket.validate() == []


# ---------------------------------------------------------------------------
# duplicate_names
# ---------------------------------------------------------------------------

class TestDuplicateNames:
    def test_no_duplicates(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert basket.duplicate_names == set()

    def test_with_duplicates(self, basket: FileBasket, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "report.txt").write_text("a")
        (dir2 / "report.txt").write_text("b")
        basket.add([dir1 / "report.txt", dir2 / "report.txt"])
        assert basket.duplicate_names == {"report.txt"}


# ---------------------------------------------------------------------------
# display_labels
# ---------------------------------------------------------------------------

class TestDisplayLabels:
    def test_simple_labels(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        labels = basket.display_labels()
        assert len(labels) == 3
        for p, label in labels:
            assert label == p.name

    def test_duplicate_labels_include_parent(self, basket: FileBasket, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "readme.md").write_text("a")
        (dir2 / "readme.md").write_text("b")
        basket.add([dir1 / "readme.md", dir2 / "readme.md"])
        labels = basket.display_labels()
        parents = {p.parent.name for p, _ in labels}
        assert parents == {"dir1", "dir2"}

    def test_max_count_truncates(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert len(basket.display_labels(max_count=2)) == 2

    def test_long_label_truncated(self, basket: FileBasket, tmp_path: Path) -> None:
        long_name = "x" * 60 + ".txt"
        p = tmp_path / long_name
        p.write_text("data")
        basket.add([p])
        label = basket.display_labels()[0][1]
        assert len(label) == 44
        assert label.endswith("...")

    def test_empty_basket(self, basket: FileBasket) -> None:
        assert basket.display_labels() == []


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------

class TestIteration:
    def test_iter(self, basket: FileBasket, files: list[Path]) -> None:
        basket.add(files)
        assert list(basket) == basket.files

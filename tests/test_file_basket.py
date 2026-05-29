from pathlib import Path

import pytest

from src.utils.file_basket import FileBasket


@pytest.fixture
def basket() -> FileBasket:
    return FileBasket()


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    return [_write(tmp_path / name, name * 100) for name in ("a.txt", "b.txt", "c.txt")]


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_new_files(basket: FileBasket, files: list[Path]) -> None:
    assert basket.add(files) == 3
    assert len(basket) == 3
    assert all(p.resolve() in basket._paths for p in files)


def test_add_deduplicates(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert basket.add(files) == 0
    assert len(basket) == 3


def test_add_partial_duplicates(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files[:2])
    assert basket.add(files) == 1
    assert len(basket) == 3


def test_add_resolves_paths(basket: FileBasket, tmp_path: Path) -> None:
    nested = tmp_path / "sub" / ".." / "a.txt"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("data")
    basket.add([nested])
    assert nested.resolve() in basket._paths


def test_add_empty_list(basket: FileBasket) -> None:
    assert basket.add([]) == 0
    assert not basket


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def test_remove_existing(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert basket.remove(files[0]) is True
    assert len(basket) == 2


def test_remove_non_existing(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert basket.remove(Path("/nonexistent/file.txt")) is False
    assert len(basket) == 3


def test_remove_unknown_empty(basket: FileBasket) -> None:
    assert basket.remove(Path("/nonexistent/file.txt")) is False


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_removes_all(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    basket.clear()
    assert not basket
    assert len(basket) == 0


def test_clear_empty_basket(basket: FileBasket) -> None:
    basket.clear()
    assert not basket


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------


def test_files_returns_copy(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    result = basket.files
    result.append(Path("/fake"))
    assert len(basket.files) == 3


def test_is_empty_initially(basket: FileBasket) -> None:
    assert basket.is_empty


def test_is_empty_after_add(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files[:1])
    assert not basket.is_empty


def test_total_size_with_files(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert basket.total_size == 1500  # each "name.txt"*100 = 500 bytes


def test_total_size_with_directory(basket: FileBasket, tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "f1.txt").write_text("a" * 50)
    (sub / "f2.txt").write_text("b" * 30)
    basket.add([sub])
    assert basket.total_size == 80


def test_total_size_non_existent(basket: FileBasket, tmp_path: Path) -> None:
    basket.add([tmp_path / "_nonexistent_"])
    assert basket.total_size == 0


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "0 B"),
        (500, "500.00 B"),
        (2048, "2.00 KB"),
        (3 * 1024 * 1024, "3.00 MB"),
        (2 * 1024**3, "2.00 GB")
    ],
)
def test_format_size(size: int, expected: str) -> None:
    assert FileBasket._format_size(size) == expected


def test_len(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert len(basket) == 3


def test_bool_empty(basket: FileBasket) -> None:
    assert not basket


def test_bool_non_empty(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files[:1])
    assert basket


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_all_exist(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert not basket.validate()


def test_validate_some_stale(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    files[0].unlink()
    stale = basket.validate()
    assert len(stale) == 1
    assert stale[0] == files[0].resolve()


def test_validate_all_stale(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    for f in files:
        f.unlink()
    assert len(basket.validate()) == 3


def test_validate_no_files(basket: FileBasket) -> None:
    assert not basket.validate()


# ---------------------------------------------------------------------------
# duplicate_names
# ---------------------------------------------------------------------------


def test_no_duplicate_names(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert not basket.duplicate_names


def test_with_duplicates(basket: FileBasket, tmp_path: Path) -> None:
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


def test_simple_labels(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    labels = basket.display_labels()
    assert len(labels) == 3
    assert all(label == p.name for p, label in labels)


def test_duplicate_labels_include_parent(basket: FileBasket, tmp_path: Path) -> None:
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "readme.md").write_text("a")
    (dir2 / "readme.md").write_text("b")
    basket.add([dir1 / "readme.md", dir2 / "readme.md"])
    parents = {p.parent.name for p, _ in basket.display_labels()}
    assert parents == {"dir1", "dir2"}


def test_max_count_truncates(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert len(basket.display_labels(max_count=2)) == 2


def test_long_label_truncated(basket: FileBasket, tmp_path: Path) -> None:
    p = tmp_path / ("x" * 60 + ".txt")
    p.write_text("data")
    basket.add([p])
    label = basket.display_labels()[0][1]
    assert len(label) == 44
    assert label.endswith("...")


def test_empty_basket_labels(basket: FileBasket) -> None:
    assert not basket.display_labels()


# ---------------------------------------------------------------------------
# iteration
# ---------------------------------------------------------------------------


def test_iter(basket: FileBasket, files: list[Path]) -> None:
    basket.add(files)
    assert list(basket) == basket.files

from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import run_local


def test_restore_packaged_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ZipFile(tmp_path / "chroma_index.zip", "w") as archive:
        archive.writestr("chroma/chroma.sqlite3", b"index")
    monkeypatch.setattr(run_local, "PROJECT_ROOT", tmp_path)

    run_local._restore_packaged_index()

    assert (tmp_path / "data/indexes/chroma/chroma.sqlite3").read_bytes() == b"index"


def test_restore_rejects_archive_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with ZipFile(tmp_path / "chroma_index.zip", "w") as archive:
        archive.writestr("../../outside.txt", b"unsafe")
    monkeypatch.setattr(run_local, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="Unsafe path"):
        run_local._restore_packaged_index()

    assert not (tmp_path.parent / "outside.txt").exists()

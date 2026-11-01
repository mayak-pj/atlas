from atlas.shared.fs.moves import REASON_EXISTS, REASON_MISSING, move_files, undo_moves


def _file(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_moves_into_new_cyrillic_folder(tmp_path):
    src = _file(tmp_path / "Папка с пробелом" / "a.jpg", "A")
    dst = tmp_path / "Папка с пробелом" / "Тип 1" / "a.jpg"
    report = move_files([(src, dst)])
    assert report.done == [(src, dst)] and report.failed == []
    assert dst.read_text(encoding="utf-8") == "A" and not src.exists()


def test_never_overwrites_and_continues_after_failure(tmp_path):
    a = _file(tmp_path / "a.jpg", "A")
    b = _file(tmp_path / "b.jpg", "B")
    taken = _file(tmp_path / "Тип 1" / "a.jpg", "OLD")
    report = move_files([(a, taken), (tmp_path / "нет.jpg", tmp_path / "Тип 1" / "нет.jpg"), (b, tmp_path / "Тип 1" / "b.jpg")])
    assert [reason for _s, _d, reason in report.failed] == [REASON_EXISTS, REASON_MISSING]
    assert taken.read_text(encoding="utf-8") == "OLD" and a.exists()
    assert (tmp_path / "Тип 1" / "b.jpg").read_text(encoding="utf-8") == "B"


def test_os_error_is_reported_not_raised(tmp_path, monkeypatch):
    src = _file(tmp_path / "a.jpg")

    def broken(*args):
        raise PermissionError("файл занят")

    monkeypatch.setattr("atlas.shared.fs.moves.os.rename", broken)
    report = move_files([(src, tmp_path / "Тип 1" / "a.jpg")])
    assert report.done == [] and "файл занят" in report.failed[0][2] and src.exists()


def test_undo_returns_files_and_removes_empty_folder(tmp_path):
    src = _file(tmp_path / "a.jpg", "A")
    report = move_files([(src, tmp_path / "Тип 1" / "a.jpg")])
    back = undo_moves(report.done)
    assert back.failed == [] and src.read_text(encoding="utf-8") == "A"
    assert not (tmp_path / "Тип 1").exists()


def test_undo_keeps_folder_with_other_files(tmp_path):
    src = _file(tmp_path / "a.jpg")
    other = _file(tmp_path / "Тип 1" / "чужой.jpg")
    undo_moves(move_files([(src, tmp_path / "Тип 1" / "a.jpg")]).done)
    assert other.exists() and src.exists()

-- Черновик проверки: заметки у каждого пользователя свои (папка + пользователь), строки найденного — общие у папки.
CREATE TABLE draft_notes (
    folder_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (folder_id, user_id)
);
-- Строки, добавленные вручную. kind: type | defect | remark.
CREATE TABLE draft_items (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    type_no INTEGER,
    sn TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX draft_items_folder ON draft_items (folder_id);
-- Пояснение к автоматической строке. key: photo:<id> или type:<N>.
CREATE TABLE draft_comments (
    folder_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (folder_id, key)
);

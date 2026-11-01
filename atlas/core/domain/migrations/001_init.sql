-- Базовые таблицы ядра. Время — местное, текстом ГГГГ-ММ-ДД ЧЧ:ММ:СС, дата папки — ГГГГ-ММ-ДД.
-- Ключи *_key считает Python (atlas/core/domain/text.py): LOWER в SQLite не понимает кириллицу.

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,  -- вид проекта: допустимые значения — настройка project_kinds, проверяет сервис parts
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    UNIQUE (kind, name_key)
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects (id),
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    UNIQUE (project_id, name_key)
);

CREATE TABLE parts (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices (id),
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    article TEXT,
    UNIQUE (device_id, name_key)
);
CREATE INDEX parts_name_key ON parts (name_key);

CREATE TABLE folders (
    id INTEGER PRIMARY KEY,
    part_id INTEGER NOT NULL REFERENCES parts (id),
    path TEXT NOT NULL,
    path_key TEXT NOT NULL UNIQUE,
    folder_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'in_work', 'done')),
    created_by INTEGER REFERENCES users (id),
    created_at TEXT NOT NULL,
    status_by INTEGER REFERENCES users (id),
    status_at TEXT
);
CREATE INDEX folders_part ON folders (part_id, folder_date);
CREATE INDEX folders_status ON folders (status, folder_date);

-- rel_path — путь внутри папки через «/»: так разбор по подпапкам типов меняет одну строку,
-- а смена буквы диска не затрагивает фото.
CREATE TABLE photos (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES folders (id),
    rel_path TEXT NOT NULL,
    rel_key TEXT NOT NULL,
    sn TEXT,
    mark TEXT CHECK (mark IS NULL OR mark IN ('defect', 'remark') OR mark GLOB 'type:[0-9]*'),
    marked_by INTEGER REFERENCES users (id),
    marked_at TEXT,
    UNIQUE (folder_id, rel_key)
);
CREATE INDEX photos_sn ON photos (sn);

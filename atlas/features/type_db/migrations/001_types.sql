-- Типы и дефекты деталей. Время — местное, текстом. part_id — деталь ядра (таблица parts).
-- Пути к файлам — внутри папки type_db.dir, через «/»: папку с картинками можно перенести, не трогая базу.
CREATE TABLE types (
    id INTEGER PRIMARY KEY,
    part_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('type', 'defect')),
    type_no INTEGER,  -- номер типа; у дефекта пусто
    description TEXT NOT NULL,
    article TEXT,
    photo_rel TEXT NOT NULL,  -- всё фото с обводкой и подписями
    crop_rel TEXT,  -- вырезка («ножницы»), если была
    source_photo TEXT,  -- откуда взято: путь исходного фото
    source_sn TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX types_part ON types (part_id, kind, type_no);

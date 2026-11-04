-- Папку можно удалить из Atlas (04.11.2026): ссылка «над какой папкой работает» тогда просто пустеет.
-- В SQLite ограничение внешнего ключа не изменить, поэтому таблица пересоздаётся; данные — только сигналы «жив».
CREATE TABLE presence_new (
    user_id INTEGER PRIMARY KEY REFERENCES users (id),
    folder_id INTEGER REFERENCES folders (id) ON DELETE SET NULL,
    beat INTEGER NOT NULL,
    seen_at TEXT NOT NULL
);
INSERT INTO presence_new (user_id, folder_id, beat, seen_at) SELECT user_id, folder_id, beat, seen_at FROM presence;
DROP TABLE presence;
ALTER TABLE presence_new RENAME TO presence;

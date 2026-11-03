-- Виды замечаний: общий список для всех ПК. Удалённый вид остаётся строкой с removed_at:
-- старые отметки хранят свой текст, а список при пустой таблице заполняется из data/defect_kinds.json только один раз.
CREATE TABLE defect_kinds (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,  -- регистр, «е/ё» и лишние пробелы не важны: «Сбит элемент» и «сбит  элемент» — одно
    position INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    removed_at TEXT
);
CREATE UNIQUE INDEX defect_kinds_live_key ON defect_kinds (name_key) WHERE removed_at IS NULL;

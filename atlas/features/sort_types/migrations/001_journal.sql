-- Журнал раскладок: что куда перемещено, чтобы можно было отменить. Время — местное, текстом.
CREATE TABLE sort_batches (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL,
    user_id INTEGER,
    created_at TEXT NOT NULL,
    undone_at TEXT
);
CREATE INDEX sort_batches_folder ON sort_batches (folder_id, id);

CREATE TABLE sort_moves (
    batch_id INTEGER NOT NULL REFERENCES sort_batches (id),
    photo_id INTEGER NOT NULL,
    from_rel TEXT NOT NULL,
    to_rel TEXT NOT NULL
);
CREATE INDEX sort_moves_batch ON sort_moves (batch_id);

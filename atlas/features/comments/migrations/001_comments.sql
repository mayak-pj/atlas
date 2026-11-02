-- Комментарии: временные сообщения. Время — местное, текстом. Деталь хранится вместе с подписью (part_label).
CREATE TABLE comments (
    id INTEGER PRIMARY KEY,
    author_id INTEGER NOT NULL,
    to_user_id INTEGER,  -- NULL — всем
    body TEXT NOT NULL DEFAULT '',
    part_id INTEGER,
    folder_id INTEGER,
    part_label TEXT NOT NULL DEFAULT '',
    earlier_error INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT  -- NULL — не удалять
);
CREATE INDEX comments_created ON comments (created_at);
-- Фото: пути внутри comments.dir, через «/»; рядом лежит миниатюра (см. logic.thumb_rel).
CREATE TABLE comment_photos (
    id INTEGER PRIMARY KEY,
    comment_id INTEGER NOT NULL,
    rel TEXT NOT NULL
);
CREATE INDEX comment_photos_comment ON comment_photos (comment_id);
-- «Готово» — у каждого пользователя своё: убирает сообщение из его списка и счётчика.
CREATE TABLE comment_done (
    comment_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    done_at TEXT NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);

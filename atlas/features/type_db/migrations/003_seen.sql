-- «Видел» — у каждого пользователя своё (14.11.2026): новый тип и тип, ушедший в архив, подсвечиваются, пока человек
-- не открыл карточку. Что было до этой миграции, новым не считается: type_news_base — время её применения.
CREATE TABLE type_seen (
    type_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (type_id, user_id)
);
CREATE TABLE type_news_base (at TEXT NOT NULL);
INSERT INTO type_news_base (at) VALUES (datetime('now', 'localtime'));

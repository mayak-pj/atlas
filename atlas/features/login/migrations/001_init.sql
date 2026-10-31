-- Пользователи. Пока их владелец — login; шаг 1.1 может вынести таблицу в ядро миграцией.
CREATE TABLE login_users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,   -- имя без регистра: «петров» и «Петров» — один человек
    color TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

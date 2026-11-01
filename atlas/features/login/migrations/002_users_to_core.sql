-- Пользователи теперь в таблице ядра users. На id пока ничего не ссылается.
INSERT OR IGNORE INTO users (name, name_key, color, created_at, last_login_at)
    SELECT name, name_key, color, created_at, last_login_at FROM login_users ORDER BY id;
DROP TABLE login_users;

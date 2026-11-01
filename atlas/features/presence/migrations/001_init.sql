-- beat растёт с каждым сигналом. По нему и узнаём, что человек жив: часы разных ПК могут расходиться.
CREATE TABLE presence (
    user_id INTEGER PRIMARY KEY REFERENCES users (id),
    folder_id INTEGER REFERENCES folders (id),
    beat INTEGER NOT NULL,
    seen_at TEXT NOT NULL
);

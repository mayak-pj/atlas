-- Правила проверки. Время — местное, текстом. Область действия хранится вместе с подписью (scope_label):
-- переименование проекта или детали старое правило не ломает.
CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('general', 'kind', 'project', 'device', 'part')),
    kind TEXT,  -- вид проекта (для kind/project/device/part)
    project_id INTEGER,
    device_id INTEGER,
    part_id INTEGER,
    name_key TEXT,  -- у детали: «та же деталь» ищется по имени, как в сводке
    scope_label TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    author_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX rules_created ON rules (created_at);
-- Фото правила: пути внутри rules.dir, через «/»; рядом лежит уменьшенная копия (см. logic.thumb_rel).
CREATE TABLE rule_photos (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER NOT NULL,
    rel TEXT NOT NULL
);
CREATE INDEX rule_photos_rule ON rule_photos (rule_id);
-- «Прочитано» — у каждого пользователя своё.
CREATE TABLE rule_reads (
    rule_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (rule_id, user_id)
);

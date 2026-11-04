-- Правило можно изменить, убрать в архив и удалить (04.11.2026). Архивное остаётся видно внизу списка,
-- но к детали не показывается и непрочитанным не считается.
ALTER TABLE rules ADD COLUMN archived_at TEXT;
ALTER TABLE rules ADD COLUMN archived_by INTEGER;
ALTER TABLE rules ADD COLUMN updated_at TEXT;
ALTER TABLE rules ADD COLUMN updated_by INTEGER;

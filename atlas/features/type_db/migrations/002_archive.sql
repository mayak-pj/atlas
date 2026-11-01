-- Архив: запись остаётся в базе, но в выдаче всегда внизу. Включает и выключает шаг 4.4; сортировку по этому полю делает поиск (4.3).
ALTER TABLE types ADD COLUMN archived_at TEXT;
ALTER TABLE types ADD COLUMN archived_by INTEGER;
CREATE INDEX types_archived ON types (archived_at);

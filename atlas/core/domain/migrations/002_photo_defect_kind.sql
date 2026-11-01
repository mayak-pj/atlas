-- Вид дефекта из справочника data/defect_kinds.json: текстом, чтобы смена списка не ломала старые отметки.
ALTER TABLE photos ADD COLUMN defect_kind TEXT;

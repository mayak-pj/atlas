-- «Относится к» больше нет (14.11.2026): у нового правила деталь и модель вписываются в форме и обязательны.
-- По part_name (его ключ — в name_key) правило показывается к детали в «Сравнении»; model — для поиска.
-- У старых правил обе колонки пустые: их область — прежняя (scope, scope_label).
ALTER TABLE rules ADD COLUMN part_name TEXT;
ALTER TABLE rules ADD COLUMN model TEXT;

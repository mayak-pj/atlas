-- Поворот фото при просмотре, градусы по часовой стрелке. Файл на диске не меняется.
ALTER TABLE photos ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270));

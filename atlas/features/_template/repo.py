"""Доступ к своим таблицам. Вызывать не из GUI-потока."""


class Repo:
    def __init__(self, db):
        self.db = db

    def count(self):
        return self.db.read(lambda conn: conn.execute("SELECT COUNT(*) FROM template_item").fetchone()[0])

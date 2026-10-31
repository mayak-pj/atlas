"""Текстовый отчёт проверок: читается в Блокноте Win7 (UTF-8 с BOM, CRLF).

Каждая строка сразу на диске: если процесс упадёт, в отчёте останется, где это случилось.
"""
from __future__ import annotations


class TextReport:
    def __init__(self, path):
        self.path = path
        with open(str(path), "w", encoding="utf-8-sig", newline="\r\n"):
            pass

    def line(self, text=""):
        with open(str(self.path), "a", encoding="utf-8", newline="\r\n") as stream:
            stream.write(text + "\n")

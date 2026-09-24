"""Ошибка источника с уже полученными страницами."""


class PartialCollectionError(Exception):
    def __init__(self, rows, reason):
        super().__init__(reason)
        self.rows = rows
        self.reason = reason

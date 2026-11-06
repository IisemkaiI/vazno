"""Автотесты правил ввода и транзакций библиотечного приложения.
Запуск: python -m unittest -v test_library_core.py
Тесты используют имитацию соединения, поэтому реальная база не изменяется.
"""

import unittest
from datetime import date

from library_core import (
    LibraryRepository,
    ValidationError,
    validate_book,
    validate_reader,
)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = 41
        self.current_row = None
        self.queries = []

    def execute(self, sql, params=()):
        compact_sql = " ".join(sql.split())
        self.queries.append((compact_sql, params))
        if "SELECT available_copies FROM books" in compact_sql:
            self.current_row = {"available_copies": self.connection.available_copies}
        elif "SELECT book_id, return_date FROM loans" in compact_sql:
            self.current_row = self.connection.loan_row
        elif "SELECT total_copies - available_copies AS borrowed" in compact_sql:
            self.current_row = {"borrowed": self.connection.borrowed}
        elif "SELECT category_id FROM categories" in compact_sql:
            self.current_row = {"category_id": 7}
        return self.lastrowid

    def fetchone(self):
        row = self.current_row
        self.current_row = None
        return row

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, available_copies=2, loan_row=None, borrowed=0):
        self.available_copies = available_copies
        self.loan_row = loan_row or {"book_id": 5, "return_date": None}
        self.borrowed = borrowed
        self.cursor_instance = FakeCursor(self)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class LibraryCoreTests(unittest.TestCase):
    def test_book_validation_trims_values(self):
        values = validate_book("  Код  ", " Автор ", "2020", " Роман ", "2")
        self.assertEqual(values, ("Код", "Автор", 2020, "Роман", 2))

    def test_book_validation_rejects_bad_year_and_quantity(self):
        with self.assertRaises(ValidationError):
            validate_book("Книга", "Автор", "завтра", "Роман", "1")
        with self.assertRaises(ValidationError):
            validate_book("Книга", "Автор", str(date.today().year), "Роман", "0")

    def test_add_book_creates_category_then_book(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)

        result = repository.add_book("Книга", "Автор", 2020, "Роман", 3)

        self.assertEqual(result, 41)
        self.assertTrue(connection.committed)
        queries = connection.cursor_instance.queries
        self.assertTrue(any("INSERT INTO categories" in sql for sql, _ in queries))
        insert = next((sql, params) for sql, params in queries if "INSERT INTO books" in sql)
        self.assertEqual(insert[1], ("Книга", "Автор", 2020, 7, 3, 3))

    def test_book_search_uses_title_author_and_category(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.get_books("фантастика")

        sql, params = connection.cursor_instance.queries[0]
        self.assertIn("b.title LIKE %s OR b.author LIKE %s OR c.name LIKE %s", sql)
        self.assertEqual(params, ("%фантастика%",) * 3)

    def test_reader_validation_normalizes_empty_email(self):
        values = validate_reader(" Иванов Иван ", "+70000000000", " ")
        self.assertEqual(values, ("Иванов Иван", "+70000000000", None))

    def test_reader_validation_rejects_invalid_email(self):
        with self.assertRaises(ValidationError):
            validate_reader("Иван Иванов", "+70000000000", "bad-email")

    def test_reader_add_update_delete_queries(self):
        connections = [FakeConnection(), FakeConnection(), FakeConnection()]
        used_connections = list(connections)
        repository = LibraryRepository(connection_factory=lambda: connections.pop(0))

        repository.add_reader("Иван Иванов", "+70000000000", None)
        repository.update_reader(3, "Иван Петров", "+70000000001", "ivan@example.ru")
        repository.delete_reader(3)

        self.assertTrue(all(connection.committed for connection in used_connections))
        statements = [
            connection.cursor_instance.queries[0][0]
            for connection in used_connections
        ]
        self.assertIn("INSERT INTO readers", statements[0])
        self.assertIn("UPDATE readers", statements[1])
        self.assertIn("DELETE FROM readers", statements[2])

    def test_issue_commits_and_updates_stock_in_one_transaction(self):
        connection = FakeConnection(available_copies=2)
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.issue_book(book_id=5, reader_id=9)

        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        sql = " ".join(query for query, _params in connection.cursor_instance.queries)
        self.assertIn("INSERT INTO loans", sql)
        self.assertIn("available_copies = available_copies - 1", sql)

    def test_issue_without_available_copy_rolls_back(self):
        connection = FakeConnection(available_copies=0)
        repository = LibraryRepository(connection_factory=lambda: connection)

        with self.assertRaisesRegex(ValueError, "Нет свободных экземпляров"):
            repository.issue_book(book_id=5, reader_id=9)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_return_updates_loan_and_stock(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.return_book(loan_id=12)

        self.assertTrue(connection.committed)
        sql = " ".join(query for query, _params in connection.cursor_instance.queries)
        self.assertIn("UPDATE loans SET return_date", sql)
        self.assertIn("available_copies = available_copies + 1", sql)

    def test_return_rejects_already_returned_loan(self):
        connection = FakeConnection(loan_row={"book_id": 5, "return_date": date.today()})
        repository = LibraryRepository(connection_factory=lambda: connection)

        with self.assertRaisesRegex(ValueError, "уже возвращена"):
            repository.return_book(loan_id=12)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_loan_filter_limits_results_to_overdue_returns(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.get_loans("Просроченные")

        sql, _params = connection.cursor_instance.queries[0]
        self.assertIn("l.return_date IS NULL AND l.due_date < CURDATE()", sql)

    def test_report_counts_only_real_active_loans(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.get_report()

        sql, _params = connection.cursor_instance.queries[0]
        self.assertIn("l.loan_id IS NOT NULL AND l.return_date IS NULL", sql)

    def test_book_edit_preserves_currently_borrowed_count(self):
        connection = FakeConnection(borrowed=2)
        repository = LibraryRepository(connection_factory=lambda: connection)

        repository.update_book(5, "Новое название", "Автор", 2020, "Роман", 4)

        self.assertTrue(connection.committed)
        update = next(
            (sql, params)
            for sql, params in connection.cursor_instance.queries
            if sql.startswith("UPDATE books") and "SET title" in sql
        )
        self.assertIn("available_copies = %s", update[0])
        self.assertEqual(update[1][-3:-1], (4, 2))

    def test_book_edit_cannot_reduce_total_below_borrowed_count(self):
        connection = FakeConnection(borrowed=3)
        repository = LibraryRepository(connection_factory=lambda: connection)

        with self.assertRaisesRegex(ValueError, "меньше 3 экземпляров"):
            repository.update_book(5, "Название", "Автор", 2020, "Роман", 2)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_connection_closes_after_successful_transaction(self):
        connection = FakeConnection()
        repository = LibraryRepository(connection_factory=lambda: connection)
        repository.issue_book(book_id=5, reader_id=9)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)

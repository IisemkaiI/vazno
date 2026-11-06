"""Правила проверки данных и доступ к MySQL для библиотечного приложения."""

from datetime import date
import os


class ValidationError(ValueError):
    """Ошибка проверки введенных пользователем значений."""


def validate_book(title, author, year, category, copies):
    """Проверяет форму книги и возвращает нормализованные значения."""
    title = title.strip()
    author = author.strip()
    category = category.strip()

    if not title or not author or not category:
        raise ValidationError("Заполните название, автора и жанр книги.")

    try:
        year = int(year)
        copies = int(copies)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Год и количество должны быть целыми числами.") from exc

    if not 0 < year <= date.today().year:
        raise ValidationError("Укажите корректный год издания.")
    if copies < 1:
        raise ValidationError("Количество экземпляров должно быть не меньше 1.")

    return title, author, year, category, copies


def validate_reader(full_name, phone, email):
    """Проверяет и нормализует значения карточки читателя."""
    full_name = full_name.strip()
    phone = phone.strip()
    email = email.strip()

    if len(full_name) < 3 or not phone:
        raise ValidationError("Укажите ФИО длиной не менее 3 символов и телефон.")
    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        raise ValidationError("Проверьте формат электронной почты.")

    return full_name, phone, email or None


def connect_to_database():
    """Подключается к MySQL, используя настройки окружения или значения по умолчанию."""
    try:
        import mysql.connector
    except ImportError as exc:
        raise RuntimeError(
            "Не найден mysql-connector-python. Установите его командой: "
            "pip install -r requirements.txt"
        ) from exc

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "1234"),
        database=os.getenv("MYSQL_DATABASE", "library_db"),
    )


class LibraryRepository:
    """SQL-операции над книгами, читателями и выдачами."""

    def __init__(self, connection_factory=connect_to_database):
        self.connection_factory = connection_factory

    def _run(self, operation):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            result = operation(cursor, connection)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def get_books(self, search=""):
        """Возвращает книги; поиск учитывает название, автора и жанр."""
        term = f"%{search.strip()}%"
        sql = """
            SELECT b.book_id, b.title, b.author, b.publication_year,
                   c.name AS category, b.total_copies, b.available_copies
            FROM books AS b
            JOIN categories AS c ON c.category_id = b.category_id
            WHERE b.title LIKE %s OR b.author LIKE %s OR c.name LIKE %s
            ORDER BY b.title, b.author
        """
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql, (term, term, term)))

    def add_book(self, title, author, year, category, copies):
        def operation(cursor, _connection):
            category_id = self._get_or_create_category(cursor, category)
            cursor.execute(
                """INSERT INTO books
                   (title, author, publication_year, category_id, total_copies, available_copies)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (title, author, year, category_id, copies, copies),
            )
            return cursor.lastrowid
        return self._run(operation)

    def update_book(self, book_id, title, author, year, category, copies):
        def operation(cursor, _connection):
            cursor.execute(
                "SELECT total_copies - available_copies AS borrowed "
                "FROM books WHERE book_id = %s FOR UPDATE",
                (book_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("Книга не найдена. Обновите список и попробуйте снова.")
            borrowed = row["borrowed"]
            if copies < borrowed:
                raise ValueError(
                    f"Нельзя указать меньше {borrowed} экземпляров: столько книг сейчас выдано."
                )

            category_id = self._get_or_create_category(cursor, category)
            cursor.execute(
                """UPDATE books
                   SET title = %s, author = %s, publication_year = %s,
                       category_id = %s, total_copies = %s, available_copies = %s
                   WHERE book_id = %s""",
                (title, author, year, category_id, copies, copies - borrowed, book_id),
            )
        return self._run(operation)

    def delete_book(self, book_id):
        return self._execute("DELETE FROM books WHERE book_id = %s", (book_id,))

    def get_readers(self, search=""):
        term = f"%{search.strip()}%"
        sql = """
            SELECT reader_id, full_name, phone, email
            FROM readers
            WHERE full_name LIKE %s OR phone LIKE %s OR email LIKE %s
            ORDER BY full_name
        """
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql, (term, term, term)))

    def add_reader(self, full_name, phone, email):
        return self._execute(
            "INSERT INTO readers (full_name, phone, email) VALUES (%s, %s, %s)",
            (full_name, phone, email),
        )

    def update_reader(self, reader_id, full_name, phone, email):
        return self._execute(
            """UPDATE readers SET full_name = %s, phone = %s, email = %s
               WHERE reader_id = %s""",
            (full_name, phone, email, reader_id),
        )

    def delete_reader(self, reader_id):
        return self._execute("DELETE FROM readers WHERE reader_id = %s", (reader_id,))

    def get_loans(self, filter_name="Все"):
        filters = {
            "Все": "",
            "На руках": "WHERE l.return_date IS NULL AND l.due_date >= CURDATE()",
            "Просроченные": "WHERE l.return_date IS NULL AND l.due_date < CURDATE()",
            "Возвращенные": "WHERE l.return_date IS NOT NULL",
        }
        if filter_name not in filters:
            raise ValueError("Неизвестный фильтр выдач.")

        sql = f"""
            SELECT l.loan_id, l.book_id, l.reader_id, b.title AS book_title,
                   r.full_name AS reader_name, l.issue_date, l.due_date,
                   l.return_date,
                   CASE
                     WHEN l.return_date IS NOT NULL THEN 'Возвращена'
                     WHEN l.due_date < CURDATE() THEN 'Просрочена'
                     ELSE 'На руках'
                   END AS status
            FROM loans AS l
            JOIN books AS b ON b.book_id = l.book_id
            JOIN readers AS r ON r.reader_id = l.reader_id
            {filters[filter_name]}
            ORDER BY l.issue_date DESC, l.loan_id DESC
        """
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql))

    def get_book_choices(self):
        sql = """SELECT book_id, title, author, available_copies
                 FROM books WHERE available_copies > 0 ORDER BY title"""
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql))

    def get_reader_choices(self):
        sql = "SELECT reader_id, full_name FROM readers ORDER BY full_name"
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql))

    def issue_book(self, book_id, reader_id):
        def operation(cursor, _connection):
            cursor.execute(
                "SELECT available_copies FROM books WHERE book_id = %s FOR UPDATE",
                (book_id,),
            )
            book = cursor.fetchone()
            if not book:
                raise ValueError("Книга не найдена.")
            if book["available_copies"] < 1:
                raise ValueError("Нет свободных экземпляров этой книги.")

            cursor.execute(
                """INSERT INTO loans (book_id, reader_id, issue_date, due_date)
                   VALUES (%s, %s, CURDATE(), DATE_ADD(CURDATE(), INTERVAL 14 DAY))""",
                (book_id, reader_id),
            )
            cursor.execute(
                "UPDATE books SET available_copies = available_copies - 1 "
                "WHERE book_id = %s",
                (book_id,),
            )
            return cursor.lastrowid
        return self._run(operation)

    def return_book(self, loan_id):
        def operation(cursor, _connection):
            cursor.execute(
                "SELECT book_id, return_date FROM loans WHERE loan_id = %s FOR UPDATE",
                (loan_id,),
            )
            loan = cursor.fetchone()
            if not loan:
                raise ValueError("Выдача не найдена.")
            if loan["return_date"] is not None:
                raise ValueError("Эта книга уже возвращена.")

            cursor.execute(
                "UPDATE loans SET return_date = CURDATE() WHERE loan_id = %s",
                (loan_id,),
            )
            cursor.execute(
                "UPDATE books SET available_copies = available_copies + 1 "
                "WHERE book_id = %s",
                (loan["book_id"],),
            )
        return self._run(operation)

    def get_report(self):
        sql = """
            SELECT c.name AS genre,
                   COUNT(l.loan_id) AS loan_count,
                   SUM(CASE
                         WHEN l.loan_id IS NOT NULL AND l.return_date IS NULL THEN 1
                         ELSE 0
                       END) AS active_count
            FROM categories AS c
            LEFT JOIN books AS b ON b.category_id = c.category_id
            LEFT JOIN loans AS l ON l.book_id = b.book_id
            GROUP BY c.category_id, c.name
            ORDER BY loan_count DESC, c.name
        """
        return self._run(lambda cursor, _conn: self._fetch(cursor, sql))

    def _execute(self, sql, params):
        return self._run(lambda cursor, _conn: cursor.execute(sql, params))

    @staticmethod
    def _fetch(cursor, sql, params=()):
        cursor.execute(sql, params)
        return cursor.fetchall()

    @staticmethod
    def _get_or_create_category(cursor, name):
        cursor.execute(
            "INSERT INTO categories (name) VALUES (%s) "
            "ON DUPLICATE KEY UPDATE category_id = LAST_INSERT_ID(category_id)",
            (name,),
        )
        cursor.execute("SELECT category_id FROM categories WHERE name = %s", (name,))
        row = cursor.fetchone()
        return row["category_id"]

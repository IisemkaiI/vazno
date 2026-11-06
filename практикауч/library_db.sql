CREATE DATABASE IF NOT EXISTS library_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE library_db;

CREATE TABLE IF NOT EXISTS categories (
  category_id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS books (
  book_id INT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  author VARCHAR(200) NOT NULL,
  publication_year SMALLINT NOT NULL,
  category_id INT NOT NULL,
  total_copies INT NOT NULL DEFAULT 1,
  available_copies INT NOT NULL DEFAULT 1,
  CONSTRAINT chk_books_total CHECK (total_copies >= 1),
  CONSTRAINT chk_books_available CHECK (available_copies >= 0 AND available_copies <= total_copies),
  CONSTRAINT fk_books_category FOREIGN KEY(category_id) REFERENCES categories(category_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  INDEX ix_books_title(title), INDEX ix_books_author(author)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS readers (
  reader_id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(200) NOT NULL,
  phone VARCHAR(30) NOT NULL,
  email VARCHAR(150) NULL,
  registered_at DATE NOT NULL DEFAULT (CURRENT_DATE),
  UNIQUE KEY uq_readers_phone(phone)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS loans (
  loan_id INT AUTO_INCREMENT PRIMARY KEY,
  book_id INT NOT NULL,
  reader_id INT NOT NULL,
  issue_date DATE NOT NULL,
  due_date DATE NOT NULL,
  return_date DATE NULL,
  CONSTRAINT fk_loans_book FOREIGN KEY(book_id) REFERENCES books(book_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_loans_reader FOREIGN KEY(reader_id) REFERENCES readers(reader_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  CHECK (due_date >= issue_date), CHECK (return_date IS NULL OR return_date >= issue_date),
  INDEX ix_loans_due(due_date,return_date)
) ENGINE=InnoDB;

INSERT INTO categories(name) VALUES ('Программирование'),('История'),('Фантастика')
ON DUPLICATE KEY UPDATE name=VALUES(name);
INSERT INTO books(title,author,publication_year,category_id,total_copies,available_copies)
SELECT 'Чистый код','Роберт Мартин',2008,category_id,3,3 FROM categories WHERE name='Программирование'
AND NOT EXISTS(SELECT 1 FROM books WHERE title='Чистый код' AND author='Роберт Мартин');
INSERT INTO readers(full_name,phone,email)
SELECT 'Иванов Иван Иванович','+70000000001','ivanov@gmail.com'
WHERE NOT EXISTS(SELECT 1 FROM readers WHERE phone='+70000000001');
UPDATE readers SET email='ivanov@gmail.com' WHERE phone='+70000000001';

-- Примеры запросов из отчета:
-- SELECT b.title,b.author,c.name FROM books b JOIN categories c ON c.category_id=b.category_id;
-- INSERT INTO readers(full_name,phone,email) VALUES('Петров Петр Петрович','+70000000002','petrov@example.ru');
-- UPDATE readers SET email='new@example.ru' WHERE reader_id=1;
-- DELETE FROM readers WHERE reader_id=1; -- только если нет связанных выдач

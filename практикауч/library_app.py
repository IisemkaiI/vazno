"""Графическое приложение учета библиотечного фонда на CustomTkinter."""

from pathlib import Path
import tkinter.messagebox as messagebox

import customtkinter as ctk

from library_core import (
    LibraryRepository,
    ValidationError,
    validate_book,
    validate_reader,
)

APP_DIR = Path(__file__).resolve().parent
THEME_FILE = APP_DIR / "themes" / "coffee.json"

ctk.set_appearance_mode("System")
ctk.set_default_color_theme(str(THEME_FILE))


class LibraryApp(ctk.CTk):
    """Главное окно библиотеки."""

    def __init__(self, repository=None):
        super().__init__()
        self.repository = repository or LibraryRepository()
        self.title("Библиотека | Учет фонда")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color=("#F4E6D1", "#111316"))
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.status_text = ctk.StringVar(value="Готово")
        self.selected_book_id = None
        self.selected_reader_id = None
        self.book_choice_ids = {}
        self.reader_choice_ids = {}
        self._book_search_job = None
        self._reader_search_job = None
        self._startup_loading = True
        
        self._build_header()
        self._build_main_tabs()
        self._build_status_bar()
        self.refresh_all(show_errors=False)
        self._startup_loading = False

    # --- Базовые построители UI ---
    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 10))
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_box, text="Библиотека", font=ctk.CTkFont(size=28, weight="bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(title_box, text="Учет книжного фонда, читателей и выдач", text_color=("#735744", "#B99A7E"), font=ctk.CTkFont(size=13), anchor="w").pack(anchor="w", pady=(2, 0))

    def _build_main_tabs(self):
        self.tabs = ctk.CTkTabview(self, corner_radius=12)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=8)
        self.books_tab = self.tabs.add("Книги")
        self.readers_tab = self.tabs.add("Читатели")
        self.loans_tab = self.tabs.add("Выдачи и отчет")
        self._build_books_tab()
        self._build_readers_tab()
        self._build_loans_tab()

    def _build_status_bar(self):
        ctk.CTkLabel(self, textvariable=self.status_text, anchor="w", text_color=("#755B46", "#B99A7E")).pack(fill="x", padx=26, pady=(0, 12))

    def close_app(self):
        for job in (self._book_search_job, self._reader_search_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkToplevel): child.destroy()
        self.destroy()

    # --- Утилиты и хелперы ---
    @staticmethod
    def _section_title(parent, text, subtitle=None):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=18, weight="bold"), anchor="w").pack(fill="x", pady=(0, 3))
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, text_color=("#755B46", "#B99A7E"), anchor="w", wraplength=280, justify="left").pack(fill="x", pady=(0, 12))

    @staticmethod
    def _field(parent, label, placeholder=""):
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", pady=(8, 3))
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder, height=36)
        entry.pack(fill="x")
        return entry

    @staticmethod
    def _clear_children(widget):
        for child in widget.winfo_children(): child.destroy()

    @staticmethod
    def _entry_value(entry): return entry.get().strip()

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        if value is not None: entry.insert(0, str(value))

    def _show_error(self, error):
        if isinstance(error, ValidationError):
            messagebox.showwarning("Проверьте данные", str(error), parent=self)
        elif isinstance(error, ValueError):
            messagebox.showwarning("Операция не выполнена", str(error), parent=self)
        else:
            messagebox.showerror("Ошибка базы данных", str(error), parent=self)
        self.status_text.set("Операция не выполнена")

    def _schedule_search(self, job_attr, refresh_func):
        job = getattr(self, job_attr)
        if job: self.after_cancel(job)
        setattr(self, job_attr, self.after(300, refresh_func))

    def _build_form(self, parent, title, subtitle, fields_config, save_cmd, clear_cmd, delete_cmd):
        form = ctk.CTkFrame(parent, width=290, corner_radius=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(8, 12), pady=8)
        form.grid_propagate(False)
        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)
        self._section_title(inner, title, subtitle)

        entries = {}
        for f in fields_config:
            entries[f["attr"]] = self._field(inner, f["label"], f.get("placeholder", ""))
            if "default" in f: entries[f["attr"]].insert(0, f["default"])

        save_btn = ctk.CTkButton(inner, text=fields_config[0].get("save_text", "Сохранить"), height=38, command=save_cmd)
        save_btn.pack(fill="x", pady=(18, 6))
        ctk.CTkButton(inner, text="Очистить форму", height=34, fg_color="transparent", border_width=1, command=clear_cmd).pack(fill="x")
        ctk.CTkButton(inner, text="Удалить выбранную", height=34, fg_color=("#9A493B", "#78372E"), hover_color=("#823C31", "#612B24"), command=delete_cmd).pack(fill="x", pady=(6, 0))
        return entries, save_btn

    def _build_card(self, parent, text1, text2, command=None, is_loan=False, return_cmd=None):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", padx=4, pady=4)
        if is_loan:
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=f"{text1}\n{text2}", anchor="w", justify="left", height=58).pack(side="left", fill="x", expand=True, padx=12, pady=5)
            if return_cmd:
                ctk.CTkButton(card, text="Принять возврат", width=132, command=return_cmd).pack(side="right", padx=10, pady=8)
        else:
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(card, text=f"{text1}\n{text2}", anchor="w", height=58, fg_color="transparent", hover_color=("#E8D2B9", "#29211D"), text_color=("#39271D", "#E9D7C4"), command=command).grid(row=0, column=0, sticky="ew", padx=6, pady=5)

    def _refresh_list(self, get_func, list_widget, row_builder, empty_text, search_entry=None, filter_widget=None):
        try:
            if search_entry: rows = get_func(self._entry_value(search_entry))
            elif filter_widget: rows = get_func(filter_widget.get())
            else: rows = get_func()
            
            self._clear_children(list_widget)
            if not rows:
                ctk.CTkLabel(list_widget, text=empty_text).pack(pady=18)
                return
            for row in rows: row_builder(row)
        except Exception as exc:
            if not self._startup_loading: self._show_error(exc)

    # --- Универсальные CRUD-методы ---
    def _save_entity(self, validate_func, entries, selected_id_attr, add_func, update_func, clear_func, refresh_func, msg_add, msg_update):
        try:
            values = validate_func(*(self._entry_value(e) for e in entries))
            selected_id = getattr(self, selected_id_attr)
            msg = msg_add if selected_id is None else msg_update
            (add_func if selected_id is None else update_func)(*(values if selected_id is None else (selected_id, *values)))
            self.status_text.set(msg)
            clear_func()
            refresh_func()
            self.refresh_choices()
        except Exception as exc:
            if not self._startup_loading: self._show_error(exc)

    def _delete_entity(self, selected_id_attr, delete_func, clear_func, title, confirm_msg, success_msg):
        selected_id = getattr(self, selected_id_attr)
        if selected_id is None:
            messagebox.showinfo(title, "Сначала выберите запись в списке.", parent=self)
            return
        if not messagebox.askyesno(title, confirm_msg, parent=self): return
        try:
            delete_func(selected_id)
            clear_func()
            self.refresh_all()
            self.status_text.set(success_msg)
        except Exception as exc:
            self._show_error(exc)

    def _select_entity(self, item, id_key, selected_id_attr, entries_mapping, save_btn, status_prefix):
        setattr(self, selected_id_attr, item[id_key])
        for entry, key in entries_mapping.items(): self._set_entry(entry, item.get(key))
        save_btn.configure(text="Сохранить изменения")
        self.status_text.set(f"{status_prefix}: {item.get('title') or item.get('full_name')}")

    def _clear_form(self, entries, default_values, selected_id_attr, save_btn, default_text):
        setattr(self, selected_id_attr, None)
        for entry in entries: entry.delete(0, "end")
        for entry, val in default_values.items(): self._set_entry(entry, val)
        save_btn.configure(text=default_text)

    # --- Построение вкладок ---
    def _build_books_tab(self):
        self.books_tab.grid_columnconfigure(0, weight=0, minsize=290)
        self.books_tab.grid_columnconfigure(1, weight=1)
        self.books_tab.grid_rowconfigure(0, weight=1)

        fields = [
            {"attr": "title", "label": "Название", "placeholder": "Например, Чистый код", "save_text": "Добавить книгу"},
            {"attr": "author", "label": "Автор", "placeholder": "Имя и фамилия автора"},
            {"attr": "year", "label": "Год издания", "placeholder": "Например, 2020"},
            {"attr": "category", "label": "Жанр", "placeholder": "Например, Программирование"},
            {"attr": "copies", "label": "Количество экземпляров", "placeholder": "1", "default": "1"},
        ]
        entries, self.book_save_button = self._build_form(self.books_tab, "Карточка книги", "Добавьте книгу или выберите запись для редактирования.", fields, self.save_book, self.clear_book_form, self.delete_book)
        self.book_title_entry, self.book_author_entry, self.book_year_entry, self.book_category_entry, self.book_copies_entry = (entries[f] for f in ["title", "author", "year", "category", "copies"])

        listing = ctk.CTkFrame(self.books_tab, corner_radius=12)
        listing.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        listing.grid_rowconfigure(2, weight=1)
        listing.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(listing, text="Каталог книг", font=ctk.CTkFont(size=18, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

        search_bar = ctk.CTkFrame(listing, fg_color="transparent")
        search_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        search_bar.grid_columnconfigure(0, weight=1)
        self.book_search_entry = ctk.CTkEntry(search_bar, placeholder_text="Поиск по названию, автору или жанру")
        self.book_search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.book_search_entry.bind("<KeyRelease>", lambda e: self._schedule_search('_book_search_job', self.refresh_books))
        ctk.CTkButton(search_bar, text="Найти", width=82, command=self.refresh_books).grid(row=0, column=1)
        self.books_list = ctk.CTkScrollableFrame(listing, label_text="Список")
        self.books_list.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _build_readers_tab(self):
        self.readers_tab.grid_columnconfigure(0, weight=0, minsize=290)
        self.readers_tab.grid_columnconfigure(1, weight=1)
        self.readers_tab.grid_rowconfigure(0, weight=1)

        fields = [
            {"attr": "name", "label": "ФИО", "placeholder": "Фамилия Имя Отчество", "save_text": "Зарегистрировать"},
            {"attr": "phone", "label": "Телефон", "placeholder": "+7 900 000-00-00"},
            {"attr": "email", "label": "Электронная почта", "placeholder": "name@example.ru"},
        ]
        entries, self.reader_save_button = self._build_form(self.readers_tab, "Карточка читателя", "Зарегистрируйте читателя или измените выбранную запись.", fields, self.save_reader, self.clear_reader_form, self.delete_reader)
        self.reader_name_entry, self.reader_phone_entry, self.reader_email_entry = (entries[f] for f in ["name", "phone", "email"])

        listing = ctk.CTkFrame(self.readers_tab, corner_radius=12)
        listing.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        listing.grid_rowconfigure(2, weight=1)
        listing.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(listing, text="Читатели", font=ctk.CTkFont(size=18, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        self.reader_search_entry = ctk.CTkEntry(listing, placeholder_text="Поиск по ФИО, телефону или электронной почте")
        self.reader_search_entry.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.reader_search_entry.bind("<KeyRelease>", lambda e: self._schedule_search('_reader_search_job', self.refresh_readers))
        self.readers_list = ctk.CTkScrollableFrame(listing, label_text="Список")
        self.readers_list.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _build_loans_tab(self):
        self.loans_tab.grid_columnconfigure(0, weight=1)
        self.loans_tab.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self.loans_tab, text="Выдача и возврат книг", font=ctk.CTkFont(size=20, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        issue_panel = ctk.CTkFrame(self.loans_tab, corner_radius=12)
        issue_panel.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        issue_panel.grid_columnconfigure((0, 1), weight=1)
        self.book_choice = ctk.CTkComboBox(issue_panel, values=["Нет книг"])
        self.book_choice.grid(row=0, column=0, sticky="ew", padx=(14, 7), pady=14)
        self.reader_choice = ctk.CTkComboBox(issue_panel, values=["Нет читателей"])
        self.reader_choice.grid(row=0, column=1, sticky="ew", padx=7, pady=14)
        ctk.CTkButton(issue_panel, text="Выдать на 14 дней", width=160, command=self.issue_book).grid(row=0, column=2, padx=(7, 14), pady=14)

        listing = ctk.CTkFrame(self.loans_tab, corner_radius=12)
        listing.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        listing.grid_columnconfigure(0, weight=1)
        listing.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(listing, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        toolbar.grid_columnconfigure(0, weight=1)
        self.loan_filter = ctk.CTkOptionMenu(toolbar, values=["Все", "На руках", "Просроченные", "Возвращенные"], command=lambda _: self.refresh_loans(), width=170)
        self.loan_filter.set("Все")
        self.loan_filter.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(toolbar, text="Отчет по выдачам", command=self.show_report).grid(row=0, column=1, sticky="e", padx=6)
        ctk.CTkButton(toolbar, text="Обновить", fg_color="transparent", border_width=1, command=self.refresh_all).grid(row=0, column=2, sticky="e")
        self.loans_list = ctk.CTkScrollableFrame(listing, label_text="Журнал выдач")
        self.loans_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    # --- Логика вкладок (Книги) ---
    def refresh_books(self):
        self._refresh_list(self.repository.get_books, self.books_list, self._book_row, "Книги не найдены.", self.book_search_entry)

    def _book_row(self, book):
        title = f"{book['title']}  ·  {book['author']}"
        details = f"{book['category']}  |  {book['publication_year']}  |  Доступно: {book['available_copies']} из {book['total_copies']}"
        self._build_card(self.books_list, title, details, lambda: self.select_book(book))

    def select_book(self, book):
        self._select_entity(book, 'book_id', 'selected_book_id', {self.book_title_entry: 'title', self.book_author_entry: 'author', self.book_year_entry: 'publication_year', self.book_category_entry: 'category', self.book_copies_entry: 'total_copies'}, self.book_save_button, "Выбрана книга")

    def clear_book_form(self):
        self._clear_form([self.book_title_entry, self.book_author_entry, self.book_year_entry, self.book_category_entry, self.book_copies_entry], {self.book_copies_entry: "1"}, 'selected_book_id', self.book_save_button, "Добавить книгу")

    def save_book(self):
        self._save_entity(validate_book, [self.book_title_entry, self.book_author_entry, self.book_year_entry, self.book_category_entry, self.book_copies_entry], 'selected_book_id', self.repository.add_book, self.repository.update_book, self.clear_book_form, self.refresh_books, "Книга добавлена", "Изменения книги сохранены")

    def delete_book(self):
        self._delete_entity('selected_book_id', self.repository.delete_book, self.clear_book_form, "Удаление книги", "Удалить выбранную книгу? Записи с историей выдач удалить нельзя.", "Книга удалена")

    # --- Логика вкладок (Читатели) ---
    def refresh_readers(self):
        self._refresh_list(self.repository.get_readers, self.readers_list, self._reader_row, "Читатели не найдены.", self.reader_search_entry)

    def _reader_row(self, reader):
        email = reader["email"] or "электронная почта не указана"
        self._build_card(self.readers_list, reader['full_name'], f"{reader['phone']}  ·  {email}", lambda: self.select_reader(reader))

    def select_reader(self, reader):
        self._select_entity(reader, 'reader_id', 'selected_reader_id', {self.reader_name_entry: 'full_name', self.reader_phone_entry: 'phone', self.reader_email_entry: 'email'}, self.reader_save_button, "Выбран читатель")

    def clear_reader_form(self):
        self._clear_form([self.reader_name_entry, self.reader_phone_entry, self.reader_email_entry], {}, 'selected_reader_id', self.reader_save_button, "Зарегистрировать")

    def save_reader(self):
        self._save_entity(validate_reader, [self.reader_name_entry, self.reader_phone_entry, self.reader_email_entry], 'selected_reader_id', self.repository.add_reader, self.repository.update_reader, self.clear_reader_form, self.refresh_readers, "Читатель зарегистрирован", "Изменения читателя сохранены")

    def delete_reader(self):
        self._delete_entity('selected_reader_id', self.repository.delete_reader, self.clear_reader_form, "Удаление читателя", "Удалить читателя? Записи с историей выдач удалить нельзя.", "Читатель удален")

    # --- Логика вкладок (Выдачи) ---
    def refresh_choices(self):
        books = self.repository.get_book_choices()
        readers = self.repository.get_reader_choices()
        self.book_choice_ids = {f"{b['title']} — {b['author']} (доступно {b['available_copies']})": b["book_id"] for b in books}
        self.reader_choice_ids = {f"{r['full_name']} (ID {r['reader_id']})": r["reader_id"] for r in readers}
        
        book_options = list(self.book_choice_ids) or ["Нет доступных книг"]
        reader_options = list(self.reader_choice_ids) or ["Нет читателей"]
        self.book_choice.configure(values=book_options)
        self.reader_choice.configure(values=reader_options)
        self.book_choice.set(book_options[0])
        self.reader_choice.set(reader_options[0])

    def issue_book(self):
        book_id = self.book_choice_ids.get(self.book_choice.get())
        reader_id = self.reader_choice_ids.get(self.reader_choice.get())
        if book_id is None:
            messagebox.showwarning("Выдача книги", "Нет доступных книг для выдачи.", parent=self); return
        if reader_id is None:
            messagebox.showwarning("Выдача книги", "Сначала зарегистрируйте читателя.", parent=self); return
        try:
            self.repository.issue_book(book_id, reader_id)
            self.refresh_all()
            self.status_text.set("Книга выдана на 14 дней")
        except Exception as exc:
            self._show_error(exc)

    def refresh_loans(self):
        self._refresh_list(self.repository.get_loans, self.loans_list, self._loan_row, "Выдач по этому фильтру нет.", filter_widget=self.loan_filter)

    def _loan_row(self, loan):
        returned = loan["return_date"] or "—"
        line1 = f"{loan['book_title']}  ·  {loan['reader_name']}"
        line2 = f"Выдана: {loan['issue_date']}  |  Срок: {loan['due_date']}  |  Возвращена: {returned}  |  {loan['status']}"
        return_cmd = (lambda lid=loan["loan_id"]: self.return_book(lid)) if loan["return_date"] is None else None
        self._build_card(self.loans_list, line1, line2, is_loan=True, return_cmd=return_cmd)

    def return_book(self, loan_id):
        if not messagebox.askyesno("Возврат книги", "Подтвердить возврат выбранной книги?", parent=self): return
        try:
            self.repository.return_book(loan_id)
            self.refresh_all()
            self.status_text.set("Возврат зарегистрирован")
        except Exception as exc:
            self._show_error(exc)

    def refresh_all(self, show_errors=True):
        try:
            self.refresh_books()
            self.refresh_readers()
            self.refresh_choices()
            self.refresh_loans()
            self.status_text.set("Данные обновлены")
        except Exception as exc:
            if show_errors: self._show_error(exc)
            else: self.status_text.set("Нет подключения к базе данных")

    def show_report(self):
        try:
            rows = self.repository.get_report()
        except Exception as exc:
            self._show_error(exc); return

        window = ctk.CTkToplevel(self)
        window.title("Отчет по выдачам")
        window.geometry("520x430")
        window.transient(self)
        ctk.CTkLabel(window, text="Отчет по библиотечному фонду", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=20, pady=(20, 8))

        total = sum(row["loan_count"] or 0 for row in rows)
        active = sum(row["active_count"] or 0 for row in rows)
        ctk.CTkLabel(window, text=f"Всего выдач: {total}     Сейчас на руках: {active}", anchor="w").pack(fill="x", padx=20, pady=(0, 12))

        report_box = ctk.CTkTextbox(window, wrap="word")
        report_box.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        if rows:
            for row in rows: report_box.insert("end", f"{row['genre']}: {row['loan_count']} выдач, {row['active_count']} сейчас на руках\n")
        else:
            report_box.insert("end", "Данных для отчета пока нет.")
        report_box.configure(state="disabled")


if __name__ == "__main__":
    app = LibraryApp()
    app.mainloop()

"""
shelf_track.py
Ebookstore database manager (SQLite) with two linked tables: author and book.

Highlights:
- Foreign key enforcement enabled
- Strong schema constraints
- Clear separation: DB layer + repository + CLI
- Safer input parsing + specific exception handling
- Consistent querying with sqlite3.Row results
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence


# ----------------------------
# Initial seed data
# ----------------------------
INITIAL_BOOKS: list[tuple[int, str, int, int]] = [
    (3001, "A Tale of Two Cities", 1290, 30),
    (3002, "Harry Potter and the Philosopher's Stone", 8937, 40),
    (3003, "The Lion, the Witch and the Wardrobe", 2356, 25),
    (3004, "The Lord of the Rings", 6380, 37),
    (3005, "Alice's Adventures in Wonderland", 5620, 12),
]

INITIAL_AUTHORS: list[tuple[int, str, str]] = [
    (1290, "Charles Dickens", "England"),
    (8937, "J.K. Rowling", "England"),
    (2356, "C.S Lewis", "Ireland"),
    (6380, "J.R.R Tolkien", "South Africa"),
    (5620, "Lewis Carrol", "England"),
]


# ----------------------------
# Models (optional but clean)
# ----------------------------
@dataclass(frozen=True)
class BookDetails:
    book_id: int
    title: str
    author_id: int
    author_name: str
    author_country: str
    qty: int


# ----------------------------
# DB / Repository layer
# ----------------------------
class EbookstoreDB:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enforce FK constraints in SQLite
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @staticmethod
    def create_schema(conn: sqlite3.Connection) -> None:
        # Create referenced table FIRST
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS author (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS book (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                authorID INTEGER NOT NULL,
                qty INTEGER NOT NULL CHECK(qty >= 0),
                FOREIGN KEY(authorID) REFERENCES author(id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_book_authorID ON book(authorID);")

    @staticmethod
    def seed(conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT OR IGNORE INTO author(id, name, country)
            VALUES(?, ?, ?);
            """,
            INITIAL_AUTHORS,
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO book(id, title, authorID, qty)
            VALUES(?, ?, ?, ?);
            """,
            INITIAL_BOOKS,
        )

    # ---- CRUD operations ----
    @staticmethod
    def add_book(
        conn: sqlite3.Connection,
        *,
        book_id: int,
        title: str,
        author_id: int,
        qty: int,
        author_name: Optional[str] = None,
        author_country: Optional[str] = None,
    ) -> None:
        if qty < 0:
            raise ValueError("Quantity must be 0 or greater.")

        # If author doesn't exist, require name/country to create it
        author_exists = conn.execute(
            "SELECT 1 FROM author WHERE id = ?;",
            (author_id,),
        ).fetchone()

        if not author_exists:
            if not author_name or not author_country:
                raise ValueError("Author not found. Please provide author name and country to create it.")
            conn.execute(
                "INSERT INTO author(id, name, country) VALUES(?, ?, ?);",
                (author_id, author_name, author_country),
            )

        conn.execute(
            "INSERT INTO book(id, title, authorID, qty) VALUES(?, ?, ?, ?);",
            (book_id, title, author_id, qty),
        )

    @staticmethod
    def get_book_details(conn: sqlite3.Connection, book_id: int) -> Optional[BookDetails]:
        row = conn.execute(
            """
            SELECT
                b.id AS book_id,
                b.title,
                b.authorID AS author_id,
                a.name AS author_name,
                a.country AS author_country,
                b.qty
            FROM book b
            INNER JOIN author a ON b.authorID = a.id
            WHERE b.id = ?;
            """,
            (book_id,),
        ).fetchone()

        if not row:
            return None

        return BookDetails(
            book_id=row["book_id"],
            title=row["title"],
            author_id=row["author_id"],
            author_name=row["author_name"],
            author_country=row["author_country"],
            qty=row["qty"],
        )

    @staticmethod
    def list_all_books(conn: sqlite3.Connection) -> list[BookDetails]:
        rows = conn.execute(
            """
            SELECT
                b.id AS book_id,
                b.title,
                b.authorID AS author_id,
                a.name AS author_name,
                a.country AS author_country,
                b.qty
            FROM book b
            INNER JOIN author a ON b.authorID = a.id
            ORDER BY b.id;
            """
        ).fetchall()

        return [
            BookDetails(
                book_id=r["book_id"],
                title=r["title"],
                author_id=r["author_id"],
                author_name=r["author_name"],
                author_country=r["author_country"],
                qty=r["qty"],
            )
            for r in rows
        ]

    @staticmethod
    def update_book_qty(conn: sqlite3.Connection, book_id: int, qty: int) -> int:
        if qty < 0:
            raise ValueError("Quantity must be 0 or greater.")
        cur = conn.execute("UPDATE book SET qty = ? WHERE id = ?;", (qty, book_id))
        return cur.rowcount

    @staticmethod
    def update_book_title(conn: sqlite3.Connection, book_id: int, title: str) -> int:
        cur = conn.execute("UPDATE book SET title = ? WHERE id = ?;", (title, book_id))
        return cur.rowcount

    @staticmethod
    def update_author_name(conn: sqlite3.Connection, author_id: int, name: str) -> int:
        cur = conn.execute("UPDATE author SET name = ? WHERE id = ?;", (name, author_id))
        return cur.rowcount

    @staticmethod
    def update_author_country(conn: sqlite3.Connection, author_id: int, country: str) -> int:
        cur = conn.execute("UPDATE author SET country = ? WHERE id = ?;", (country, author_id))
        return cur.rowcount

    @staticmethod
    def delete_book(conn: sqlite3.Connection, book_id: int) -> bool:
        # Get authorID for cleanup
        row = conn.execute("SELECT authorID FROM book WHERE id = ?;", (book_id,)).fetchone()
        if not row:
            return False
        author_id = int(row["authorID"])

        conn.execute("DELETE FROM book WHERE id = ?;", (book_id,))

        # If author now unused, delete it (optional policy)
        ref_count = conn.execute(
            "SELECT COUNT(*) AS c FROM book WHERE authorID = ?;",
            (author_id,),
        ).fetchone()["c"]

        if ref_count == 0:
            conn.execute("DELETE FROM author WHERE id = ?;", (author_id,))
        return True


# ----------------------------
# CLI helpers
# ----------------------------
def prompt_int(message: str, *, min_value: Optional[int] = None) -> int:
    while True:
        raw = input(message).strip()
        try:
            value = int(raw)
            if min_value is not None and value < min_value:
                print(f"Please enter a number >= {min_value}.")
                continue
            return value
        except ValueError:
            print("Please enter a valid integer.")


def prompt_text(message: str, *, allow_empty: bool = False) -> str:
    while True:
        text = input(message).strip()
        if text or allow_empty:
            return text
        print("Input cannot be empty.")


def print_book(details: BookDetails) -> None:
    print("\n--- Book Details ---")
    print(f"Book ID:   {details.book_id}")
    print(f"Title:     {details.title}")
    print(f"Author ID: {details.author_id}")
    print(f"Author:    {details.author_name}")
    print(f"Country:   {details.author_country}")
    print(f"Quantity:  {details.qty}")


def print_books_table(books: Sequence[BookDetails]) -> None:
    if not books:
        print("No books available.")
        return

    # Simple fixed-width table output (no extra deps)
    headers = ("BookID", "Title", "Author", "Country", "Qty")
    rows = [(str(b.book_id), b.title, b.author_name, b.author_country, str(b.qty)) for b in books]

    col_widths = [
        max(len(headers[i]), max(len(r[i]) for r in rows))
        for i in range(len(headers))
    ]

    def fmt_row(r: Sequence[str]) -> str:
        return " | ".join(r[i].ljust(col_widths[i]) for i in range(len(headers)))

    print("\n" + fmt_row(headers))
    print("-" * (sum(col_widths) + 3 * (len(headers) - 1)))
    for r in rows:
        print(fmt_row(r))


# ----------------------------
# Main program
# ----------------------------
def run_cli(db_path: str) -> None:
    db = EbookstoreDB(db_path)

    with db.connect() as conn:
        db.create_schema(conn)
        db.seed(conn)
        conn.commit()
        print(f"Database ready: {db_path}")

        while True:
            print(
                """
=== Menu ===
1. Enter book
2. Update book
3. Delete book
4. Search book by ID
5. View all books
0. Exit
"""
            )
            choice = prompt_text("Enter your selection: ")

            try:
                if choice == "1":
                    book_id = prompt_int("Enter book ID (e.g., 3001): ", min_value=1)
                    title = prompt_text("Enter book title: ")
                    author_id = prompt_int("Enter author ID (e.g., 1290): ", min_value=1)
                    qty = prompt_int("Enter quantity: ", min_value=0)

                    # Only ask for author details if needed
                    author_name = None
                    author_country = None
                    exists = conn.execute("SELECT 1 FROM author WHERE id = ?;", (author_id,)).fetchone()
                    if not exists:
                        author_name = prompt_text("Enter author name: ")
                        author_country = prompt_text("Enter author country: ")

                    db.add_book(
                        conn,
                        book_id=book_id,
                        title=title,
                        author_id=author_id,
                        qty=qty,
                        author_name=author_name,
                        author_country=author_country,
                    )
                    conn.commit()
                    print("Book added successfully.")

                elif choice == "2":
                    book_id = prompt_int("Enter book ID to update: ", min_value=1)
                    details = db.get_book_details(conn, book_id)
                    if not details:
                        print("No book found with that ID.")
                        continue

                    print_book(details)
                    print(
                        """
Update options:
1. Quantity
2. Title
3. Author name
4. Author country
0. Cancel
"""
                    )
                    opt = prompt_text("Choose option: ")

                    if opt == "1":
                        qty = prompt_int("Enter new quantity: ", min_value=0)
                        changed = db.update_book_qty(conn, book_id, qty)
                        conn.commit()
                        print("Quantity updated." if changed else "No changes made.")

                    elif opt == "2":
                        title = prompt_text("Enter new title: ")
                        changed = db.update_book_title(conn, book_id, title)
                        conn.commit()
                        print("Title updated." if changed else "No changes made.")

                    elif opt == "3":
                        name = prompt_text("Enter new author name: ")
                        changed = db.update_author_name(conn, details.author_id, name)
                        conn.commit()
                        print("Author name updated." if changed else "No changes made.")

                    elif opt == "4":
                        country = prompt_text("Enter new author country: ")
                        changed = db.update_author_country(conn, details.author_id, country)
                        conn.commit()
                        print("Author country updated." if changed else "No changes made.")

                    elif opt == "0":
                        continue
                    else:
                        print("Invalid option.")

                elif choice == "3":
                    book_id = prompt_int("Enter book ID to delete: ", min_value=1)
                    deleted = db.delete_book(conn, book_id)
                    conn.commit()
                    print("Book deleted." if deleted else "Book not found.")

                elif choice == "4":
                    book_id = prompt_int("Enter book ID to search: ", min_value=1)
                    details = db.get_book_details(conn, book_id)
                    if details:
                        print_book(details)
                    else:
                        print("Book not found.")

                elif choice == "5":
                    books = db.list_all_books(conn)
                    print_books_table(books)

                elif choice == "0":
                    print("Goodbye!")
                    break

                else:
                    print("Invalid choice. Please select from the menu.")

            except sqlite3.IntegrityError as e:
                # e.g., duplicate primary key, FK constraint issues
                conn.rollback()
                print(f"Database constraint error: {e}")

            except ValueError as e:
                conn.rollback()
                print(f"Input error: {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ebookstore DB manager (SQLite).")
    parser.add_argument("--db", default="ebookstore.db", help="Path to SQLite database file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_cli(args.db)


if __name__ == "__main__":
    main()

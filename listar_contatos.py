import argparse
import csv
import sqlite3
from pathlib import Path

import config
import database


def fetch_known_contacts(limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT phone, name, created_at
        FROM known_contacts
        ORDER BY created_at DESC, id DESC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with database.get_connection() as conn:
        return conn.execute(query, params).fetchall()


def export_csv(rows: list[sqlite3.Row], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["telefone", "nome", "created_at"])
        for row in rows:
            writer.writerow([row["phone"], row["name"], row["created_at"]])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lista ou exporta os contatos conhecidos do bot."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Quantidade de contatos para mostrar no terminal. Padrao: 30",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Mostra todos os contatos no terminal.",
    )
    parser.add_argument(
        "--export",
        help="Exporta todos os contatos conhecidos para um CSV.",
    )
    args = parser.parse_args()

    database.init_db()

    if args.export:
        rows = fetch_known_contacts(limit=None)
        output_path = Path(args.export)
        export_csv(rows, output_path)
        print(f"Contatos exportados: {len(rows)}")
        print(f"Arquivo: {output_path.resolve()}")
        return

    rows = fetch_known_contacts(limit=None if args.all else args.limit)
    total = database.get_connection().execute(
        "SELECT COUNT(*) FROM known_contacts"
    ).fetchone()[0]

    print(f"Total de contatos conhecidos: {total}")
    print("")
    for row in rows:
        name = row["name"] or "-"
        print(f"{row['phone']} | {name} | {row['created_at']}")


if __name__ == "__main__":
    main()

import argparse

import database


def add_contact(phone: str, name: str) -> None:
    database.init_db()
    inserted = database.add_known_contact(phone, name)
    phones = database.phone_lookup_candidates(phone)
    if inserted:
        print(f"Contato adicionado: {', '.join(phones)} | {name or '-'}")
    else:
        print(f"Contato já existia: {', '.join(phones)}")


def remove_contact(phone: str) -> None:
    database.init_db()
    phones = database.phone_lookup_candidates(phone)
    if not phones:
        print("Telefone inválido.")
        return

    placeholders = ",".join("?" for _ in phones)
    with database.get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM known_contacts WHERE phone IN ({placeholders})",
            phones,
        )
    if cursor.rowcount:
        print(f"Contatos/variações removidos: {cursor.rowcount}")
    else:
        print(f"Contato não encontrado. Variações buscadas: {', '.join(phones)}")


def find_contact(phone: str) -> None:
    database.init_db()
    phones = database.phone_lookup_candidates(phone)
    if not phones:
        print("Telefone inválido.")
        return

    placeholders = ",".join("?" for _ in phones)
    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT phone, name, created_at
            FROM known_contacts
            WHERE phone IN ({placeholders})
            ORDER BY id ASC
            """,
            phones,
        ).fetchall()

    if rows:
        for row in rows:
            print(
                f"Encontrado: {row['phone']} | {row['name'] or '-'} | {row['created_at']}"
            )
    else:
        print(f"Não encontrado. Variações buscadas: {', '.join(phones)}")


def reset_lead(phone: str) -> None:
    database.init_db()
    phones = database.phone_lookup_candidates(phone)
    if not phones:
        print("Telefone inválido.")
        return

    placeholders = ",".join("?" for _ in phones)
    with database.get_connection() as conn:
        lead = conn.execute(
            f"SELECT id FROM leads WHERE phone IN ({placeholders})",
            phones,
        ).fetchall()
        if not lead:
            print(f"Nenhum lead encontrado. Variações buscadas: {', '.join(phones)}")
            return

        lead_ids = [row["id"] for row in lead]
        lead_placeholders = ",".join("?" for _ in lead_ids)
        deleted_answers = conn.execute(
            f"DELETE FROM lead_answers WHERE lead_id IN ({lead_placeholders})",
            lead_ids,
        ).rowcount
        deleted_leads = conn.execute(
            f"DELETE FROM leads WHERE id IN ({lead_placeholders})",
            lead_ids,
        ).rowcount

    print(
        f"Lead resetado: {', '.join(phones)} | "
        f"leads removidos={deleted_leads} respostas removidas={deleted_answers}"
    )


def reset_for_test(phone: str) -> None:
    remove_contact(phone)
    reset_lead(phone)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adiciona, remove, busca ou reseta contatos para testes do bot."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Adiciona contato conhecido.")
    add_parser.add_argument("phone", help="Telefone com ou sem +55.")
    add_parser.add_argument("name", nargs="?", default="", help="Nome do contato.")

    remove_parser = subparsers.add_parser("remove", help="Remove contato conhecido.")
    remove_parser.add_argument("phone", help="Telefone com ou sem +55.")

    find_parser = subparsers.add_parser("find", help="Busca contato conhecido.")
    find_parser.add_argument("phone", help="Telefone com ou sem +55.")

    reset_parser = subparsers.add_parser(
        "reset-lead",
        help="Remove o lead e respostas de um telefone, sem mexer nos contatos.",
    )
    reset_parser.add_argument("phone", help="Telefone com ou sem +55.")

    test_parser = subparsers.add_parser(
        "reset-test",
        help="Remove da lista de contatos e apaga lead/respostas para testar como novo.",
    )
    test_parser.add_argument("phone", help="Telefone com ou sem +55.")

    args = parser.parse_args()

    if args.command == "add":
        add_contact(args.phone, args.name)
    elif args.command == "remove":
        remove_contact(args.phone)
    elif args.command == "find":
        find_contact(args.phone)
    elif args.command == "reset-lead":
        reset_lead(args.phone)
    elif args.command == "reset-test":
        reset_for_test(args.phone)


if __name__ == "__main__":
    main()

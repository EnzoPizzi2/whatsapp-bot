import argparse
from pathlib import Path

import config
import database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa contatos conhecidos CSV ou VCF para o SQLite."
    )
    parser.add_argument(
        "contacts_path",
        nargs="?",
        default=str(config.KNOWN_CONTACTS_CSV),
        help="Caminho do CSV ou VCF de contatos. Padrao: contatos_conhecidos.csv",
    )
    args = parser.parse_args()

    database.init_db()
    contacts_path = Path(args.contacts_path)
    if contacts_path.suffix.lower() == ".vcf":
        imported = database.import_known_contacts_from_vcf(contacts_path)
    else:
        imported = database.import_known_contacts_from_csv(contacts_path)
    print(f"Contatos novos importados: {imported}")


if __name__ == "__main__":
    main()

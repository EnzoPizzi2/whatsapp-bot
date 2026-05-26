import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import config


def normalize_phone(phone: str | None) -> str:
    return "".join(char for char in str(phone or "") if char.isdigit())


def normalize_known_contact_phone(phone: str | None) -> str:
    digits = normalize_phone(phone)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("55") and len(digits) in {12, 13}:
        return digits
    if digits.startswith("0") and len(digits) in {11, 12}:
        digits = digits[1:]
    elif digits.startswith("0") and len(digits) in {13, 14}:
        digits = digits[3:]
    if len(digits) in {10, 11} and not digits.startswith("55"):
        return f"55{digits}"
    return digits


def phone_lookup_candidates(phone: str | None) -> list[str]:
    primary = normalize_known_contact_phone(phone)
    candidates: list[str] = []

    def add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    add(primary)

    if primary.startswith("55"):
        national_number = primary[2:]
        if len(national_number) == 11:
            ddd = national_number[:2]
            subscriber = national_number[2:]
            if subscriber.startswith("9"):
                add(f"55{ddd}{subscriber[1:]}")
        elif len(national_number) == 10:
            ddd = national_number[:2]
            subscriber = national_number[2:]
            if subscriber[:1] in {"6", "7", "8", "9"}:
                add(f"55{ddd}9{subscriber}")

    return candidates


def _split_phone_values(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"\s*(?:/{2,}|:::|;|\|)\s*", value)
    return [part.strip() for part in parts if part.strip()]


def _is_phone_column(column_name: str) -> bool:
    normalized = column_name.strip().lower()
    phone_fragments = (
        "telefone",
        "phone",
        "mobile",
        "celular",
        "whatsapp",
        "numero",
        "número",
    )
    return any(fragment in normalized for fragment in phone_fragments)


def _extract_contact_name(row: dict[str, str]) -> str:
    for key in ("nome", "name", "full name", "display name"):
        if row.get(key):
            return row[key].strip()

    first_name = row.get("first name") or row.get("given name") or ""
    last_name = row.get("last name") or row.get("family name") or ""
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    return ""


def _extract_contact_phones(row: dict[str, str]) -> list[str]:
    phones: list[str] = []
    for key, value in row.items():
        if not _is_phone_column(key):
            continue
        for raw_phone in _split_phone_values(value):
            phone = normalize_known_contact_phone(raw_phone)
            if phone and phone not in phones:
                phones.append(phone)
    return phones


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _insert_known_contact(
    conn: sqlite3.Connection,
    phone: str,
    name: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO known_contacts (phone, name)
        VALUES (?, ?)
        """,
        (phone, name),
    )
    return cursor.rowcount


def _insert_known_contact_variants(
    conn: sqlite3.Connection,
    phone: str,
    name: str,
) -> int:
    inserted = 0
    for candidate in phone_lookup_candidates(phone):
        inserted += _insert_known_contact(conn, candidate, name)
    return inserted


def add_known_contact(phone: str, name: str | None = None) -> bool:
    phone = normalize_known_contact_phone(phone)
    if not phone:
        return False

    with get_connection() as conn:
        inserted = _insert_known_contact_variants(conn, phone, name or "")
    return inserted > 0


def get_connection() -> sqlite3.Connection:
    db_path = Path(config.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS known_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                profile_name TEXT,
                current_node TEXT,
                status TEXT,
                initial_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS lead_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                node_id TEXT,
                field TEXT,
                raw_answer TEXT,
                selected_option TEXT,
                selected_label TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS incoming_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                profile_name TEXT,
                message_id TEXT,
                message_text TEXT,
                message_type TEXT,
                raw_payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS message_statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wamid TEXT,
                recipient_id TEXT,
                status TEXT,
                error_code TEXT,
                error_title TEXT,
                error_message TEXT,
                raw_payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS outgoing_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                wamid TEXT,
                message_text TEXT,
                success INTEGER,
                raw_response TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_known_contacts_phone
                ON known_contacts(phone);

            CREATE INDEX IF NOT EXISTS idx_leads_phone
                ON leads(phone);

            CREATE INDEX IF NOT EXISTS idx_lead_answers_lead_id
                ON lead_answers(lead_id);

            CREATE INDEX IF NOT EXISTS idx_incoming_messages_phone
                ON incoming_messages(phone);

            CREATE INDEX IF NOT EXISTS idx_message_statuses_wamid
                ON message_statuses(wamid);
            """
        )


def import_known_contacts_from_csv(csv_path: str | Path | None = None) -> int:
    path = Path(csv_path or config.KNOWN_CONTACTS_CSV)
    if not path.exists():
        if config.DEBUG:
            print(f"[database] CSV de contatos conhecidos não encontrado: {path}")
        return 0

    imported = 0
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        with get_connection() as conn:
            for row in reader:
                normalized_row = {
                    str(key).strip().lower(): (value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                name = _extract_contact_name(normalized_row)
                phones = _extract_contact_phones(normalized_row)

                for phone in phones:
                    imported += _insert_known_contact_variants(conn, phone, name)

    if config.DEBUG:
        print(f"[database] Contatos conhecidos importados: {imported}")
    return imported


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def _unfold_vcard_lines(text: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw_line[1:]
        else:
            unfolded.append(raw_line.strip())
    return unfolded


def _vcard_property_name(line: str) -> str:
    property_part = line.split(":", 1)[0]
    property_name = property_part.split(";", 1)[0]
    if "." in property_name:
        property_name = property_name.rsplit(".", 1)[-1]
    return property_name.strip().upper()


def _unescape_vcard_value(value: str) -> str:
    return (
        value.replace(r"\n", "\n")
        .replace(r"\N", "\n")
        .replace(r"\;", ";")
        .replace(r"\,", ",")
        .replace(r"\\", "\\")
        .strip()
    )


def _name_from_structured_vcard_name(value: str) -> str:
    parts = [_unescape_vcard_value(part) for part in value.split(";")]
    last_name = parts[0] if len(parts) > 0 else ""
    first_name = parts[1] if len(parts) > 1 else ""
    middle_name = parts[2] if len(parts) > 2 else ""
    return " ".join(part for part in (first_name, middle_name, last_name) if part).strip()


def _parse_vcards(text: str) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in _unfold_vcard_lines(text):
        upper_line = line.upper()
        if upper_line == "BEGIN:VCARD":
            current = {"name": "", "structured_name": "", "phones": []}
            continue
        if upper_line == "END:VCARD":
            if current is not None:
                if not current["name"] and current["structured_name"]:
                    current["name"] = _name_from_structured_vcard_name(
                        current["structured_name"]
                    )
                contacts.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        property_name = _vcard_property_name(line)
        value = _unescape_vcard_value(line.split(":", 1)[1])

        if property_name == "FN":
            current["name"] = value
        elif property_name == "N":
            current["structured_name"] = value
        elif property_name == "TEL":
            phone = normalize_known_contact_phone(value)
            if phone and phone not in current["phones"]:
                current["phones"].append(phone)

    return contacts


def import_known_contacts_from_vcf(vcf_path: str | Path) -> int:
    path = Path(vcf_path)
    if not path.exists():
        if config.DEBUG:
            print(f"[database] VCF de contatos conhecidos não encontrado: {path}")
        return 0

    imported = 0
    contacts = _parse_vcards(_read_text_file(path))
    with get_connection() as conn:
        for contact in contacts:
            name = contact.get("name") or ""
            for phone in contact.get("phones") or []:
                imported += _insert_known_contact_variants(conn, phone, name)

    if config.DEBUG:
        print(f"[database] Contatos conhecidos importados do VCF: {imported}")
    return imported


def is_known_contact(phone: str) -> bool:
    phones = phone_lookup_candidates(phone)
    if not phones:
        return False

    placeholders = ",".join("?" for _ in phones)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT id FROM known_contacts WHERE phone IN ({placeholders}) LIMIT 1",
            phones,
        ).fetchone()
    return row is not None


def get_lead_by_phone(phone: str) -> dict[str, Any] | None:
    exact_phone = normalize_phone(phone)
    phones = phone_lookup_candidates(phone)
    if exact_phone and exact_phone not in phones:
        phones.insert(0, exact_phone)
    if not phones:
        return None

    placeholders = ",".join("?" for _ in phones)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM leads
            WHERE phone IN ({placeholders})
            ORDER BY CASE phone
                WHEN ? THEN 0
                ELSE 1
            END, id DESC
            LIMIT 1
            """,
            [*phones, exact_phone],
        ).fetchone()
    return _row_to_dict(row)


def get_lead_by_id(lead_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
    return _row_to_dict(row)


def create_lead(
    phone: str,
    profile_name: str | None,
    initial_message: str | None,
    current_node: str,
) -> dict[str, Any]:
    phone = normalize_phone(phone)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO leads
                (phone, profile_name, current_node, status, initial_message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                phone,
                profile_name or "",
                current_node,
                "in_progress",
                initial_message or "",
            ),
        )
    lead = get_lead_by_phone(phone)
    if lead is None:
        raise RuntimeError("Não foi possível criar ou recuperar o lead.")
    return lead


def update_lead(
    lead_id: int,
    *,
    profile_name: str | None = None,
    current_node: str | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = []
    values: list[Any] = []

    if profile_name is not None:
        fields.append("profile_name = ?")
        values.append(profile_name)
    if current_node is not None:
        fields.append("current_node = ?")
        values.append(current_node)
    if status is not None:
        fields.append("status = ?")
        values.append(status)

    if not fields:
        return get_lead_by_id(lead_id)

    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(lead_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE leads SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    return get_lead_by_id(lead_id)


def save_lead_answer(
    lead_id: int,
    node_id: str,
    field: str,
    raw_answer: str | None,
    selected_option: str | None = None,
    selected_label: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO lead_answers
                (lead_id, node_id, field, raw_answer, selected_option, selected_label)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                lead_id,
                node_id,
                field,
                raw_answer or "",
                selected_option,
                selected_label,
            ),
        )


def get_lead_answers(lead_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM lead_answers
            WHERE lead_id = ?
            ORDER BY id ASC
            """,
            (lead_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_incoming_message(
    phone: str,
    profile_name: str | None,
    message_id: str | None,
    message_text: str | None,
    message_type: str | None,
    raw_payload: Any,
) -> None:
    phone = normalize_phone(phone)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO incoming_messages
                (phone, profile_name, message_id, message_text, message_type, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                phone,
                profile_name or "",
                message_id or "",
                message_text or "",
                message_type or "",
                _json_dumps(raw_payload),
            ),
        )


def incoming_message_exists(message_id: str | None) -> bool:
    if not message_id:
        return False

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM incoming_messages WHERE message_id = ? LIMIT 1",
            (message_id,),
        ).fetchone()
    return row is not None


def save_message_status(
    wamid: str | None,
    recipient_id: str | None,
    status: str | None,
    error_code: str | None,
    error_title: str | None,
    error_message: str | None,
    raw_payload: Any,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO message_statuses
                (wamid, recipient_id, status, error_code, error_title, error_message, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wamid or "",
                normalize_phone(recipient_id),
                status or "",
                str(error_code or ""),
                error_title or "",
                error_message or "",
                _json_dumps(raw_payload),
            ),
        )


def save_outgoing_message(
    phone: str,
    wamid: str | None,
    message_text: str | None,
    success: bool,
    raw_response: Any,
) -> None:
    phone = normalize_phone(phone)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO outgoing_messages
                (phone, wamid, message_text, success, raw_response)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                phone,
                wamid or "",
                message_text or "",
                1 if success else 0,
                _json_dumps(raw_response),
            ),
        )

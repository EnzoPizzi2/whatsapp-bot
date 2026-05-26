import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path: Path) -> None:
        if not path.exists():
            return

        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v25.0").strip() or "v25.0"
OWNER_WHATSAPP_NUMBER = os.getenv("OWNER_WHATSAPP_NUMBER", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()

DATABASE_PATH = _resolve_project_path(
    os.getenv("DATABASE_PATH", "data/leads.db").strip() or "data/leads.db"
)
KNOWN_CONTACTS_CSV = _resolve_project_path(
    os.getenv("KNOWN_CONTACTS_CSV", "contatos_conhecidos.csv").strip()
    or "contatos_conhecidos.csv"
)
QUESTIONNAIRE_FILE = _resolve_project_path(
    os.getenv("QUESTIONNAIRE_FILE", "questionario.json").strip() or "questionario.json"
)

DEBUG = _env_bool(os.getenv("DEBUG"), default=False)
META_GRAPH_API_BASE_URL = "https://graph.facebook.com"


def missing_required_settings() -> list[str]:
    required_settings = {
        "META_ACCESS_TOKEN": META_ACCESS_TOKEN,
        "WHATSAPP_PHONE_NUMBER_ID": WHATSAPP_PHONE_NUMBER_ID,
        "WHATSAPP_VERIFY_TOKEN": WHATSAPP_VERIFY_TOKEN,
        "OWNER_WHATSAPP_NUMBER": OWNER_WHATSAPP_NUMBER,
    }
    placeholder_fragments = {
        "coloque",
        "55dddnumero",
    }

    missing = []
    for name, value in required_settings.items():
        normalized_value = value.strip().lower()
        if not normalized_value:
            missing.append(name)
            continue
        if any(fragment in normalized_value for fragment in placeholder_fragments):
            missing.append(name)
    return missing


def validate_config() -> None:
    missing = missing_required_settings()
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Variáveis obrigatórias ausentes no .env: {names}. "
            "Crie o arquivo .env a partir do .env.example antes de iniciar o servidor."
        )

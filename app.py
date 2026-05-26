import hashlib
import hmac
from typing import Any

from flask import Flask, Response, request

import config
import database
from bot_logic import process_incoming_message, process_message_status


def create_app() -> Flask:
    config.validate_config()
    database.init_db()
    database.import_known_contacts_from_csv()

    flask_app = Flask(__name__)

    @flask_app.get("/")
    def index() -> Response:
        return Response("whatsapp-leads-bot ok", status=200, mimetype="text/plain")

    @flask_app.get("/healthz")
    def healthcheck() -> Response:
        return Response("ok", status=200, mimetype="text/plain")

    @flask_app.get("/webhook")
    def verify_webhook() -> Response | tuple[str, int]:
        mode = request.args.get("hub.mode") or request.args.get("hub_mode")
        verify_token = request.args.get("hub.verify_token") or request.args.get(
            "hub_verify_token"
        )
        challenge = request.args.get("hub.challenge") or request.args.get("hub_challenge")

        if mode == "subscribe" and verify_token == config.WHATSAPP_VERIFY_TOKEN:
            if config.DEBUG:
                print("[app] Webhook verificado com sucesso.")
            return Response(challenge or "", status=200, mimetype="text/plain")

        if config.DEBUG:
            print(
                "[app] Falha na verificação do webhook. "
                f"mode={mode or '-'} token_recebido_len={len(verify_token or '')}"
            )
        return "Forbidden", 403

    @flask_app.post("/webhook")
    def receive_webhook() -> tuple[str, int]:
        try:
            raw_body = request.get_data()
            if not _is_valid_webhook_signature(raw_body):
                if config.DEBUG:
                    print("[app] Assinatura do webhook inválida. Evento ignorado.")
                return "EVENT_RECEIVED", 200

            payload = request.get_json(silent=True) or {}
            processed_any_event = _process_payload(payload)

            if config.DEBUG and not processed_any_event:
                print("[app] Evento recebido sem messages/statuses. Ignorando com HTTP 200.")

        except Exception as exc:
            print(f"[app] Erro ao processar webhook. Evento ignorado com HTTP 200: {exc}")

        return "EVENT_RECEIVED", 200

    return flask_app


def _is_valid_webhook_signature(raw_body: bytes) -> bool:
    if not config.META_APP_SECRET:
        return True

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False

    expected_signature = hmac.new(
        config.META_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    received_signature = signature.split("=", 1)[1]
    return hmac.compare_digest(received_signature, expected_signature)


def _process_payload(payload: dict[str, Any]) -> bool:
    processed_any_event = False

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            field = change.get("field") or ""

            statuses = value.get("statuses") or []
            for status_payload in statuses:
                processed_any_event = True
                process_message_status(status_payload)

            messages = value.get("messages") or []
            contacts = value.get("contacts") or []
            profiles_by_phone = _profiles_by_phone(contacts)

            if field == "smb_message_echoes":
                for message_payload in messages:
                    processed_any_event = True
                    _save_smb_message_echo(message_payload, payload)
                continue

            if field != "messages":
                continue

            for message_payload in messages:
                processed_any_event = True
                phone = message_payload.get("from") or ""
                profile_name = profiles_by_phone.get(phone, "")
                message_type = message_payload.get("type") or ""
                message_text = _extract_message_text(message_payload)

                process_incoming_message(
                    phone=phone,
                    profile_name=profile_name,
                    message_id=message_payload.get("id"),
                    message_text=message_text,
                    message_type=message_type,
                    raw_payload=payload,
                )

    return processed_any_event


def _save_smb_message_echo(
    message_payload: dict[str, Any],
    raw_payload: dict[str, Any],
) -> None:
    phone = (
        message_payload.get("to")
        or message_payload.get("recipient_id")
        or message_payload.get("from")
        or ""
    )
    message_type = message_payload.get("type") or "unknown"
    message_text = _extract_message_text(message_payload)

    database.save_incoming_message(
        phone=phone,
        profile_name="",
        message_id=message_payload.get("id"),
        message_text=message_text,
        message_type=f"smb_message_echo:{message_type}",
        raw_payload=raw_payload,
    )

    if config.DEBUG:
        print(
            "[app] Echo do WhatsApp Business App salvo sem acionar bot | "
            f"phone={phone or '-'} message_id={message_payload.get('id') or '-'}"
        )


def _profiles_by_phone(contacts: list[dict[str, Any]]) -> dict[str, str]:
    profiles: dict[str, str] = {}
    for contact in contacts:
        phone = contact.get("wa_id") or ""
        profile = contact.get("profile") or {}
        name = profile.get("name") or ""
        if phone:
            profiles[phone] = name
    return profiles


def _extract_message_text(message_payload: dict[str, Any]) -> str:
    message_type = message_payload.get("type")
    if message_type == "text":
        return ((message_payload.get("text") or {}).get("body") or "").strip()
    return f"[Mensagem do tipo {message_type or 'desconhecido'} recebida]"


app = create_app()


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

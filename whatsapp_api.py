from typing import Any

import requests

import config
import database


def _message_preview(text: str, limit: int = 90) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _extract_wamid(response_json: dict[str, Any]) -> str | None:
    messages = response_json.get("messages")
    if isinstance(messages, list) and messages:
        first_message = messages[0]
        if isinstance(first_message, dict):
            return first_message.get("id")
    return None


def _log_meta_error(response_json: dict[str, Any]) -> None:
    error = response_json.get("error")
    if not isinstance(error, dict):
        return

    code = str(error.get("code") or "")
    message = error.get("message") or ""

    if code == "130497":
        print("Mensagem falhou por restrição de país/região da conta comercial.")
    elif config.DEBUG:
        print(f"[whatsapp_api] Erro da Meta: code={code} message={message}")


def send_text_message(phone: str, text: str) -> dict[str, Any]:
    phone = database.normalize_phone(phone)
    text = text or ""

    if config.DEBUG:
        print(
            f"[whatsapp_api] Enviando mensagem para {phone}: "
            f"{_message_preview(text)!r}"
        )

    if not phone:
        response_json = {
            "error": {
                "message": "Número de destino vazio.",
                "type": "local_validation_error",
            }
        }
        database.save_outgoing_message(phone, None, text, False, response_json)
        return response_json

    url = (
        f"{config.META_GRAPH_API_BASE_URL}/{config.WHATSAPP_API_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {config.META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        try:
            response_json = response.json()
        except ValueError:
            response_json = {
                "error": {
                    "message": response.text,
                    "type": "invalid_json_response",
                    "status_code": response.status_code,
                }
            }

        success = response.ok and "error" not in response_json
        wamid = _extract_wamid(response_json)
        database.save_outgoing_message(phone, wamid, text, success, response_json)

        if config.DEBUG:
            if wamid:
                print(f"[whatsapp_api] wamid: {wamid}")
            if not success:
                print(f"[whatsapp_api] Envio sem sucesso para {phone}.")

        if not success:
            _log_meta_error(response_json)

        return response_json

    except requests.RequestException as exc:
        response_json = {
            "error": {
                "message": str(exc),
                "type": exc.__class__.__name__,
            }
        }
        database.save_outgoing_message(phone, None, text, False, response_json)
        if config.DEBUG:
            print(f"[whatsapp_api] Falha de rede ao enviar para {phone}: {exc}")
        return response_json

from typing import Any

import config
import database
from flow_engine import FlowEngine, FlowResult
from whatsapp_api import send_text_message


_flow_engine: FlowEngine | None = None


def get_flow_engine() -> FlowEngine:
    global _flow_engine
    if _flow_engine is None:
        _flow_engine = FlowEngine()
    return _flow_engine


def _debug(message: str) -> None:
    if config.DEBUG:
        print(message)


def process_incoming_message(
    *,
    phone: str,
    profile_name: str | None,
    message_id: str | None,
    message_text: str | None,
    message_type: str | None,
    raw_payload: Any,
) -> FlowResult | None:
    phone = database.normalize_phone(phone)
    message_text = message_text or ""

    if message_id and database.incoming_message_exists(message_id):
        database.save_incoming_message(
            phone=phone,
            profile_name=profile_name,
            message_id=message_id,
            message_text=message_text,
            message_type=f"duplicate:{message_type or ''}",
            raw_payload=raw_payload,
        )
        _debug(
            "[bot_logic] Mensagem duplicada ignorada | "
            f"numero={phone or '-'} message_id={message_id}"
        )
        return None

    database.save_incoming_message(
        phone=phone,
        profile_name=profile_name,
        message_id=message_id,
        message_text=message_text,
        message_type=message_type,
        raw_payload=raw_payload,
    )

    _debug(
        "[bot_logic] Mensagem recebida | "
        f"numero={phone} nome={profile_name or '-'} "
        f"texto={message_text!r} message_id={message_id or '-'}"
    )

    if not phone:
        _debug("[bot_logic] Mensagem ignorada: número ausente.")
        return None

    if database.is_known_contact(phone):
        _debug(
            f"[bot_logic] Número {phone} está em known_contacts. "
            "Atendimento automático não iniciado."
        )
        return None

    engine = get_flow_engine()
    lead = database.get_lead_by_phone(phone)

    if lead is None:
        lead = database.create_lead(
            phone=phone,
            profile_name=profile_name,
            initial_message=message_text,
            current_node=engine.start_node,
        )
        result = engine.present_current_node(lead)
    elif lead.get("status") == "in_progress":
        if profile_name and profile_name != lead.get("profile_name"):
            lead = database.update_lead(lead["id"], profile_name=profile_name) or lead
        result = engine.handle_user_reply(lead, message_text)
    else:
        _debug(
            f"[bot_logic] Lead {phone} já está com status "
            f"{lead.get('status')}. Fluxo automático não reiniciado."
        )
        return None

    _send_result_messages(phone, result)
    _mark_completed_lead_as_known_contact(phone, result)
    _send_summary_if_needed(phone, result)
    return result


def _send_result_messages(phone: str, result: FlowResult) -> None:
    for message in result.messages:
        if message:
            send_text_message(phone, message)


def _mark_completed_lead_as_known_contact(phone: str, result: FlowResult) -> None:
    if result.summary_status not in {"completed", "handoff"}:
        return

    lead = database.get_lead_by_phone(phone)
    if not lead:
        return

    inserted = database.add_known_contact(
        lead.get("phone") or phone,
        lead.get("profile_name") or "",
    )

    if inserted:
        _debug(
            "[bot_logic] Lead finalizado adicionado aos contatos conhecidos | "
            f"numero={lead.get('phone') or phone}"
        )
    else:
        _debug(
            "[bot_logic] Lead finalizado já estava em contatos conhecidos | "
            f"numero={lead.get('phone') or phone}"
        )


def _send_summary_if_needed(phone: str, result: FlowResult) -> None:
    if not result.summary_required:
        return

    lead = database.get_lead_by_phone(phone)
    if not lead:
        _debug(f"[bot_logic] Não foi possível montar resumo: lead {phone} ausente.")
        return

    summary = get_flow_engine().build_summary(
        lead,
        status=result.summary_status,
        department=result.department,
    )

    if not config.OWNER_WHATSAPP_NUMBER:
        _debug("[bot_logic] OWNER_WHATSAPP_NUMBER não configurado. Resumo não enviado.")
        return

    send_text_message(config.OWNER_WHATSAPP_NUMBER, summary)


def process_message_status(status_payload: dict[str, Any]) -> None:
    wamid = status_payload.get("id")
    recipient_id = status_payload.get("recipient_id")
    status = status_payload.get("status")
    error_code = None
    error_title = None
    error_message = None

    errors = status_payload.get("errors") or []
    if isinstance(errors, list) and errors:
        first_error = errors[0] or {}
        error_code = first_error.get("code")
        error_title = first_error.get("title") or first_error.get("type")
        error_message = first_error.get("message") or ""
        details = (first_error.get("error_data") or {}).get("details")
        if details:
            if error_message:
                error_message = f"{error_message} Detalhes: {details}"
            else:
                error_message = details

    database.save_message_status(
        wamid=wamid,
        recipient_id=recipient_id,
        status=status,
        error_code=str(error_code or ""),
        error_title=error_title,
        error_message=error_message,
        raw_payload=status_payload,
    )

    if str(error_code or "") == "130497":
        print("Mensagem falhou por restrição de país/região da conta comercial.")

    _debug(
        "[bot_logic] Status recebido | "
        f"recipient_id={recipient_id or '-'} status={status or '-'} "
        f"wamid={wamid or '-'} erro={error_code or '-'}"
    )

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
import database


@dataclass
class FlowResult:
    messages: list[str] = field(default_factory=list)
    summary_required: bool = False
    summary_status: str | None = None
    department: str | None = None
    final_node_id: str | None = None


class FlowEngine:
    def __init__(self, questionnaire_file: str | Path | None = None) -> None:
        self.questionnaire_file = Path(questionnaire_file or config.QUESTIONNAIRE_FILE)
        self.flow = self._load_flow()
        self.start_node = self.flow["start_node"]
        self.invalid_option_message = self.flow.get(
            "invalid_option_message",
            "Não entendi sua resposta. Por favor, responda apenas com o número de uma das opções.",
        )
        self.handoff_message = self.flow.get(
            "handoff_message",
            "Aguarde um momento, por favor. Um responsável dará continuidade ao seu atendimento.",
        )

    def _load_flow(self) -> dict[str, Any]:
        with self.questionnaire_file.open("r", encoding="utf-8") as file:
            flow = json.load(file)

        if "start_node" not in flow or "nodes" not in flow:
            raise ValueError("questionario.json precisa conter start_node e nodes.")
        if flow["start_node"] not in flow["nodes"]:
            raise ValueError("start_node não existe em nodes.")

        return flow

    def get_node(self, node_id: str) -> dict[str, Any]:
        try:
            return self.flow["nodes"][node_id]
        except KeyError as exc:
            raise ValueError(f"Nó não encontrado no questionario.json: {node_id}") from exc

    def present_current_node(self, lead: dict[str, Any]) -> FlowResult:
        node_id = lead.get("current_node") or self.start_node
        return self._advance_to_node(lead, node_id)

    def handle_user_reply(self, lead: dict[str, Any], raw_answer: str | None) -> FlowResult:
        node_id = lead.get("current_node") or self.start_node
        node = self.get_node(node_id)
        node_type = node.get("type")

        if node_type == "question":
            return self._handle_question_node(lead, node_id, node, raw_answer)
        if node_type == "text":
            return self._handle_text_node(lead, node_id, node, raw_answer)

        return self._advance_to_node(lead, node_id)

    def build_summary(
        self,
        lead: dict[str, Any],
        *,
        status: str | None = None,
        department: str | None = None,
    ) -> str:
        refreshed_lead = database.get_lead_by_id(lead["id"]) or lead
        answers = database.get_lead_answers(refreshed_lead["id"])
        final_status = status or refreshed_lead.get("status") or ""

        lines = [
            "Novo atendimento recebido:",
            "",
            f"Nome: {refreshed_lead.get('profile_name') or '-'}",
            f"Telefone: {refreshed_lead.get('phone') or '-'}",
            f"Status: {final_status}",
        ]

        if department:
            lines.append(f"Departamento/Destino: {department}")

        lines.extend(["", "Respostas:"])
        if answers:
            for answer in answers:
                value = (
                    answer.get("selected_label")
                    or answer.get("raw_answer")
                    or answer.get("selected_option")
                    or "-"
                )
                lines.append(f"- {answer.get('field') or answer.get('node_id')}: {value}")
        else:
            lines.append("- Sem respostas registradas.")

        lines.extend(["", "Mensagem inicial:", refreshed_lead.get("initial_message") or ""])
        return "\n".join(lines)

    def _handle_question_node(
        self,
        lead: dict[str, Any],
        node_id: str,
        node: dict[str, Any],
        raw_answer: str | None,
    ) -> FlowResult:
        answer = (raw_answer or "").strip()
        options = node.get("options") or {}

        if not answer.isdigit() or answer not in options:
            repeated_question = node.get("message", "")
            return FlowResult(
                messages=[
                    f"{self.invalid_option_message}\n\n{repeated_question}".strip()
                ]
            )

        selected_option = options[answer]
        selected_label = selected_option.get("label") or ""
        field_name = node.get("field") or node_id
        database.save_lead_answer(
            lead_id=lead["id"],
            node_id=node_id,
            field=field_name,
            raw_answer=answer,
            selected_option=answer,
            selected_label=selected_label,
        )

        next_node_id = selected_option.get("next")
        if not next_node_id:
            updated_lead = database.update_lead(
                lead["id"],
                current_node=node_id,
                status="completed",
            )
            return FlowResult(
                summary_required=True,
                summary_status="completed",
                final_node_id=node_id,
            )

        updated_lead = database.update_lead(
            lead["id"],
            current_node=next_node_id,
            status="in_progress",
        )
        return self._advance_to_node(updated_lead or lead, next_node_id)

    def _handle_text_node(
        self,
        lead: dict[str, Any],
        node_id: str,
        node: dict[str, Any],
        raw_answer: str | None,
    ) -> FlowResult:
        answer = (raw_answer or "").strip()
        field_name = node.get("field") or node_id
        database.save_lead_answer(
            lead_id=lead["id"],
            node_id=node_id,
            field=field_name,
            raw_answer=answer,
        )

        next_node_id = node.get("default_next_after_text") or node.get("next")
        if not next_node_id:
            database.update_lead(
                lead["id"],
                current_node=node_id,
                status="completed",
            )
            return FlowResult(
                summary_required=True,
                summary_status="completed",
                final_node_id=node_id,
            )

        updated_lead = database.update_lead(
            lead["id"],
            current_node=next_node_id,
            status="in_progress",
        )
        return self._advance_to_node(updated_lead or lead, next_node_id)

    def _advance_to_node(self, lead: dict[str, Any], node_id: str) -> FlowResult:
        messages: list[str] = []
        current_node_id = node_id

        for _ in range(30):
            node = self.get_node(current_node_id)
            node_type = node.get("type")

            if node_type in {"question", "text"}:
                database.update_lead(
                    lead["id"],
                    current_node=current_node_id,
                    status="in_progress",
                )
                messages.append(node.get("message", ""))
                return FlowResult(messages=messages, final_node_id=current_node_id)

            if node_type == "message":
                message = node.get("message")
                if message:
                    messages.append(message)

                next_node_id = node.get("next")
                if next_node_id:
                    database.update_lead(
                        lead["id"],
                        current_node=next_node_id,
                        status="in_progress",
                    )
                    current_node_id = next_node_id
                    continue

                final_status = node.get("status") or "completed"
                database.update_lead(
                    lead["id"],
                    current_node=current_node_id,
                    status=final_status,
                )
                return FlowResult(
                    messages=messages,
                    summary_required=True,
                    summary_status=final_status,
                    department=node.get("department"),
                    final_node_id=current_node_id,
                )

            if node_type == "end":
                message = node.get("message")
                if message:
                    messages.append(message)

                final_status = node.get("status") or "completed"
                database.update_lead(
                    lead["id"],
                    current_node=current_node_id,
                    status=final_status,
                )
                return FlowResult(
                    messages=messages,
                    summary_required=True,
                    summary_status=final_status,
                    department=node.get("department"),
                    final_node_id=current_node_id,
                )

            if node_type == "handoff":
                message = node.get("message") or self.handoff_message
                messages.append(message)
                final_status = node.get("status") or "handoff"
                database.update_lead(
                    lead["id"],
                    current_node=current_node_id,
                    status=final_status,
                )
                return FlowResult(
                    messages=messages,
                    summary_required=True,
                    summary_status=final_status,
                    department=node.get("department"),
                    final_node_id=current_node_id,
                )

            raise ValueError(f"Tipo de nó inválido em {current_node_id}: {node_type}")

        raise RuntimeError("Possível loop infinito no fluxo do questionário.")

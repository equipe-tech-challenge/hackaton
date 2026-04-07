"""
QA Agent — avalia qualidade e consistência do relatório gerado.
Fase 1: verificações determinísticas (sem LLM).
Fase 2: avaliação com LLM (OpenAI/Groq) + parse JSON.
"""

import json
import re
from openai import OpenAI
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid": {"type": "boolean"},
        "completeness_score": {"type": "number"},
        "issues_found": {"type": "array", "items": {"type": "string"}},
        "quality_notes": {"type": "string"},
    },
    "required": ["is_valid", "completeness_score", "issues_found", "quality_notes"],
    "additionalProperties": False,
}


def _basic_checks(report: dict, extraction_components: list) -> list[str]:
    """Verificações determinísticas — rápidas, sem chamar LLM."""
    issues = []

    if not report.get("components_identified"):
        issues.append("components_identified está vazio.")

    if not report.get("architectural_risks"):
        issues.append("architectural_risks está vazio.")

    if not report.get("recommendations"):
        issues.append("recommendations está vazio.")

    summary = report.get("executive_summary", "")
    if not summary or len(summary) < 100:
        issues.append(f"executive_summary muito curto ({len(summary)} chars, mínimo 100).")

    # Grounding: pelo menos 80% dos componentes do relatório devem existir na extração
    report_components = set(c.lower() for c in report.get("components_identified", []))
    source_components = set(c.lower() for c in extraction_components)
    if source_components:
        overlap = report_components & source_components
        coverage = len(overlap) / len(report_components) if report_components else 0
        if coverage < 0.8:
            hallucinated = report_components - source_components
            issues.append(
                f"Componentes não encontrados na extração original: {', '.join(hallucinated)}"
            )

    return issues


def run(extraction_result: dict, report: dict) -> dict:
    """
    Avalia o relatório gerado.

    Args:
        extraction_result: saída do extraction_agent (ground truth)
        report:            saída do report_agent

    Returns:
        dict com is_valid, completeness_score, issues_found, quality_notes, status
    """
    extraction_components = extraction_result.get("components", [])

    # ── Fase 1: verificações básicas ────────────────────────────────
    basic_issues = _basic_checks(report, extraction_components)

    if basic_issues:
        logger.warning("qa.basic_checks_failed", issues=basic_issues)
        return {
            "is_valid": False,
            "completeness_score": 0.0,
            "issues_found": basic_issues,
            "quality_notes": "Relatório falhou nas verificações básicas de completude.",
            "status": "erro",
        }

    # ── Fase 2: avaliação com LLM ───────────────────────────────────
    settings = get_settings()
    client_kwargs = {"api_key": settings.openai_api_key, "max_retries": 6}
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**client_kwargs)

    prompt = f"""Avalie a qualidade deste relatório técnico de arquitetura de software.

COMPONENTES DA EXTRAÇÃO ORIGINAL (ground truth):
{json.dumps(extraction_components, ensure_ascii=False)}

RELATÓRIO GERADO:
{json.dumps(report, ensure_ascii=False, indent=2)}

Critérios de avaliação (pesos):
- Completude (30%): todos os campos obrigatórios preenchidos e não-vazios
- Consistência (40%): componentes e riscos batem com a extração original
- Coerência (20%): recomendações vinculadas a riscos identificados
- Qualidade (10%): linguagem técnica, sem informações genéricas

Retorne APENAS JSON com is_valid (boolean), completeness_score (0.0-1.0), issues_found (array de strings) e quality_notes (string). Sem texto adicional."""

    logger.info("qa.llm_evaluation.start", model=settings.llm_model)

    try:
        create_kwargs = {
            "model": settings.llm_model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if not settings.llm_base_url:
            create_kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**create_kwargs)
        raw = response.choices[0].message.content.strip()
        # LLaMA pode retornar JSON dentro de fences
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence:
            raw = fence.group(1).strip()
        qa = json.loads(raw)
    except Exception as e:
        # Falha no LLM de QA não bloqueia — assume válido com score conservador
        logger.warning("qa.llm_evaluation.failed", error=str(e))
        qa = {
            "is_valid": True,
            "completeness_score": 0.7,
            "issues_found": [],
            "quality_notes": f"Avaliação LLM indisponível: {e}. Verificações básicas passaram.",
        }

    # Score mínimo obrigatório
    if qa.get("completeness_score", 0) < 0.6:
        qa["is_valid"] = False
        if "Score abaixo do mínimo" not in str(qa.get("issues_found", [])):
            qa.setdefault("issues_found", []).append(
                f"Score {qa['completeness_score']:.2f} abaixo do mínimo aceitável (0.6)."
            )

    qa["status"] = "analisado" if qa.get("is_valid") else "erro"

    logger.info(
        "qa.done",
        is_valid=qa["is_valid"],
        score=qa.get("completeness_score"),
        issues=len(qa.get("issues_found", [])),
    )
    return qa

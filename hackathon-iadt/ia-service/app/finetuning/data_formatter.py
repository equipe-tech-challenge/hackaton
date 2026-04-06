"""
Data Formatter — converte pares brutos para JSONL no formato chat instruction-tuning.

Formato de saída (compatível com SFTTrainer do trl e maioria dos LLMs):
{
  "messages": [
    {"role": "system",    "content": "<system prompt>"},
    {"role": "user",      "content": "<extraction + risks + rag formatados>"},
    {"role": "assistant", "content": "<JSON do relatório>"}
  ]
}

Uso:
    python -m app.finetuning.data_formatter \
        --input  ./data/raw_pairs.jsonl \
        --output ./data \
        --split  0.9
"""

import argparse
import json
import random
from pathlib import Path

# System prompt — espelha exatamente o usado em report_agent.py
_SYSTEM_PROMPT = (
    "Você é um arquiteto de software sênior gerando relatórios técnicos.\n"
    "Baseie-se APENAS nos dados fornecidos. Não invente componentes ou riscos.\n"
    "Use linguagem técnica em português. Retorne APENAS JSON válido."
)


def _build_user_message(extraction: dict, risks: dict, rag_enrichment: str = "") -> str:
    """Constrói a mensagem do usuário no mesmo formato do report_agent.py."""
    components = extraction.get("components", [])
    patterns = extraction.get("patterns", [])
    risk_list = risks.get("risks", [])
    severity = risks.get("severity_summary", {"high": 0, "medium": 0, "low": 0})

    rag_section = (
        f"=== CONTEXTO DE ARQUITETURAS SIMILARES (RAG) ===\n{rag_enrichment}\n"
        "Identifique com [RAG] as recomendações influenciadas por este contexto histórico."
        if rag_enrichment
        else "Sem contexto histórico disponível para esta análise."
    )

    return f"""Gere um relatório técnico com base nos dados abaixo:

=== COMPONENTES ===
{json.dumps(components, ensure_ascii=False)}

=== PADRÕES ARQUITETURAIS ===
{json.dumps(patterns, ensure_ascii=False)}

=== RISCOS IDENTIFICADOS ===
{json.dumps(risk_list, ensure_ascii=False)}

=== SEVERIDADE ===
Alto: {severity.get('high', 0)} | Médio: {severity.get('medium', 0)} | Baixo: {severity.get('low', 0)}

{rag_section}

Retorne JSON com exatamente estas chaves:
{{
  "components_identified": ["lista de componentes"],
  "architectural_risks": [
    {{
      "type": "tipo",
      "description": "descrição",
      "severity": "ALTO|MÉDIO|BAIXO",
      "affected_components": ["componentes"],
      "mitigation": "mitigação"
    }}
  ],
  "recommendations": ["lista de recomendações — use [RAG] nas influenciadas pelo contexto histórico"],
  "executive_summary": "sumário executivo em até 3 parágrafos",
  "rag_used": false
}}"""


def _validate_pair(pair: dict) -> bool:
    """Valida que o par tem todos os campos obrigatórios e JSON parseable."""
    try:
        report = pair.get("report", {})
        required_keys = {"components_identified", "architectural_risks", "recommendations", "executive_summary"}
        if not required_keys.issubset(report.keys()):
            return False
        if not report.get("components_identified"):
            return False
        if not report.get("recommendations"):
            return False
        summary = report.get("executive_summary", "")
        if not summary or len(summary) < 50:
            return False
        # Valida que o report é serializável em JSON
        json.dumps(report, ensure_ascii=False)
        return True
    except (TypeError, ValueError):
        return False


def format_pairs(
    input_path: str,
    output_dir: str,
    train_split: float = 0.9,
    seed: int = 42,
) -> tuple[int, int]:
    """
    Lê o JSONL bruto, converte para formato chat e grava train.jsonl e val.jsonl.

    Args:
        input_path:  Caminho do arquivo raw_pairs.jsonl.
        output_dir:  Diretório de saída para train.jsonl e val.jsonl.
        train_split: Fração dos dados para treino (padrão: 0.9).
        seed:        Seed para shuffle reproduzível.

    Returns:
        Tupla (n_train, n_val).
    """
    raw_pairs: list[dict] = []
    skipped = 0

    with open(input_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                pair = json.loads(line)
                if _validate_pair(pair):
                    raw_pairs.append(pair)
                else:
                    print(f"  [SKIP] Linha {i}: par inválido ou incompleto")
                    skipped += 1
            except json.JSONDecodeError as exc:
                print(f"  [SKIP] Linha {i}: JSON inválido — {exc}")
                skipped += 1

    print(f"Pares carregados: {len(raw_pairs)} válidos, {skipped} ignorados")

    random.seed(seed)
    random.shuffle(raw_pairs)

    split_idx = int(len(raw_pairs) * train_split)
    train_pairs = raw_pairs[:split_idx]
    val_pairs = raw_pairs[split_idx:]

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    train_path = Path(output_dir) / "train.jsonl"
    val_path = Path(output_dir) / "val.jsonl"

    for path, pairs in [(train_path, train_pairs), (val_path, val_pairs)]:
        with open(path, "w", encoding="utf-8") as f:
            for pair in pairs:
                example = {
                    "messages": [
                        {"role": "system",    "content": _SYSTEM_PROMPT},
                        {"role": "user",      "content": _build_user_message(
                            pair["extraction"], pair["risks"]
                        )},
                        {"role": "assistant", "content": json.dumps(
                            pair["report"], ensure_ascii=False
                        )},
                    ]
                }
                f.write(json.dumps(example, ensure_ascii=False) + "\n")

    print(f"✅ Treino:  {len(train_pairs)} exemplos → {train_path}")
    print(f"✅ Val:     {len(val_pairs)} exemplos  → {val_path}")
    return len(train_pairs), len(val_pairs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Formata dados brutos para fine-tuning")
    parser.add_argument("--input",  default="./data/raw_pairs.jsonl", help="JSONL bruto de entrada")
    parser.add_argument("--output", default="./data",                  help="Diretório de saída")
    parser.add_argument("--split",  type=float, default=0.9,           help="Fração treino")
    parser.add_argument("--seed",   type=int,   default=42,            help="Seed para shuffle")
    args = parser.parse_args()

    format_pairs(args.input, args.output, args.split, args.seed)

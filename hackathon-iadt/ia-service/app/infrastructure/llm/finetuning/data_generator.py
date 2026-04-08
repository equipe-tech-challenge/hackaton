"""
Data Generator — gera pares de treino (input → relatório) usando um LLM como professor.

Estratégia:
  1. Para cada template de arquitetura, gera extraction_result sintético via LLM.
  2. Gera o risk_result correspondente via LLM.
  3. Gera o relatório gold-standard usando o MESMO system prompt do report_agent.
  4. Salva os pares em formato bruto para processamento pelo data_formatter.

O LLM professor garante que os dados de treino sigam exatamente o schema
esperado pelo pipeline, evitando inconsistências de formato.

Uso:
    python -m app.finetuning.data_generator --output ./data/raw_pairs.jsonl
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ──────────────────────────────────────────────
# System prompts (espelham os agentes reais)
# ──────────────────────────────────────────────

_EXTRACTION_SYSTEM = """Você é um arquiteto de software sênior simulando a saída de um sistema de análise de diagramas.
Gere dados realistas de extração de um diagrama de arquitetura de software.
Retorne APENAS um JSON válido, sem texto adicional."""

_RISK_SYSTEM = """Você é um arquiteto de software sênior especializado em identificação de riscos arquiteturais.
Gere uma análise de riscos realista com base nos componentes fornecidos.
Retorne APENAS um JSON válido, sem texto adicional."""

_REPORT_SYSTEM = """Você é um arquiteto de software sênior gerando relatórios técnicos.
Baseie-se APENAS nos dados fornecidos. Não invente componentes ou riscos.
Use linguagem técnica em português. Retorne APENAS JSON válido."""

# Descrições dos templates de arquitetura para guiar a geração
_TEMPLATE_DESCRIPTIONS = {
    "microservices_api_gateway": "Arquitetura de microsserviços com API Gateway, serviços de autenticação, catálogo de produtos e banco de dados por serviço",
    "monolith_single_db": "Aplicação monolítica com único banco de dados relacional, servidor web e cache Redis",
    "event_driven_kafka": "Arquitetura orientada a eventos com Kafka, múltiplos consumers, serviço de notificação e storage",
    "serverless_lambda_dynamodb": "Arquitetura serverless com AWS Lambda, API Gateway, DynamoDB e S3",
    "kubernetes_service_mesh": "Cluster Kubernetes com Istio service mesh, múltiplos deployments e Prometheus para observabilidade",
    "cqrs_event_sourcing": "Padrão CQRS com event sourcing, projeções read-only, event store e múltiplos read models",
    "bff_mobile_web": "Backend For Frontend com BFF separado para mobile e web, serviços compartilhados downstream",
    "data_pipeline_etl": "Pipeline ETL com ingestão de dados, processamento batch com Spark, data warehouse e dashboard",
    "hexagonal_clean_arch": "Aplicação com arquitetura hexagonal, ports e adapters, múltiplos adaptadores de entrada e saída",
    "multi_region_failover": "Arquitetura multi-região com failover automático, Route53, replicação de banco e CDN",
}


def _call_llm(client, prompt: str, system: str, model: str) -> dict:
    """Chama o LLM e parseia o JSON retornado."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return json.loads(raw)


def _generate_extraction(client, template: str, description: str, variation: int, model: str) -> dict:
    prompt = f"""Simule a extração de um diagrama de arquitetura do tipo: {description}
Variação {variation}/5 — use componentes e nomes ligeiramente diferentes das variações anteriores.

Retorne JSON com exatamente estas chaves:
{{
  "components": ["lista de 5-12 componentes identificados no diagrama"],
  "relationships": ["lista de 4-8 relacionamentos no formato 'ComponenteA → ComponenteB: descrição'"],
  "patterns": ["lista de 1-4 padrões arquiteturais identificados"],
  "raw_description": "descrição textual completa do diagrama em 2-3 parágrafos"
}}"""
    return _call_llm(client, prompt, _EXTRACTION_SYSTEM, model)


def _generate_risks(client, extraction: dict, model: str) -> dict:
    prompt = f"""Com base nos componentes e padrões abaixo, identifique riscos arquiteturais:

Componentes: {json.dumps(extraction['components'], ensure_ascii=False)}
Relacionamentos: {json.dumps(extraction['relationships'], ensure_ascii=False)}
Padrões: {json.dumps(extraction['patterns'], ensure_ascii=False)}

Retorne JSON com exatamente estas chaves:
{{
  "risks": [
    {{
      "type": "SPOF|Segurança|Escalabilidade|Acoplamento|Observabilidade|Resiliência",
      "description": "descrição do risco",
      "severity": "ALTO|MÉDIO|BAIXO",
      "affected_components": ["componentes afetados"],
      "mitigation": "sugestão de mitigação"
    }}
  ],
  "severity_summary": {{"high": 0, "medium": 0, "low": 0}}
}}

Identifique entre 2 e 6 riscos. severity_summary deve contar os totais."""
    return _call_llm(client, prompt, _RISK_SYSTEM, model)


def _generate_report(client, extraction: dict, risks: dict, model: str) -> dict:
    components = extraction.get("components", [])
    patterns = extraction.get("patterns", [])
    risk_list = risks.get("risks", [])
    severity = risks.get("severity_summary", {"high": 0, "medium": 0, "low": 0})

    prompt = f"""Gere um relatório técnico com base nos dados abaixo:

=== COMPONENTES ===
{json.dumps(components, ensure_ascii=False)}

=== PADRÕES ARQUITETURAIS ===
{json.dumps(patterns, ensure_ascii=False)}

=== RISCOS IDENTIFICADOS ===
{json.dumps(risk_list, ensure_ascii=False)}

=== SEVERIDADE ===
Alto: {severity.get('high', 0)} | Médio: {severity.get('medium', 0)} | Baixo: {severity.get('low', 0)}

Sem contexto histórico disponível para esta análise.

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
  "recommendations": ["lista de 3-6 recomendações específicas e acionáveis"],
  "executive_summary": "sumário executivo em até 3 parágrafos (mínimo 150 caracteres)",
  "rag_used": false
}}"""
    return _call_llm(client, prompt, _REPORT_SYSTEM, model)


def generate(
    api_key: str,
    model: str,
    output_path: str,
    num_samples: int = 50,
    delay_seconds: float = 1.0,
) -> list[dict]:
    """
    Gera pares de treino sintéticos e salva em JSONL.

    Args:
        api_key:       Chave de API do LLM professor.
        model:         ID do modelo a usar como professor.
        output_path:   Caminho do arquivo JSONL de saída.
        num_samples:   Número de pares a gerar.
        delay_seconds: Pausa entre chamadas (respeitar rate limit).

    Returns:
        Lista de pares gerados.
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        raise RuntimeError("anthropic não instalado. Execute: pip install anthropic")

    templates = list(_TEMPLATE_DESCRIPTIONS.items())
    pairs = []
    count = 0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for template_name, template_desc in templates:
            if count >= num_samples:
                break

            variations = min(5, num_samples - count)
            for v in range(1, variations + 1):
                print(f"[{count + 1}/{num_samples}] {template_name} — variação {v}", flush=True)

                try:
                    extraction = _generate_extraction(client, template_name, template_desc, v, model)
                    time.sleep(delay_seconds)

                    risks = _generate_risks(client, extraction, model)
                    time.sleep(delay_seconds)

                    report = _generate_report(client, extraction, risks, model)
                    time.sleep(delay_seconds)

                    pair = {
                        "template": template_name,
                        "variation": v,
                        "extraction": extraction,
                        "risks": risks,
                        "report": report,
                    }
                    pairs.append(pair)
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    f.flush()

                    count += 1

                except (json.JSONDecodeError, KeyError) as exc:
                    print(f"  [WARN] Erro ao gerar par ({template_name} v{v}): {exc}", flush=True)
                    continue

    print(f"\n✅ {count} pares gerados → {output_path}", flush=True)
    return pairs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gerador de dados de treino para fine-tuning")
    parser.add_argument("--api-key", default=os.getenv("ANTHROPIC_API_KEY"), help="Chave de API")
    parser.add_argument("--model", default="claude-3-5-sonnet-20241022", help="Modelo professor")
    parser.add_argument("--output", default="./data/raw_pairs.jsonl", help="Arquivo de saída")
    parser.add_argument("--samples", type=int, default=50, help="Número de pares")
    parser.add_argument("--delay", type=float, default=1.0, help="Pausa entre chamadas (s)")
    args = parser.parse_args()

    if not args.api_key:
        print("ERRO: defina --api-key ou a variável ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    generate(
        api_key=args.api_key,
        model=args.model,
        output_path=args.output,
        num_samples=args.samples,
        delay_seconds=args.delay,
    )

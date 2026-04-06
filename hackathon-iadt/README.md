# Hackathon FIAP — Time IADT · Análise de Diagramas de Arquitetura com IA

Sistema de análise automatizada de diagramas de arquitetura de software. Recebe imagens ou PDFs de diagramas via fila SQS, processa com um pipeline de 6 agentes de IA e devolve um relatório técnico estruturado via webhook.

---

## Índice

1. [Visão Geral](#1-visão-geral)
2. [Arquitetura](#2-arquitetura)
3. [Componentes](#3-componentes)
4. [Pipeline de IA — 6 Agentes](#4-pipeline-de-ia--6-agentes)
5. [RAG com pgvector](#5-rag-com-pgvector)
6. [Guardrails e Controle de Qualidade](#6-guardrails-e-controle-de-qualidade)
7. [Webhook de Devolutiva](#7-webhook-de-devolutiva)
8. [Fine-Tuning](#8-fine-tuning)
9. [Schema do Banco de Dados](#9-schema-do-banco-de-dados)
10. [Configuração de Ambiente](#10-configuração-de-ambiente)
11. [Execução](#11-execução)
12. [API Reference](#12-api-reference)
13. [Testes](#13-testes)
14. [Segurança](#14-segurança)
15. [Limitações e Decisões de Projeto](#15-limitações-e-decisões-de-projeto)

---

## 1. Visão Geral

### O Problema

Empresas que operam sistemas distribuídos possuem dezenas de diagramas de arquitetura armazenados como imagens ou PDFs. Sua análise é feita **manualmente**, demanda muito tempo, depende de especialistas e **não escala**.

### A Solução

Este serviço automatiza a análise usando um pipeline de IA que:

- **Lê** o diagrama visualmente (sem OCR — usa LLM Vision multimodal)
- **Extrai** componentes, relacionamentos e padrões arquiteturais
- **Enriquece** a análise com contexto de diagramas similares já processados (RAG)
- **Classifica** riscos em 6 categorias com severidade
- **Gera** um relatório técnico estruturado em JSON
- **Valida** o relatório automaticamente com critérios de qualidade
- **Devolve** o resultado via webhook para o sistema solicitante

### Responsabilidade do Time IADT

O time IADT é responsável pelos 3 serviços deste repositório:

| Serviço | Porta | Responsabilidade |
|---|---|---|
| `ia-service` | 8000 | Pipeline de IA + SQS consumer + webhook |
| `report-api` | 8001 | API REST de consulta de relatórios (read-only) |
| `pgvector` | 5432 | PostgreSQL com extensão vetorial para RAG |

O time **SOAT** é responsável pelo API Gateway, serviço de upload, publicação na fila SQS e infraestrutura AWS.

---

## 2. Arquitetura

```
                         ┌─────────────────────────────────────┐
                         │           SOAT (Externo)            │
                         │  API Gateway · Upload Service · S3  │
                         └────────────┬────────────────────────┘
                                      │ publica mensagem
                                      ▼
                              ┌───────────────┐
                              │   AWS SQS     │
                              │     Fila      │
                              └───────┬───────┘
                                      │ long polling (20s)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ia-service (:8000)                             │
│                                                                             │
│  ┌──────────────┐    ┌─────────────────────────────────────────────────┐   │
│  │ SQS Consumer │───▶│              Pipeline de 6 Agentes              │   │
│  │ (thread)     │    │                                                 │   │
│  └──────────────┘    │  Ingestion → Extraction → RAG → Risk →         │   │
│                      │  Report → QA                                    │   │
│  ┌──────────────┐    └──────────────────────┬──────────────────────────┘  │
│  │  FastAPI     │                           │ persiste                    │
│  │  /analyze    │                           ▼                            │
│  │  /health     │    ┌────────────────────────────────────────────────┐  │
│  │  /status     │    │          PostgreSQL + pgvector                 │  │
│  └──────────────┘    │  analyses · extraction_results · reports       │  │
│                      │  langchain_pg_embedding (vectors 1536d)        │  │
│  ┌──────────────┐    └────────────────────────────────────────────────┘  │
│  │   Webhook    │                                                          │
│  │   Sender     │───▶  POST callback_url · retry 3x backoff              │
│  └──────────────┘                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │   report-api (:8001)   │
                         │  GET /reports/{id}     │
                         │  GET /reports          │
                         └────────────────────────┘
```

### Diagrama de Componentes

![Diagrama de Arquitetura](docs/architecture.png)

---

## 3. Componentes

### 3.1 ia-service

Serviço principal. Responsável pelo pipeline de IA, consumer SQS e webhook.

**Estrutura de pastas:**

```
ia-service/
└── app/
    ├── main.py                  # FastAPI + startup do SQS consumer
    ├── config.py                # Settings via pydantic-settings
    ├── webhook.py               # Envio de resultado via HTTP POST
    ├── sqs_consumer.py          # Consumer SQS com graceful shutdown
    │
    ├── pipeline/
    │   ├── orchestrator.py      # Coordena os 6 agentes
    │   ├── ingestion_agent.py   # Validação e conversão do arquivo
    │   ├── extraction_agent.py  # LLM Vision — extração de componentes
    │   ├── rag_agent.py         # pgvector — indexação e busca
    │   ├── risk_agent.py        # LLM — classificação de riscos
    │   ├── report_agent.py      # LLM — geração do relatório
    │   └── qa_agent.py          # Validação de qualidade do relatório
    │
    ├── finetuning/
    │   ├── config.py            # Hiperparâmetros de treino
    │   ├── data_generator.py    # Geração de dados sintéticos via LLM
    │   ├── data_formatter.py    # Conversão para JSONL formato chat
    │   ├── train.py             # Script QLoRA (roda em GPU externa)
    │   └── inference.py         # Cliente de inferência (HF API ou local)
    │
    ├── db/
    │   ├── connection.py        # SQLAlchemy engine + session factory
    │   └── repositories.py      # CRUD: analyses, extraction_results, reports
    │
    └── utils/
        ├── exceptions.py        # PipelineError, GuardrailError, RAGError...
        └── logger.py            # Structured logging (JSON via structlog)
```

### 3.2 report-api

API read-only para consulta de relatórios gerados. Usada pelo API Gateway do time SOAT.

**Endpoints:**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Healthcheck — verifica conexão com DB |
| `GET` | `/reports/{analysis_id}` | Relatório completo de uma análise |
| `GET` | `/reports?limit=20&offset=0` | Lista paginada de análises |

### 3.3 pgvector

PostgreSQL 16 com extensão `pgvector`. Armazena:
- Estado de cada análise (`analyses`)
- Cache de extração para evitar reprocessamento (`extraction_results`)
- Relatórios gerados com métricas de QA (`reports`)
- Embeddings vetoriais para o RAG (`langchain_pg_embedding`)

---

## 4. Pipeline de IA — 6 Agentes

O pipeline é **sequencial**, gerenciado pelo `orchestrator.py`. Cada agente recebe a saída do anterior e produz um resultado estruturado.

```
[arquivo binário]
      │
      ▼
① Ingestion Agent          → valida, converte para base64
      │
      ▼
② Extraction Agent         → LLM Vision → componentes, relacionamentos, padrões
      │           │
      │           ▼
      │     ③ RAG Agent    → indexa no pgvector, busca similares (não-bloqueante)
      │           │
      ▼           ▼
④ Risk Agent               → LLM Adaptive Thinking → 6 categorias de risco
      │
      ▼
⑤ Report Agent             → LLM + Guardrails → relatório JSON estruturado
      │
      ▼
⑥ QA Agent                 → 2 fases de validação → score de qualidade
      │
      ▼
[PostgreSQL] + [Webhook]
```

### Agente 1 — Ingestion Agent

**Arquivo:** `pipeline/ingestion_agent.py`

Responsável por validar o arquivo recebido e prepará-lo para o LLM Vision.

**O que faz:**
- Valida o tamanho: rejeita arquivos > 20MB
- Detecta o MIME type pelo nome do arquivo
- Verifica se o tipo é suportado: `png`, `jpg`, `jpeg`, `gif`, `webp`, `pdf`
- Converte o conteúdo binário para Base64

**Saída:**
```json
{
  "file_name": "diagrama.png",
  "file_type": "png",
  "media_type": "image/png",
  "content_base64": "iVBORw0KGgo...",
  "file_size_kb": 512.3
}
```

**Falha:** Lança `IngestionError` — **bloqueia o pipeline**.

---

### Agente 2 — Extraction Agent

**Arquivo:** `pipeline/extraction_agent.py`

Usa um **LLM com capacidade Vision** para interpretar o diagrama visualmente e extrair informações estruturadas.

> **Não usa OCR.** O arquivo (imagem ou PDF) é enviado diretamente para o LLM como conteúdo multimodal. O modelo interpreta o diagrama com compreensão semântica — lê setas, caixas, relacionamentos e padrões arquiteturais — sem necessidade de extração de texto intermediária.

**Como funciona:**
1. Monta um bloco multimodal com o arquivo em Base64
2. Para imagens: `{type: "image", source: {type: "base64", data: "..."}}`
3. Para PDFs: `{type: "document", source: {type: "base64", media_type: "application/pdf", data: "..."}}`
4. Envia para o LLM com prompt de extração estruturada
5. Parseia o JSON retornado e valida campos obrigatórios

**Saída:**
```json
{
  "components": ["API Gateway", "Auth Service", "User DB", "Redis Cache"],
  "relationships": [
    "Client → API Gateway: requisições HTTP",
    "API Gateway → Auth Service: valida JWT",
    "Auth Service → User DB: consulta usuário"
  ],
  "patterns": ["Microservices", "API Gateway Pattern", "JWT Authentication"],
  "raw_description": "O diagrama apresenta uma arquitetura de microsserviços..."
}
```

**Falha:** Lança `ExtractionError` — **bloqueia o pipeline**.

---

### Agente 3 — RAG Agent

**Arquivo:** `pipeline/rag_agent.py`

Implementa **Retrieval-Augmented Generation** usando LangChain + pgvector. Enriquece a análise com contexto de diagramas similares já processados anteriormente.

> **Não-bloqueante:** Se o pgvector estiver indisponível ou não houver análises no histórico, retorna `has_context: false` e o pipeline continua normalmente.

**Como funciona:**

Fase de Indexação (toda nova análise):
```
extraction_result
      │
      ▼
LangChain Document (page_content = raw_description + components + patterns)
      │
      ▼
Embeddings (modelo de texto → vetor 1536 dimensões)
      │
      ▼
PGVector.add_documents() → langchain_pg_embedding
```

Fase de Recuperação (antes do risk_agent):
```
query = raw_description + components + patterns
      │
      ▼
Embeddings → query vector
      │
      ▼
PGVector.similarity_search_with_score(k=3, filter={"has_report": True})
      │
      ├── distância coseno < 0.3 → similar (>70%) → inclui no contexto
      └── distância coseno ≥ 0.3 → descarta
      │
      ▼
LLM chain → rag_enrichment (recomendações baseadas no histórico)
```

**Saída:**
```json
{
  "has_context": true,
  "rag_enrichment": "Análises similares indicam risco recorrente de SPOF no banco...",
  "similar_analyses": [
    {"analysis_id": "uuid", "similarity_score": 0.87, "components_count": 8, "risks_high": 2}
  ]
}
```

---

### Agente 4 — Risk Agent

**Arquivo:** `pipeline/risk_agent.py`

Classifica riscos arquiteturais em 6 categorias usando LLM com **Adaptive Thinking** — o modelo "pensa" antes de responder, produzindo análises mais profundas para arquiteturas complexas.

**Categorias avaliadas:**

| Categoria | O que avalia |
|---|---|
| **SPOF** | Pontos únicos de falha sem redundância |
| **Segurança** | Ausência de autenticação, dados expostos, endpoints sem proteção |
| **Escalabilidade** | Gargalos, ausência de cache, filas sem DLQ |
| **Acoplamento** | Dependências síncronas excessivas, falta de interfaces |
| **Observabilidade** | Ausência de logs, métricas, tracing |
| **Resiliência** | Sem circuit breaker, retry, fallback |

O contexto RAG (quando disponível) é incluído no prompt para identificar padrões de risco recorrentes em arquiteturas similares.

**Saída:**
```json
{
  "risks": [
    {
      "type": "SPOF",
      "description": "User DB sem réplica de leitura",
      "severity": "ALTO",
      "affected_components": ["User DB"],
      "mitigation": "Adicionar réplica read-only com failover automático"
    }
  ],
  "severity_summary": {"high": 1, "medium": 2, "low": 1}
}
```

**Falha:** Lança `RiskAnalysisError` — **bloqueia o pipeline**.

---

### Agente 5 — Report Agent

**Arquivo:** `pipeline/report_agent.py`

Gera o relatório técnico estruturado. Suporta **dois backends configuráveis** via variável de ambiente `REPORT_MODEL_BACKEND`.

**Backend `langchain` (padrão):**
- Usa LangChain `ChatPromptTemplate | LLM | JsonOutputParser`
- Modelo configurável via `LLM_MODEL`
- Inclui seção RAG condicional no prompt (marcada com `[RAG]`)

**Backend `finetuned_api` / `finetuned_local`:**
- Usa LLM fine-tunado com QLoRA (ver seção Fine-Tuning)
- Mesma interface de entrada/saída do backend padrão
- Guardrails aplicados igualmente em ambos os backends

**Guardrails pós-geração** (compartilhados entre todos os backends):
- `components_identified` não pode estar vazio
- Componentes inventados não podem superar 20% dos componentes da extração
- `recommendations` não pode estar vazio
- `executive_summary` deve ter no mínimo 100 caracteres

**Saída:**
```json
{
  "components_identified": ["API Gateway", "Auth Service", "User DB"],
  "architectural_risks": [...],
  "recommendations": [
    "Configurar DLQ no SQS para mensagens não processadas",
    "[RAG] Implementar circuit breaker — padrão recorrente em arquiteturas similares"
  ],
  "executive_summary": "A arquitetura analisada implementa um padrão de microsserviços...",
  "rag_used": true
}
```

**Falha:** Lança `ReportGenerationError` — **bloqueia o pipeline**.

---

### Agente 6 — QA Agent

**Arquivo:** `pipeline/qa_agent.py`

Valida o relatório gerado em **duas fases** antes de persistir.

**Fase 1 — Verificações Determinísticas (sem LLM):**
- `components_identified` não vazio
- `architectural_risks` não vazio
- `recommendations` não vazio
- `executive_summary` com no mínimo 100 caracteres
- Grounding: ao menos 80% dos componentes do relatório existem na extração original

Se a Fase 1 falhar, o relatório é rejeitado imediatamente sem chamar o LLM.

**Fase 2 — Avaliação com LLM (JSON Schema forçado):**

O LLM avalia 4 critérios com pesos:
- **Completude (30%):** todos os campos obrigatórios preenchidos
- **Consistência (40%):** componentes e riscos batem com a extração original
- **Coerência (20%):** recomendações vinculadas a riscos identificados
- **Qualidade (10%):** linguagem técnica, sem generalidades

O output é forçado via `json_schema` estrito — o LLM é obrigado a retornar o formato correto.

**Score mínimo:** `0.6` — relatórios abaixo disso são rejeitados (`is_valid: false`).

> **Resiliência:** se o LLM de QA estiver indisponível, assume `is_valid: true` com score conservador `0.7`, desde que a Fase 1 tenha passado.

**Saída:**
```json
{
  "is_valid": true,
  "completeness_score": 0.92,
  "issues_found": [],
  "quality_notes": "Relatório completo, consistente e bem fundamentado.",
  "status": "analisado"
}
```

---

## 5. RAG com pgvector

O sistema aprende com análises anteriores. Quanto mais diagramas forem processados, mais rico fica o contexto histórico fornecido ao pipeline.

### Como o RAG melhora o relatório

- O **Risk Agent** usa o contexto RAG para identificar padrões de risco recorrentes
- O **Report Agent** marca com `[RAG]` as recomendações baseadas em histórico
- O relatório final informa `rag_used: true/false` para rastreabilidade

### Índice HNSW

```sql
-- Criado automaticamente pelo pgvector após a primeira análise
CREATE INDEX ON langchain_pg_embedding
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

O índice HNSW (Hierarchical Navigable Small World) garante buscas por similaridade com latência inferior a 50ms mesmo com milhares de embeddings.

### Threshold de similaridade

```python
# score < 0.3 (distância coseno) = similaridade > 70%
relevant = [(doc, score) for doc, score in similar_docs if score < 0.3]
```

Apenas análises com similaridade alta (> 70%) são incluídas no contexto. Isso evita que arquiteturas muito diferentes influenciem o relatório.

---

## 6. Guardrails e Controle de Qualidade

O sistema implementa múltiplas camadas de proteção contra alucinações e saídas inválidas:

| Guardrail | Onde | Implementação |
|---|---|---|
| **Tipo e tamanho de arquivo** | Ingestion Agent | Bloqueia arquivos > 20MB e tipos não suportados |
| **Componentes visíveis apenas** | Extraction Agent | Prompt instrui a identificar apenas o que está no diagrama |
| **Grounding check** | Report Agent | Componentes inventados > 20% dos extraídos = `GuardrailError` |
| **Completude mínima** | Report Agent | `recommendations` não vazio, `executive_summary` > 100 chars |
| **JSON Schema estrito** | QA Agent | `output_config` força o LLM a retornar formato correto |
| **Score mínimo de qualidade** | QA Agent | Score < 0.6 = relatório rejeitado |
| **Grounding duplo** | QA Agent | >= 80% dos componentes do relatório existem na extração |
| **Transparência RAG** | Report Agent | Tag `[RAG]` em recomendações de origem histórica |

---

## 7. Webhook de Devolutiva

Após o pipeline concluir (sucesso ou erro), o serviço envia o resultado via HTTP POST para o `callback_url` informado na mensagem SQS.

### Política de retry

```
Tentativa 1 → falha → aguarda 2s
Tentativa 2 → falha → aguarda 4s
Tentativa 3 → falha → loga erro → pipeline continua
```

- **Retenta em:** timeout, erro de conexão, respostas 5xx
- **Não retenta em:** respostas 4xx (erro do cliente)
- **Falha total não bloqueia:** resultado já está no banco de dados

### Payload de sucesso

```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analisado",
  "report": {
    "components_identified": ["API Gateway", "Auth Service"],
    "architectural_risks": [...],
    "recommendations": [...],
    "executive_summary": "...",
    "rag_used": true
  },
  "error_message": null,
  "completed_at": "2026-04-02T21:30:00.000Z"
}
```

### Payload de erro

```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "erro",
  "report": null,
  "error_message": "Arquivo excede o limite de 20MB.",
  "completed_at": "2026-04-02T21:30:00.000Z"
}
```

---

## 8. Fine-Tuning

O módulo de fine-tuning treina um LLM open-source com QLoRA para gerar relatórios no formato exato exigido pelo pipeline — como alternativa ao LLM principal.

### Visão geral

```
[LLM professor]
      │  gera 50-75 pares sintéticos
      ▼
data_generator.py  →  raw_pairs.jsonl
      │
      ▼
data_formatter.py  →  train.jsonl + val.jsonl (formato chat)
      │
      ▼
train.py           →  LoRA adapter (roda em GPU: Colab, RunPod)
      │
      ▼
HuggingFace Hub    →  adapter publicado
      │
      ▼
inference.py       →  HuggingFaceAPIClient ← report_agent.py
```

### Passo a passo

**1. Instalar dependências de treino (apenas em máquina com GPU):**

```bash
pip install -r ia-service/finetuning-requirements.txt
```

**2. Gerar dados sintéticos de treino:**

```bash
cd ia-service
python -m app.finetuning.data_generator \
  --api-key $ANTHROPIC_API_KEY \
  --samples 50 \
  --output ./data/raw_pairs.jsonl
```

O gerador cria pares `(extração + riscos) → relatório` usando um LLM como professor, garantindo que os dados seguem o mesmo formato esperado pelo pipeline.

**3. Formatar para fine-tuning:**

```bash
python -m app.finetuning.data_formatter \
  --input ./data/raw_pairs.jsonl \
  --output ./data \
  --split 0.9
```

Gera `train.jsonl` (90%) e `val.jsonl` (10%) no formato chat compatível com `SFTTrainer`.

**4. Treinar (em GPU — ex: Google Colab A100):**

```bash
python -m app.finetuning.train \
  --epochs 3 \
  --output-dir ./output/report-lora-adapter \
  --push-to-hub \
  --hub-model-id "seu-usuario/report-lora"
```

Configuração QLoRA: 4-bit (NF4), LoRA r=16/alpha=32, 3 epochs, lr=2e-4, batch efetivo=16.

**5. Usar o modelo fine-tunado no pipeline:**

```bash
# .env
REPORT_MODEL_BACKEND=finetuned_api
HUGGINGFACE_API_TOKEN=hf_...
HUGGINGFACE_ENDPOINT_URL=https://api-inference.huggingface.co/models/seu-usuario/report-lora
```

### Backends disponíveis

| `REPORT_MODEL_BACKEND` | Descrição | Quando usar |
|---|---|---|
| `langchain` | LangChain + LLM via `LLM_MODEL` | Padrão — não requer GPU |
| `finetuned_api` | LLM fine-tunado via HuggingFace Inference API | Com modelo treinado hospedado |
| `finetuned_local` | Adapter carregado localmente | Desenvolvimento com GPU local |

> Os guardrails são aplicados **igualmente em todos os backends**.

---

## 9. Schema do Banco de Dados

```sql
-- Ciclo de vida de cada análise
CREATE TABLE analyses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status          VARCHAR(50) NOT NULL DEFAULT 'recebido',
    -- recebido | em_processamento | analisado | erro
    file_name       VARCHAR(500) NOT NULL,
    file_type       VARCHAR(50) NOT NULL,
    s3_key          VARCHAR(1000),
    sqs_message_id  VARCHAR(255) UNIQUE,   -- garante idempotência SQS
    error_message   TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Cache da extração (evita re-chamar Vision LLM em retries)
CREATE TABLE extraction_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components      JSONB NOT NULL DEFAULT '[]',
    relationships   JSONB NOT NULL DEFAULT '[]',
    patterns        JSONB NOT NULL DEFAULT '[]',
    raw_description TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Relatório técnico gerado + métricas de QA
CREATE TABLE reports (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id           UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components_identified JSONB NOT NULL DEFAULT '[]',
    architectural_risks   JSONB NOT NULL DEFAULT '[]',
    recommendations       JSONB NOT NULL DEFAULT '[]',
    executive_summary     TEXT NOT NULL,
    rag_used              BOOLEAN DEFAULT FALSE,
    qa_is_valid           BOOLEAN,
    qa_completeness_score NUMERIC(4,3),
    qa_issues_found       JSONB DEFAULT '[]',
    qa_quality_notes      TEXT,
    created_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Gerenciada automaticamente pelo LangChain/pgvector
-- langchain_pg_embedding: embedding vector(1536), document TEXT, cmetadata JSONB
```

---

## 10. Configuração de Ambiente

Copie o arquivo de exemplo e preencha as variáveis:

```bash
cp ia-service/.env.example ia-service/.env
```

### Variáveis obrigatórias

| Variável | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | Chave de API Anthropic |
| `OPENAI_API_KEY` | Chave OpenAI para embeddings (`text-embedding-3-small`) |
| `POSTGRES_CONNECTION_STRING` | Connection string para LangChain/pgvector |
| `SQS_QUEUE_URL` | URL da fila SQS (provida pelo time SOAT) |

### Variáveis opcionais

| Variável | Padrão | Descrição |
|---|---|---|
| `REPORT_MODEL_BACKEND` | `langchain` | Backend do report agent |
| `LLM_MODEL` | `claude-opus-4-6` | Modelo LLM para o backend langchain |
| `HUGGINGFACE_API_TOKEN` | — | Token HuggingFace (para `finetuned_api`) |
| `HUGGINGFACE_ENDPOINT_URL` | — | URL do endpoint HuggingFace |
| `LOCAL_MODEL_PATH` | — | Caminho do adapter local (para `finetuned_local`) |
| `AWS_ACCESS_KEY_ID` | — | Credenciais AWS (se não usar IAM Role) |
| `LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`) |

---

## 11. Execução

### Subir todos os serviços

```bash
cp ia-service/.env.example .env   # preencher as variáveis obrigatórias
docker-compose up --build
```

### Verificar saúde dos serviços

```bash
curl http://localhost:8000/health  # ia-service
curl http://localhost:8001/health  # report-api
```

### Executar migrations manualmente

```bash
docker exec -i hackathon_pgvector psql -U hackathon -d hackathon_db \
  < pgvector/init/00_extensions.sql

docker exec -i hackathon_pgvector psql -U hackathon -d hackathon_db \
  < pgvector/init/01_schema.sql

docker exec -i hackathon_pgvector psql -U hackathon -d hackathon_db \
  < pgvector/init/02_indexes.sql
```

### Testar o pipeline diretamente (sem SQS)

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@/caminho/para/diagrama.png"
```

### Consultar relatório gerado

```bash
# Por ID de análise
curl http://localhost:8001/reports/{analysis_id}

# Listar todos
curl "http://localhost:8001/reports?limit=10&offset=0"

# Checar status de processamento
curl http://localhost:8000/analyses/{analysis_id}/status
```

### Simular mensagem SQS localmente

```bash
aws --endpoint-url=http://localhost:4566 sqs send-message \
  --queue-url http://localhost:4566/000000000000/hackathon-queue \
  --message-body '{
    "file_name": "diagrama.png",
    "s3_url": "https://s3.amazonaws.com/bucket/diagrama.png",
    "callback_url": "https://webhook.site/seu-token"
  }'
```

---

## 12. API Reference

### ia-service (:8000)

#### `GET /health`

```json
{"status": "healthy", "db": "connected"}
```

#### `POST /analyze`

Upload direto de arquivo. Usado para testes — em produção o fluxo principal é via SQS.

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@diagrama.png"
```

**Response 200:**
```json
{
  "analysis_id": "uuid",
  "status": "analisado",
  "report": {
    "components_identified": [...],
    "architectural_risks": [...],
    "recommendations": [...],
    "executive_summary": "...",
    "rag_used": false
  },
  "qa": {
    "is_valid": true,
    "completeness_score": 0.92,
    "issues_found": [],
    "quality_notes": "..."
  }
}
```

**Response 422** (pipeline falhou):
```json
{"detail": "Arquivo excede o limite de 20MB."}
```

#### `GET /analyses/{analysis_id}/status`

```json
{
  "analysis_id": "uuid",
  "status": "analisado",
  "file_name": "diagrama.png",
  "created_at": "2026-04-02T21:30:00",
  "error_message": null
}
```

**Status possíveis:** `recebido` → `em_processamento` → `analisado` | `erro`

### report-api (:8001)

#### `GET /reports/{analysis_id}`

**Response 200:**
```json
{
  "analysis_id": "uuid",
  "status": "analisado",
  "file_name": "diagrama.png",
  "created_at": "...",
  "report": {
    "components_identified": ["API Gateway", "Auth Service", "User DB"],
    "architectural_risks": [
      {
        "type": "SPOF",
        "description": "User DB sem réplica de leitura",
        "severity": "ALTO",
        "affected_components": ["User DB"],
        "mitigation": "Adicionar réplica read-only com failover automático"
      }
    ],
    "recommendations": [
      "Configurar DLQ no SQS",
      "[RAG] Implementar circuit breaker — padrão recorrente em arquiteturas similares"
    ],
    "executive_summary": "A arquitetura analisada...",
    "rag_used": true,
    "qa_completeness_score": 0.92
  }
}
```

**Response 202** (ainda processando):
```json
{"analysis_id": "uuid", "status": "em_processamento", "message": "Análise em andamento."}
```

**Response 404:**
```json
{"detail": "Análise não encontrada"}
```

---

## 13. Testes

### Executar testes unitários

```bash
cd ia-service
pip install -r requirements.txt
pytest tests/ -v
```

### Executar com cobertura

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

### Módulos testados

| Arquivo | O que cobre |
|---|---|
| `test_ingestion.py` | Validação de tipo, tamanho, conversão base64 |
| `test_extraction.py` | Parsing do JSON do LLM, campos obrigatórios, markdown |
| `test_risk.py` | Classificação de severidade, recálculo de summary, erros de API |
| `test_qa.py` | Verificações básicas, grounding, score mínimo, fallback |

---

## 14. Segurança

### Validação de entrada

- Arquivos validados por MIME type e tamanho antes de chegar no LLM
- URLs do S3 são pré-assinadas — sem exposição de credenciais
- Tipos não suportados são rejeitados na borda, antes de qualquer processamento

### Controle do LLM

- **System prompts restritos:** instruem o modelo a responder apenas sobre dados fornecidos
- **Guardrail de grounding:** componentes inventados acima de 20% — relatório descartado
- **JSON Schema obrigatório no QA:** o LLM não pode retornar formato livre
- **Score mínimo de qualidade:** relatórios abaixo de 0.6 não são entregues
- **Temperatura baixa no fine-tuning:** `temperature=0.1` para saídas mais determinísticas

### Comunicação entre serviços

- `ia-service` e `report-api` comunicam com o PostgreSQL via connection string autenticada
- Variáveis sensíveis injetadas via variáveis de ambiente — nunca hardcoded
- `report-api` é estritamente read-only — não aceita escrita

### Resiliência a falhas

- **Falha do pgvector (RAG):** pipeline continua sem contexto histórico
- **Falha do LLM de QA:** assume score conservador (0.7) se checks básicos passaram
- **Falha do webhook:** resultado já está no banco; a falha é logada mas não bloqueia
- **Mensagens duplicadas SQS:** idempotência por `sqs_message_id` — reprocessamento ignorado
- **Graceful shutdown:** `SIGTERM` finaliza o processamento atual antes de encerrar

### Limitações de segurança conhecidas

- Não há autenticação entre `ia-service` e `report-api` (mesma rede Docker interna)
- O endpoint `POST /analyze` não requer autenticação (uso interno/testes)
- O LLM pode alucinar componentes dentro da tolerância de 20%
- Dados dos diagramas são enviados para APIs externas — avaliar termos de uso antes de processar diagramas sigilosos

---

## 15. Limitações e Decisões de Projeto

### Por que não OCR?

LLMs Vision modernos interpretam diagramas com compreensão semântica — entendem setas, caixas, relacionamentos e padrões arquiteturais. OCR extrairia apenas texto, perdendo toda a informação visual estrutural. A abordagem Vision é superior para este caso de uso e não requer pré-processamento adicional.

### Por que a escolha do LLM é configurável?

O mercado de LLMs evolui rapidamente. Fixar um modelo específico no código criaria dependência rígida. O sistema usa uma abstração (`REPORT_MODEL_BACKEND` + `LLM_MODEL`) que permite trocar o modelo sem alterar o código do pipeline.

### Por que o RAG é não-bloqueante?

O pgvector é uma dependência de enriquecimento, não de funcionamento. Um diagrama pode ser analisado com qualidade mesmo sem histórico de análises similares. Tornar o RAG bloqueante quebraria o pipeline em cold start (banco vazio) ou falhas de infraestrutura.

### Por que fine-tuning fora do Docker?

Treinar um modelo de 7B parâmetros requer GPU com no mínimo 16GB de VRAM. O ambiente Docker do hackathon roda em CPU. O script `train.py` é executado externamente (Colab, RunPod) e o adapter treinado é servido via HuggingFace Inference API — sem necessidade de GPU no ambiente de produção.

### Por que o QA tem duas fases?

Verificações determinísticas (Fase 1) são instantâneas e sem custo de API — capturam erros óbvios como campos vazios e alucinações grosseiras. A avaliação com LLM (Fase 2) é mais cara mas avalia nuances qualitativas. Separar as fases evita chamar o LLM para relatórios claramente inválidos, reduzindo custo e latência.

### Por que o webhook não bloqueia o pipeline?

O resultado da análise é sempre persistido no banco de dados antes do webhook ser enviado. Se o endpoint do SOAT estiver temporariamente indisponível, o time SOAT ainda pode consultar o relatório via `report-api`. O webhook é uma notificação de conveniência, não o único canal de entrega.

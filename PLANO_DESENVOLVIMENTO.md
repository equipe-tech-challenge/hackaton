# Plano de Desenvolvimento — Hackathon FIAP IADT
## Sistema de Análise de Diagramas de Arquitetura

**Tech Lead:** Equipe IADT
**Data:** Março 2026
**Escopo:** ia-service · pgvector · report-api

---

## 1. Visão Geral

### O que precisa ser construído (escopo IADT)

| Módulo | Responsabilidade | Tecnologia |
|---|---|---|
| **ia-service** | Pipeline de 6 agentes IA (ingestão → extração → RAG → risco → relatório → QA) | FastAPI + Anthropic SDK + LangChain |
| **pgvector** | Banco de dados PostgreSQL com extensão vetorial para RAG | PostgreSQL 16 + pgvector + langchain-postgres |
| **report-api** | REST API para consulta de relatórios gerados | FastAPI + SQLAlchemy + psycopg2 |

### Dependências entre módulos

```
[SOAT: EKS Worker]
       │  POST /analyze  (dispara o pipeline)
       ▼
[ia-service]
  ├── ingestion-agent   (valida o arquivo recebido do S3)
  ├── extraction-agent  (Claude Vision LLM)
  ├── rag-agent         ──► [pgvector] (indexa + recupera)
  ├── risk-agent        (Claude adaptive thinking)
  ├── report-agent      ──► [pgvector] (recupera contexto final)
  └── qa-agent          (valida relatório)
       │
       ▼  persiste resultado
[PostgreSQL — tabelas: analyses, reports, rag_documents]
       │
       ▼  consulta
[report-api]  ◄── [SOAT: API Gateway / BFF]
```

### Dependências externas (SOAT provê, IADT consome)

- URL do arquivo no S3 (pré-assinada ou path interno)
- `analysis_id` gerado pelo Serviço de Upload
- Variáveis de ambiente injetadas no container EKS:
  - `POSTGRES_CONNECTION_STRING`
  - `ANTHROPIC_API_KEY`
  - `OPENAI_API_KEY` (para embeddings)
  - `S3_BUCKET_NAME`
  - `AWS_REGION`

---

## 2. Estrutura de Pastas

```
hackathon-iadt/
│
├── ia-service/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app + rotas /analyze e /health
│   │   ├── config.py                 # Settings via pydantic-settings
│   │   ├── models.py                 # Pydantic models (request/response)
│   │   │
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py       # Tech Lead — coordena agentes
│   │   │   ├── ingestion_agent.py    # Baixa do S3, valida, converte base64
│   │   │   ├── extraction_agent.py   # Claude Vision LLM
│   │   │   ├── rag_agent.py          # LangChain + pgvector
│   │   │   ├── risk_agent.py         # Claude adaptive thinking
│   │   │   ├── report_agent.py       # LangChain + JsonOutputParser + guardrails
│   │   │   └── qa_agent.py           # Validação de qualidade
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py         # SQLAlchemy engine + session factory
│   │   │   ├── repositories.py       # CRUD: analyses, reports
│   │   │   └── migrations/
│   │   │       └── 001_initial.sql   # DDL completo
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── s3_client.py          # Download de arquivo do S3
│   │       ├── logger.py             # Structured logging (JSON)
│   │       └── exceptions.py         # PipelineError, GuardrailError, etc.
│   │
│   ├── tests/
│   │   ├── test_ingestion.py
│   │   ├── test_extraction.py
│   │   ├── test_rag.py
│   │   ├── test_risk.py
│   │   ├── test_report.py
│   │   ├── test_qa.py
│   │   └── test_pipeline_integration.py
│   │
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── pgvector/
│   ├── docker-compose.yml            # PostgreSQL + pgvector local
│   ├── init/
│   │   ├── 00_extensions.sql         # CREATE EXTENSION vector
│   │   ├── 01_schema.sql             # Todas as tabelas
│   │   └── 02_indexes.sql            # Índices HNSW + B-tree
│   └── README.md                     # Instruções de setup local e produção
│
└── report-api/
    ├── app/
    │   ├── __init__.py
    │   ├── main.py                   # FastAPI app
    │   ├── config.py
    │   ├── models.py                 # Pydantic response schemas
    │   ├── routers/
    │   │   ├── __init__.py
    │   │   ├── reports.py            # GET /reports/{id}, GET /reports, etc.
    │   │   └── health.py             # GET /health
    │   └── db/
    │       ├── __init__.py
    │       ├── connection.py
    │       └── queries.py            # Queries SQLAlchemy (read-only)
    │
    ├── tests/
    │   └── test_reports_api.py
    │
    ├── Dockerfile
    ├── requirements.txt
    └── .env.example
```

---

## 3. Schema do Banco de Dados

### 3.1 Extensão e configuração inicial (`00_extensions.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 3.2 Tabelas principais (`01_schema.sql`)

```sql
-- ================================================================
-- TABELA: analyses
-- Rastreia o ciclo de vida de cada análise (status + metadados)
-- ================================================================
CREATE TABLE analyses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id     VARCHAR(255) UNIQUE,           -- ID vindo do SOAT (Serviço de Upload)
    file_name       VARCHAR(500) NOT NULL,
    file_type       VARCHAR(50)  NOT NULL,          -- 'image' | 'pdf'
    media_type      VARCHAR(100) NOT NULL,          -- 'image/png', 'application/pdf', etc.
    file_size_kb    INTEGER,
    s3_key          VARCHAR(1000),                  -- caminho do arquivo no S3
    status          VARCHAR(50)  NOT NULL DEFAULT 'recebido',
                    -- recebido | em_processamento | analisado | erro
    error_message   TEXT,
    pipeline_log    JSONB,                          -- log de cada etapa do pipeline
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_analyses_status    ON analyses(status);
CREATE INDEX idx_analyses_external  ON analyses(external_id);
CREATE INDEX idx_analyses_created   ON analyses(created_at DESC);


-- ================================================================
-- TABELA: reports
-- Armazena o relatório técnico gerado para cada análise
-- ================================================================
CREATE TABLE reports (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id             UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components_identified   JSONB NOT NULL DEFAULT '[]',   -- lista de strings
    architectural_risks     JSONB NOT NULL DEFAULT '[]',   -- lista de objetos {type, description, severity, affected_components, mitigation}
    recommendations         JSONB NOT NULL DEFAULT '[]',   -- lista de strings (com tag [RAG] quando aplicável)
    executive_summary       TEXT NOT NULL,
    severity_summary        JSONB,                          -- {high: N, medium: N, low: N}
    rag_used                BOOLEAN DEFAULT FALSE,
    similar_analyses        JSONB DEFAULT '[]',             -- referências a análises similares recuperadas
    qa_score                NUMERIC(4,3),                   -- 0.000 a 1.000
    qa_issues               JSONB DEFAULT '[]',             -- lista de problemas encontrados pelo QA
    qa_notes                TEXT,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_reports_analysis_id ON reports(analysis_id);
CREATE INDEX idx_reports_created     ON reports(created_at DESC);
CREATE INDEX idx_reports_qa_score    ON reports(qa_score);


-- ================================================================
-- TABELA: langchain_pg_embedding
-- Gerenciada pelo langchain-postgres / PGVector automaticamente.
-- Documentada aqui para referência. Não criar manualmente.
-- ================================================================
-- collection_id  UUID  FK → langchain_pg_collection
-- embedding      vector(1536)    (text-embedding-3-small = 1536 dims)
-- document       TEXT            (conteúdo textual indexado)
-- cmetadata      JSONB           (analysis_id, components, patterns, etc.)
-- id             UUID PRIMARY KEY


-- ================================================================
-- TABELA: extraction_results (cache intermediário do pipeline)
-- Evita re-chamar a Vision LLM em caso de retry
-- ================================================================
CREATE TABLE extraction_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components      JSONB NOT NULL DEFAULT '[]',
    relationships   JSONB NOT NULL DEFAULT '[]',
    patterns        JSONB NOT NULL DEFAULT '[]',
    raw_description TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_extraction_analysis ON extraction_results(analysis_id);
```

### 3.3 Índices HNSW para pgvector (`02_indexes.sql`)

```sql
-- Índice HNSW para busca por similaridade de cosseno (mais eficiente para embedding de texto)
-- Aplicado à tabela gerenciada pelo langchain-postgres
CREATE INDEX IF NOT EXISTS idx_embedding_hnsw
ON langchain_pg_embedding
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

## 4. Contratos de Integração com SOAT

### 4.1 O que o SOAT precisa enviar para o ia-service

**Endpoint:** `POST /analyze`
**Quem chama:** EKS Worker (consumidor SQS)
**Autenticação:** Bearer token interno (header `Authorization`)

**Request body:**
```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "uploads/2026/03/diagrama_v2.png",
  "file_name": "diagrama_v2.png",
  "media_type": "image/png",
  "file_size_kb": 512,
  "callback_url": "https://soat-service/internal/analysis-complete"
}
```

**Response imediata (202 Accepted):**
```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "em_processamento",
  "message": "Pipeline iniciado com sucesso"
}
```

O pipeline roda de forma assíncrona. Ao concluir, o ia-service faz callback ou o SOAT consulta o report-api.

---

### 4.2 Formato da mensagem SQS (referência para o EKS Worker SOAT)

```json
{
  "MessageId": "uuid-da-mensagem-sqs",
  "Body": {
    "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
    "s3_key": "uploads/2026/03/diagrama_v2.png",
    "file_name": "diagrama_v2.png",
    "media_type": "image/png",
    "file_size_kb": 512
  }
}
```

O EKS Worker SOAT lê a mensagem do SQS e chama `POST /analyze` no ia-service com o body acima.

---

### 4.3 Endpoints do report-api (para o API Gateway / BFF SOAT)

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/reports/{analysis_id}` | Relatório completo de uma análise |
| `GET` | `/reports` | Lista análises (paginada, filtro por status) |
| `GET` | `/health` | Healthcheck (retorna 200 se DB OK) |

**GET /reports/{analysis_id} — Response 200:**
```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analisado",
  "file_name": "diagrama_v2.png",
  "created_at": "2026-03-26T14:30:00Z",
  "completed_at": "2026-03-26T14:32:45Z",
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
      "Configurar DLQ no SQS para mensagens não processadas",
      "[RAG] Implementar circuit breaker — padrão recorrente em arquiteturas similares"
    ],
    "executive_summary": "A arquitetura analisada implementa...",
    "severity_summary": { "high": 1, "medium": 2, "low": 1 },
    "rag_used": true,
    "qa_score": 0.92
  }
}
```

**GET /reports/{analysis_id} — Response 404:**
```json
{ "detail": "Análise não encontrada" }
```

**GET /reports/{analysis_id} — Response 202 (ainda processando):**
```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "em_processamento",
  "message": "Análise em andamento. Tente novamente em instantes."
}
```

---

### 4.4 Variáveis de ambiente que o SOAT deve injetar no container ia-service

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...           # Para embeddings text-embedding-3-small
POSTGRES_CONNECTION_STRING=postgresql+psycopg://user:pass@pg-host:5432/hackathon
S3_BUCKET_NAME=hackathon-diagrams
AWS_REGION=us-east-1
INTERNAL_API_TOKEN=token-interno-compartilhado
LOG_LEVEL=INFO
```

---

## 5. Pipeline de IA Detalhado

### 5.1 Diagrama de fluxo

```
EKS Worker (SOAT)
       │
       │ POST /analyze {analysis_id, s3_key, ...}
       ▼
[ia-service / orchestrator.py]
       │
       ├──[1] ingestion-agent
       │       - Baixa arquivo do S3 via boto3
       │       - Valida tipo (png/jpg/jpeg/gif/webp/pdf)
       │       - Valida tamanho (≤ 20MB)
       │       - Converte para base64
       │       - Identifica media_type
       │       OUTPUT → {file_name, file_type, media_type, content_base64, file_size_kb}
       │
       ├──[2] extraction-agent
       │       INPUT ← output do ingestion-agent
       │       - Chama claude-opus-4-6 com Vision (image/document)
       │       - Extrai: components, relationships, patterns, raw_description
       │       - Persiste em extraction_results (cache)
       │       OUTPUT → {components[], relationships[], patterns[], raw_description}
       │
       ├──[3] rag-agent
       │       INPUT ← output do extraction-agent
       │       - Indexa extração no pgvector (LangChain PGVector.add_documents)
       │       - Busca análises similares (similarity_search_with_score, k=3, score < 0.3)
       │       - Se há contexto: gera rag_enrichment via ChatAnthropic chain
       │       - Em caso de falha: retorna {has_context: false} e NÃO bloqueia pipeline
       │       OUTPUT → {has_context, similar_analyses[], rag_enrichment}
       │
       ├──[4] risk-agent
       │       INPUT ← extraction (components/patterns/relationships) + rag_enrichment
       │       - Chama claude-opus-4-6 com adaptive thinking
       │       - Avalia 6 categorias: SPOF, Segurança, Escalabilidade, Acoplamento,
       │         Observabilidade, Resiliência
       │       - Enriquece com contexto RAG (padrões recorrentes identificados)
       │       OUTPUT → {risks[], severity_summary{high, medium, low}}
       │
       ├──[5] report-agent
       │       INPUT ← extraction + risks + rag_context
       │       - Monta prompt com seção RAG condicional
       │       - Chama ChatAnthropic via LangChain + JsonOutputParser
       │       - Aplica guardrails pós-geração (grounding check)
       │       OUTPUT → {components_identified[], architectural_risks[], recommendations[],
       │                  executive_summary, rag_used}
       │
       └──[6] qa-agent
               INPUT ← report + extraction (para comparação)
               - Verificações básicas sem IA (5 checks)
               - Avaliação com IA via claude-opus-4-6 + JSON Schema output
               OUTPUT → {is_valid, completeness_score, issues_found[], quality_notes}

       ▼
[orchestrator] — persiste report + qa no PostgreSQL
[orchestrator] — atualiza analyses.status = 'analisado' | 'erro'
```

### 5.2 Contrato de dados entre agentes

| De → Para | Campos obrigatórios |
|---|---|
| orchestrator → ingestion | `s3_key`, `media_type`, `file_name` |
| ingestion → extraction | `content_base64`, `media_type`, `file_type` |
| extraction → rag | `components[]`, `relationships[]`, `patterns[]`, `raw_description` |
| extraction → risk | `components[]`, `relationships[]`, `patterns[]` |
| rag → risk | `rag_enrichment` (string, pode ser vazia) |
| extraction + risk + rag → report | todos os campos acima |
| extraction + report → qa | `components[]` (source of truth), relatório completo |
| qa → orchestrator | `is_valid`, `completeness_score`, `issues_found[]` |

### 5.3 Tratamento de erros no pipeline

| Agente | Falha | Comportamento |
|---|---|---|
| ingestion | Arquivo inválido / S3 inacessível | **INTERROMPE** — status `erro` |
| extraction | API Anthropic indisponível | **INTERROMPE** — status `erro` |
| rag | pgvector indisponível | **CONTINUA** sem contexto — `has_context: false` |
| risk | API Anthropic indisponível | **INTERROMPE** — status `erro` |
| report | Guardrail falha | Retry 1x. Após 2 falhas → **INTERROMPE** |
| qa | `is_valid: false` ou score < 0.6 | Registra issues, status `erro` |

---

## 6. Implementação do RAG

### 6.1 Fluxo completo de indexação + recuperação

```
INDEXAÇÃO (executa em cada nova análise):
  extraction_result
       │
       ▼
  LangChain Document(
    page_content = raw_description + components + patterns,
    metadata = {analysis_id, components[], patterns[], components_count, has_report=False}
  )
       │
       ▼
  OpenAIEmbeddings("text-embedding-3-small")  →  vetor 1536 dimensões
       │
       ▼
  PGVector.add_documents([doc], ids=[analysis_id])  →  langchain_pg_embedding

RECUPERAÇÃO (executa antes do report-agent):
  query = raw_description + components + patterns
       │
       ▼
  OpenAIEmbeddings("text-embedding-3-small")  →  query vector
       │
       ▼
  PGVector.similarity_search_with_score(query, k=3, filter={"has_report": True})
       │
       ├── distância coseno < 0.3  →  inclui no contexto (similaridade > 70%)
       └── distância coseno ≥ 0.3  →  descarta
       │
       ▼
  Documentos relevantes → formata como contexto textual
       │
       ▼
  ChatAnthropic chain → rag_enrichment (recomendações enriquecidas com histórico)

PÓS-RELATÓRIO (opcional — reindexação com relatório):
  Após report-agent → atualiza documento no pgvector com has_report=True
  e adiciona executive_summary + risks_high ao metadata
```

### 6.2 Configuração do PGVector no código

```python
# ia-service/app/pipeline/rag_agent.py

CONNECTION_STRING = settings.POSTGRES_CONNECTION_STRING
# Formato exigido pelo langchain-postgres:
# postgresql+psycopg://user:password@host:5432/dbname

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

vector_store = PGVector(
    embeddings=embeddings,
    collection_name="diagram_analyses",
    connection=CONNECTION_STRING,
    use_jsonb=True,  # metadados em JSONB para filtros eficientes
)
```

### 6.3 Considerações de performance para MVP

- Índice HNSW criado em `02_indexes.sql` (busca aproximada, latência < 50ms)
- Filtro `has_report: True` evita retornar análises incompletas
- `top_k=3` suficiente para o contexto RAG no MVP
- Threshold de similaridade 0.3 (distância coseno) calibrado empiricamente

---

## 7. Guardrails e Segurança

### 7.1 Guardrails contra alucinações

| Guardrail | Onde | Implementação |
|---|---|---|
| **Grounding check** | report-agent | Compara `components_identified` do relatório com `components` da extração. Tolerância de 20%. Lança `GuardrailError` se exceder. |
| **Completude mínima** | report-agent + qa-agent | `recommendations` não vazio, `executive_summary` > 100 chars |
| **Sem generalidades** | Prompt do report-agent | "Cada recomendação deve referenciar um componente ou risco específico identificado" |
| **JSON Schema forçado** | qa-agent | `output_config` com JSON Schema na API Anthropic |
| **RAG transparente** | report-agent | Tag `[RAG]` em recomendações de origem histórica |
| **Score mínimo QA** | qa-agent | Rejeita relatório com `completeness_score < 0.6` |
| **Componentes fonte** | extraction-agent | "Identifique APENAS o que está visível no diagrama" no system prompt |

### 7.2 Segurança da API

```python
# ia-service/app/main.py — autenticação por token interno
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(credentials = Security(security)):
    if credentials.credentials != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")
```

### 7.3 Tratamento de erros estruturado

```python
# ia-service/app/utils/exceptions.py

class PipelineError(Exception):
    """Erro bloqueante no pipeline — interrompe a análise."""
    def __init__(self, stage: str, message: str):
        self.stage = stage
        self.message = message

class GuardrailError(PipelineError):
    """Violação de guardrail — relatório não confiável."""
    pass

class RagUnavailableError(Exception):
    """pgvector indisponível — não-bloqueante, pipeline continua."""
    pass
```

### 7.4 Retry e resiliência

```python
# Configuração de retry para chamadas à API Anthropic
from anthropic import Anthropic

client = Anthropic(
    max_retries=2,          # 2 tentativas adicionais além da original
    timeout=120.0,          # timeout de 120s (Vision LLM pode ser lento)
)
```

---

## 8. Sprints de Desenvolvimento

> **Premissa:** Hackathon de ~3 dias. Divisão sugerida para equipe de 3-4 pessoas.

---

### Dia 1 — Fundação e Pipeline Core

#### Manhã (3h) — Infraestrutura Local
- [ ] Criar estrutura de pastas completa
- [ ] `pgvector/docker-compose.yml` — PostgreSQL + pgvector rodando localmente
- [ ] `pgvector/init/*.sql` — executar migrations e validar schema
- [ ] `.env.example` para ia-service e report-api
- [ ] `requirements.txt` com todas as dependências pinadas

```txt
# ia-service/requirements.txt
anthropic==0.40.0
langchain==0.3.0
langchain-anthropic==0.3.0
langchain-postgres==0.0.12
langchain-openai==0.2.0
langchain-core==0.3.0
openai==1.50.0
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.0
pydantic-settings==2.6.0
psycopg[binary]==3.2.0
psycopg2-binary==2.9.10
boto3==1.35.0
sqlalchemy==2.0.36
python-multipart==0.0.12
```

#### Tarde (4h) — ingestion-agent + extraction-agent
- [ ] `ingestion_agent.py` — download S3 + validação + base64
- [ ] `extraction_agent.py` — Claude Vision LLM + output JSON
- [ ] Testar manualmente com 2-3 imagens de diagrama reais
- [ ] `db/connection.py` + `db/repositories.py` — CRUD básico
- [ ] `utils/logger.py` — structured logging JSON

#### Noite (2h) — orchestrator base
- [ ] `pipeline/orchestrator.py` — esqueleto com estados do pipeline
- [ ] `app/main.py` — FastAPI com `POST /analyze` (síncrono no MVP)
- [ ] Testar fluxo ingestion → extraction end-to-end

---

### Dia 2 — RAG, Riscos e Relatório

#### Manhã (4h) — rag-agent + pgvector
- [ ] `rag_agent.py` — PGVector setup + index_analysis + retrieve_context
- [ ] Testar indexação e busca por similaridade
- [ ] Validar filtros de metadata (has_report, score threshold)
- [ ] `02_indexes.sql` — HNSW index criado e testado

#### Tarde (4h) — risk-agent + report-agent
- [ ] `risk_agent.py` — adaptive thinking + 6 categorias de risco
- [ ] `report_agent.py` — LangChain chain + guardrails + RAG condicional
- [ ] Testar guardrail de grounding (forçar violação e validar erro)
- [ ] Integrar rag_enrichment no prompt do risk-agent

#### Noite (2h) — qa-agent + pipeline completo
- [ ] `qa_agent.py` — verificações sem IA + avaliação com JSON Schema
- [ ] Conectar todos os agentes no orchestrator
- [ ] Rodar pipeline completo end-to-end com diagrama real
- [ ] Ajustar prompts com base nos resultados

---

### Dia 3 — report-api, Integração e Polimento

#### Manhã (3h) — report-api
- [ ] `report-api/app/main.py` — FastAPI setup
- [ ] `report-api/app/routers/reports.py` — GET /reports/{id} e GET /reports
- [ ] `report-api/app/routers/health.py`
- [ ] Testar endpoints com dados persistidos no Dia 2

#### Tarde (3h) — Integração com SOAT + Docker
- [ ] `ia-service/Dockerfile` + `report-api/Dockerfile`
- [ ] Validar variáveis de ambiente
- [ ] Testar fluxo completo: request HTTP → pipeline → persistência → consulta
- [ ] Alinhar contratos com equipe SOAT (URL dos endpoints, token, format SQS)
- [ ] Smoke test com EKS Worker do SOAT

#### Noite (2h) — Preparação para apresentação
- [ ] Preparar 2-3 diagramas de exemplo para demonstração ao vivo
- [ ] Popular pgvector com 5+ análises para demonstrar RAG
- [ ] Gravar output de exemplo (JSON completo)
- [ ] Ajustes finais de prompts e guardrails

---

## 9. Checklist de Entregáveis

### Funcionalidade Core (MVP obrigatório)

- [ ] `POST /analyze` aceita `s3_key` e inicia pipeline
- [ ] ingestion-agent valida e processa imagem/PDF do S3
- [ ] extraction-agent identifica componentes via Claude Vision
- [ ] risk-agent classifica riscos em 6 categorias com severidade
- [ ] report-agent gera relatório técnico estruturado em JSON
- [ ] qa-agent valida relatório com score de qualidade
- [ ] Relatório persistido no PostgreSQL
- [ ] `GET /reports/{id}` retorna relatório completo
- [ ] Pipeline atualiza status: recebido → em_processamento → analisado | erro
- [ ] Tratamento de erros com mensagens claras em `analyses.error_message`

### RAG (diferencial técnico)

- [ ] pgvector indexa cada nova análise após extração
- [ ] RAG recupera até 3 análises similares (threshold 70%)
- [ ] Recomendações enriquecidas com contexto histórico são marcadas com `[RAG]`
- [ ] Falha do pgvector não bloqueia o pipeline
- [ ] `rag_used: true/false` no relatório final
- [ ] Índice HNSW configurado para performance

### Qualidade e Confiabilidade

- [ ] Guardrail de grounding (componentes inventados < 20%)
- [ ] Guardrail de completude (summary > 100 chars, recomendações não vazias)
- [ ] QA rejeita relatórios com score < 0.6
- [ ] Retry automático (2x) para chamadas à API Anthropic
- [ ] Logs estruturados em JSON com `stage` e `analysis_id`

### Integração

- [ ] `POST /analyze` com autenticação por token
- [ ] `GET /health` respondendo 200 com DB acessível
- [ ] Contratos de integração documentados e validados com SOAT
- [ ] Dockerfiles funcionais para ia-service e report-api
- [ ] `.env.example` com todas as variáveis necessárias

### Demonstração

- [ ] 3+ análises pré-carregadas no pgvector para demonstrar RAG
- [ ] Diagrama de exemplo com riscos evidentes (SPOF, sem DLQ, etc.)
- [ ] Output JSON completo de uma análise real
- [ ] Pipeline rodando em menos de 3 minutos end-to-end

---

## 10. Referências Rápidas

### Inicializar ambiente local

```bash
# 1. Subir PostgreSQL + pgvector
cd pgvector
docker-compose up -d

# 2. Executar migrations
docker exec -i pg-hackathon psql -U hackathon -d hackathon < init/00_extensions.sql
docker exec -i pg-hackathon psql -U hackathon -d hackathon < init/01_schema.sql
docker exec -i pg-hackathon psql -U hackathon -d hackathon < init/02_indexes.sql

# 3. Rodar ia-service
cd ../ia-service
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. Rodar report-api
cd ../report-api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Testar pipeline manualmente

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Authorization: Bearer token-interno" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_id": "test-001",
    "s3_key": "uploads/test/diagrama.png",
    "file_name": "diagrama.png",
    "media_type": "image/png",
    "file_size_kb": 256
  }'

# Consultar relatório
curl http://localhost:8001/reports/test-001
```

### Checklist de variáveis de ambiente

```bash
# Verificar se todas as vars estão configuradas
echo $ANTHROPIC_API_KEY   # deve começar com sk-ant-
echo $OPENAI_API_KEY      # deve começar com sk-
echo $POSTGRES_CONNECTION_STRING  # postgresql+psycopg://...
echo $S3_BUCKET_NAME
echo $INTERNAL_API_TOKEN
```

---

*Plano elaborado com base nos agentes .md definidos e na arquitetura IADT do Hackathon FIAP.*

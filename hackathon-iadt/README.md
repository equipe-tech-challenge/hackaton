# Hackathon FIAP — Time IADT · Análise de Diagramas de Arquitetura com IA

Sistema de análise automatizada de diagramas de arquitetura de software. Recebe imagens ou PDFs de diagramas via fila SQS, processa com um pipeline de 6 agentes de IA e devolve um relatório técnico estruturado via webhook.

---

## Índice

1. [Visão Geral](#1-visão-geral)
2. [Arquitetura](#2-arquitetura)
3. [Arquitetura Hexagonal (Ports & Adapters)](#3-arquitetura-hexagonal-ports--adapters)
4. [Componentes do Sistema](#4-componentes-do-sistema)
5. [SQS Consumer — Arquitetura Event-Driven](#5-sqs-consumer--arquitetura-event-driven)
6. [Pipeline de IA — 6 Agentes](#6-pipeline-de-ia--6-agentes)
7. [RAG com pgvector](#7-rag-com-pgvector)
8. [Guardrails e Controle de Qualidade](#8-guardrails-e-controle-de-qualidade)
9. [Estratégia de Convergência do Pipeline](#9-estratégia-de-convergência-do-pipeline)
10. [Webhook de Devolutiva](#10-webhook-de-devolutiva)
11. [Fine-Tuning](#11-fine-tuning)
12. [Schema do Banco de Dados](#12-schema-do-banco-de-dados)
13. [Configuração de Ambiente](#13-configuração-de-ambiente)
14. [Execução](#14-execução)
15. [API Reference](#15-api-reference)
16. [Streamlit — Interface de Validação](#16-streamlit--interface-de-validação)
17. [Testes](#17-testes)
18. [Segurança](#18-segurança)
19. [Limitações e Decisões de Projeto](#19-limitações-e-decisões-de-projeto)

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

## 3. Arquitetura Hexagonal (Ports & Adapters)

O `ia-service` adota **Arquitetura Hexagonal** (Ports & Adapters) como padrão arquitetural. Dentro da camada de domínio, aplica **modelagem tática DDD** (agregados, value objects, domain events) para expressar as regras de negócio. A distinção é importante: a arquitetura hexagonal organiza *como as camadas se comunicam*; DDD modela *o problema de negócio dentro do domínio*.

### 3.1 Camadas da Arquitetura

```
                    ┌──────────────────────────────────────────────────────┐
                    │              INFRASTRUCTURE (Adapters)               │
                    │                                                      │
                    │  OpenAIVisionAdapter    SQLAlchemy*Repository        │
                    │  OpenAITextAdapter      PGVectorAdapter              │
                    │                                                      │
                    │    ┌──────────────────────────────────────────┐      │
                    │    │          APPLICATION (Use Cases + Ports)  │      │
                    │    │                                          │      │
                    │    │  AnalyzeDiagramUseCase                   │      │
                    │    │  RetrieveReportUseCase                   │      │
                    │    │                                          │      │
                    │    │  Ports: IVisionLLM · ITextLLM            │      │
                    │    │         IVectorStore                     │      │
                    │    │         IAnalysisRepository              │      │
                    │    │         IReportRepository                │      │
                    │    │                                          │      │
                    │    │    ┌──────────────────────────────┐      │      │
                    │    │    │     DOMAIN (Modelo Tático)   │      │      │
                    │    │    │                              │      │      │
                    │    │    │  AnalysisAggregate           │      │      │
                    │    │    │  ReportAggregate             │      │      │
                    │    │    │  GuardrailService            │      │      │
                    │    │    │  Value Objects · Events      │      │      │
                    │    │    └──────────────────────────────┘      │      │
                    │    └──────────────────────────────────────────┘      │
                    └──────────────────────────────────────────────────────┘
```

**Regra de dependência:** as setas apontam para dentro. Infrastructure depende de Application, que depende de Domain. Domain não importa nada externo.

### 3.2 Portas (Interfaces — Camada Application)

As portas definem *o que* a aplicação precisa, sem saber *como* será implementado.

**Arquivo:** `application/ports/llm_port.py`

```python
class IVisionLLM(ABC):
    def extract_components(self, diagram_file: DiagramFile) -> ExtractionResult: ...

class ITextLLM(ABC):
    def generate_report(self, extraction, rag_context) -> TechnicalReport: ...
    def evaluate_quality(self, extraction, report) -> QAScore: ...
```

**Arquivo:** `application/ports/vector_store_port.py`

```python
class IVectorStore(ABC):
    def index(self, analysis_id, extraction) -> None: ...
    def retrieve_context(self, extraction, exclude_analysis_id) -> RagContext: ...
```

### 3.3 Adaptadores (Implementações — Camada Infrastructure)

| Porta | Adaptador | Tecnologia |
|---|---|---|
| `IVisionLLM` | `OpenAIVisionAdapter` | OpenAI SDK / Groq (via `base_url`) |
| `ITextLLM` | `OpenAITextAdapter` | LangChain chains + OpenAI/Groq |
| `IVectorStore` | `PGVectorAdapter` | LangChain PGVector + `text-embedding-3-small` |
| `IAnalysisRepository` | `SQLAlchemyAnalysisRepository` | SQLAlchemy + PostgreSQL |
| `IReportRepository` | `SQLAlchemyReportRepository` | SQLAlchemy + PostgreSQL |

**Trocar de provider de LLM** (ex: OpenAI → Anthropic) significa criar um novo adapter que implemente `IVisionLLM` / `ITextLLM`. O domínio e os use cases permanecem intactos.

### 3.4 Composition Root (Injeção de Dependências)

**Arquivo:** `infrastructure/composition_root.py`

Ponto único de montagem do grafo de dependências. Nenhuma outra camada conhece as implementações concretas.

```python
def build_analyze_use_case(db: Session) -> AnalyzeDiagramUseCase:
    return AnalyzeDiagramUseCase(
        analysis_repo=SQLAlchemyAnalysisRepository(db),
        report_repo=SQLAlchemyReportRepository(db),
        vision_llm=OpenAIVisionAdapter(),
        text_llm=OpenAITextAdapter(),
        vector_store=PGVectorAdapter(db),
        guardrail_svc=GuardrailService(),
    )
```

### 3.5 Modelagem Tática DDD (Camada Domain)

Dentro da camada de domínio, o problema é modelado com padrões táticos DDD:

#### Bounded Contexts

| Contexto | Responsabilidade | Agregado |
|---|---|---|
| **Analysis** | Ciclo de vida da análise (recebimento → processamento → conclusão/erro) | `AnalysisAggregate` |
| **Report** | Geração, validação e persistência do relatório técnico | `ReportAggregate` |

#### AnalysisAggregate — Máquina de Estados

```
RECEIVED ──start_ingestion()──▶ PROCESSING ──complete()──▶ ANALYZED
                                     │
                                     └──fail()──▶ ERROR
```

**Invariantes protegidas pelo agregado:**
- Um diagrama só pode ser processado a partir do estado `RECEIVED`
- A extração só pode acontecer após a ingestão
- O pipeline só pode completar após extração bem-sucedida
- Qualquer etapa pode transitar para `ERROR`

#### Value Objects

| Value Object | Contexto | Descrição |
|---|---|---|
| `DiagramFile` | Analysis | Arquivo validado (tipo, tamanho, base64) — imutável |
| `Component`, `Relationship`, `ArchitecturalPattern` | Analysis | Elementos extraídos do diagrama |
| `AnalysisId`, `ReportId` | Shared | UUIDs tipados |
| `RiskItem` | Report | Risco categorizado com severidade e mitigação |
| `Recommendation` | Report | Recomendação com flag `[RAG]` de origem histórica |
| `QAScore` | Report | Score de qualidade + issues encontradas |
| `RagContext` | Report | Contexto histórico recuperado do pgvector |

#### Domain Events

O agregado emite eventos a cada transição de estado (padrão outbox):

```python
aggregate.pull_events()  # Retorna e limpa eventos pendentes
```

| Evento | Quando emitido |
|---|---|
| `DiagramReceived` | Análise criada |
| `DiagramIngested` | Arquivo validado e convertido para base64 |
| `ComponentsExtracted` | LLM Vision extraiu componentes |
| `AnalysisCompleted` | Pipeline finalizou com sucesso |
| `AnalysisFailed` | Qualquer etapa falhou |
| `ReportGenerated` | Relatório técnico gerado |
| `QAValidationCompleted` | QA executado (aprovado ou rejeitado) |

#### Domain Service — GuardrailService

**Arquivo:** `domain/report/services.py`

Encapsula as regras de validação que não pertencem a nenhuma entidade:

```python
class GuardrailService:
    HALLUCINATION_THRESHOLD = 0.20  # Max 20% de componentes inventados
    MIN_SUMMARY_LENGTH = 100        # Mínimo de caracteres no sumário

    def validate(self, report, extraction) -> None:
        self._check_components_not_empty(report)
        self._check_hallucination(report, extraction)
        self._check_recommendations_not_empty(report)
        self._check_summary_length(report)
```

---

## 4. Componentes do Sistema

### 4.1 ia-service

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
    ├── domain/                  # Camada de Domínio (DDD)
    │   ├── analysis/            # Bounded Context: Analysis
    │   │   ├── aggregate.py     # AnalysisAggregate (máquina de estados)
    │   │   ├── entities.py      # ExtractionResult
    │   │   ├── value_objects.py # DiagramFile, Component, AnalysisStatus
    │   │   ├── events.py        # DiagramReceived, ComponentsExtracted...
    │   │   └── repository.py    # IAnalysisRepository (interface)
    │   ├── report/              # Bounded Context: Report
    │   │   ├── aggregate.py     # ReportAggregate
    │   │   ├── entities.py      # TechnicalReport
    │   │   ├── value_objects.py # RiskItem, QAScore, RagContext
    │   │   ├── services.py      # GuardrailService
    │   │   ├── events.py        # ReportGenerated, QAValidationCompleted
    │   │   └── repository.py    # IReportRepository (interface)
    │   └── shared/              # Value Objects compartilhados
    │       ├── value_objects.py # AnalysisId, ReportId
    │       └── events.py        # DomainEvent (base)
    │
    ├── application/             # Camada de Aplicação (Use Cases + Ports)
    │   ├── ports/
    │   │   ├── llm_port.py      # IVisionLLM, ITextLLM
    │   │   └── vector_store_port.py # IVectorStore
    │   └── use_cases/
    │       ├── analyze_diagram.py   # AnalyzeDiagramUseCase
    │       └── retrieve_report.py   # RetrieveReportUseCase
    │
    ├── infrastructure/          # Camada de Infraestrutura (Adapters)
    │   ├── composition_root.py  # Injeção de dependências
    │   ├── llm/
    │   │   └── openai_llm_adapter.py  # OpenAIVisionAdapter, OpenAITextAdapter
    │   ├── vector_store/
    │   │   └── pgvector_adapter.py    # PGVectorAdapter
    │   └── persistence/
    │       ├── sqlalchemy_analysis_repository.py
    │       └── sqlalchemy_report_repository.py
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

### 4.2 report-api

API read-only para consulta de relatórios gerados. Usada pelo API Gateway do time SOAT.

**Endpoints:**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Healthcheck — verifica conexão com DB |
| `GET` | `/reports/{analysis_id}` | Relatório completo de uma análise |
| `GET` | `/reports?limit=20&offset=0` | Lista paginada de análises |

### 4.3 pgvector

PostgreSQL 16 com extensão `pgvector`. Armazena:
- Estado de cada análise (`analyses`)
- Cache de extração para evitar reprocessamento (`extraction_results`)
- Relatórios gerados com métricas de QA (`reports`)
- Embeddings vetoriais para o RAG (`langchain_pg_embedding`)

---

## 5. SQS Consumer — Arquitetura Event-Driven

**Arquivo:** `ia-service/app/sqs_consumer.py`

O `ia-service` opera como **consumer de uma fila SQS** publicada pelo time SOAT. O consumer roda como **thread daemon** iniciada no startup do FastAPI, sem bloquear o event loop HTTP.

### Fluxo de Processamento

```
SQS Queue
   │
   ▼  long polling (20s)
┌──────────────────────────────────────────────────────────────┐
│  Consumer Thread                                             │
│                                                              │
│  receive_message(MaxMessages=5, VisibilityTimeout=300s)      │
│       │                                                      │
│       ├── Idempotência: sqs_message_id já existe? → skip     │
│       │                                                      │
│       ├── Poison pill: ApproximateReceiveCount > 3? → warning│
│       │                                                      │
│       ├── Download S3: retry 3x (backoff 2s → 4s → 8s)      │
│       │                                                      │
│       ├── run_pipeline(file_bytes, file_name)                │
│       │                                                      │
│       ├── delete_message() ← somente após sucesso            │
│       │                                                      │
│       └── send_webhook(callback_url, result)                 │
└──────────────────────────────────────────────────────────────┘
```

### Mensagem SQS esperada

```json
{
  "file_name":    "diagrama.png",
  "s3_url":       "https://s3.amazonaws.com/...",
  "callback_url": "https://soat-api.example.com/webhook"
}
```

### Resiliência do Consumer

| Mecanismo | Implementação |
|---|---|
| **Long polling** | `WaitTimeSeconds=20` — reduz chamadas vazias à API SQS |
| **Idempotência** | `sqs_message_id` com constraint `UNIQUE` no banco — mensagens duplicadas são ignoradas |
| **Graceful shutdown** | Handlers de `SIGTERM`/`SIGINT` — finaliza a mensagem atual antes de parar |
| **Poison pill detection** | Loga warning quando `ApproximateReceiveCount > 3` |
| **Download com retry** | `tenacity`: 3 tentativas, backoff exponencial (2s → 4s → 8s), retenta em timeout/network error |
| **Visibility timeout** | 300s (5 min) — mensagem não processada volta à fila automaticamente |
| **Webhook non-blocking** | Falha no webhook não impede deleção da mensagem — resultado já está no banco |

---

## 6. Pipeline de IA — 6 Agentes

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
1. Monta um bloco multimodal com o arquivo em Base64 no formato OpenAI Vision: `{type: "image_url", image_url: {url: "data:{media_type};base64,..."}}`
2. Envia para o LLM Vision com prompt de extração estruturada
3. Ativa JSON mode quando disponível (OpenAI); faz fallback de markdown fences para Groq/LLaMA
4. Parseia o JSON retornado e valida campos obrigatórios (`components`, `relationships`, `patterns`, `raw_description`)

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

## 7. RAG com pgvector

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

## 8. Guardrails e Controle de Qualidade

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

## 9. Estratégia de Convergência do Pipeline

O pipeline de 6 agentes precisa convergir de forma determinística para um resultado coerente, mesmo quando um LLM externo pode alucinar ou falhar. As seguintes estratégias garantem convergência:

### Ground Truth — ExtractionResult como Âncora

O `ExtractionResult` (saída do Agente 2) é a **fonte de verdade** para todo o pipeline. Todos os agentes subsequentes (RAG, Risk, Report, QA) recebem a extração original e são validados contra ela:

```
ExtractionResult (ground truth)
     │
     ├──▶ RAG Agent:    busca similares no histórico baseado na extração
     ├──▶ Risk Agent:   analisa riscos dos componentes extraídos
     ├──▶ Report Agent: gera relatório e valida grounding contra extração
     └──▶ QA Agent:     valida 80% overlap entre relatório e extração
```

### Mecanismos de Convergência

| Mecanismo | Onde | Como garante convergência |
|---|---|---|
| **Pipeline sequencial** | Orchestrator | Cada agente recebe output do anterior — sem execução paralela, sem race conditions |
| **Grounding check (20%)** | GuardrailService | Max 20% dos componentes do relatório podem ser inventados — o resto deve existir na extração |
| **Grounding duplo (80%)** | QA Agent Fase 1 | ≥ 80% dos componentes do relatório devem existir na extração original |
| **Recálculo server-side** | Risk Agent | `severity_summary` é recalculado no servidor — não confia no LLM para somar |
| **RAG non-blocking** | Use Case | Falha no RAG retorna `RagContext.empty()` — pipeline continua sem enriquecimento |
| **QA fallback** | Use Case | Se LLM de QA indisponível, assume score conservador 0.7 (desde que Fase 1 tenha passado) |
| **JSON Schema estrito** | QA Agent Fase 2 | `json_schema` obriga o LLM a retornar formato correto — sem outputs livres |
| **Score mínimo** | QA Agent | Score < 0.6 = relatório rejeitado (`is_valid: false`) |
| **Transparência RAG** | Report Agent | Recomendações de origem histórica marcadas com `[RAG]` — rastreabilidade |

### Diagrama de Convergência

```
[Ingestion]  →  VALIDA formato/tamanho
                    │ falha → IngestionError (bloqueia)
                    ▼
[Extraction] →  EXTRAI ground truth
                    │ falha → ExtractionError (bloqueia)
                    ▼
[RAG]        →  ENRIQUECE com histórico
                    │ falha → RagContext.empty() (continua ✓)
                    ▼
[Risk]       →  CLASSIFICA riscos + RECALCULA severidade server-side
                    │ falha → RiskAnalysisError (bloqueia)
                    ▼
[Report]     →  GERA relatório + GUARDRAIL grounding ≤ 20%
                    │ falha → ReportGenerationError (bloqueia)
                    ▼
[QA Fase 1]  →  VERIFICA: campos, completude, grounding ≥ 80%
                    │ falha → is_valid=false (rejeita imediatamente)
                    ▼
[QA Fase 2]  →  AVALIA: completude 30%, consistência 40%, coerência 20%, qualidade 10%
                    │ falha LLM → score=0.7 (fallback conservador ✓)
                    │ score < 0.6 → rejeitado
                    ▼
[Persistência + Webhook]
```

**Resultado:** o pipeline *sempre* converge para um dos dois estados: `analisado` (com relatório válido) ou `erro` (com mensagem descritiva). Nunca fica em estado intermediário indefinidamente.

---

## 10. Webhook de Devolutiva

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

## 11. Fine-Tuning

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

## 12. Schema do Banco de Dados

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

## 13. Configuração de Ambiente

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
| `LLM_MODEL` | `gpt-4o` | Modelo LLM para o backend langchain |
| `HUGGINGFACE_API_TOKEN` | — | Token HuggingFace (para `finetuned_api`) |
| `HUGGINGFACE_ENDPOINT_URL` | — | URL do endpoint HuggingFace |
| `LOCAL_MODEL_PATH` | — | Caminho do adapter local (para `finetuned_local`) |
| `AWS_ACCESS_KEY_ID` | — | Credenciais AWS (se não usar IAM Role) |
| `LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`) |

---

## 14. Execução

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

---

## 15. API Reference

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

## 16. Streamlit — Interface de Validação

**Arquivo:** `streamlit-app/app.py`

O Streamlit serve como **interface visual de validação** do pipeline, permitindo testar a análise de diagramas sem depender da integração SQS/SOAT. Opera de forma independente do consumer — consome o endpoint HTTP `POST /analyze/stream` diretamente.

### Por que Streamlit?

- **Prototipagem rápida:** nativo Python, sem necessidade de frontend separado (React, Vue)
- **Ideal para hackathon:** interface funcional com ~340 linhas de código
- **SSE nativo:** `httpx.Client.stream()` consome eventos em tempo real
- **Componentes prontos:** file uploader, expanders, metrics, download buttons

### Fluxo de Interação

```
┌──────────────────────────────────────────────────────────┐
│  Streamlit App (:8501)                                   │
│                                                          │
│  1. Usuário faz upload (drag & drop / file picker)       │
│       │                                                  │
│  2. Preview do diagrama (se imagem)                      │
│       │                                                  │
│  3. Clica "Analisar Diagrama"                            │
│       │                                                  │
│  4. POST /analyze/stream ──▶ ia-service (:8000)          │
│       │                                                  │
│  5. Consome SSE em tempo real:                           │
│       │  ⏳ Ingestão — Processando...                    │
│       │  ✅ Ingestão (0.1s) — PNG, 512 KB                │
│       │  ⏳ Extração — Processando...                    │
│       │  ✅ Extração (3.2s) — 8 componentes, 5 relações  │
│       │  ✅ RAG (0.5s) — 2 análises similares            │
│       │  ✅ Relatório (4.1s) — 3 riscos, 5 recomendações │
│       │  ✅ QA (1.8s) — Score 92% — aprovado             │
│       │                                                  │
│  6. Renderiza relatório completo:                        │
│       ├── Resumo Executivo                               │
│       ├── Componentes (grid 3 colunas)                   │
│       ├── Riscos (expanders com badges 🔴🟡🟢)           │
│       ├── Recomendações (🔗 = RAG, ➡️ = original)        │
│       ├── Score QA (metric widget)                       │
│       └── Download JSON (botão)                          │
└──────────────────────────────────────────────────────────┘
```

### SSE (Server-Sent Events) — Streaming em Tempo Real

O `ia-service` emite eventos SSE durante o pipeline via `StreamingResponse` do FastAPI:

```
data: {"step": "ingestion", "status": "running", "data": {}}

data: {"step": "ingestion", "status": "done", "data": {"file_type": "png", "file_size_kb": 512, "elapsed": 0.1}}

data: {"step": "extraction", "status": "running", "data": {}}

data: {"step": "extraction", "status": "done", "data": {"components_count": 8, "elapsed": 3.2}}
```

O Streamlit consome esses eventos via `httpx.Client.stream()` e atualiza a UI incrementalmente usando `st.empty()` para redesenhar os passos sem flickering.

### Sidebar — Monitoramento

- **Health check:** verifica conectividade do `ia-service` (GET /health)
- **Histórico:** lista últimas 10 análises via `report-api` (GET /reports)
- **Pipeline visual:** diagrama simplificado das etapas

### Tratamento de Erros

- **Erro no pipeline:** exibe a etapa que falhou com ícone ❌ e mensagem
- **Stack trace do servidor:** capturado via campo `traceback` do evento SSE e exibido em expander
- **Stack trace local:** traceback Python do Streamlit exibido separadamente

---

## 17. Testes

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

### Testes E2E com Playwright

O diretório `tests/e2e/` contém **7 specs E2E** escritos em TypeScript com Playwright, cobrindo o fluxo completo da aplicação.

**Specs disponíveis:**

| Spec | O que valida |
|---|---|
| `health-check.spec.ts` | Endpoints /health do ia-service e report-api |
| `upload-flow.spec.ts` | Upload de arquivo e início da análise |
| `sse-pipeline.spec.ts` | Streaming SSE com progresso de cada agente |
| `report-display.spec.ts` | Renderização do relatório no Streamlit |
| `error-scenarios.spec.ts` | Comportamento com arquivos inválidos |
| `report-api.spec.ts` | Endpoints REST do report-api |
| `history.spec.ts` | Histórico e paginação de análises |

**Helpers reutilizáveis:**
- `api-client.ts` — cliente HTTP para ia-service e report-api
- `sse-client.ts` — consumer de Server-Sent Events
- `selectors.ts` — seletores CSS do Streamlit

**Executar:**

```bash
cd tests/e2e
npm install
npx playwright test                # todos os testes
npx playwright test upload-flow    # teste específico
npx playwright test --ui           # modo visual interativo
npm run report                     # relatório HTML
```

**Scripts npm disponíveis:**

```bash
npm run test:health     # health check
npm run test:upload     # upload flow
npm run test:sse        # SSE pipeline
npm run test:report     # report display
npm run test:errors     # cenários de erro
npm run test:api        # report API
npm run test:history    # histórico
```

---

## 18. Segurança

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

## 19. Limitações e Decisões de Projeto

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

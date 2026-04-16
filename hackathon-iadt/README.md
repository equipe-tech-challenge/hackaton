# Hackathon FIAP — Time IADT · Analise de Diagramas de Arquitetura com IA

Sistema de analise automatizada de diagramas de arquitetura de software. Recebe imagens ou PDFs de diagramas via fila SQS (ou upload direto), processa com um pipeline de 5 etapas de IA (com guardrails de entrada e saida, RAG e QA) e devolve um relatorio tecnico estruturado via webhook. Oferece tambem execucao sincrona, streaming SSE e processamento assincrono via Celery + Redis.

---

## Indice

1. [Visao Geral](#1-visao-geral)
2. [Arquitetura de Alto Nivel](#2-arquitetura-de-alto-nivel)
3. [Stack Tecnologica](#3-stack-tecnologica)
4. [Arquitetura Hexagonal (Ports & Adapters)](#4-arquitetura-hexagonal-ports--adapters)
5. [Dominio (Modelagem Tatica DDD)](#5-dominio-modelagem-tatica-ddd)
6. [Componentes do Sistema](#6-componentes-do-sistema)
7. [Modos de Execucao do Pipeline](#7-modos-de-execucao-do-pipeline)
8. [SQS Consumer — Arquitetura Event-Driven](#8-sqs-consumer--arquitetura-event-driven)
9. [Celery + Redis — Processamento Assincrono](#9-celery--redis--processamento-assincrono)
10. [Pipeline de IA — 5 Etapas + Guardrails](#10-pipeline-de-ia--5-etapas--guardrails)
11. [RAG com pgvector](#11-rag-com-pgvector)
12. [Guardrails e Controle de Qualidade](#12-guardrails-e-controle-de-qualidade)
13. [Estrategia de Convergencia do Pipeline](#13-estrategia-de-convergencia-do-pipeline)
14. [Webhook de Devolutiva](#14-webhook-de-devolutiva)
15. [Fine-Tuning](#15-fine-tuning)
16. [Schema do Banco de Dados](#16-schema-do-banco-de-dados)
17. [Configuracao de Ambiente](#17-configuracao-de-ambiente)
18. [Executando o Projeto do Zero](#18-executando-o-projeto-do-zero)
19. [API Reference](#19-api-reference)
20. [Streamlit — Interface de Validacao](#20-streamlit--interface-de-validacao)
21. [Testes](#21-testes)
22. [Seguranca](#22-seguranca)
23. [Limitacoes e Decisoes de Projeto](#23-limitacoes-e-decisoes-de-projeto)

---

## 1. Visao Geral

### O Problema

Empresas que operam sistemas distribuidos possuem dezenas de diagramas de arquitetura armazenados como imagens ou PDFs. Sua analise e feita **manualmente**, demanda muito tempo, depende de especialistas e **nao escala**.

### A Solucao

Este servico automatiza a analise usando um pipeline de IA que:

- **Le** o diagrama visualmente (sem OCR — usa LLM Vision multimodal)
- **Extrai** componentes, relacionamentos e padroes arquiteturais
- **Enriquece** a analise com contexto de diagramas similares ja processados (RAG via pgvector)
- **Classifica** riscos em 6 categorias com severidade
- **Gera** um relatorio tecnico estruturado em JSON
- **Valida** o relatorio com QA em duas fases (deterministica + LLM)
- **Devolve** o resultado via webhook para o sistema solicitante

### Escopo de Responsabilidade

O time **IADT** e responsavel pelos servicos deste repositorio:

| Servico | Porta | Responsabilidade |
|---|---|---|
| [ia-service](ia-service/) | 8000 | Pipeline de IA + SQS consumer + webhook + endpoints sincronos/async/SSE |
| [report-api](report-api/) | 8001 | API REST read-only de consulta de relatorios |
| [pgvector](pgvector/) | 5432 | PostgreSQL 16 com extensao vetorial |
| [streamlit-app](streamlit-app/) | 8501 | Front-end de validacao visual |
| redis | 6379 | Broker/backend Celery + pub-sub para jobs assincronos |
| celery-worker | — | Worker Celery que executa o pipeline em background |

O time **SOAT** e responsavel pelo API Gateway, servico de upload, publicacao na fila SQS e infraestrutura AWS adjacente.

---

## 2. Arquitetura de Alto Nivel

```
                         +-------------------------------------+
                         |           SOAT (Externo)            |
                         |  API Gateway . Upload Service . S3  |
                         +----------------+--------------------+
                                          | publica mensagem
                                          v
                                  +---------------+
                                  |   AWS SQS     |
                                  |     Fila      |
                                  +-------+-------+
                                          | long polling (20s)
                                          v
+-------------------------------------------------------------------------------+
|                              ia-service (:8000)                                |
|                                                                                |
|  +--------------+    +---------------------------------------------------+    |
|  | SQS Consumer |--->|         Pipeline de 5 Etapas + Guardrails         |    |
|  | (thread)     |    |                                                   |    |
|  +--------------+    |  Input Guardrails -> Ingestion -> Extraction ->   |    |
|                      |  RAG -> Report (com riscos) -> QA                 |    |
|  +--------------+    +---------------------+---------------------------- +    |
|  |  FastAPI     |                          | persiste                         |
|  |  /analyze    |                          v                                  |
|  |  /health     |    +----------------------------------------------------+   |
|  |  /status     |    |          PostgreSQL + pgvector (:5432)             |   |
|  |  /stream     |    |  analyses . extraction_results . reports           |   |
|  |  /async      |    |  langchain_pg_embedding (vetores)                  |   |
|  |  /jobs       |    +----------------------------------------------------+   |
|  +--------------+                                                              |
|         ^                                                                      |
|         |                 +----------------------+                             |
|         +---------------> |  Redis (:6379)       |<------ celery-worker        |
|   pub/sub + catch-up      |  broker + pub/sub    |        (background)         |
|                           +----------------------+                             |
|                                                                                |
|  +--------------+                                                              |
|  |   Webhook    |--->  POST callback_url . retry 3x backoff                    |
|  |   Sender     |                                                              |
|  +--------------+                                                              |
+-------------------------------------------------------------------------------+
                                          |
                                          v
                     +-----------------------------------------+
                     |   report-api (:8001)                    |
                     |   GET /reports/{id}  GET /reports       |
                     +-----------------------------------------+
                                          |
                                          v
                     +-----------------------------------------+
                     |   streamlit-app (:8501)                 |
                     |   upload + SSE + historico              |
                     +-----------------------------------------+
```

Diagrama de componentes: [docs/architecture.png](docs/architecture.png)

---

## 3. Stack Tecnologica

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Web framework | FastAPI + Uvicorn |
| ORM / DB | SQLAlchemy 2.x + PostgreSQL 16 |
| Vector DB | pgvector + LangChain PGVector |
| LLM orquestracao | LangChain (`ChatOpenAI`, `JsonOutputParser`) |
| LLM Vision/Text | OpenAI (`gpt-4o`) ou Groq/outros compativeis |
| Embeddings | `text-embedding-3-small` (OpenAI) ou `all-MiniLM-L6-v2` (HuggingFace local) |
| Fila externa | AWS SQS (`boto3`) |
| Fila interna | Celery 5 + Redis 7 |
| Resiliencia | `tenacity` (retry com backoff) |
| Logging | `structlog` (JSON) |
| Settings | `pydantic-settings` |
| UI de validacao | Streamlit |
| Containerizacao | Docker + Docker Compose |
| Fine-tuning | `peft` (QLoRA) + `transformers` + HuggingFace Hub |
| Testes | `pytest` (unit) + Playwright (E2E em TypeScript) |

---

## 4. Arquitetura Hexagonal (Ports & Adapters)

O `ia-service` adota **Arquitetura Hexagonal** (Ports & Adapters) como padrao arquitetural. Dentro da camada de dominio, aplica **modelagem tatica DDD** (agregados, value objects, domain events) para expressar as regras de negocio.

### 4.1 Camadas

```
                    +------------------------------------------------------+
                    |              INFRASTRUCTURE (Adapters)               |
                    |                                                      |
                    |  OpenAIVisionAdapter    SQLAlchemy*Repository        |
                    |  OpenAITextAdapter      PGVectorAdapter              |
                    |  SQSConsumer            WebhookSender                |
                    |  CeleryApp / Tasks      RedisClient                  |
                    |                                                      |
                    |    +----------------------------------------------+  |
                    |    |         APPLICATION (Use Cases + Ports)      |  |
                    |    |                                              |  |
                    |    |  AnalyzeDiagramUseCase                       |  |
                    |    |  RetrieveReportUseCase                       |  |
                    |    |                                              |  |
                    |    |  Ports: IVisionLLM . ITextLLM                |  |
                    |    |         IVectorStore                         |  |
                    |    |         IAnalysisRepository                  |  |
                    |    |         IReportRepository                    |  |
                    |    |                                              |  |
                    |    |    +----------------------------------+      |  |
                    |    |    |     DOMAIN (Modelo Tatico DDD)   |      |  |
                    |    |    |                                  |      |  |
                    |    |    |  AnalysisAggregate               |      |  |
                    |    |    |  ReportAggregate                 |      |  |
                    |    |    |  GuardrailService                |      |  |
                    |    |    |  InputGuardrailService           |      |  |
                    |    |    |  OutputGuardrailService          |      |  |
                    |    |    |  Value Objects . Events          |      |  |
                    |    |    +----------------------------------+      |  |
                    |    +----------------------------------------------+  |
                    +------------------------------------------------------+
```

**Regra de dependencia:** as setas apontam para dentro. Infrastructure depende de Application, que depende de Domain. Domain nao importa nada externo.

### 4.2 Portas (Interfaces — Camada Application)

```python
# ia-service/app/application/ports/llm_port.py
class IVisionLLM(ABC):
    def extract_components(self, diagram_file: DiagramFile) -> ExtractionResult: ...

class ITextLLM(ABC):
    def generate_report(self, extraction, rag_context) -> TechnicalReport: ...
    def evaluate_quality(self, extraction, report) -> QAScore: ...

# ia-service/app/application/ports/vector_store_port.py
class IVectorStore(ABC):
    def index(self, analysis_id, extraction) -> None: ...
    def retrieve_context(self, extraction, exclude_analysis_id) -> RagContext: ...
```

### 4.3 Adaptadores (Camada Infrastructure)

| Porta | Adaptador | Tecnologia |
|---|---|---|
| `IVisionLLM` | `OpenAIVisionAdapter` | OpenAI SDK (compativel com Groq via `base_url`) |
| `ITextLLM` | `OpenAITextAdapter` | LangChain chains + OpenAI/Groq/fine-tuned |
| `IVectorStore` | `PGVectorAdapter` | LangChain PGVector + `text-embedding-3-small` (fallback HuggingFace) |
| `IAnalysisRepository` | `SQLAlchemyAnalysisRepository` | SQLAlchemy + PostgreSQL |
| `IReportRepository` | `SQLAlchemyReportRepository` | SQLAlchemy + PostgreSQL |

**Trocar de provider de LLM** (ex: OpenAI -> Anthropic) significa criar um novo adapter que implemente `IVisionLLM` / `ITextLLM`. O dominio e os use cases permanecem intactos.

### 4.4 Composition Root (DI)

Arquivo unico de montagem do grafo de dependencias: [ia-service/app/infrastructure/composition_root.py](ia-service/app/infrastructure/composition_root.py).

```python
def build_analyze_use_case(db: Session) -> AnalyzeDiagramUseCase:
    return AnalyzeDiagramUseCase(
        analysis_repo=SQLAlchemyAnalysisRepository(db),
        report_repo=SQLAlchemyReportRepository(db),
        vision_llm=OpenAIVisionAdapter(),
        text_llm=OpenAITextAdapter(),
        vector_store=PGVectorAdapter(db),
        guardrail_svc=GuardrailService(),
        input_guardrail=InputGuardrailService(),
        output_guardrail=OutputGuardrailService(),
    )
```

---

## 5. Dominio (Modelagem Tatica DDD)

### 5.1 Bounded Contexts

| Contexto | Responsabilidade | Agregado |
|---|---|---|
| **DiagramAnalysis** | Ciclo de vida da analise (recebimento -> processamento -> conclusao/erro) | `AnalysisAggregate` |
| **ReportGeneration** | Geracao, validacao e persistencia do relatorio tecnico | `ReportAggregate` |

### 5.2 AnalysisAggregate — Maquina de Estados

```
RECEIVED --start_ingestion()--> PROCESSING --complete()--> ANALYZED
                                     |
                                     +--fail()--> ERROR
```

**Invariantes protegidas pelo agregado:**
- Um diagrama so pode ser processado a partir do estado `RECEIVED`
- A extracao so pode acontecer apos a ingestao
- O pipeline so pode completar apos extracao bem-sucedida
- Qualquer etapa pode transitar para `ERROR`

### 5.3 Value Objects

| Value Object | Contexto | Descricao |
|---|---|---|
| `DiagramFile` | DiagramAnalysis | Arquivo validado (tipo, tamanho, base64) — imutavel |
| `Component`, `Relationship`, `ArchitecturalPattern` | DiagramAnalysis | Elementos extraidos do diagrama |
| `AnalysisId`, `ReportId` | Shared | UUIDs tipados |
| `RiskItem` | ReportGeneration | Risco categorizado com severidade e mitigacao |
| `Recommendation` | ReportGeneration | Recomendacao com flag `[RAG]` de origem historica |
| `QAScore` | ReportGeneration | Score de qualidade + issues encontradas |
| `RagContext` | ReportGeneration | Contexto historico recuperado do pgvector |

### 5.4 Domain Events

O agregado emite eventos a cada transicao de estado (padrao outbox). Acesso via `aggregate.pull_events()` (retorna e limpa eventos pendentes).

| Evento | Quando emitido |
|---|---|
| `DiagramReceivedEvent` | Analise criada |
| `DiagramIngestedEvent` | Arquivo validado e convertido para base64 |
| `ComponentsExtractedEvent` | LLM Vision extraiu componentes |
| `AnalysisCompletedEvent` | Pipeline finalizou com sucesso |
| `AnalysisFailedEvent` | Qualquer etapa falhou |
| `ReportGeneratedEvent` | Relatorio tecnico gerado |
| `QAValidationCompletedEvent` | QA executado (aprovado ou rejeitado) |

### 5.5 Domain Services

| Servico | Arquivo | Responsabilidade |
|---|---|---|
| `GuardrailService` | [domain/report_generation/guardrail.py](ia-service/app/domain/report_generation/guardrail.py) | Validacao do relatorio contra dados de extracao (anti-alucinacao) |
| `InputGuardrailService` | [domain/shared/input_guardrail.py](ia-service/app/domain/shared/input_guardrail.py) | Deteccao de prompt injection, sanitizacao de inputs, validacao de schema |
| `OutputGuardrailService` | [domain/shared/output_guardrail.py](ia-service/app/domain/shared/output_guardrail.py) | Validacao de schema de saida, deteccao de PII, filtro de conteudo proibido |

---

## 6. Componentes do Sistema

### 6.1 ia-service — Estrutura de Pastas

```
ia-service/
├── Dockerfile
├── requirements.txt
├── finetuning-requirements.txt          # dependencias de GPU (QLoRA)
├── tests/                               # testes unitarios (pytest)
└── app/
    ├── main.py                          # FastAPI + startup do SQS consumer
    │
    ├── domain/                          # Camada de Dominio (DDD)
    │   ├── diagram_analysis/            # Bounded Context
    │   │   ├── analysis.py              # AnalysisAggregate
    │   │   ├── analysis_status.py       # Enum: RECEIVED, PROCESSING, ANALYZED, ERROR
    │   │   ├── component.py             # Component, Relationship, ArchitecturalPattern
    │   │   ├── diagram_file.py          # DiagramFile (VO imutavel)
    │   │   ├── extraction_result.py     # ground truth do pipeline
    │   │   ├── file_type.py
    │   │   ├── repository.py            # IAnalysisRepository
    │   │   └── events/                  # Domain Events
    │   ├── report_generation/           # Bounded Context
    │   │   ├── report.py                # ReportAggregate
    │   │   ├── technical_report.py      # Entidade relatorio
    │   │   ├── risk.py                  # RiskItem, RiskCategory, Severity
    │   │   ├── recommendation.py
    │   │   ├── qa_score.py              # MIN_SCORE = 0.6
    │   │   ├── rag_context.py
    │   │   ├── guardrail.py             # GuardrailService
    │   │   ├── repository.py            # IReportRepository
    │   │   └── events/
    │   └── shared/
    │       ├── analysis_id.py           # UUID tipado
    │       ├── report_id.py
    │       ├── input_guardrail.py
    │       ├── output_guardrail.py
    │       └── events/domain_event.py   # DomainEvent base
    │
    ├── application/                     # Camada de Aplicacao
    │   ├── ports/
    │   │   ├── llm_port.py              # IVisionLLM, ITextLLM
    │   │   └── vector_store_port.py     # IVectorStore
    │   └── use_cases/
    │       ├── analyze_diagram.py       # AnalyzeDiagramUseCase (orquestracao E2E)
    │       └── retrieve_report.py       # RetrieveReportUseCase
    │
    ├── infrastructure/                  # Camada de Infraestrutura
    │   ├── composition_root.py          # DI
    │   ├── config/settings.py           # pydantic-settings
    │   ├── llm/
    │   │   ├── openai_adapter.py        # OpenAIVisionAdapter, OpenAITextAdapter
    │   │   └── finetuning/              # QLoRA (data_generator, train, inference)
    │   ├── vector_store/
    │   │   └── pgvector_adapter.py      # PGVectorAdapter
    │   ├── persistence/
    │   │   ├── database.py              # engine + session factory
    │   │   ├── sqlalchemy_analysis_repository.py
    │   │   └── sqlalchemy_report_repository.py
    │   ├── messaging/
    │   │   └── sqs_consumer.py          # consumer com graceful shutdown
    │   ├── http/
    │   │   └── webhook_sender.py        # retry 3x backoff
    │   └── celery/
    │       ├── celery_app.py            # app Celery (broker/backend = Redis)
    │       └── tasks.py                 # analyze_diagram_task + pub/sub Redis
    │
    ├── pipeline/                        # Delegacao ao use case (compat)
    │   ├── analysis_orchestrator.py     # run_pipeline (ponto unico de entrada)
    │   ├── diagram_ingestion_step.py
    │   ├── component_extraction_step.py
    │   ├── context_enrichment_step.py
    │   ├── risk_assessment_step.py
    │   ├── report_generation_step.py
    │   └── quality_validation_step.py
    │
    └── shared/
        ├── exceptions.py                # PipelineError, IngestionError, GuardrailError...
        └── logging.py                   # structlog (JSON)
```

### 6.2 report-api

API read-only para consulta de relatorios gerados. Usada pelo API Gateway do time SOAT.

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/health` | Healthcheck — verifica conexao com DB |
| `GET` | `/reports/{analysis_id}` | Relatorio completo de uma analise |
| `GET` | `/reports?limit=20&offset=0` | Lista paginada de analises |

### 6.3 pgvector

PostgreSQL 16 + extensao `pgvector`. Schemas inicializados automaticamente em [pgvector/init](pgvector/init):
- `00_extensions.sql` — habilita `pgvector` e `uuid-ossp`
- `01_schema.sql` — tabelas `analyses`, `extraction_results`, `reports`
- `02_indexes.sql` — indices de status/criacao/analysis_id

### 6.4 redis + celery-worker

- **redis** (`:6379`) — broker Celery, backend de resultados e canal pub/sub para eventos SSE de jobs
- **celery-worker** — reaproveita a imagem do `ia-service` e roda `celery -A app.infrastructure.celery.celery_app worker --concurrency=2`

### 6.5 streamlit-app

Interface visual de validacao do pipeline na porta `8501`. Consome o endpoint SSE `POST /analyze/stream`.

---

## 7. Modos de Execucao do Pipeline

O `ia-service` expoe **4 formas** de executar o pipeline, todas compartilhando a mesma funcao `run_pipeline` ([pipeline/analysis_orchestrator.py](ia-service/app/pipeline/analysis_orchestrator.py)):

| Modo | Entrada | Quem consome | Quando usar |
|---|---|---|---|
| **SQS consumer** | mensagem SQS | time SOAT | Fluxo principal em producao |
| **Sincrono** | `POST /analyze` | clientes HTTP | Testes rapidos |
| **SSE streaming** | `POST /analyze/stream` | streamlit-app, frontends | UI com progresso em tempo real |
| **Assincrono (Celery)** | `POST /analyze/async` + `GET /jobs/{id}/events` | UIs com fila de jobs | Alta carga, uploads em paralelo |

---

## 8. SQS Consumer — Arquitetura Event-Driven

Arquivo: [ia-service/app/infrastructure/messaging/sqs_consumer.py](ia-service/app/infrastructure/messaging/sqs_consumer.py)

Roda como **thread daemon** iniciada no startup do FastAPI, sem bloquear o event loop HTTP.

### Fluxo

```
SQS Queue
   |
   v  long polling (WaitTimeSeconds=20)
+--------------------------------------------------------------+
|  Consumer Thread                                             |
|                                                              |
|  receive_message(MaxMessages=5, VisibilityTimeout=300s)      |
|       |                                                      |
|       +-- Idempotencia: sqs_message_id ja existe? -> skip    |
|       +-- Poison pill: ApproximateReceiveCount > 3? -> warn  |
|       +-- Download S3: retry 3x (backoff exponencial)        |
|       +-- run_pipeline(file_bytes, file_name)                |
|       +-- delete_message()  <- somente apos sucesso          |
|       +-- send_webhook(callback_url, result)                 |
+--------------------------------------------------------------+
```

### Mensagem SQS esperada

```json
{
  "file_name":    "diagrama.png",
  "s3_url":       "https://s3.amazonaws.com/...",
  "callback_url": "https://soat-api.example.com/webhook"
}
```

### Resiliencia

| Mecanismo | Implementacao |
|---|---|
| Long polling | `WaitTimeSeconds=20` — reduz chamadas vazias |
| Idempotencia | `sqs_message_id` verificado no banco |
| Graceful shutdown | Handlers de `SIGTERM`/`SIGINT` |
| Poison pill | Warn se `ApproximateReceiveCount > 3` |
| Download com retry | `tenacity`: 3 tentativas, backoff (2s -> 10s) |
| Visibility timeout | 300s — mensagem nao processada volta a fila |
| Webhook non-blocking | Falha no webhook nao impede delecao (resultado ja no banco) |

---

## 9. Celery + Redis — Processamento Assincrono

Quando um cliente quer submeter muitos diagramas sem bloquear conexoes HTTP, ele usa o endpoint assincrono:

```
Cliente                 ia-service                 Redis                 celery-worker
   |                        |                        |                        |
   |  POST /analyze/async   |                        |                        |
   |----------------------> | task.delay(...)        |                        |
   |                        |----------------------->| push(task)             |
   |  202 {job_id: ...}     |                        |<---------------------- | pop(task)
   |<---------------------- |                        |                        | run_pipeline
   |                        |                        | pub  job:{id}          |<---- on_step
   |                        |                        | rpush job:{id}:events  |
   |  GET /jobs/{id}/events |                        |                        |
   |----------------------> | subscribe + catch-up   |                        |
   |  SSE stream            |<---------------------- |                        |
```

### Canais Redis

- **`job:{task_id}`** (pub/sub) — eventos em tempo real
- **`job:{task_id}:events`** (list, TTL 10 min) — log de eventos para *catch-up*/reconexao

### Garantias

| Garantia | Implementacao |
|---|---|
| Reconexao sem perder eventos | `GET /jobs/{id}/events?last_index=N` — envia eventos acumulados no list, depois assina pub/sub |
| Concorrencia | `--concurrency=2` no worker (configuravel) |
| Prefetch justo | `worker_prefetch_multiplier=1` — um worker nao segura tasks que nao vai processar |
| ACK tardio | `task_acks_late=True` — so confirma apos conclusao |

---

## 10. Pipeline de IA — 5 Etapas + Guardrails

Orquestrado por `AnalyzeDiagramUseCase` ([analyze_diagram.py](ia-service/app/application/use_cases/analyze_diagram.py)). O `analysis_orchestrator.py` delega para o use case, mantendo compatibilidade com os pontos de entrada.

```
[arquivo binario]
      |
      v
(0) Input Guardrails   -> sanitiza filename, detecta prompt injection
      |
      v
(1) Ingestion          -> valida tipo/tamanho, converte para base64
      |
      v
(2) Extraction         -> LLM Vision -> componentes, relacionamentos, padroes
      |
      v
(2.5) Input Guardrail  -> valida schema da extracao, detecta injection nos dados
      |
      v
(3) RAG                -> indexa no pgvector, busca similares (non-blocking)
      |
      v
(4) Report + Riscos    -> LLM + Output Guardrails -> relatorio JSON com riscos
      |
      v
(5) QA                 -> 2 fases de validacao -> score de qualidade
      |
      v
[PostgreSQL] + [Webhook]
```

### Etapa 0 — Input Guardrails

Executada antes de qualquer processamento. Protege contra inputs maliciosos.

- Sanitiza filename (remove path traversal, caracteres perigosos, limita a 255 chars)
- Detecta padroes de prompt injection via regex (override de instrucoes, role-play, exfiltracao, delimitadores)

**Falha:** `GuardrailError` — bloqueia o pipeline.

### Etapa 1 — Ingestion

- Rejeita arquivos > 20MB
- Valida MIME type (`png`, `jpg`, `jpeg`, `gif`, `webp`, `pdf`)
- Converte binario para Base64 via `DiagramFile.create()`

**Falha:** `IngestionError`.

**Saida:**
```json
{
  "file_name": "diagrama.png",
  "file_type": "png",
  "media_type": "image/png",
  "content_base64": "iVBORw0KGgo...",
  "file_size_kb": 512.3
}
```

### Etapa 2 — Extraction (LLM Vision)

Arquivo: [infrastructure/llm/openai_adapter.py](ia-service/app/infrastructure/llm/openai_adapter.py)

> **Nao usa OCR.** O arquivo e enviado diretamente para o LLM como conteudo multimodal. O modelo interpreta setas, caixas, relacionamentos e padroes arquiteturais semanticamente.

1. Monta payload multimodal: `{type: "image_url", image_url: {url: "data:{media_type};base64,..."}}`
2. Ativa `response_format: json_object` (OpenAI) ou fallback markdown fences (Groq/LLaMA)
3. Valida campos obrigatorios (`components`, `relationships`, `patterns`, `raw_description`)

Apos a extracao, `InputGuardrailService` valida o schema dos dados extraidos (tipos, limites de tamanho, prompt injection nos componentes).

**Saida:**
```json
{
  "components": ["API Gateway", "Auth Service", "User DB", "Redis Cache"],
  "relationships": [
    "Client -> API Gateway: requisicoes HTTP",
    "API Gateway -> Auth Service: valida JWT",
    "Auth Service -> User DB: consulta usuario"
  ],
  "patterns": ["Microservices", "API Gateway Pattern", "JWT Authentication"],
  "raw_description": "O diagrama apresenta uma arquitetura de microsservicos..."
}
```

**Falha:** `ExtractionError`.

### Etapa 3 — RAG

Arquivo: [infrastructure/vector_store/pgvector_adapter.py](ia-service/app/infrastructure/vector_store/pgvector_adapter.py)

> **Non-blocking:** Se o pgvector estiver indisponivel, nao houver historico ou ocorrer qualquer erro, retorna `RagContext.empty()` e o pipeline continua.

**Indexacao (toda nova analise):**
```
ExtractionResult
      -> LangChain Document (raw_description + components + patterns)
      -> Embeddings (text-embedding-3-small ou HuggingFace fallback)
      -> PGVector.add_documents()
```

**Recuperacao:**
```
query = raw_description + components + patterns
      -> PGVector.similarity_search_with_score(k=3, filter={"has_report": True})
      -> distancia coseno < 0.3 -> similar (>70%) -> inclui
      -> LLM chain -> rag_enrichment
```

**Saida:** `RagContext` com `has_context`, `enrichment_text` e `similar_analyses_count`.

### Etapa 4 — Report + Riscos

Arquivo: [OpenAITextAdapter.generate_report](ia-service/app/infrastructure/llm/openai_adapter.py)

Gera relatorio tecnico estruturado **incluindo analise de riscos** em uma unica chamada ao LLM. Riscos classificados em 6 categorias:

| Categoria | O que avalia |
|---|---|
| **SPOF** | Pontos unicos de falha sem redundancia |
| **Seguranca** | Ausencia de autenticacao, dados expostos, endpoints sem protecao |
| **Escalabilidade** | Gargalos, ausencia de cache, filas sem DLQ |
| **Acoplamento** | Dependencias sincronas excessivas, falta de interfaces |
| **Observabilidade** | Ausencia de logs, metricas, tracing |
| **Resiliencia** | Sem circuit breaker, retry, fallback |

Contexto RAG (quando disponivel) e incluido no prompt. Recomendacoes influenciadas pelo historico sao marcadas com `[RAG]`.

**Pos-geracao:**
1. `OutputGuardrailService.validate_output()` — schema, conteudo proibido, redacao de PII
2. `GuardrailService.validate()` — grounding (anti-alucinacao), completude, sumario
3. `risk_severity_summary` recalculado server-side (nao confia no LLM para somar)

**Backends disponiveis (`REPORT_MODEL_BACKEND`):**
- `langchain` (padrao) — `ChatPromptTemplate | ChatOpenAI | JsonOutputParser`
- `finetuned_api` — HuggingFace Inference API
- `finetuned_local` — adapter QLoRA carregado localmente (requer GPU)

**Saida:**
```json
{
  "components_identified": ["API Gateway", "Auth Service", "User DB"],
  "architectural_risks": [
    {
      "type": "SPOF",
      "description": "User DB sem replica de leitura",
      "severity": "ALTO",
      "affected_components": ["User DB"],
      "mitigation": "Adicionar replica read-only com failover automatico"
    }
  ],
  "recommendations": [
    "Configurar DLQ no SQS para mensagens nao processadas",
    "[RAG] Implementar circuit breaker — padrao recorrente em arquiteturas similares"
  ],
  "executive_summary": "A arquitetura analisada implementa um padrao de microsservicos...",
  "rag_used": true
}
```

### Etapa 5 — QA

**Fase 1 — Deterministica (sem LLM):**
- `components_identified` nao vazio
- `architectural_risks` nao vazio
- `recommendations` nao vazio
- `executive_summary` >= 100 caracteres
- **Grounding:** >= 80% dos componentes do relatorio existem na extracao original

Falha na Fase 1 rejeita o relatorio sem chamar o LLM.

**Fase 2 — LLM (`json_object` mode):**

| Criterio | Peso |
|---|---|
| Completude (todos os campos obrigatorios) | 30% |
| Consistencia (componentes/riscos batem com a extracao) | 40% |
| Coerencia (recomendacoes vinculadas a riscos) | 20% |
| Qualidade (linguagem tecnica, sem generalidades) | 10% |

**Score minimo:** `0.6`. Abaixo disso `is_valid: false`.

**Resiliencia:** se o LLM de QA estiver indisponivel, assume `is_valid: true` com score conservador `0.7`, desde que a Fase 1 tenha passado.

---

## 11. RAG com pgvector

### Embeddings

- Padrao: **OpenAI `text-embedding-3-small`**
- Fallback: **HuggingFace `all-MiniLM-L6-v2`** (local, quando `LLM_BASE_URL` esta configurado)

### Indice HNSW (criar manualmente apos o LangChain inicializar a tabela)

```sql
CREATE INDEX idx_langchain_hnsw
  ON langchain_pg_embedding
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

Latencia de busca: < 50ms.

### Threshold de similaridade

```python
# score < 0.3 (distancia coseno) = similaridade > 70%
relevant = [(doc, score) for doc, score in similar_docs if score < 0.3]
```

---

## 12. Guardrails e Controle de Qualidade

### Input Guardrails

| Guardrail | Quando | Implementacao |
|---|---|---|
| Prompt injection | Antes do pipeline e apos extracao | Regex |
| Sanitizacao de filename | Antes do pipeline | Remove path traversal, limita tamanho |
| Sanitizacao de texto | Campos textuais | Remove delimitadores e caracteres de controle |
| Validacao de schema | Apos extracao | Limites: max 200 componentes, 500 relacionamentos |

### Report Guardrails

| Guardrail | Implementacao |
|---|---|
| Tipo/tamanho de arquivo | Bloqueia > 20MB e tipos nao suportados |
| Componentes nao vazios | >= 1 item |
| Grounding check (20%) | Componentes inventados > 20% -> `ReportGenerationError` |
| Completude minima | `recommendations` nao vazio, `executive_summary` > 100 chars |

### Output Guardrails

| Guardrail | Implementacao |
|---|---|
| Validacao de schema | Chaves obrigatorias, severidades validas (ALTO/MEDIO/BAIXO) |
| Conteudo proibido | Filtro: discriminatorio, instrucoes ilegais, engenharia social |
| Deteccao de PII | CPF, CNPJ, email, telefone, IP, API keys, cartoes |
| Redacao recursiva | `redact_dict()` substitui por `[REDACTED]` |

### QA Guardrails

| Guardrail | Implementacao |
|---|---|
| Grounding duplo (80%) | >= 80% dos componentes do relatorio na extracao |
| JSON mode | `response_format: json_object` |
| Score minimo | `< 0.6` = rejeitado |
| Transparencia RAG | Tag `[RAG]` em recomendacoes historicas |

---

## 13. Estrategia de Convergencia do Pipeline

O `ExtractionResult` e a **fonte de verdade** do pipeline. Todas as etapas subsequentes sao validadas contra ele.

```
ExtractionResult (ground truth)
     |
     +-->  RAG:     busca similares baseado na extracao
     +-->  Report:  gera relatorio e valida grounding contra extracao
     +-->  QA:      valida 80% overlap entre relatorio e extracao
```

### Mecanismos de Convergencia

| Mecanismo | Onde | Como garante convergencia |
|---|---|---|
| Pipeline sequencial | Use Case | Cada etapa recebe output da anterior — sem race conditions |
| Input Guardrails | Pre-pipeline + pos-extracao | Bloqueia injection antes de chegar ao LLM |
| Output Guardrails | Pos-report | Schema, PII, conteudo proibido |
| Grounding check (20%) | GuardrailService | Max 20% de componentes inventados |
| Grounding duplo (80%) | QA Fase 1 | Rejeita se overlap < 80% |
| Recalculo server-side | TechnicalReport | `risk_severity_summary` recalculado no servidor |
| RAG non-blocking | Use Case | Falha retorna `RagContext.empty()` |
| QA fallback | Use Case | Score conservador 0.7 se LLM indisponivel |
| Score minimo | QA | `< 0.6` rejeita |

**Resultado:** o pipeline sempre converge para `analisado` ou `erro`. Nunca fica indefinido.

---

## 14. Webhook de Devolutiva

Arquivo: [ia-service/app/infrastructure/http/webhook_sender.py](ia-service/app/infrastructure/http/webhook_sender.py)

### Politica de retry

```
Tentativa 1 -> falha -> aguarda 2s
Tentativa 2 -> falha -> aguarda 4s
Tentativa 3 -> falha -> aguarda 8s (max)
               falha -> loga erro -> pipeline continua
```

- Retenta em: timeout, erro de conexao, 5xx
- Nao retenta em: 4xx (erro do cliente)
- Falha total nao bloqueia: resultado ja persistido

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
  "completed_at": "2026-04-02T21:30:00.000000+00:00"
}
```

### Payload de erro

```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "erro",
  "report": null,
  "error_message": "Arquivo excede o limite de 20MB.",
  "completed_at": "2026-04-02T21:30:00.000000+00:00"
}
```

---

## 15. Fine-Tuning

Base: [ia-service/app/infrastructure/llm/finetuning/](ia-service/app/infrastructure/llm/finetuning/)

Treina um LLM open-source com QLoRA para gerar relatorios no formato exato exigido pelo pipeline — como alternativa ao LLM principal.

```
[LLM professor] -> data_generator.py -> raw_pairs.jsonl
                 \
                  data_formatter.py -> train.jsonl + val.jsonl
                                        |
                                        v
                                   train.py (GPU: Colab, RunPod)
                                        |
                                        v
                                   HuggingFace Hub (adapter)
                                        |
                                        v
                              inference.py <- report generation
```

### Passo a passo

```bash
# 1. Dependencias de treino (em maquina com GPU)
pip install -r ia-service/finetuning-requirements.txt

# 2. Gerar dados sinteticos
cd ia-service
python -m app.infrastructure.llm.finetuning.data_generator \
  --api-key $ANTHROPIC_API_KEY \
  --samples 50 \
  --output ./data/raw_pairs.jsonl

# 3. Formatar
python -m app.infrastructure.llm.finetuning.data_formatter \
  --input ./data/raw_pairs.jsonl \
  --output ./data \
  --split 0.9

# 4. Treinar (GPU)
python -m app.infrastructure.llm.finetuning.train \
  --epochs 3 \
  --output-dir ./output/report-lora-adapter \
  --push-to-hub \
  --hub-model-id "seu-usuario/report-lora"

# 5. Usar
# .env:
#   REPORT_MODEL_BACKEND=finetuned_api
#   HUGGINGFACE_API_TOKEN=hf_...
#   HUGGINGFACE_ENDPOINT_URL=https://api-inference.huggingface.co/models/seu-usuario/report-lora
```

### Backends

| `REPORT_MODEL_BACKEND` | Descricao |
|---|---|
| `langchain` | LangChain + LLM via `LLM_MODEL` (padrao, sem GPU) |
| `finetuned_api` | LLM fine-tunado via HuggingFace Inference API |
| `finetuned_local` | Adapter carregado localmente (GPU) |

> Guardrails sao aplicados **igualmente em todos os backends**.

---

## 16. Schema do Banco de Dados

```sql
-- Ciclo de vida de cada analise
CREATE TABLE analyses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status          VARCHAR(20) NOT NULL DEFAULT 'recebido'
                        CHECK (status IN ('recebido', 'em_processamento', 'analisado', 'erro')),
    file_name       VARCHAR(255) NOT NULL,
    file_type       VARCHAR(10)  NOT NULL,
    s3_key          VARCHAR(512),
    sqs_message_id  VARCHAR(255),       -- idempotencia SQS
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cache da extracao (evita re-chamar Vision LLM em retries)
CREATE TABLE extraction_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components      JSONB NOT NULL DEFAULT '[]',
    relationships   JSONB NOT NULL DEFAULT '[]',
    patterns        JSONB NOT NULL DEFAULT '[]',
    raw_description TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Relatorio tecnico gerado + metricas de QA
CREATE TABLE reports (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id           UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    components_identified JSONB NOT NULL DEFAULT '[]',
    architectural_risks   JSONB NOT NULL DEFAULT '[]',
    recommendations       JSONB NOT NULL DEFAULT '[]',
    executive_summary     TEXT,
    rag_used              BOOLEAN NOT NULL DEFAULT FALSE,
    qa_is_valid           BOOLEAN,
    qa_completeness_score FLOAT,
    qa_issues_found       JSONB DEFAULT '[]',
    qa_quality_notes      TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Triggers de updated_at automatico em analyses e reports

-- Gerenciada automaticamente pelo LangChain/pgvector
-- langchain_pg_embedding(embedding vector, document TEXT, cmetadata JSONB)
```

---

## 17. Configuracao de Ambiente

Copie o exemplo e preencha as variaveis:

```bash
cp ia-service/.env.example ia-service/.env
# OU na raiz (o docker-compose carrega daqui)
cp ia-service/.env.example .env
```

### Variaveis obrigatorias

| Variavel | Descricao |
|---|---|
| `OPENAI_API_KEY` | Chave OpenAI (Vision, texto e embeddings `text-embedding-3-small`) |

### Variaveis opcionais

| Variavel | Padrao | Descricao |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Chave Anthropic (usado apenas no `data_generator` de fine-tuning) |
| `POSTGRES_CONNECTION_STRING` | `postgresql+psycopg://hackathon:hackathon123@localhost:5432/hackathon_db` | Connection string |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `hackathon` / `hackathon123` / `hackathon_db` | Credenciais DB (docker-compose) |
| `REDIS_URL` | `redis://redis:6379/0` | Broker/backend Celery + pub/sub |
| `SQS_QUEUE_URL` | `""` | URL da fila SQS (se vazio, consumer nao inicia) |
| `REPORT_MODEL_BACKEND` | `langchain` | `langchain`, `finetuned_api`, `finetuned_local` |
| `LLM_MODEL` | `gpt-4o` | Modelo LLM para texto e Vision (quando `LLM_VISION_MODEL` vazio) |
| `LLM_BASE_URL` | `""` | URL base (vazio = OpenAI; preenchido = Groq/outro) |
| `LLM_VISION_MODEL` | `""` | Modelo especifico para Vision |
| `HUGGINGFACE_API_TOKEN` | `""` | Token HuggingFace (`finetuned_api`) |
| `HUGGINGFACE_ENDPOINT_URL` | `""` | Endpoint HuggingFace |
| `LOCAL_MODEL_PATH` | `""` | Caminho do adapter local (`finetuned_local`) |
| `BASE_MODEL_ID` | `""` | ID do modelo base para fine-tuning local |
| `AWS_ACCESS_KEY_ID` | `""` | Credenciais AWS (se nao usar IAM Role) |
| `AWS_SECRET_ACCESS_KEY` | `""` | Credenciais AWS |
| `AWS_SESSION_TOKEN` | `""` | Token de sessao AWS (STS) |
| `AWS_REGION` | `us-east-1` | Regiao AWS |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |

---

## 18. Executando o Projeto do Zero

### Pre-requisitos

- **Docker Desktop** >= 4.x (inclui Docker Compose V2)
- **Git**
- **OpenAI API Key** (para Vision, texto e embeddings)
- Opcional: Node 20+ (para testes E2E com Playwright)
- Opcional: Python 3.11 (para rodar testes unitarios fora do container)

### Passo 1 — Clonar o repositorio

```bash
git clone <url-do-repo> hackathon-iadt
cd hackathon-iadt
```

### Passo 2 — Configurar variaveis de ambiente

```bash
cp ia-service/.env.example .env
# edite .env e preencha OPENAI_API_KEY
```

### Passo 3 — Subir toda a stack

```bash
docker-compose up --build
```

Sao criados **6 containers**:

| Container | Porta | Funcao |
|---|---|---|
| `hackathon_pgvector` | 5432 | PostgreSQL + pgvector |
| `hackathon_redis` | 6379 | Broker Celery + pub/sub |
| `hackathon_ia_service` | 8000 | API principal (FastAPI) |
| `hackathon_celery_worker` | — | Worker background (jobs `/analyze/async`) |
| `hackathon_report_api` | 8001 | API read-only de relatorios |
| `hackathon_streamlit` | 8501 | UI de validacao |

Aguarde as mensagens de startup:
```
hackathon_pgvector      | database system is ready to accept connections
hackathon_ia_service    | INFO:     Uvicorn running on http://0.0.0.0:8000
hackathon_report_api    | INFO:     Uvicorn running on http://0.0.0.0:8001
hackathon_streamlit     | You can now view your Streamlit app in your browser.
hackathon_celery_worker | celery@... ready.
```

### Passo 4 — Verificar saude

```bash
curl http://localhost:8000/health    # ia-service
curl http://localhost:8001/health    # report-api
```

Ambos devem retornar `{"status": "healthy", "db": "connected"}`.

### Passo 5 — (Opcional) Criar o indice HNSW do pgvector

Apos a primeira analise bem-sucedida, a tabela `langchain_pg_embedding` e criada automaticamente pelo LangChain. Crie o indice:

```bash
docker exec -it hackathon_pgvector psql -U hackathon -d hackathon_db -c \
  "CREATE INDEX IF NOT EXISTS idx_langchain_hnsw \
   ON langchain_pg_embedding USING hnsw (embedding vector_cosine_ops) \
   WITH (m = 16, ef_construction = 64);"
```

### Passo 6 — Testar o pipeline

**Opcao A — via Streamlit (recomendado para validacao visual):**
```
http://localhost:8501
# faca upload de um diagrama (ex: docs/diagrama-exemplo1.png)
```

**Opcao B — via curl (sincrono):**
```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@docs/diagrama-exemplo1.png"
```

**Opcao C — via curl (assincrono com Celery):**
```bash
# 1. Submete o job
JOB=$(curl -s -X POST http://localhost:8000/analyze/async \
  -F "file=@docs/diagrama-exemplo1.png" | jq -r '.job_id')

# 2. Acompanha via SSE
curl -N http://localhost:8000/jobs/$JOB/events

# OU via polling
curl http://localhost:8000/jobs/$JOB/status
```

### Passo 7 — Consultar relatorios

```bash
# Lista
curl "http://localhost:8001/reports?limit=10&offset=0"

# Detalhe
curl "http://localhost:8001/reports/{analysis_id}"
```

### Parando os servicos

```bash
docker-compose down               # mantem volumes (DB persiste)
docker-compose down -v            # remove volumes (reset total)
```

### Desenvolvimento local (fora do Docker)

```bash
# 1. Suba apenas as dependencias
docker-compose up pgvector redis

# 2. Rode o ia-service localmente
cd ia-service
python -m venv .venv
source .venv/bin/activate            # Linux/Mac
.venv\Scripts\activate               # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. (Outro terminal) Celery worker
celery -A app.infrastructure.celery.celery_app worker --loglevel=info

# 4. (Outro terminal) report-api
cd report-api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

---

## 19. API Reference

### ia-service (`:8000`)

#### `GET /health`

```json
{"status": "healthy", "db": "connected"}
```

#### `POST /analyze` (sincrono)

```bash
curl -X POST http://localhost:8000/analyze -F "file=@diagrama.png"
```

**200:**
```json
{
  "analysis_id": "uuid",
  "status": "analisado",
  "report": { "components_identified": [...], "architectural_risks": [...], "recommendations": [...], "executive_summary": "...", "rag_used": false },
  "qa": { "is_valid": true, "completeness_score": 0.92, "issues_found": [], "quality_notes": "..." }
}
```

**400:** tipo nao suportado · **422:** pipeline falhou · **500:** erro interno

#### `POST /analyze/stream` (SSE)

```
data: {"step": "ingestion", "status": "running", "data": {}}
data: {"step": "ingestion", "status": "done", "data": {"file_type": "png", "file_size_kb": 512, "elapsed": 0.1}}
data: {"step": "extraction", "status": "done", "data": {"components_count": 8, "elapsed": 3.2}}
...
```

#### `POST /analyze/async` (Celery)

**202:**
```json
{"job_id": "f3a2...", "status": "recebido"}
```

#### `GET /jobs/{job_id}/events?last_index=0` (SSE)

- Fase 1 (catch-up): envia eventos ja armazenados no Redis list
- Fase 2 (real-time): assina `job:{id}` via pub/sub

#### `GET /jobs/{job_id}/status` (polling)

```json
{
  "job_id": "f3a2...",
  "finished": true,
  "last_event": { "step": "done", "status": "complete", "data": {...} },
  "total_events": 12
}
```

#### `GET /analyses/{analysis_id}/status`

```json
{
  "analysis_id": "uuid",
  "status": "analisado",
  "file_name": "diagrama.png",
  "error_message": null
}
```

Transicoes: `recebido` -> `em_processamento` -> `analisado` | `erro`

### report-api (`:8001`)

#### `GET /health`

```json
{"status": "healthy", "db": "connected"}
```

#### `GET /reports/{analysis_id}`

**200:**
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
        "description": "User DB sem replica de leitura",
        "severity": "ALTO",
        "affected_components": ["User DB"],
        "mitigation": "Adicionar replica read-only com failover automatico"
      }
    ],
    "recommendations": [
      "Configurar DLQ no SQS",
      "[RAG] Implementar circuit breaker — padrao recorrente em arquiteturas similares"
    ],
    "executive_summary": "A arquitetura analisada...",
    "rag_used": true,
    "qa_completeness_score": 0.92
  }
}
```

**404:** `{"detail": "Analise nao encontrada"}`

#### `GET /reports?limit=20&offset=0`

```json
{
  "total": 5,
  "limit": 20,
  "offset": 0,
  "items": [...]
}
```

---

## 20. Streamlit — Interface de Validacao

Arquivo: [streamlit-app/app.py](streamlit-app/app.py)

Serve como **interface visual de validacao** do pipeline, permitindo testar a analise sem depender da integracao SQS/SOAT. Consome `POST /analyze/stream` diretamente.

### Fluxo

```
+-----------------------------------------------------------+
|  Streamlit App (:8501)                                    |
|                                                           |
|  1. Upload (drag & drop / file picker)                    |
|  2. Preview do diagrama (se imagem)                       |
|  3. Clica "Analisar Diagrama"                             |
|  4. POST /analyze/stream -> ia-service (:8000)            |
|  5. Consome SSE em tempo real:                            |
|       Ingestion (0.1s) — PNG, 512 KB                      |
|       Extraction (3.2s) — 8 componentes, 5 relacoes       |
|       RAG (0.5s) — 2 analises similares                   |
|       Relatorio (4.1s) — 3 riscos, 5 recomendacoes        |
|       QA (1.8s) — Score 92% — aprovado                    |
|  6. Renderiza relatorio:                                  |
|       - Resumo Executivo                                  |
|       - Componentes (grid 3 colunas)                      |
|       - Riscos (expanders com badges)                     |
|       - Recomendacoes (RAG vs original)                   |
|       - Score QA (metric widget)                          |
|       - Download JSON                                     |
+-----------------------------------------------------------+
```

### Sidebar

- **Health check** do `ia-service` (GET /health)
- **Historico** via `report-api` (GET /reports)

---

## 21. Testes

### Testes unitarios (pytest)

```bash
cd ia-service
pip install -r requirements.txt
pytest tests/ -v

# com cobertura
pytest tests/ --cov=app --cov-report=term-missing
```

| Arquivo | Cobre |
|---|---|
| [test_diagram_ingestion.py](ia-service/tests/test_diagram_ingestion.py) | Validacao de tipo, tamanho, conversao base64 |
| [test_component_extraction.py](ia-service/tests/test_component_extraction.py) | Parsing do JSON do LLM, campos obrigatorios, markdown |
| [test_risk_assessment.py](ia-service/tests/test_risk_assessment.py) | Classificacao de severidade, recalculo de summary |
| [test_quality_validation.py](ia-service/tests/test_quality_validation.py) | Verificacoes basicas, grounding, score minimo, fallback |

### Testes E2E (Playwright + TypeScript)

Diretorio: [tests/e2e/](tests/e2e/)

| Spec | Valida |
|---|---|
| `health-check.spec.ts` | Endpoints `/health` do ia-service e report-api |
| `upload-flow.spec.ts` | Upload de arquivo e inicio da analise |
| `sse-pipeline.spec.ts` | Streaming SSE com progresso de cada etapa |
| `report-display.spec.ts` | Renderizacao do relatorio no Streamlit |
| `error-scenarios.spec.ts` | Comportamento com arquivos invalidos |
| `report-api.spec.ts` | Endpoints REST do report-api |
| `history.spec.ts` | Historico e paginacao |

**Helpers:** `api-client.ts`, `sse-client.ts`, `selectors.ts`.

```bash
cd tests/e2e
npm install
npx playwright test                  # todos
npx playwright test upload-flow      # especifico
npx playwright test --ui             # modo visual
```

---

## 22. Seguranca

### Validacao de entrada (Input Guardrails)

- Deteccao de prompt injection via regex
- Sanitizacao de filename (path traversal, caracteres perigosos)
- Validacao de schema dos dados extraidos
- Arquivos validados por MIME type e tamanho antes do LLM
- Tipos nao suportados rejeitados na borda

### Controle do LLM

- **System prompts restritos** — modelo responde apenas sobre dados fornecidos
- **Grounding check (20%)** — componentes inventados acima do limite descartam o relatorio
- **JSON mode** — `response_format: json_object` no QA
- **Score minimo** — relatorios abaixo de 0.6 nao sao entregues

### Protecao de saida (Output Guardrails)

- **Deteccao de PII** — CPF, CNPJ, email, telefone, IP, API keys, cartoes
- **Redacao automatica** — `[REDACTED]` recursivo
- **Filtro de conteudo proibido** — discriminatorio, ilegal, engenharia social
- **Validacao de schema** — chaves obrigatorias, severidades validas

### Comunicacao entre servicos

- Conexao ao PostgreSQL via connection string autenticada
- Variaveis sensiveis via env vars — nunca hardcoded
- `report-api` estritamente read-only

### Resiliencia

- **Falha do pgvector:** pipeline continua sem RAG
- **Falha do LLM de QA:** score conservador 0.7 se Fase 1 passou
- **Falha do webhook:** resultado ja no banco — consulta via `report-api`
- **Mensagens SQS duplicadas:** idempotencia por `sqs_message_id`
- **Graceful shutdown:** `SIGTERM`/`SIGINT` finalizam processamento atual

### Limitacoes conhecidas

- Nao ha autenticacao entre `ia-service` e `report-api` (assume rede Docker interna)
- `POST /analyze` nao requer autenticacao (uso interno/testes)
- LLM pode alucinar componentes dentro da tolerancia de 20%
- Dados dos diagramas sao enviados para APIs externas — avaliar termos de uso antes de processar diagramas sigilosos

---

## 23. Limitacoes e Decisoes de Projeto

### Por que nao OCR?

LLMs Vision modernos interpretam diagramas com compreensao semantica — entendem setas, caixas, relacionamentos e padroes. OCR extrairia apenas texto, perdendo toda a informacao visual estrutural.

### Por que a escolha do LLM e configuravel?

A abstracao (`LLM_MODEL` + `LLM_BASE_URL`) permite trocar modelo e provider sem alterar o codigo. Suporta OpenAI, Groq e qualquer provider compativel com a API OpenAI.

### Por que o RAG e non-blocking?

O pgvector e dependencia de enriquecimento, nao de funcionamento. Um diagrama pode ser analisado sem historico (cold start, banco vazio). Tornar o RAG bloqueante quebraria o pipeline em cenarios validos.

### Por que riscos sao gerados junto com o relatorio?

A classificacao de riscos e a geracao do relatorio compartilham o mesmo contexto (extracao + RAG). Unificar em uma chamada reduz latencia e custo, alem de garantir coerencia entre riscos e recomendacoes.

### Por que fine-tuning fora do Docker?

Treinar um modelo de 7B parametros requer GPU com >= 16GB de VRAM. O ambiente Docker do hackathon roda em CPU. `train.py` e executado externamente (Colab, RunPod) e o adapter e servido via HuggingFace Inference API.

### Por que o QA tem duas fases?

Verificacoes deterministicas (Fase 1) sao instantaneas e sem custo de API — capturam erros obvios. A Fase 2 com LLM avalia nuances qualitativas. Separar as fases evita chamar o LLM para relatorios claramente invalidos.

### Por que o webhook nao bloqueia o pipeline?

O resultado e sempre persistido antes do webhook. Se o endpoint do SOAT estiver indisponivel, o time pode consultar via `report-api`. O webhook e notificacao de conveniencia, nao o unico canal.

### Por que Celery + Redis alem do SQS?

SQS e o canal **externo** (SOAT -> IADT). Celery/Redis e o canal **interno** para UIs e integracoes que precisam acompanhar o progresso em tempo real (SSE) com reconexao resiliente via Redis list/pub-sub.

### Por que Input e Output Guardrails?

- **Input Guardrails** protegem contra prompt injection e dados maliciosos **antes** do LLM — defesa em profundidade na entrada
- **Output Guardrails** protegem contra vazamento de PII, conteudo proibido e schemas invalidos **na saida** — garantem que o sistema nunca entrega dados sensiveis ao usuario final

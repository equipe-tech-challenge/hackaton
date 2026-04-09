# Hackathon FIAP — Time IADT · Analise de Diagramas de Arquitetura com IA

Sistema de analise automatizada de diagramas de arquitetura de software. Recebe imagens ou PDFs de diagramas via fila SQS, processa com um pipeline de 5 etapas de IA (com guardrails de entrada e saida) e devolve um relatorio tecnico estruturado via webhook.

---

## Indice

1. [Visao Geral](#1-visao-geral)
2. [Arquitetura](#2-arquitetura)
3. [Arquitetura Hexagonal (Ports & Adapters)](#3-arquitetura-hexagonal-ports--adapters)
4. [Componentes do Sistema](#4-componentes-do-sistema)
5. [SQS Consumer — Arquitetura Event-Driven](#5-sqs-consumer--arquitetura-event-driven)
6. [Pipeline de IA — 5 Etapas + Guardrails](#6-pipeline-de-ia--5-etapas--guardrails)
7. [RAG com pgvector](#7-rag-com-pgvector)
8. [Guardrails e Controle de Qualidade](#8-guardrails-e-controle-de-qualidade)
9. [Estrategia de Convergencia do Pipeline](#9-estrategia-de-convergencia-do-pipeline)
10. [Webhook de Devolutiva](#10-webhook-de-devolutiva)
11. [Fine-Tuning](#11-fine-tuning)
12. [Schema do Banco de Dados](#12-schema-do-banco-de-dados)
13. [Configuracao de Ambiente](#13-configuracao-de-ambiente)
14. [Execucao](#14-execucao)
15. [API Reference](#15-api-reference)
16. [Streamlit — Interface de Validacao](#16-streamlit--interface-de-validacao)
17. [Testes](#17-testes)
18. [Seguranca](#18-seguranca)
19. [Limitacoes e Decisoes de Projeto](#19-limitacoes-e-decisoes-de-projeto)

---

## 1. Visao Geral

### O Problema

Empresas que operam sistemas distribuidos possuem dezenas de diagramas de arquitetura armazenados como imagens ou PDFs. Sua analise e feita **manualmente**, demanda muito tempo, depende de especialistas e **nao escala**.

### A Solucao

Este servico automatiza a analise usando um pipeline de IA que:

- **Le** o diagrama visualmente (sem OCR — usa LLM Vision multimodal)
- **Extrai** componentes, relacionamentos e padroes arquiteturais
- **Enriquece** a analise com contexto de diagramas similares ja processados (RAG)
- **Classifica** riscos em 6 categorias com severidade (integrado na geracao do relatorio)
- **Gera** um relatorio tecnico estruturado em JSON
- **Valida** o relatorio automaticamente com criterios de qualidade (determinisicos + LLM)
- **Devolve** o resultado via webhook para o sistema solicitante

### Responsabilidade do Time IADT

O time IADT e responsavel pelos 3 servicos deste repositorio:

| Servico | Porta | Responsabilidade |
|---|---|---|
| `ia-service` | 8000 | Pipeline de IA + SQS consumer + webhook |
| `report-api` | 8001 | API REST de consulta de relatorios (read-only) |
| `pgvector` | 5432 | PostgreSQL 16 com extensao vetorial para RAG |

O time **SOAT** e responsavel pelo API Gateway, servico de upload, publicacao na fila SQS e infraestrutura AWS.

---

## 2. Arquitetura

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
+-----------------------------------------------------------------------------+
|                              ia-service (:8000)                              |
|                                                                              |
|  +--------------+    +-------------------------------------------------+    |
|  | SQS Consumer |--->|         Pipeline de 5 Etapas + Guardrails       |    |
|  | (thread)     |    |                                                 |    |
|  +--------------+    |  Input Guardrails -> Ingestion -> Extraction ->  |    |
|                      |  RAG -> Report (com riscos) -> QA               |    |
|  +--------------+    +----------------------+--------------------------+    |
|  |  FastAPI     |                           | persiste                      |
|  |  /analyze    |                           v                               |
|  |  /health     |    +----------------------------------------------------+ |
|  |  /status     |    |          PostgreSQL + pgvector                      | |
|  +--------------+    |  analyses . extraction_results . reports            | |
|                      |  langchain_pg_embedding (vetores)                   | |
|  +--------------+    +----------------------------------------------------+ |
|  |   Webhook    |                                                            |
|  |   Sender     |--->  POST callback_url . retry 3x backoff                 |
|  +--------------+                                                            |
+-----------------------------------------------------------------------------+
                                          |
                                          v
                         +------------------------+
                         |   report-api (:8001)   |
                         |  GET /reports/{id}     |
                         |  GET /reports          |
                         +------------------------+
```

### Diagrama de Componentes

![Diagrama de Arquitetura](docs/architecture.png)

---

## 3. Arquitetura Hexagonal (Ports & Adapters)

O `ia-service` adota **Arquitetura Hexagonal** (Ports & Adapters) como padrao arquitetural. Dentro da camada de dominio, aplica **modelagem tatica DDD** (agregados, value objects, domain events) para expressar as regras de negocio.

### 3.1 Camadas da Arquitetura

```
                    +------------------------------------------------------+
                    |              INFRASTRUCTURE (Adapters)                |
                    |                                                      |
                    |  OpenAIVisionAdapter    SQLAlchemy*Repository        |
                    |  OpenAITextAdapter      PGVectorAdapter              |
                    |                                                      |
                    |    +----------------------------------------------+  |
                    |    |          APPLICATION (Use Cases + Ports)      |  |
                    |    |                                              |  |
                    |    |  AnalyzeDiagramUseCase                       |  |
                    |    |  RetrieveReportUseCase                       |  |
                    |    |                                              |  |
                    |    |  Ports: IVisionLLM . ITextLLM               |  |
                    |    |         IVectorStore                        |  |
                    |    |         IAnalysisRepository                 |  |
                    |    |         IReportRepository                   |  |
                    |    |                                              |  |
                    |    |    +----------------------------------+      |  |
                    |    |    |     DOMAIN (Modelo Tatico)       |      |  |
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

### 3.2 Portas (Interfaces — Camada Application)

As portas definem *o que* a aplicacao precisa, sem saber *como* sera implementado.

**Arquivo:** `ia-service/app/application/ports/llm_port.py`

```python
class IVisionLLM(ABC):
    def extract_components(self, diagram_file: DiagramFile) -> ExtractionResult: ...

class ITextLLM(ABC):
    def generate_report(self, extraction, rag_context) -> TechnicalReport: ...
    def evaluate_quality(self, extraction, report) -> QAScore: ...
```

**Arquivo:** `ia-service/app/application/ports/vector_store_port.py`

```python
class IVectorStore(ABC):
    def index(self, analysis_id, extraction) -> None: ...
    def retrieve_context(self, extraction, exclude_analysis_id) -> RagContext: ...
```

### 3.3 Adaptadores (Implementacoes — Camada Infrastructure)

| Porta | Adaptador | Tecnologia |
|---|---|---|
| `IVisionLLM` | `OpenAIVisionAdapter` | OpenAI SDK (compativel com Groq via `base_url`) |
| `ITextLLM` | `OpenAITextAdapter` | LangChain chains + OpenAI/Groq |
| `IVectorStore` | `PGVectorAdapter` | LangChain PGVector + `text-embedding-3-small` (ou HuggingFace local como fallback) |
| `IAnalysisRepository` | `SQLAlchemyAnalysisRepository` | SQLAlchemy + PostgreSQL |
| `IReportRepository` | `SQLAlchemyReportRepository` | SQLAlchemy + PostgreSQL |

**Trocar de provider de LLM** (ex: OpenAI -> Anthropic) significa criar um novo adapter que implemente `IVisionLLM` / `ITextLLM`. O dominio e os use cases permanecem intactos.

### 3.4 Composition Root (Injecao de Dependencias)

**Arquivo:** `ia-service/app/infrastructure/composition_root.py`

Ponto unico de montagem do grafo de dependencias. Nenhuma outra camada conhece as implementacoes concretas.

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

### 3.5 Modelagem Tatica DDD (Camada Domain)

Dentro da camada de dominio, o problema e modelado com padroes taticos DDD:

#### Bounded Contexts

| Contexto | Responsabilidade | Agregado |
|---|---|---|
| **DiagramAnalysis** | Ciclo de vida da analise (recebimento -> processamento -> conclusao/erro) | `AnalysisAggregate` |
| **ReportGeneration** | Geracao, validacao e persistencia do relatorio tecnico | `ReportAggregate` |

#### AnalysisAggregate — Maquina de Estados

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

#### Value Objects

| Value Object | Contexto | Descricao |
|---|---|---|
| `DiagramFile` | DiagramAnalysis | Arquivo validado (tipo, tamanho, base64) — imutavel |
| `Component`, `Relationship`, `ArchitecturalPattern` | DiagramAnalysis | Elementos extraidos do diagrama |
| `AnalysisId`, `ReportId` | Shared | UUIDs tipados |
| `RiskItem` | ReportGeneration | Risco categorizado com severidade e mitigacao |
| `Recommendation` | ReportGeneration | Recomendacao com flag `[RAG]` de origem historica |
| `QAScore` | ReportGeneration | Score de qualidade + issues encontradas |
| `RagContext` | ReportGeneration | Contexto historico recuperado do pgvector |

#### Domain Events

O agregado emite eventos a cada transicao de estado (padrao outbox):

```python
aggregate.pull_events()  # Retorna e limpa eventos pendentes
```

| Evento | Quando emitido |
|---|---|
| `DiagramReceivedEvent` | Analise criada |
| `DiagramIngestedEvent` | Arquivo validado e convertido para base64 |
| `ComponentsExtractedEvent` | LLM Vision extraiu componentes |
| `AnalysisCompletedEvent` | Pipeline finalizou com sucesso |
| `AnalysisFailedEvent` | Qualquer etapa falhou |
| `ReportGeneratedEvent` | Relatorio tecnico gerado |
| `QAValidationCompletedEvent` | QA executado (aprovado ou rejeitado) |

#### Domain Services

| Servico | Arquivo | Responsabilidade |
|---|---|---|
| `GuardrailService` | `domain/report_generation/guardrail.py` | Validacao do relatorio contra dados de extracao (anti-alucinacao) |
| `InputGuardrailService` | `domain/shared/input_guardrail.py` | Deteccao de prompt injection, sanitizacao de inputs, validacao de schema |
| `OutputGuardrailService` | `domain/shared/output_guardrail.py` | Validacao de schema de saida, deteccao de PII, filtro de conteudo proibido |

---

## 4. Componentes do Sistema

### 4.1 ia-service

Servico principal. Responsavel pelo pipeline de IA, consumer SQS e webhook.

**Estrutura de pastas:**

```
ia-service/
+-- app/
    +-- main.py                              # FastAPI + startup do SQS consumer
    +-- __init__.py
    |
    +-- domain/                              # Camada de Dominio (DDD)
    |   +-- diagram_analysis/                # Bounded Context: DiagramAnalysis
    |   |   +-- analysis.py                  # AnalysisAggregate (maquina de estados)
    |   |   +-- analysis_status.py           # Enum: RECEIVED, PROCESSING, ANALYZED, ERROR
    |   |   +-- component.py                 # Component, Relationship, ArchitecturalPattern
    |   |   +-- diagram_file.py              # DiagramFile (value object imutavel)
    |   |   +-- extraction_result.py         # ExtractionResult (ground truth do pipeline)
    |   |   +-- file_type.py                 # FileType enum
    |   |   +-- repository.py                # IAnalysisRepository (interface)
    |   |   +-- events/                      # Domain Events
    |   |       +-- diagram_received_event.py
    |   |       +-- diagram_ingested_event.py
    |   |       +-- components_extracted_event.py
    |   |       +-- analysis_completed_event.py
    |   |       +-- analysis_failed_event.py
    |   |
    |   +-- report_generation/               # Bounded Context: ReportGeneration
    |   |   +-- report.py                    # ReportAggregate
    |   |   +-- technical_report.py          # TechnicalReport (entidade)
    |   |   +-- risk.py                      # RiskItem, RiskCategory, Severity
    |   |   +-- recommendation.py            # Recommendation (com flag RAG)
    |   |   +-- qa_score.py                  # QAScore (MIN_SCORE = 0.6)
    |   |   +-- rag_context.py               # RagContext
    |   |   +-- guardrail.py                 # GuardrailService (anti-alucinacao)
    |   |   +-- repository.py                # IReportRepository (interface)
    |   |   +-- events/
    |   |       +-- report_generated_event.py
    |   |       +-- qa_validation_completed_event.py
    |   |
    |   +-- shared/                          # Value Objects compartilhados
    |       +-- analysis_id.py               # AnalysisId (UUID tipado)
    |       +-- report_id.py                 # ReportId (UUID tipado)
    |       +-- input_guardrail.py           # InputGuardrailService
    |       +-- output_guardrail.py          # OutputGuardrailService
    |       +-- events/
    |           +-- domain_event.py          # DomainEvent (base)
    |
    +-- application/                         # Camada de Aplicacao (Use Cases + Ports)
    |   +-- ports/
    |   |   +-- llm_port.py                  # IVisionLLM, ITextLLM
    |   |   +-- vector_store_port.py         # IVectorStore
    |   +-- use_cases/
    |       +-- analyze_diagram.py           # AnalyzeDiagramUseCase (orquestracao E2E)
    |       +-- retrieve_report.py           # RetrieveReportUseCase
    |
    +-- infrastructure/                      # Camada de Infraestrutura (Adapters)
    |   +-- composition_root.py              # Injecao de dependencias
    |   +-- config/
    |   |   +-- settings.py                  # Settings via pydantic-settings
    |   +-- llm/
    |   |   +-- openai_adapter.py            # OpenAIVisionAdapter, OpenAITextAdapter
    |   |   +-- finetuning/                  # Modulo de fine-tuning (QLoRA)
    |   |       +-- config.py
    |   |       +-- data_generator.py
    |   |       +-- data_formatter.py
    |   |       +-- train.py
    |   |       +-- inference.py
    |   +-- vector_store/
    |   |   +-- pgvector_adapter.py          # PGVectorAdapter
    |   +-- persistence/
    |   |   +-- database.py                  # SQLAlchemy engine + session factory
    |   |   +-- sqlalchemy_analysis_repository.py
    |   |   +-- sqlalchemy_report_repository.py
    |   +-- messaging/
    |   |   +-- sqs_consumer.py              # Consumer SQS com graceful shutdown
    |   +-- http/
    |       +-- webhook_sender.py            # Envio de resultado via HTTP POST
    |
    +-- pipeline/
    |   +-- analysis_orchestrator.py         # Delegacao ao AnalyzeDiagramUseCase
    |   +-- diagram_ingestion_step.py
    |   +-- component_extraction_step.py
    |   +-- context_enrichment_step.py
    |   +-- risk_assessment_step.py
    |   +-- report_generation_step.py
    |   +-- quality_validation_step.py
    |
    +-- shared/
    |   +-- exceptions.py                    # PipelineError, IngestionError, GuardrailError...
    |   +-- logging.py                       # Structured logging (JSON via structlog)
    |
    +-- static/
        +-- index.html                       # Front-end de teste para upload direto
```

### 4.2 report-api

API read-only para consulta de relatorios gerados. Usada pelo API Gateway do time SOAT.

**Endpoints:**

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/health` | Healthcheck — verifica conexao com DB |
| `GET` | `/reports/{analysis_id}` | Relatorio completo de uma analise |
| `GET` | `/reports?limit=20&offset=0` | Lista paginada de analises |

### 4.3 pgvector

PostgreSQL 16 com extensao `pgvector`. Armazena:
- Estado de cada analise (`analyses`)
- Cache de extracao para evitar reprocessamento (`extraction_results`)
- Relatorios gerados com metricas de QA (`reports`)
- Embeddings vetoriais para o RAG (`langchain_pg_embedding`)

### 4.4 streamlit-app

Interface visual de validacao do pipeline na porta 8501. Consome o endpoint SSE `POST /analyze/stream`.

---

## 5. SQS Consumer — Arquitetura Event-Driven

**Arquivo:** `ia-service/app/infrastructure/messaging/sqs_consumer.py`

O `ia-service` opera como **consumer de uma fila SQS** publicada pelo time SOAT. O consumer roda como **thread daemon** iniciada no startup do FastAPI, sem bloquear o event loop HTTP.

### Fluxo de Processamento

```
SQS Queue
   |
   v  long polling (20s)
+--------------------------------------------------------------+
|  Consumer Thread                                             |
|                                                              |
|  receive_message(MaxMessages=5, VisibilityTimeout=300s)      |
|       |                                                      |
|       +-- Idempotencia: sqs_message_id ja existe? -> skip    |
|       |                                                      |
|       +-- Poison pill: ApproximateReceiveCount > 3? -> warning|
|       |                                                      |
|       +-- Download S3: retry 3x (backoff exponencial)        |
|       |                                                      |
|       +-- run_pipeline(file_bytes, file_name)                |
|       |                                                      |
|       +-- delete_message() <- somente apos sucesso           |
|       |                                                      |
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

### Resiliencia do Consumer

| Mecanismo | Implementacao |
|---|---|
| **Long polling** | `WaitTimeSeconds=20` — reduz chamadas vazias a API SQS |
| **Idempotencia** | `sqs_message_id` verificado no banco — mensagens duplicadas sao ignoradas |
| **Graceful shutdown** | Handlers de `SIGTERM`/`SIGINT` — finaliza a mensagem atual antes de parar |
| **Poison pill detection** | Loga warning quando `ApproximateReceiveCount > 3` |
| **Download com retry** | `tenacity`: 3 tentativas, backoff exponencial (2s -> 10s) |
| **Visibility timeout** | 300s (5 min) — mensagem nao processada volta a fila automaticamente |
| **Webhook non-blocking** | Falha no webhook nao impede delecao da mensagem — resultado ja esta no banco |

---

## 6. Pipeline de IA — 5 Etapas + Guardrails

O pipeline e orquestrado pelo `AnalyzeDiagramUseCase` (arquivo `application/use_cases/analyze_diagram.py`). O `analysis_orchestrator.py` apenas delega para o use case, mantendo compatibilidade com os pontos de entrada (`main.py`, `sqs_consumer.py`).

```
[arquivo binario]
      |
      v
(0) Input Guardrails     -> sanitiza filename, detecta prompt injection
      |
      v
(1) Ingestion             -> valida tipo/tamanho, converte para base64
      |
      v
(2) Extraction            -> LLM Vision -> componentes, relacionamentos, padroes
      |
      v
(2.5) Input Guardrail     -> valida schema da extracao, detecta injection nos dados
      |
      v
(3) RAG                   -> indexa no pgvector, busca similares (non-blocking)
      |
      v
(4) Report + Riscos       -> LLM + Output Guardrails -> relatorio JSON com riscos
      |
      v
(5) QA                    -> 2 fases de validacao -> score de qualidade
      |
      v
[PostgreSQL] + [Webhook]
```

### Etapa 0 — Input Guardrails

**Arquivo:** `domain/shared/input_guardrail.py`

Executada antes de qualquer processamento. Protege o pipeline contra inputs maliciosos.

**O que faz:**
- Sanitiza o nome do arquivo (remove path traversal, caracteres perigosos)
- Detecta padroes de prompt injection via regex (override de instrucoes, role-play, exfiltracao, delimitadores de prompt)
- Limita tamanho do filename a 255 caracteres

**Falha:** Lanca `GuardrailError` — **bloqueia o pipeline**.

---

### Etapa 1 — Ingestion

Responsavel por validar o arquivo recebido e prepara-lo para o LLM Vision.

**O que faz:**
- Valida o tamanho: rejeita arquivos > 20MB
- Detecta o MIME type pelo nome do arquivo
- Verifica se o tipo e suportado: `png`, `jpg`, `jpeg`, `gif`, `webp`, `pdf`
- Converte o conteudo binario para Base64 via `DiagramFile.create()`

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

**Falha:** Lanca `IngestionError` — **bloqueia o pipeline**.

---

### Etapa 2 — Extraction (LLM Vision)

**Arquivo:** `infrastructure/llm/openai_adapter.py` (`OpenAIVisionAdapter`)

Usa um **LLM com capacidade Vision** para interpretar o diagrama visualmente e extrair informacoes estruturadas.

> **Nao usa OCR.** O arquivo (imagem ou PDF) e enviado diretamente para o LLM como conteudo multimodal. O modelo interpreta o diagrama com compreensao semantica — le setas, caixas, relacionamentos e padroes arquiteturais.

**Como funciona:**
1. Monta um bloco multimodal com o arquivo em Base64 no formato OpenAI Vision: `{type: "image_url", image_url: {url: "data:{media_type};base64,..."}}`
2. Envia para o LLM Vision com prompt de extracao estruturada
3. Ativa `response_format: json_object` quando disponivel (OpenAI); faz fallback de markdown fences para Groq/LLaMA
4. Parseia o JSON retornado e valida campos obrigatorios (`components`, `relationships`, `patterns`, `raw_description`)
5. Rejeita se nenhum componente foi identificado

Apos a extracao, o `InputGuardrailService` valida o schema dos dados extraidos (tipos, limites de tamanho, prompt injection nos componentes e descricao).

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

**Falha:** Lanca `ExtractionError` — **bloqueia o pipeline**.

---

### Etapa 3 — RAG (Retrieval-Augmented Generation)

**Arquivo:** `infrastructure/vector_store/pgvector_adapter.py` (`PGVectorAdapter`)

Implementa **RAG** usando LangChain + pgvector. Enriquece a analise com contexto de diagramas similares ja processados.

> **Non-blocking:** Se o pgvector estiver indisponivel, nao houver analises no historico, ou ocorrer qualquer erro, retorna `RagContext.empty()` e o pipeline continua normalmente.

**Como funciona:**

Fase de Indexacao (toda nova analise):
```
ExtractionResult
      |
      v
LangChain Document (page_content = raw_description + components + patterns + relationships)
      |
      v
Embeddings (text-embedding-3-small ou HuggingFace all-MiniLM-L6-v2 como fallback)
      |
      v
PGVector.add_documents() -> langchain_pg_embedding
```

Fase de Recuperacao:
```
query = raw_description + components + patterns
      |
      v
Embeddings -> query vector
      |
      v
PGVector.similarity_search_with_score(k=3, filter={"has_report": True})
      |
      +-- distancia coseno < 0.3 -> similar (>70%) -> inclui no contexto
      +-- distancia coseno >= 0.3 -> descarta
      |
      v
LLM chain -> rag_enrichment (recomendacoes baseadas no historico)
```

**Saida:** `RagContext` com `has_context`, `enrichment_text` e `similar_analyses_count`.

---

### Etapa 4 — Report + Riscos

**Arquivo:** `infrastructure/llm/openai_adapter.py` (`OpenAITextAdapter.generate_report`)

Gera o relatorio tecnico estruturado **incluindo a analise de riscos** em uma unica chamada ao LLM. Os riscos sao classificados em 6 categorias:

| Categoria | O que avalia |
|---|---|
| **SPOF** | Pontos unicos de falha sem redundancia |
| **Seguranca** | Ausencia de autenticacao, dados expostos, endpoints sem protecao |
| **Escalabilidade** | Gargalos, ausencia de cache, filas sem DLQ |
| **Acoplamento** | Dependencias sincronas excessivas, falta de interfaces |
| **Observabilidade** | Ausencia de logs, metricas, tracing |
| **Resiliencia** | Sem circuit breaker, retry, fallback |

O contexto RAG (quando disponivel) e incluido no prompt para identificar padroes de risco recorrentes. Recomendacoes influenciadas pelo historico sao marcadas com `[RAG]`.

**Apos a geracao:**
1. `OutputGuardrailService.validate_output()` valida o schema, detecta conteudo proibido e redacta PII
2. `GuardrailService.validate()` verifica grounding (anti-alucinacao), completude e tamanho do sumario

**Severidade (`risk_severity_summary`) e recalculada server-side** pelo `TechnicalReport.risk_severity_summary` — nao confia no LLM para somar.

**Backend `langchain` (padrao):**
- Usa LangChain `ChatPromptTemplate | ChatOpenAI | JsonOutputParser`
- Modelo configuravel via `LLM_MODEL` (padrao: `gpt-4o`)
- Compativel com Groq e outros providers via `LLM_BASE_URL`

**Backend `finetuned_api` / `finetuned_local`:**
- Usa LLM fine-tunado com QLoRA (ver secao Fine-Tuning)
- Mesma interface de entrada/saida

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

**Falha:** Lanca `ReportGenerationError` — **bloqueia o pipeline**.

---

### Etapa 5 — QA (Quality Assurance)

**Arquivo:** `application/use_cases/analyze_diagram.py` (metodos `_evaluate_quality` e `_deterministic_qa_checks`)

Valida o relatorio gerado em **duas fases** antes de persistir.

**Fase 1 — Verificacoes Deterministicas (sem LLM):**
- `components_identified` nao vazio
- `architectural_risks` nao vazio
- `recommendations` nao vazio
- `executive_summary` com no minimo 100 caracteres
- Grounding: ao menos 80% dos componentes do relatorio existem na extracao original

Se a Fase 1 falhar, o relatorio e rejeitado imediatamente sem chamar o LLM.

**Fase 2 — Avaliacao com LLM (`json_object` mode):**

O LLM avalia 4 criterios com pesos:
- **Completude (30%):** todos os campos obrigatorios preenchidos
- **Consistencia (40%):** componentes e riscos batem com a extracao original
- **Coerencia (20%):** recomendacoes vinculadas a riscos identificados
- **Qualidade (10%):** linguagem tecnica, sem generalidades

O output usa `response_format: {"type": "json_object"}` para garantir retorno em JSON valido.

**Score minimo:** `0.6` — relatorios abaixo disso sao rejeitados (`is_valid: false`).

> **Resiliencia:** se o LLM de QA estiver indisponivel, assume `is_valid: true` com score conservador `0.7`, desde que a Fase 1 tenha passado.

**Saida:**
```json
{
  "is_valid": true,
  "completeness_score": 0.92,
  "issues_found": [],
  "quality_notes": "Relatorio completo, consistente e bem fundamentado.",
  "status": "analisado"
}
```

---

## 7. RAG com pgvector

O sistema aprende com analises anteriores. Quanto mais diagramas forem processados, mais rico fica o contexto historico fornecido ao pipeline.

### Como o RAG melhora o relatorio

- A etapa de **Report** usa o contexto RAG para identificar padroes de risco recorrentes e gerar recomendacoes embasadas
- Recomendacoes baseadas em historico sao marcadas com `[RAG]`
- O relatorio final informa `rag_used: true/false` para rastreabilidade

### Embeddings

O sistema usa **OpenAI `text-embedding-3-small`** por padrao. Quando `LLM_BASE_URL` esta configurado (ex: Groq), faz fallback automatico para **HuggingFace `all-MiniLM-L6-v2`** localmente.

### Indice HNSW

```sql
-- Deve ser criado manualmente apos o LangChain inicializar a tabela:
CREATE INDEX idx_langchain_hnsw
  ON langchain_pg_embedding
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

O indice HNSW (Hierarchical Navigable Small World) garante buscas por similaridade com latencia inferior a 50ms.

### Threshold de similaridade

```python
# score < 0.3 (distancia coseno) = similaridade > 70%
relevant = [(doc, score) for doc, score in similar_docs if score < 0.3]
```

Apenas analises com similaridade alta (> 70%) sao incluidas no contexto.

---

## 8. Guardrails e Controle de Qualidade

O sistema implementa multiplas camadas de protecao:

### Input Guardrails (`InputGuardrailService`)

| Guardrail | Quando | Implementacao |
|---|---|---|
| **Prompt injection** | Antes do pipeline e apos extracao | Regex para override de instrucoes, role-play, delimitadores de prompt |
| **Sanitizacao de filename** | Antes do pipeline | Remove path traversal, caracteres perigosos, limita tamanho |
| **Sanitizacao de texto** | Campos textuais | Remove delimitadores de prompt e caracteres de controle Unicode |
| **Validacao de schema** | Apos extracao | Verifica chaves obrigatorias, tipos, limites (max 200 componentes, 500 relacionamentos) |

### Report Guardrails (`GuardrailService`)

| Guardrail | Onde | Implementacao |
|---|---|---|
| **Tipo e tamanho de arquivo** | Ingestion | Bloqueia arquivos > 20MB e tipos nao suportados |
| **Componentes nao vazios** | Report | `components_identified` deve conter ao menos 1 item |
| **Grounding check (20%)** | Report | Componentes inventados > 20% dos extraidos = `ReportGenerationError` |
| **Completude minima** | Report | `recommendations` nao vazio, `executive_summary` > 100 chars |

### Output Guardrails (`OutputGuardrailService`)

| Guardrail | Onde | Implementacao |
|---|---|---|
| **Validacao de schema** | Apos geracao do relatorio | Verifica chaves obrigatorias, tipos, severidades validas (ALTO/MEDIO/BAIXO) |
| **Conteudo proibido** | Apos geracao do relatorio | Filtro para conteudo discriminatorio, instrucoes ilegais, engenharia social |
| **Deteccao de PII** | Saida final | Detecta CPF, CNPJ, email, telefone, IP, API keys, cartoes e substitui por `[REDACTED]` |
| **Redacao recursiva** | Resposta ao usuario | `redact_dict()` aplica redacao em todos os campos string do resultado |

### QA Guardrails

| Guardrail | Onde | Implementacao |
|---|---|---|
| **Grounding duplo (80%)** | QA Fase 1 | >= 80% dos componentes do relatorio devem existir na extracao |
| **JSON mode** | QA Fase 2 | `response_format: json_object` obriga o LLM a retornar JSON valido |
| **Score minimo** | QA Fase 2 | Score < 0.6 = relatorio rejeitado (`is_valid: false`) |
| **Transparencia RAG** | Report | Tag `[RAG]` em recomendacoes de origem historica |

---

## 9. Estrategia de Convergencia do Pipeline

O pipeline precisa convergir de forma deterministica para um resultado coerente, mesmo quando um LLM externo pode alucinar ou falhar.

### Ground Truth — ExtractionResult como Ancora

O `ExtractionResult` (saida da Etapa 2) e a **fonte de verdade** para todo o pipeline. Todas as etapas subsequentes recebem a extracao original e sao validadas contra ela:

```
ExtractionResult (ground truth)
     |
     +-->  RAG:     busca similares no historico baseado na extracao
     +-->  Report:  gera relatorio com riscos e valida grounding contra extracao
     +-->  QA:      valida 80% overlap entre relatorio e extracao
```

### Mecanismos de Convergencia

| Mecanismo | Onde | Como garante convergencia |
|---|---|---|
| **Pipeline sequencial** | Use Case | Cada etapa recebe output da anterior — sem execucao paralela, sem race conditions |
| **Input Guardrails** | Pre-pipeline + pos-extracao | Bloqueia prompt injection e dados malformados antes de chegarem ao LLM |
| **Output Guardrails** | Pos-report | Valida schema, filtra conteudo proibido e redacta PII antes da entrega |
| **Grounding check (20%)** | GuardrailService | Max 20% dos componentes do relatorio podem ser inventados |
| **Grounding duplo (80%)** | QA Fase 1 | >= 80% dos componentes do relatorio devem existir na extracao original |
| **Recalculo server-side** | TechnicalReport | `risk_severity_summary` e recalculado no servidor — nao confia no LLM para somar |
| **RAG non-blocking** | Use Case | Falha no RAG retorna `RagContext.empty()` — pipeline continua sem enriquecimento |
| **QA fallback** | Use Case | Se LLM de QA indisponivel, assume score conservador 0.7 (desde que Fase 1 tenha passado) |
| **Score minimo** | QA | Score < 0.6 = relatorio rejeitado (`is_valid: false`) |

### Diagrama de Convergencia

```
[Input Guardrails]  ->  SANITIZA filename, detecta injection
                    |   falha -> GuardrailError (bloqueia)
                    v
[Ingestion]  ->  VALIDA formato/tamanho
                    |   falha -> IngestionError (bloqueia)
                    v
[Extraction] ->  EXTRAI ground truth
                    |   falha -> ExtractionError (bloqueia)
                    v
[Input Guardrail]  ->  VALIDA schema da extracao
                    |   falha -> GuardrailError (bloqueia)
                    v
[RAG]        ->  ENRIQUECE com historico
                    |   falha -> RagContext.empty() (continua ok)
                    v
[Report]     ->  GERA relatorio + riscos
                    |   Output Guardrail: schema, PII, conteudo proibido
                    |   GuardrailService: grounding <= 20%
                    |   falha -> ReportGenerationError (bloqueia)
                    v
[QA Fase 1]  ->  VERIFICA: campos, completude, grounding >= 80%
                    |   falha -> is_valid=false (rejeita imediatamente)
                    v
[QA Fase 2]  ->  AVALIA: completude 30%, consistencia 40%, coerencia 20%, qualidade 10%
                    |   falha LLM -> score=0.7 (fallback conservador ok)
                    |   score < 0.6 -> rejeitado
                    v
[Persistencia + Webhook]
```

**Resultado:** o pipeline *sempre* converge para um dos dois estados: `analisado` (com relatorio valido) ou `erro` (com mensagem descritiva). Nunca fica em estado intermediario indefinidamente.

---

## 10. Webhook de Devolutiva

**Arquivo:** `ia-service/app/infrastructure/http/webhook_sender.py`

Apos o pipeline concluir (sucesso ou erro), o servico envia o resultado via HTTP POST para o `callback_url` informado na mensagem SQS.

### Politica de retry

```
Tentativa 1 -> falha -> aguarda 2s
Tentativa 2 -> falha -> aguarda 4s
Tentativa 3 -> falha -> aguarda 8s (max)
               falha -> loga erro -> pipeline continua
```

- **Retenta em:** timeout, erro de conexao, respostas 5xx
- **Nao retenta em:** respostas 4xx (erro do cliente)
- **Falha total nao bloqueia:** resultado ja esta no banco de dados

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

## 11. Fine-Tuning

O modulo de fine-tuning treina um LLM open-source com QLoRA para gerar relatorios no formato exato exigido pelo pipeline — como alternativa ao LLM principal.

**Arquivo base:** `ia-service/app/infrastructure/llm/finetuning/`

### Visao geral

```
[LLM professor]
      |  gera 50-75 pares sinteticos
      v
data_generator.py  ->  raw_pairs.jsonl
      |
      v
data_formatter.py  ->  train.jsonl + val.jsonl (formato chat)
      |
      v
train.py           ->  LoRA adapter (roda em GPU: Colab, RunPod)
      |
      v
HuggingFace Hub    ->  adapter publicado
      |
      v
inference.py       ->  HuggingFaceAPIClient <- report generation
```

### Passo a passo

**1. Instalar dependencias de treino (apenas em maquina com GPU):**

```bash
pip install -r ia-service/finetuning-requirements.txt
```

**2. Gerar dados sinteticos de treino:**

```bash
cd ia-service
python -m app.infrastructure.llm.finetuning.data_generator \
  --api-key $ANTHROPIC_API_KEY \
  --samples 50 \
  --output ./data/raw_pairs.jsonl
```

**3. Formatar para fine-tuning:**

```bash
python -m app.infrastructure.llm.finetuning.data_formatter \
  --input ./data/raw_pairs.jsonl \
  --output ./data \
  --split 0.9
```

**4. Treinar (em GPU — ex: Google Colab A100):**

```bash
python -m app.infrastructure.llm.finetuning.train \
  --epochs 3 \
  --output-dir ./output/report-lora-adapter \
  --push-to-hub \
  --hub-model-id "seu-usuario/report-lora"
```

**5. Usar o modelo fine-tunado no pipeline:**

```bash
# .env
REPORT_MODEL_BACKEND=finetuned_api
HUGGINGFACE_API_TOKEN=hf_...
HUGGINGFACE_ENDPOINT_URL=https://api-inference.huggingface.co/models/seu-usuario/report-lora
```

### Backends disponiveis

| `REPORT_MODEL_BACKEND` | Descricao | Quando usar |
|---|---|---|
| `langchain` | LangChain + LLM via `LLM_MODEL` | Padrao — nao requer GPU |
| `finetuned_api` | LLM fine-tunado via HuggingFace Inference API | Com modelo treinado hospedado |
| `finetuned_local` | Adapter carregado localmente | Desenvolvimento com GPU local |

> Os guardrails sao aplicados **igualmente em todos os backends**.

---

## 12. Schema do Banco de Dados

```sql
-- Ciclo de vida de cada analise
CREATE TABLE analyses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status          VARCHAR(20) NOT NULL DEFAULT 'recebido'
                        CHECK (status IN ('recebido', 'em_processamento', 'analisado', 'erro')),
    file_name       VARCHAR(255) NOT NULL,
    file_type       VARCHAR(10) NOT NULL,
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
-- langchain_pg_embedding: embedding vector, document TEXT, cmetadata JSONB
```

---

## 13. Configuracao de Ambiente

Copie o arquivo de exemplo e preencha as variaveis:

```bash
cp ia-service/.env.example ia-service/.env
```

### Variaveis obrigatorias

| Variavel | Descricao |
|---|---|
| `OPENAI_API_KEY` | Chave OpenAI (Vision, texto e embeddings `text-embedding-3-small`) |

### Variaveis opcionais

| Variavel | Padrao | Descricao |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Chave Anthropic (mantida por compatibilidade) |
| `POSTGRES_CONNECTION_STRING` | `postgresql+psycopg://hackathon:hackathon123@localhost:5432/hackathon_db` | Connection string para LangChain/pgvector |
| `SQS_QUEUE_URL` | `""` | URL da fila SQS (se vazio, consumer nao inicia) |
| `REPORT_MODEL_BACKEND` | `langchain` | Backend do report agent (`langchain`, `finetuned_api`, `finetuned_local`) |
| `LLM_MODEL` | `gpt-4o` | Modelo LLM para texto e Vision (quando `LLM_VISION_MODEL` vazio) |
| `LLM_BASE_URL` | `""` | URL base do LLM (vazio = OpenAI; preenchido = Groq/outro provider) |
| `LLM_VISION_MODEL` | `""` | Modelo especifico para Vision (se vazio, usa `LLM_MODEL`) |
| `HUGGINGFACE_API_TOKEN` | `""` | Token HuggingFace (para `finetuned_api`) |
| `HUGGINGFACE_ENDPOINT_URL` | `""` | URL do endpoint HuggingFace |
| `LOCAL_MODEL_PATH` | `""` | Caminho do adapter local (para `finetuned_local`) |
| `BASE_MODEL_ID` | `""` | ID do modelo base para fine-tuning local |
| `AWS_ACCESS_KEY_ID` | `""` | Credenciais AWS (se nao usar IAM Role) |
| `AWS_SECRET_ACCESS_KEY` | `""` | Credenciais AWS |
| `AWS_SESSION_TOKEN` | `""` | Token de sessao AWS (STS) |
| `AWS_REGION` | `us-east-1` | Regiao AWS |
| `LOG_LEVEL` | `INFO` | Nivel de log (`DEBUG`, `INFO`, `WARNING`) |

---

## 14. Execucao

### Subir todos os servicos

```bash
cp ia-service/.env.example .env   # preencher OPENAI_API_KEY
docker-compose up --build
```

Isso sobe 4 containers: `pgvector` (5432), `ia-service` (8000), `report-api` (8001), `streamlit-app` (8501).

### Verificar saude dos servicos

```bash
curl http://localhost:8000/health  # ia-service
curl http://localhost:8001/health  # report-api
```

### Testar o pipeline diretamente (sem SQS)

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@/caminho/para/diagrama.png"
```

### Consultar relatorio gerado

```bash
# Por ID de analise
curl http://localhost:8001/reports/{analysis_id}

# Listar todos
curl "http://localhost:8001/reports?limit=10&offset=0"

# Checar status de processamento
curl http://localhost:8000/analyses/{analysis_id}/status
```

---

## 15. API Reference

### ia-service (:8000)

#### `GET /`

Serve o front-end HTML de teste para upload direto.

#### `GET /health`

```json
{"status": "healthy", "db": "connected"}
```

#### `POST /analyze`

Upload direto de arquivo. Usado para testes — em producao o fluxo principal e via SQS.

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

**Response 400** (tipo nao suportado):
```json
{"detail": "Tipo de arquivo nao suportado: .bmp. Aceitos: png, jpg, jpeg, gif, webp, pdf"}
```

**Response 422** (pipeline falhou):
```json
{"detail": "Arquivo excede o limite de 20MB."}
```

#### `POST /analyze/stream`

Endpoint SSE — executa o pipeline e emite eventos a cada etapa via `StreamingResponse`.

```
data: {"step": "ingestion", "status": "running", "data": {}}

data: {"step": "ingestion", "status": "done", "data": {"file_type": "png", "file_size_kb": 512, "elapsed": 0.1}}

data: {"step": "extraction", "status": "running", "data": {}}

data: {"step": "extraction", "status": "done", "data": {"components_count": 8, "elapsed": 3.2}}
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

**Status possiveis:** `recebido` -> `em_processamento` -> `analisado` | `erro`

### report-api (:8001)

#### `GET /health`

```json
{"status": "healthy", "db": "connected"}
```

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

**Response 404:**
```json
{"detail": "Analise nao encontrada"}
```

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

## 16. Streamlit — Interface de Validacao

**Arquivo:** `streamlit-app/app.py`

O Streamlit serve como **interface visual de validacao** do pipeline, permitindo testar a analise de diagramas sem depender da integracao SQS/SOAT. Opera de forma independente do consumer — consome o endpoint HTTP `POST /analyze/stream` diretamente.

### Fluxo de Interacao

```
+----------------------------------------------------------+
|  Streamlit App (:8501)                                   |
|                                                          |
|  1. Usuario faz upload (drag & drop / file picker)       |
|       |                                                  |
|  2. Preview do diagrama (se imagem)                      |
|       |                                                  |
|  3. Clica "Analisar Diagrama"                            |
|       |                                                  |
|  4. POST /analyze/stream --> ia-service (:8000)          |
|       |                                                  |
|  5. Consome SSE em tempo real:                           |
|       |  Ingestion (0.1s) — PNG, 512 KB                  |
|       |  Extraction (3.2s) — 8 componentes, 5 relacoes   |
|       |  RAG (0.5s) — 2 analises similares               |
|       |  Relatorio (4.1s) — 3 riscos, 5 recomendacoes    |
|       |  QA (1.8s) — Score 92% — aprovado                |
|       |                                                  |
|  6. Renderiza relatorio completo:                        |
|       +-- Resumo Executivo                               |
|       +-- Componentes (grid 3 colunas)                   |
|       +-- Riscos (expanders com badges)                  |
|       +-- Recomendacoes (RAG vs original)                |
|       +-- Score QA (metric widget)                       |
|       +-- Download JSON (botao)                          |
+----------------------------------------------------------+
```

### SSE (Server-Sent Events) — Streaming em Tempo Real

O `ia-service` emite eventos SSE durante o pipeline via `StreamingResponse` do FastAPI. O Streamlit consome esses eventos via `httpx.Client.stream()` e atualiza a UI incrementalmente.

### Sidebar — Monitoramento

- **Health check:** verifica conectividade do `ia-service` (GET /health)
- **Historico:** lista ultimas analises via `report-api` (GET /reports)

---

## 17. Testes

### Testes unitarios do ia-service

```bash
cd ia-service
pip install -r requirements.txt
pytest tests/ -v
```

### Executar com cobertura

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

### Modulos testados

| Arquivo | O que cobre |
|---|---|
| `test_diagram_ingestion.py` | Validacao de tipo, tamanho, conversao base64 |
| `test_component_extraction.py` | Parsing do JSON do LLM, campos obrigatorios, markdown |
| `test_risk_assessment.py` | Classificacao de severidade, recalculo de summary |
| `test_quality_validation.py` | Verificacoes basicas, grounding, score minimo, fallback |

### Testes E2E com Playwright

O diretorio `tests/e2e/` contem **7 specs E2E** escritos em TypeScript com Playwright, cobrindo o fluxo completo da aplicacao.

**Specs disponiveis:**

| Spec | O que valida |
|---|---|
| `health-check.spec.ts` | Endpoints /health do ia-service e report-api |
| `upload-flow.spec.ts` | Upload de arquivo e inicio da analise |
| `sse-pipeline.spec.ts` | Streaming SSE com progresso de cada etapa |
| `report-display.spec.ts` | Renderizacao do relatorio no Streamlit |
| `error-scenarios.spec.ts` | Comportamento com arquivos invalidos |
| `report-api.spec.ts` | Endpoints REST do report-api |
| `history.spec.ts` | Historico e paginacao de analises |

**Helpers reutilizaveis:**
- `api-client.ts` — cliente HTTP para ia-service e report-api
- `sse-client.ts` — consumer de Server-Sent Events
- `selectors.ts` — seletores CSS do Streamlit

**Executar:**

```bash
cd tests/e2e
npm install
npx playwright test                # todos os testes
npx playwright test upload-flow    # teste especifico
npx playwright test --ui           # modo visual interativo
```

---

## 18. Seguranca

### Validacao de entrada (Input Guardrails)

- Deteccao de prompt injection via padroes regex (override, role-play, exfiltracao, delimitadores)
- Sanitizacao de filename (path traversal, caracteres perigosos)
- Validacao de schema dos dados extraidos (tipos, limites de tamanho)
- Arquivos validados por MIME type e tamanho antes de chegar no LLM
- Tipos nao suportados rejeitados na borda

### Controle do LLM

- **System prompts restritos:** instruem o modelo a responder apenas sobre dados fornecidos
- **Guardrail de grounding:** componentes inventados acima de 20% — relatorio descartado
- **JSON mode no QA:** `response_format: json_object` para saidas estruturadas
- **Score minimo de qualidade:** relatorios abaixo de 0.6 nao sao entregues

### Protecao de saida (Output Guardrails)

- **Deteccao de PII:** CPF, CNPJ, email, telefone, IP, API keys, cartoes de credito
- **Redacao automatica:** dados sensiveis substituidos por `[REDACTED]` recursivamente
- **Filtro de conteudo proibido:** discriminatorio, instrucoes ilegais, engenharia social
- **Validacao de schema:** chaves obrigatorias, tipos, severidades validas

### Comunicacao entre servicos

- `ia-service` e `report-api` comunicam com o PostgreSQL via connection string autenticada
- Variaveis sensiveis injetadas via variaveis de ambiente — nunca hardcoded
- `report-api` e estritamente read-only — nao aceita escrita

### Resiliencia a falhas

- **Falha do pgvector (RAG):** pipeline continua sem contexto historico
- **Falha do LLM de QA:** assume score conservador (0.7) se checks basicos passaram
- **Falha do webhook:** resultado ja esta no banco; a falha e logada mas nao bloqueia
- **Mensagens duplicadas SQS:** idempotencia por `sqs_message_id` — reprocessamento ignorado
- **Graceful shutdown:** `SIGTERM`/`SIGINT` finaliza o processamento atual antes de encerrar

### Limitacoes de seguranca conhecidas

- Nao ha autenticacao entre `ia-service` e `report-api` (mesma rede Docker interna)
- O endpoint `POST /analyze` nao requer autenticacao (uso interno/testes)
- O LLM pode alucinar componentes dentro da tolerancia de 20%
- Dados dos diagramas sao enviados para APIs externas — avaliar termos de uso antes de processar diagramas sigilosos

---

## 19. Limitacoes e Decisoes de Projeto

### Por que nao OCR?

LLMs Vision modernos interpretam diagramas com compreensao semantica — entendem setas, caixas, relacionamentos e padroes arquiteturais. OCR extrairia apenas texto, perdendo toda a informacao visual estrutural.

### Por que a escolha do LLM e configuravel?

O sistema usa uma abstracao (`LLM_MODEL` + `LLM_BASE_URL`) que permite trocar o modelo e o provider sem alterar o codigo do pipeline. Suporta OpenAI, Groq e qualquer provider compativel com a API OpenAI.

### Por que o RAG e non-blocking?

O pgvector e uma dependencia de enriquecimento, nao de funcionamento. Um diagrama pode ser analisado com qualidade mesmo sem historico. Tornar o RAG bloqueante quebraria o pipeline em cold start (banco vazio) ou falhas de infraestrutura.

### Por que riscos sao gerados junto com o relatorio?

A classificacao de riscos e a geracao do relatorio compartilham o mesmo contexto (extracao + RAG). Unificar em uma unica chamada ao LLM reduz latencia e custo de API, alem de manter coerencia entre riscos identificados e recomendacoes geradas.

### Por que fine-tuning fora do Docker?

Treinar um modelo de 7B parametros requer GPU com no minimo 16GB de VRAM. O ambiente Docker do hackathon roda em CPU. O script `train.py` e executado externamente (Colab, RunPod) e o adapter treinado e servido via HuggingFace Inference API.

### Por que o QA tem duas fases?

Verificacoes deterministicas (Fase 1) sao instantaneas e sem custo de API — capturam erros obvios como campos vazios e alucinacoes grosseiras. A avaliacao com LLM (Fase 2) avalia nuances qualitativas. Separar as fases evita chamar o LLM para relatorios claramente invalidos.

### Por que o webhook nao bloqueia o pipeline?

O resultado e sempre persistido no banco antes do webhook ser enviado. Se o endpoint do SOAT estiver indisponivel, o time SOAT pode consultar o relatorio via `report-api`. O webhook e uma notificacao de conveniencia, nao o unico canal de entrega.

### Por que Input e Output Guardrails?

- **Input Guardrails** protegem contra prompt injection e dados maliciosos antes que cheguem ao LLM — defesa em profundidade na entrada
- **Output Guardrails** protegem contra vazamento de PII, conteudo proibido e schemas invalidos na saida — garantem que o sistema nunca entrega dados sensiveis ao usuario final

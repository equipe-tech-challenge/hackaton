# Explicacao Tecnica do Sistema — Hackathon FIAP (IADT + SOAT)

## 1. Visao Geral da Solucao

O sistema e um MVP de analise automatizada de diagramas de arquitetura de software. O usuario envia um diagrama (imagem ou PDF) e recebe um relatorio tecnico estruturado contendo componentes identificados, riscos arquiteturais classificados por severidade e recomendacoes praticas de melhoria.

A solucao foi projetada como um sistema distribuido com 6 servicos containerizados, orquestrados via Docker Compose, seguindo principios de Domain-Driven Design (DDD) com Arquitetura Hexagonal (Ports & Adapters).

---

## 2. Arquitetura de Software (Requisitos SOAT)

### 2.1 Arquitetura de Microsservicos

O sistema e composto por 4 servicos independentes com responsabilidades claras:

| Servico | Responsabilidade | Porta | Tecnologia |
|---------|-----------------|-------|------------|
| **IA Service** | Upload, orquestracao do pipeline de IA e processamento | :8000 | FastAPI + Uvicorn |
| **Celery Worker** | Processamento assincrono de diagramas em background | — | Celery |
| **Report API** | Consulta de relatorios gerados (leitura) | :8001 | FastAPI + Uvicorn |
| **Streamlit App** | Interface do usuario (frontend) | :8501 | Streamlit |

Cada servico roda em container Docker separado, com Dockerfile proprio e dependencias isoladas.

### 2.2 Comunicacao entre Servicos

A comunicacao utiliza duas abordagens conforme exigido pelo desafio:

**REST (sincrono):**
- O Streamlit se comunica com o IA Service via `POST /analyze/async` para submeter diagramas.
- O Streamlit consulta a Report API via `GET /reports` para listar relatorios anteriores.
- O IA Service expoe endpoints de health check (`GET /health`) e status (`GET /analyses/{id}/status`).

**Fluxo Assincrono (mensageria):**
- **Celery + Redis**: O endpoint `POST /analyze/async` enfileira a task `analyze_diagram_task` no Celery via Redis como broker. O Celery Worker consome a fila e executa o pipeline de forma assincrona, publicando eventos de progresso via Redis Pub/Sub.
- **AWS SQS (integracao externa opcional)**: Um consumer SQS roda em thread separada dentro do IA Service, consumindo mensagens enviadas pelo time SOAT contendo URLs pre-assinadas do S3. Apos o processamento, o resultado e devolvido via webhook HTTP (callback_url).

O fluxo assincrono principal (Celery) suporta:
- **Server-Sent Events (SSE)** em tempo real via `GET /jobs/{job_id}/events` — o Streamlit se inscreve nesse canal e renderiza o progresso de cada etapa do pipeline.
- **Polling** como alternativa via `GET /jobs/{job_id}/status` para clientes que nao suportam SSE.

### 2.3 Arquitetura Hexagonal (Ports & Adapters)

A aplicacao segue rigorosamente a Arquitetura Hexagonal com separacao clara de camadas:

```
ia-service/app/
  domain/                    # Camada de Dominio (regras de negocio puras)
    diagram_analysis/        #   Bounded Context: Analise de Diagramas
      analysis.py            #     Aggregate Root (AnalysisAggregate)
      extraction_result.py   #     Value Object
      diagram_file.py        #     Value Object
      repository.py          #     Port (interface)
      events/                #     Domain Events
    report_generation/       #   Bounded Context: Geracao de Relatorio
      report.py              #     Aggregate Root (ReportAggregate)
      technical_report.py    #     Value Object
      risk.py                #     Value Object com categorias tipadas
      qa_score.py            #     Value Object
      guardrail.py           #     Domain Service
      repository.py          #     Port (interface)
    shared/                  #   Conceitos compartilhados entre BCs
      analysis_id.py         #     Value Object (tipagem forte)
      input_guardrail.py     #     Domain Service
      output_guardrail.py    #     Domain Service

  application/               # Camada de Aplicacao (use cases)
    use_cases/
      analyze_diagram.py     #   AnalyzeDiagramUseCase — orquestra o pipeline E2E
      retrieve_report.py     #   RetrieveReportUseCase
    ports/
      llm_port.py            #   IVisionLLM, ITextLLM (interfaces abstratas)
      vector_store_port.py   #   IVectorStore (interface abstrata)

  infrastructure/            # Camada de Infraestrutura (adaptadores concretos)
    llm/
      openai_adapter.py      #   Adapter: OpenAI Vision + Text (implementa ports)
    vector_store/
      pgvector_adapter.py    #   Adapter: pgvector (implementa IVectorStore)
    persistence/
      sqlalchemy_*.py        #   Adapter: SQLAlchemy (implementa repositories)
    celery/                  #   Adapter: Celery para processamento async
    messaging/
      sqs_consumer.py        #   Adapter: AWS SQS consumer
    composition_root.py      #   Factory: monta o grafo de dependencias (DI)
```

**Inversao de dependencia**: A camada de dominio define interfaces (ports) como `IVisionLLM`, `ITextLLM`, `IVectorStore` e `IAnalysisRepository`. As implementacoes concretas (`OpenAIVisionAdapter`, `PGVectorAdapter`, `SQLAlchemyAnalysisRepository`) ficam na camada de infraestrutura. O `composition_root.py` e o unico ponto que conhece as implementacoes concretas e faz a injecao de dependencias.

**Beneficio**: Trocar o provider de LLM (ex: de OpenAI para Anthropic) ou o banco de dados requer apenas um novo adapter, sem alterar dominio ou aplicacao.

### 2.4 Domain Events

O sistema emite Domain Events em cada transicao de estado do aggregate, documentando o ciclo de vida completo:

- `DiagramReceivedEvent` — diagrama recebido para analise
- `DiagramIngestedEvent` — arquivo validado e preprocessado
- `ComponentsExtractedEvent` — componentes extraidos pelo Vision LLM
- `ReportGeneratedEvent` — relatorio tecnico gerado
- `QAValidationCompletedEvent` — validacao de qualidade concluida
- `AnalysisCompletedEvent` / `AnalysisFailedEvent` — finalizacao

### 2.5 Persistencia (Banco de Dados Proprio)

O PostgreSQL 16 com extensao pgvector serve como banco de dados, com schema dedicado:

- **analyses**: registro de cada analise (status, arquivo, timestamps)
- **extraction_results**: resultado da extracao do Vision LLM (componentes, relacionamentos, padroes em JSONB)
- **reports**: relatorio gerado com riscos, recomendacoes e score de QA
- **langchain_pg_embedding**: embeddings vetoriais para busca semantica (RAG)

O Redis serve como broker do Celery, armazena eventos de progresso e faz pub/sub para SSE em tempo real.

---

## 3. Inteligencia Artificial (Requisitos IADT)

### 3.1 Pipeline de IA

O pipeline de IA e executado pelo `AnalyzeDiagramUseCase` com as seguintes etapas sequenciais:

```
Input Guardrails → Ingestao → Classificacao (Vision) → Extracao (Vision)
→ Validacao → RAG (pgvector) → Relatorio + Riscos (Text) → Output Guardrails
→ QA (Text) → [se rejeitado: loop de refinamento → Relatorio novamente]
```

Cada etapa emite eventos de progresso via callback, permitindo que o frontend acompanhe o processamento em tempo real.

### 3.2 Deteccao de Componentes Arquiteturais em Imagens (LLM Vision)

**Abordagem escolhida**: LLM multimodal (gpt-4o) com capacidade de visao computacional.

**Justificativa**: Modelos de visao computacional tradicionais (YOLO, Faster R-CNN) exigiriam milhares de imagens anotadas manualmente para treino, o que e inviavel em um hackathon. LLMs multimodais como o gpt-4o ja possuem conhecimento pre-treinado sobre diagramas de arquitetura e conseguem identificar componentes (servicos, bancos de dados, filas, gateways), relacionamentos e padroes arquiteturais diretamente da imagem, sem necessidade de anotacao.

**Implementacao** (`OpenAIVisionAdapter`):

1. **Classificacao** (`classify_image`): Antes de processar, o sistema verifica se a imagem e realmente um diagrama de arquitetura de software. Um prompt rigoroso define criterios de aceitacao (caixas, setas, componentes tecnicos) e rejeicao (fotos, mockups, organogramas). A confianca minima e 75% — abaixo disso, o diagrama e rejeitado com explicacao.

2. **Extracao** (`extract_components`): O diagrama e enviado em base64 ao LLM Vision com um system prompt que define o papel de "arquiteto de software senior" e instrui a retornar JSON estruturado com 4 campos obrigatorios: `components`, `relationships`, `patterns` e `raw_description`. O `response_format=json_object` forca a saida em JSON valido.

### 3.3 Classificacao de Riscos Arquiteturais

**Abordagem escolhida**: Classificacao hibrida (regras + LLM) com categorias tipadas.

**Justificativa**: Usar apenas regras fixas nao captura riscos sutis que dependem do contexto. Usar apenas LLM sem restricoes gera riscos genericos e vagos. A combinacao garante que os riscos sao classificados dentro de categorias conhecidas (SPOF, Seguranca, Escalabilidade, Acoplamento, Observabilidade, Resiliencia) mas com descricoes especificas ao diagrama analisado.

**Implementacao**:
- O `RiskCategory` define as 6 categorias validas como um enum tipado.
- O prompt do LLM de relatorio instrui a classificar riscos apenas nessas categorias, com severidade (ALTO/MEDIO/BAIXO), componentes afetados e mitigacao.
- O Output Guardrail valida que cada risco tem severidade valida e chaves obrigatorias.

### 3.4 Geracao de Relatorio Tecnico com LLM e Guardrails

**Abordagem escolhida**: LangChain com ChatOpenAI + JsonOutputParser + guardrails em 3 camadas.

**Justificativa**: A geracao de relatorios estruturados via LLM requer controle rigoroso de formato, conteudo e qualidade. O LangChain fornece `ChatPromptTemplate` para prompts reproduziveis e `JsonOutputParser` para parsing robusto de JSON. Os guardrails previnem alucinacoes, vazamento de PII e conteudo proibido.

**Implementacao** (`OpenAITextAdapter.generate_report`):
- Usa LangChain chain: `prompt | llm | JsonOutputParser()`.
- O prompt inclui dados da extracao, contexto RAG (quando disponivel) e feedback de tentativas anteriores (loop de refinamento).
- O relatorio gerado contem: `components_identified`, `architectural_risks`, `recommendations`, `executive_summary` e `rag_used`.

### 3.5 Sistema de Guardrails (3 Camadas)

O sistema implementa guardrails em 3 camadas distintas, cobrindo todo o ciclo de vida da analise:

#### Camada 1: Input Guardrails (`InputGuardrailService`)
Protege o pipeline contra entradas maliciosas **antes** do LLM:

- **Deteccao de Prompt Injection**: 25+ padroes regex detectam tentativas de override de instrucoes ("ignore previous instructions"), role-play ("you are now"), exfiltracao de prompt ("reveal your system prompt") e injecao via delimitadores de modelo (`[INST]`, `<<SYS>>`).
- **Sanitizacao de Filename**: Remove path traversal (`../`), caracteres perigosos e limita tamanho a 255 chars.
- **Sanitizacao de Texto**: Remove delimitadores de prompt e caracteres de controle Unicode de campos textuais.
- **Validacao de Schema**: Verifica tipos, chaves obrigatorias e limites (max 200 componentes, 500 relacionamentos) nos dados retornados pelo LLM de visao.
- **Verificacao de Injection nos Dados Extraidos**: Cada componente e a `raw_description` retornados pelo LLM sao escaneados para prompt injection antes de serem usados em prompts subsequentes.

#### Camada 2: Report Guardrail (`GuardrailService`)
Validacao de dominio do relatorio gerado, **independente de LLM**:

- `components_identified` nao pode estar vazio.
- **Anti-alucinacao**: Maximo 20% dos componentes do relatorio podem nao existir na extracao original. Se exceder, o relatorio e rejeitado com lista dos componentes "inventados".
- `recommendations` nao pode estar vazio.
- `executive_summary` precisa de pelo menos 100 caracteres.

#### Camada 3: Output Guardrails (`OutputGuardrailService`)
Valida e sanitiza a saida **antes** de entregar ao usuario:

- **Validacao de Schema**: Verifica todas as chaves obrigatorias, tipos corretos e valores permitidos (ex: severidade so aceita ALTO/MEDIO/BAIXO).
- **Filtro de Conteudo Proibido**: Detecta conteudo discriminatorio, instrucoes para atividades ilegais e engenharia social.
- **Deteccao e Redacao de PII**: Identifica CPF, CNPJ, email, telefone, IPv4/v6, API keys (OpenAI, GitHub, Slack, AWS) e numeros de cartao. Substitui por `[REDACTED]` recursivamente em todo o dict de saida.

### 3.6 RAG (Retrieval-Augmented Generation) com pgvector

**Abordagem escolhida**: RAG com embeddings vetoriais armazenados no PostgreSQL via extensao pgvector.

**Justificativa**: A cada nova analise, o sistema acumula conhecimento sobre padroes arquiteturais e riscos. O RAG permite que analises futuras de diagramas similares se beneficiem desse historico, gerando recomendacoes mais ricas e contextualizadas. O pgvector foi escolhido por ser parte do PostgreSQL existente, evitando um servico adicional (como Pinecone ou Weaviate).

**Implementacao** (`PGVectorAdapter`):

1. **Indexacao**: Apos a extracao, o sistema cria um Document LangChain com a descricao, componentes, padroes e relacionamentos, e o indexa no pgvector com embeddings `text-embedding-3-small` (OpenAI) ou `all-MiniLM-L6-v2` (HuggingFace local).

2. **Busca Semantica**: Antes de gerar o relatorio, o sistema busca as 3 analises mais similares ja finalizadas (filtro `has_report=True`). So considera resultados com distancia < 0.3 (alta similaridade).

3. **Enriquecimento**: Um LLM sintetiza o contexto historico recuperado, identificando padroes de risco recorrentes e boas praticas observadas em arquiteturas similares. Esse texto e injetado no prompt de geracao do relatorio.

4. **Marcacao**: Recomendacoes influenciadas pelo contexto RAG sao marcadas com `[RAG]` no relatorio final, dando transparencia ao usuario sobre o que veio do historico.

### 3.7 Avaliacao de Qualidade (QA) com Validacao Hibrida

**Abordagem escolhida**: Validacao em 2 fases (deterministica + LLM adversarial) com loop de refinamento.

**Justificativa**: Depender apenas do LLM para QA gera scores inflados. A fase deterministica aplica verificacoes objetivas (campos vazios, grounding check) antes de acionar o LLM, economizando tokens e garantindo um baseline de qualidade.

**Implementacao**:

**Fase 1 — Verificacoes Deterministicas** (sem LLM):
- `components_identified`, `architectural_risks` e `recommendations` nao podem estar vazios.
- `executive_summary` com minimo 100 caracteres.
- **Grounding check**: 80% dos componentes do relatorio devem existir na extracao original. Caso contrario, lista os componentes alucinados.

**Fase 2 — Auditor LLM Adversarial**:
- Um LLM com system prompt de "auditor tecnico adversarial" avalia o relatorio com criterios ponderados: Consistencia (40%), Completude (30%), Coerencia (20%) e Qualidade (10%).
- O auditor busca ativamente componentes inventados, riscos genericos, recomendacoes desvinculadas e linguagem vaga.
- Score minimo obrigatorio: definido em `QAScore.MIN_SCORE`.

**Loop de Refinamento**:
- Se o QA rejeitar o relatorio, os issues encontrados sao enviados como feedback ao LLM na proxima tentativa. O prompt inclui uma secao "CORRIJA OBRIGATORIAMENTE" com a lista de problemas.
- Maximo de 2 tentativas. Se o relatorio nao passar apos 2 tentativas, a analise falha com `QAError`.

### 3.8 Fine-tuning com QLoRA (Preparacao)

O sistema inclui um pipeline completo de fine-tuning preparado para treinar um modelo local como alternativa ao gpt-4o:

**Geracao de Dados Sinteticos** (`data_generator.py`):
- 30 templates de arquitetura organizados em 4 tiers de complexidade (simples a expert), com variacoes por tier.
- Um LLM "professor" (Claude/GPT) gera pares sinteticos (extracao → relatorio) seguindo o mesmo schema do pipeline.
- 30% das amostras de Tier 3-4 incluem contexto RAG sintetico para treinar o modelo a usar historico.
- Gera ate 500 pares de treino em formato JSONL.

**Treino QLoRA** (`train.py`):
- Modelo base: Mistral-7B-Instruct-v0.3 (configuravel).
- Quantizacao 4-bit com NormalFloat4 e quantizacao dupla.
- LoRA rank 8, alpha 16, dropout 0.1 aplicado em todas as camadas de projecao (q, k, v, o, gate, up, down).
- Treinamento Supervisionado (SFT) com monitoramento de convergencia, early stopping e metricas de dominio.
- Suporta publicacao no HuggingFace Hub.

**Justificativa**: O fine-tuning permite reduzir custos operacionais (modelo local vs. API paga), melhorar a qualidade para o dominio especifico de relatorios arquiteturais e operar sem dependencia de servicos externos.

---

## 4. Integracao IA + Sistema

### 4.1 Como a IA e Acionada

A IA e parte integral do fluxo do sistema, nao um script isolado. Ha 3 pontos de entrada que convergem para o mesmo pipeline:

1. **Upload via Streamlit** (`POST /analyze/async`): O usuario faz upload pelo frontend. O IA Service enfileira a task no Celery, que executa o `AnalyzeDiagramUseCase` em background.

2. **API REST direta** (`POST /analyze`): Endpoint sincrono para testes e integracoes externas.

3. **SQS Consumer** (thread daemon): Consome mensagens da fila AWS SQS, baixa o diagrama do S3 e executa o mesmo pipeline.

Todos os 3 caminhos convergem para `run_pipeline()` → `AnalyzeDiagramUseCase.execute()`, garantindo consistencia.

### 4.2 Como o Sistema Trata Falhas da IA

O tratamento de falhas e granular por etapa:

- **Falha na classificacao**: Se a API de visao estiver indisponivel, o sistema assume `is_architecture_diagram=True` e prossegue — a extracao posterior rejeita naturalmente imagens sem componentes.
- **Falha na extracao**: Erro de API ou JSON invalido levanta `ExtractionError`. A analise e marcada com status `erro` e mensagem explicativa.
- **Falha no RAG**: O RAG e non-blocking. Se falhar, retorna `RagContext.empty()` e o pipeline prossegue sem contexto historico.
- **Falha no relatorio**: `ReportGenerationError` e levantada. Status atualizado para `erro`.
- **Falha no QA**: Se o relatorio for rejeitado apos 2 tentativas, `QAError` e levantada com os issues detalhados.
- **Falha no QA LLM**: Se a avaliacao LLM falhar, retorna score conservador (0.7, is_valid=True) — as verificacoes deterministicas ja passaram.

Em todos os casos:
- O status da analise e atualizado no banco (`analysis.fail(step, message)`).
- O evento de erro e publicado via SSE/Redis para o frontend.
- No fluxo SQS, o webhook e enviado com status `erro` e mensagem descritiva.
- A mensagem SQS **nao** e deletada da fila (volta apos visibility timeout para retry).

### 4.3 Como o Resultado da IA e Persistido

- **extraction_results**: Componentes, relacionamentos e padroes em JSONB. Um registro por analise.
- **reports**: Relatorio completo com riscos, recomendacoes, sumario executivo, score QA e flag `rag_used`. Um registro por analise.
- **analyses**: Status atualizado em cada transicao (recebido → em_processamento → analisado/erro).
- **langchain_pg_embedding**: Embedding vetorial da extracao para futuras buscas RAG.

### 4.4 Como o Relatorio e Gerado a Partir da Analise

O fluxo de dados e:

```
Imagem → [Vision LLM] → ExtractionResult (componentes, relacionamentos, padroes)
                                ↓
ExtractionResult + RagContext → [Text LLM] → TechnicalReport (riscos, recomendacoes, sumario)
                                                      ↓
TechnicalReport → [Output Guardrails] → sanitizacao + validacao
                                                      ↓
TechnicalReport + ExtractionResult → [QA] → QAScore (valido/invalido, score, issues)
                                                      ↓
                                              [se invalido] → feedback → re-gerar relatorio
                                              [se valido] → persistir + retornar ao usuario
```

---

## 5. Infraestrutura e DevOps

### 5.1 Docker e Docker Compose

O sistema usa Docker Compose com 6 servicos:

```yaml
services:
  redis:           # Redis 7 Alpine — broker Celery + pub/sub SSE
  pgvector:        # PostgreSQL 16 + pgvector — persistencia + embeddings
  ia-service:      # FastAPI — API principal + pipeline
  celery-worker:   # Celery — processamento assincrono
  report-api:      # FastAPI — consulta de relatorios
  streamlit-app:   # Streamlit — interface do usuario
```

**Health checks**: Redis e PostgreSQL possuem health checks configurados. Os servicos dependentes (`ia-service`, `celery-worker`, `report-api`) usam `condition: service_healthy` para aguardar a disponibilidade antes de iniciar.

**Volumes**: `pgvector_data` para persistencia dos dados do PostgreSQL.

### 5.2 Testes

O projeto inclui testes E2E com Playwright (`tests/e2e/`):
- `playwright.config.ts` configurado para testes de integracao.
- `api-client.ts` com helper para chamadas a API.
- Fixtures com diagrama de teste (`test-diagram.png`) e arquivo invalido (`invalid-file.txt`).

---

## 6. Qualidade e Observabilidade

### 6.1 Logs Estruturados

O sistema usa **structlog** com saida JSON para todos os servicos:

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
```

Cada log inclui `analysis_id` como campo contextual (via `logger.bind()`), permitindo correlacionar todas as etapas de uma mesma analise. Os logs seguem o padrao `componente.acao.resultado` (ex: `vision_llm.extract.done`, `pipeline.qa_rejected.refinement`).

### 6.2 Tratamento de Erros

- Excecoes tipadas por etapa: `IngestionError`, `ExtractionError`, `ReportGenerationError`, `RAGError`, `QAError`, `GuardrailError`.
- Cada excecao carrega o campo `step` indicando em qual etapa do pipeline ocorreu.
- O status da analise e atualizado atomicamente no banco em caso de erro.
- O Celery Worker publica eventos de erro via Redis para que o frontend saiba em tempo real.
- O SQS Consumer implementa graceful shutdown via SIGTERM/SIGINT e deteccao de poison messages (receive_count > 3).

---

## 7. Limitacoes do Modelo

1. **Dependencia de LLM externo**: O pipeline depende do gpt-4o (ou equivalente) para visao e texto. Latencia e custos variam conforme o provider. O pipeline de fine-tuning com QLoRA e uma alternativa em preparacao para mitigar essa dependencia.

2. **Qualidade da extracao depende do diagrama**: Diagramas mal desenhados, com baixa resolucao ou sem rotulos claros podem gerar extracoes incompletas ou imprecisas.

3. **Alucinacoes controladas, nao eliminadas**: Os guardrails limitam alucinacoes a 20% dos componentes e o QA audita consistencia, mas o LLM pode inventar detalhes sutis que passam pelos checks (ex: descrever um componente com funcao incorreta).

4. **RAG limitado ao historico local**: O enriquecimento via RAG so funciona quando ha analises anteriores no banco. Na primeira execucao, o RAG e ignorado (retorna `RagContext.empty()`).

5. **Classificacao binaria de imagens**: A classificacao aceita/rejeita a imagem inteira. Nao detecta diagramas mistos (ex: diagrama de arquitetura com wireframes no mesmo PDF).

6. **Loop de refinamento limitado**: O loop de QA tenta no maximo 2 vezes. Se o LLM insistir em erros, a analise falha. Uma abordagem mais robusta usaria tecnicas de self-consistency com multiplas amostras.

7. **Sem CI/CD automatizado em cloud**: O pipeline de CI/CD esta preparado para execucao local via Docker Compose. Para deploy em cloud, seria necessario configurar GitHub Actions ou equivalente com push para registry de containers.

---

## 8. Justificativa das Abordagens Escolhidas (Resumo)

| Decisao | Escolha | Alternativa Considerada | Justificativa |
|---------|---------|------------------------|---------------|
| Extracao de componentes | LLM Vision (gpt-4o) | YOLO/Faster R-CNN | Nao requer dataset anotado; entende semantica |
| Classificacao de riscos | Hibrida (categorias tipadas + LLM) | Regras fixas / LLM livre | Equilibrio entre controle e flexibilidade |
| Geracao de relatorio | LangChain + JsonOutputParser | SDK OpenAI direta | Composicao de chains, parsing robusto |
| Guardrails | 3 camadas (input/report/output) | Apenas prompt engineering | Defesa em profundidade; prompt nao e suficiente |
| Anti-alucinacao | Grounding check + QA adversarial | Apenas temperatura baixa | Verificacao objetiva + subjetiva |
| RAG | pgvector no PostgreSQL | Pinecone/Weaviate | Reutiliza infra existente, sem servico extra |
| Processamento async | Celery + Redis | RabbitMQ / SQS puro | Ecossistema Python nativo, SSE via pub/sub |
| Arquitetura | DDD + Hexagonal | MVC / Layered | Testabilidade, troca de providers, DIP |
| Fine-tuning | QLoRA 4-bit (preparado) | Full fine-tuning | Viavel em GPU consumer (16GB VRAM) |
| Observabilidade | structlog JSON | print / logging basico | Correlacao por analysis_id, parseable |
| Frontend | Streamlit | React / Next.js | Prototipacao rapida em Python, SSE nativo |

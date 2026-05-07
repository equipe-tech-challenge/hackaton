# Hackathon FIAP — Time IADT · Análise de Diagramas de Arquitetura com IA

Sistema de análise automatizada de diagramas de arquitetura. Recebe imagens ou PDFs via fila SQS, processa com pipeline de IA (guardrails, RAG, QA) e devolve relatório técnico via webhook.

---

## Serviços

| Serviço | Porta | Repositório / Pasta | Responsabilidade |
|---|---|---|---|
| **ia-service** | 8000 | [ia-service/](ia-service/) | Pipeline de IA, SQS consumer, webhook, Celery, Streamlit |
| **report-api** | 8001 | [report-api/](report-api/) | API REST read-only de consulta de relatórios |
| pgvector | 5432 | ia-service/infrastructure/database/ | PostgreSQL 16 + pgvector |
| redis | 6379 | ia-service/infrastructure/redis/ | Broker Celery + pub/sub SSE |

O time **SOAT** é responsável pelo API Gateway, serviço de upload, publicação na fila SQS e infraestrutura AWS adjacente.

---

## Arquitetura

```
SOAT (Externo)
  | SQS message
  v
ia-service (:8000)
  | pipeline de IA (5 etapas + guardrails)
  v
PostgreSQL + pgvector (:5432)
  | read-only
  v
report-api (:8001)
```

Diagrama detalhado: [ia-service/docs/](ia-service/docs/)

---

## Full Stack — Subir tudo

### Pré-requisitos

- Docker Desktop >= 4.x (Docker Compose V2 >= 2.20)
- OpenAI API Key

### Configurar e subir

```bash
cp .env.example .env
# edite .env e preencha OPENAI_API_KEY

docker compose up --build
```

Containers criados:

| Container | Porta | Função |
|---|---|---|
| `hackathon_pgvector` | 5432 | PostgreSQL + pgvector |
| `hackathon_redis` | 6379 | Broker Celery + pub/sub |
| `hackathon_rabbitmq` | 5672 / 15672 | Broker de teste |
| `hackathon_ia_service` | 8000 | API principal |
| `hackathon_celery_worker` | — | Worker background |
| `hackathon_report_api` | 8001 | API de relatórios |
| `hackathon_streamlit` | 8501 | UI de validação |

### Verificar saúde

```bash
curl http://localhost:8000/health   # ia-service
curl http://localhost:8001/health   # report-api
```

### Parar

```bash
docker compose down      # mantém volumes (DB persiste)
docker compose down -v   # remove volumes (reset total)
```

---

## Executar serviços individualmente

Cada serviço é autossuficiente e pode ser executado de forma independente:

```bash
# Só ia-service (com banco e redis)
cd ia-service && docker compose -f docker-compose.standalone.yml up --build

# Só report-api (com banco)
cd report-api && docker compose -f docker-compose.standalone.yml up --build
```

Consulte o README de cada serviço para detalhes:
- [ia-service/README.md](ia-service/README.md)
- [report-api/README.md](report-api/README.md)

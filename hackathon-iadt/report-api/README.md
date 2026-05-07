# report-api — API de Consulta de Relatórios

API REST read-only para consulta dos relatórios gerados pelo `ia-service`. Usada pelo API Gateway do time SOAT e pelo `streamlit-app`.

---

## Índice

1. [Responsabilidade](#1-responsabilidade)
2. [Stack](#2-stack)
3. [Estrutura de Pastas](#3-estrutura-de-pastas)
4. [API Reference](#4-api-reference)
5. [Schema do Banco](#5-schema-do-banco)
6. [Configuração de Ambiente](#6-configuração-de-ambiente)
7. [Como Executar](#7-como-executar)

---

## 1. Responsabilidade

O `report-api` **não gera** relatórios — apenas os consulta. Os dados são escritos pelo `ia-service` e lidos aqui de forma isolada.

| Serviço | Porta | Operações |
|---|---|---|
| `ia-service` | 8000 | Escreve `analyses`, `extraction_results`, `reports` |
| `report-api` | 8001 | Lê `analyses`, `reports` (read-only) |

---

## 2. Stack

| Componente | Tecnologia |
|---|---|
| Web framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy (read-only queries) |
| Banco | PostgreSQL 16 + pgvector (compartilhado com ia-service) |
| Logging | `structlog` (JSON) |

---

## 3. Estrutura de Pastas

```
report-api/
├── Dockerfile
├── requirements.txt
├── .env.example
├── infrastructure/
│   └── database/
│       └── init/          # SQL de inicialização do banco (espelhado do ia-service)
└── app/
    ├── main.py            # FastAPI — 3 endpoints
    ├── db/
    │   ├── connection.py  # SQLAlchemy engine + healthcheck
    │   └── repositories.py # Queries read-only
    └── utils/
        └── logger.py
```

---

## 4. API Reference

### `GET /health`

Verifica conexão com o banco.

```json
{"status": "healthy", "db": "connected"}
```

### `GET /reports/{analysis_id}`

Retorna o relatório completo de uma análise.

**200:**
```json
{
  "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analisado",
  "file_name": "diagrama.png",
  "created_at": "2026-04-02T21:30:00Z",
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
      "[RAG] Implementar circuit breaker"
    ],
    "executive_summary": "A arquitetura analisada...",
    "rag_used": true,
    "qa_completeness_score": 0.92
  }
}
```

**404:** `{"detail": "Análise não encontrada."}`

### `GET /reports?limit=20&offset=0`

Lista relatórios paginados.

```json
{
  "total": 5,
  "limit": 20,
  "offset": 0,
  "items": [...]
}
```

---

## 5. Schema do Banco

O `report-api` lê as tabelas `analyses` e `reports`, criadas pelos scripts em `infrastructure/database/init/`:

- `00_extensions.sql` — habilita `pgvector` e `uuid-ossp`
- `01_schema.sql` — cria as tabelas
- `02_indexes.sql` — cria índices de performance

O schema é de propriedade do `ia-service`. Esta cópia existe para permitir execução standalone do `report-api`.

---

## 6. Configuração de Ambiente

```bash
cp .env.example .env
```

| Variável | Padrão | Descrição |
|---|---|---|
| `POSTGRES_USER` | `hackathon` | Usuário do banco |
| `POSTGRES_PASSWORD` | `hackathon123` | Senha do banco |
| `POSTGRES_DB` | `hackathon_db` | Nome do banco |
| `POSTGRES_HOST` | `localhost` | Host do banco |
| `POSTGRES_PORT` | `5432` | Porta do banco |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |

---

## 7. Como Executar

### Standalone (com banco incluso)

```bash
cd report-api
cp .env.example .env
docker compose -f docker-compose.standalone.yml up --build
```

Sobe: `pgvector` (com schema inicializado) + `report-api`.

### Desenvolvimento local (fora do Docker)

```bash
# 1. Suba o banco
docker compose -f docker-compose.standalone.yml up pgvector

# 2. Rode a API
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Verificar saúde

```bash
curl http://localhost:8001/health
# {"status": "healthy", "db": "connected"}
```

### Consultar relatórios

```bash
# Listar
curl "http://localhost:8001/reports?limit=10"

# Detalhe
curl "http://localhost:8001/reports/{analysis_id}"
```

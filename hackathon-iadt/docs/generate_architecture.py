"""
Gerador do diagrama de arquitetura IADT — Alta Resolução (5600x3600 px)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

# ─── Paleta ───────────────────────────────────────────────────────────────────
BG      = "#0d1117"
PANEL   = "#161b22"
BORDER  = "#30363d"

C_EXT   = "#0d2137";  S_EXT  = "#4a90d9";  T_EXT  = "#c8e6ff"
C_CONS  = "#0a2b1a";  S_CONS = "#3daa6e";  T_CONS = "#b0f0d0"
C_PROC  = "#1a0e2e";  S_PROC = "#9c6dd4";  T_PROC = "#e0c8ff"
C_REP   = "#2b1a00";  S_REP  = "#e09030";  T_REP  = "#ffe5a0"
C_DB    = "#0a1e2b";  S_DB   = "#4a7fa5";  T_DB   = "#b0d0e8"
ARROW   = "#7ab8e8"
DARROW  = "#4a7fa5"

FONT    = "DejaVu Sans"

# ─── Figure ───────────────────────────────────────────────────────────────────
W, H = 28, 18
fig, ax = plt.subplots(figsize=(W, H), dpi=200)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, W); ax.set_ylim(0, H)
ax.axis("off")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def rbox(x, y, w, h, fill, stroke, lw=1.5, dash=False):
    ls = (0, (4, 3)) if dash else "-"
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06",
                       facecolor=fill, edgecolor=stroke,
                       linewidth=lw, linestyle=ls, zorder=3)
    ax.add_patch(p)

def node(x, y, w, h, title, sub="", fill=C_PROC, stroke=S_PROC, txt=T_PROC, fs=8.5):
    rbox(x, y, w, h, fill, stroke)
    ty = y + h/2 + (0.14 if sub else 0)
    ax.text(x+w/2, ty, title, ha="center", va="center",
            fontsize=fs, fontweight="bold", color=txt, fontfamily=FONT, zorder=4)
    if sub:
        ax.text(x+w/2, y+h/2-0.2, sub, ha="center", va="center",
                fontsize=fs-1.5, color=txt, alpha=0.72, fontfamily=FONT, zorder=4)

def group(x, y, w, h, title, fill=PANEL, stroke=BORDER, tc="#8b949e", lw=1.2):
    rbox(x, y, w, h, fill, stroke, lw=lw, dash=True)
    ax.text(x+0.18, y+h-0.05, title, ha="left", va="top",
            fontsize=8, color=tc, style="italic", fontfamily=FONT, zorder=5)

def arr(x1, y1, x2, y2, label="", c=ARROW, lw=1.4, rad=0.0, dash=False):
    ls = "dashed" if dash else "solid"
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=c, lw=lw,
                                linestyle=ls,
                                connectionstyle=f"arc3,rad={rad}"),
                zorder=6)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.11, label, ha="center", va="bottom",
                fontsize=6.5, color=c, alpha=0.88, fontfamily=FONT, zorder=7)

def hline(y):
    ax.plot([0.8, W-0.8], [y, y], color=BORDER, lw=0.7, zorder=1)

# ══════════════════════════════════════════════════════════════════════════════
#  TITLE
# ══════════════════════════════════════════════════════════════════════════════
ax.text(W/2, 17.55, "IADT  —  Intelligent Architecture Diagram Analyzer",
        ha="center", va="center", fontsize=19, fontweight="bold",
        color="#58a6ff", fontfamily=FONT)
ax.text(W/2, 17.12,
        "Hackathon FIAP   ·   Microsservicos em Containers Docker   ·   Pipeline de IA Multi-Agente",
        ha="center", va="center", fontsize=10, color="#8b949e", fontfamily=FONT)
hline(16.82)

# ══════════════════════════════════════════════════════════════════════════════
#  ROW A — Externos (topo)
# ══════════════════════════════════════════════════════════════════════════════
# AWS (esq)
group(0.4, 14.1, 6.0, 2.45, "AWS / Externos",
      stroke=S_EXT, tc=T_EXT, lw=1.5)
node(0.65, 14.45, 2.55, 1.6, "AWS SQS", "Fila de mensagens\nlong-polling",
     fill=C_EXT, stroke=S_EXT, txt=T_EXT)
node(3.45, 14.45, 2.55, 1.6, "AWS S3", "Armazenamento\nde diagramas",
     fill=C_EXT, stroke=S_EXT, txt=T_EXT)

# SOAT (dir)
group(21.5, 14.1, 6.1, 2.45, "SOAT — Sistema Cliente",
      stroke=S_EXT, tc=T_EXT, lw=1.5)
node(21.75, 14.45, 5.6, 1.6, "SOAT Webhook Endpoint",
     "POST callback_url\nrecebe resultado da analise",
     fill=C_EXT, stroke=S_EXT, txt=T_EXT)

# ══════════════════════════════════════════════════════════════════════════════
#  ROW B — Clientes / Frontend
# ══════════════════════════════════════════════════════════════════════════════
group(0.4, 11.35, 8.5, 2.45, "Clientes / Frontend",
      stroke=S_CONS, tc=T_CONS, lw=1.5)
node(0.65, 11.7, 3.8, 1.6, "Streamlit App",
     "Python  |  streamlit >=1.38\nhttpx  |  porta :8501",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS)
node(4.7,  11.7, 3.8, 1.6, "Static Frontend",
     "HTML5 / Vanilla JS\nUpload + SSE  |  porta :8000",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS)

# Webhook Sender (centro-dir)
node(19.4, 11.7, 5.5, 1.6, "Webhook Sender",
     "POST callback_url  |  retry + backoff\nHTTP client interno",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS)

# ══════════════════════════════════════════════════════════════════════════════
#  IA SERVICE — contêiner principal
# ══════════════════════════════════════════════════════════════════════════════
group(0.4, 3.9, 18.5, 7.1,
      "IA Service   |   FastAPI + Uvicorn   |   Python 3.12   |   porta :8000",
      stroke=S_PROC, tc=T_PROC, lw=2.0)

# ── API Layer ──
group(0.65, 9.55, 11.0, 1.2, "API Layer  (REST + SSE)",
      stroke="#6a4da4", tc=T_PROC, lw=1.0)
node(0.85,  9.68, 3.1, 0.9, "POST /analyze",     "Sincrono",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC, fs=7.5)
node(4.2,   9.68, 3.7, 0.9, "POST /analyze/stream", "Server-Sent Events",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC, fs=7.5)
node(8.15,  9.68, 3.3, 0.9, "SQS Consumer",      "thread daemon\nlong-poll  max 5",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC, fs=7.5)

# ── Pipeline ──
group(0.65, 4.2, 17.9, 5.1, "Pipeline de Analise (Analysis Orchestrator)",
      stroke="#6a4da4", tc=T_PROC, lw=1.0)

BW, BH = 3.9, 1.45
PY1 = 7.3   # linha superior (ingestao → extracão → rag → risk)
PY2 = 5.4   # linha inferior (report gen → fine-tuned → guardrails → qa)

# Linha 1
node(0.85,  PY1, BW, BH, "1. Ingestion Agent",
     "Valida formato  |  base64\nPNG / JPG / GIF / PDF",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC)
node(5.05,  PY1, BW, BH, "2. Extraction Agent",
     "LLM Vision  (GPT-4o)\nComponentes  |  Padroes",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC)
node(9.25,  PY1, BW, BH, "3. RAG Agent",
     "pgvector  |  HNSW  1536d\nContexto historico",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC)
node(13.45, PY1, BW, BH, "4. Risk Agent",
     "LLM  |  6 categorias\nSPOF  Seguranca  Perf.",
     fill=C_PROC, stroke=S_PROC, txt=T_PROC)

# Linha 2
node(0.85,  PY2, BW, BH, "5. Report Agent",
     "LangChain  |  GPT-4o\nJsonOutputParser",
     fill=C_REP, stroke=S_REP, txt=T_REP)
node(5.05,  PY2, BW, BH, "6. Fine-Tuned LLM",
     "QLoRA Adapter\nHuggingFace Inference",
     fill=C_REP, stroke=S_REP, txt=T_REP)
node(9.25,  PY2, BW, BH, "7. Guardrails",
     "Grounding  |  JSON Schema\nCompletude  |  Consistencia",
     fill=C_REP, stroke=S_REP, txt=T_REP)
node(13.45, PY2, BW, BH, "8. QA Agent",
     "Score >= 0.6\nChecks deterministicos + LLM",
     fill=C_REP, stroke=S_REP, txt=T_REP)

# ══════════════════════════════════════════════════════════════════════════════
#  REPORT API
# ══════════════════════════════════════════════════════════════════════════════
group(19.3, 3.9, 5.5, 7.1,
      "Report API  |  FastAPI  |  porta :8001",
      stroke=S_CONS, tc=T_CONS, lw=1.5)
node(19.55, 9.55, 5.0, 1.1, "REST Endpoints",
     "/reports  GET / POST",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS, fs=8)
node(19.55, 8.15, 5.0, 1.1, "Repositories",
     "SQLAlchemy ORM",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS, fs=8)
node(19.55, 6.75, 5.0, 1.1, "Connection Pool",
     "psycopg  |  PostgreSQL 16",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS, fs=8)
node(19.55, 5.35, 5.0, 1.1, "Pydantic Models",
     "Structured output / Validation",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS, fs=8)
node(19.55, 4.15, 5.0, 0.9, "Python 3.12 + uvicorn",
     fill=C_CONS, stroke=S_CONS, txt=T_CONS, fs=7.5)

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════════════════
group(0.4, 0.35, 22.8, 3.3,
      "PostgreSQL 16 + pgvector  |  Docker Volume  |  porta :5432",
      stroke=S_DB, tc=T_DB, lw=1.5)
DW, DH = 5.0, 2.2
DY = 0.6
node(0.6,  DY, DW, DH, "analyses",
     "status  |  ciclo de vida\nfile_name  |  error_msg",
     fill=C_DB, stroke=S_DB, txt=T_DB)
node(6.0,  DY, DW, DH, "extraction_results",
     "Componentes extraidos\nCache intermediario",
     fill=C_DB, stroke=S_DB, txt=T_DB)
node(11.4, DY, DW, DH, "reports",
     "Relatorio final + QA\nJSON estruturado",
     fill=C_DB, stroke=S_DB, txt=T_DB)
node(16.8, DY, DW+0.8, DH, "pg_embedding",
     "Vetores 1536 dims  |  HNSW index\nRAG similaridade cosine",
     fill=C_DB, stroke=S_DB, txt=T_DB)

# ══════════════════════════════════════════════════════════════════════════════
#  LLM PROVIDERS
# ══════════════════════════════════════════════════════════════════════════════
group(23.3, 0.35, 4.3, 10.95, "LLM Providers\n(APIs Externas)",
      stroke=S_EXT, tc=T_EXT, lw=1.5)
LW2, LH2 = 3.8, 1.7
LX = 23.55
for i, (t, s) in enumerate([
    ("OpenAI API",       "GPT-4o Vision\nEmbeddings  text-3-small"),
    ("Anthropic API",    "Claude Sonnet\nMultimodal Vision"),
    ("HuggingFace",      "Inference API\nQLoRA endpoint"),
    ("Local LLM",        "PEFT / LoRA Adapter\nLocal model path"),
    ("LangChain",        "Orquestracao LLM\nJsonOutputParser"),
]):
    node(LX, 0.55 + i*2.1, LW2, LH2, t, s,
         fill=C_EXT, stroke=S_EXT, txt=T_EXT, fs=8)

# ══════════════════════════════════════════════════════════════════════════════
#  ARROWS — fluxo principal
# ══════════════════════════════════════════════════════════════════════════════

# SQS → SQS Consumer (diag)
arr(1.925, 14.1, 9.8, 10.58, label="msg + callback_url", c=S_EXT)

# S3 → Ingestion (diag)
arr(4.725, 14.1, 2.80, PY1+BH, label="bytes", c=S_EXT)

# Streamlit → /analyze
arr(2.55, 11.7, 1.95, 10.58, c=S_CONS)

# Static → /analyze/stream
arr(6.60, 11.7, 6.05, 10.58, c=S_CONS)

# /analyze → Ingestion
arr(1.95, 9.68, 2.80, PY1+BH, c=S_PROC)
arr(6.05, 9.68, 2.80+0.5, PY1+BH, c=S_PROC)
arr(9.80, 9.68, 2.80+1.0, PY1+BH, c=S_PROC)

# pipeline linha 1 horizontal
arr(0.85+BW, PY1+BH/2, 5.05, PY1+BH/2, c=S_PROC)
arr(5.05+BW, PY1+BH/2, 9.25, PY1+BH/2, c=S_PROC)
arr(9.25+BW, PY1+BH/2, 13.45, PY1+BH/2, c=S_PROC)

# Extraction → Risk (diagonal para baixo)
arr(5.05+BW/2, PY1, 15.45, PY1+BH, c="#c090ff", rad=-0.15)

# Risk → Report (vertical)
arr(15.45, PY1, 15.45, PY2+BH, label="output", c=S_REP)

# pipeline linha 2 horizontal
arr(0.85+BW, PY2+BH/2, 5.05, PY2+BH/2, label="backend switch", c=S_REP)
arr(5.05+BW, PY2+BH/2, 9.25, PY2+BH/2, c=S_REP)
arr(9.25+BW, PY2+BH/2, 13.45, PY2+BH/2, c=S_REP)

# QA → Webhook Sender
arr(13.45+BW, PY2+BH/2, 19.4, 12.5, label="report aprovado", c=S_REP)

# Webhook Sender → SOAT
arr(24.7, 11.7, 24.55, 14.1, label="POST", c=S_EXT)

# ia-service → report-api
arr(18.9, 7.5, 19.3, 7.5, label="salva relatorio", c=S_CONS)

# Streamlit → report-api
arr(4.55, 11.7, 20.3, 11.05, c=S_CONS, label="GET reports", rad=-0.15)

# ── Persistencia (dashed) ──
arr(2.80, PY1, 3.1, 2.9, label="status", c=DARROW, dash=True)
arr(7.0,  PY1, 8.5, 2.9, label="cache", c=DARROW, dash=True)
arr(15.0, PY2, 13.9, 2.9, label="relatorio", c=DARROW, dash=True)
# RAG ↔ pgvector (bidirecional)
arr(11.15, PY1+BH/2, 19.3, 1.7, label="indexa / busca", c=DARROW, dash=True)
# Report API → DB
arr(22.05, 4.15, 22.05, 2.9, c=DARROW, dash=True)

# LLM Providers → ia-service
arr(23.3, 8.95,  18.9, 8.0,  label="Vision", c=S_EXT)
arr(23.3, 6.85,  18.9, 6.0,  c=S_EXT)
arr(23.3, 5.8,   17.35+BW/2, PY2+BH, c=S_EXT)

# ══════════════════════════════════════════════════════════════════════════════
#  LEGEND
# ══════════════════════════════════════════════════════════════════════════════
hline(3.55)
items = [
    (C_EXT,  S_EXT,  T_EXT,  "Externos / AWS / LLM APIs"),
    (C_CONS, S_CONS, T_CONS, "Clientes / HTTP / Webhook"),
    (C_PROC, S_PROC, T_PROC, "Pipeline IA — Processamento"),
    (C_REP,  S_REP,  T_REP,  "Relatorio / QA / Guardrails"),
    (C_DB,   S_DB,   T_DB,   "Persistencia — PostgreSQL + pgvector"),
]
LGX, LGY = 0.6, 3.38
for i, (fc, ec, tc, lbl) in enumerate(items):
    rx = LGX + i * 4.3
    p = FancyBboxPatch((rx, LGY-0.22), 0.55, 0.28,
                       boxstyle="round,pad=0.03",
                       facecolor=fc, edgecolor=ec, linewidth=1.2, zorder=10)
    ax.add_patch(p)
    ax.text(rx+0.7, LGY-0.08, lbl, va="center",
            fontsize=7.5, color="#8b949e", fontfamily=FONT, zorder=11)

# ── Tech stack footer ──
hline(0.32)
stack = (
    "Python 3.12  ·  FastAPI  ·  Uvicorn  ·  LangChain  ·  SQLAlchemy  ·  pgvector  ·  "
    "PostgreSQL 16  ·  OpenAI GPT-4o  ·  Anthropic Claude  ·  HuggingFace / QLoRA  ·  "
    "Streamlit  ·  Docker Compose  ·  AWS SQS / S3  ·  Playwright (E2E Tests)"
)
ax.text(W/2, 0.17, stack, ha="center", va="center",
        fontsize=7.5, color="#484f58", fontfamily=FONT)

# ══════════════════════════════════════════════════════════════════════════════
#  SAVE
# ══════════════════════════════════════════════════════════════════════════════
out = "docs/architecture_hd.png"
fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
print(f"Salvo: {out}  ({W*200:.0f}x{H*200:.0f} px aprox)")

"""
Gerador do PDF de documentacao tecnica do workflow.
Usa ReportLab para PDF + ilustracoes vetoriais didaticas.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, Flowable, Image
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import (
    Drawing, Rect, String, Line, Polygon, Circle, Group, PolyLine
)
from reportlab.graphics import renderPDF
from pathlib import Path

# ---------------------------------------------------------------
# Paleta de cores
# ---------------------------------------------------------------
COLOR_PRIMARY   = HexColor("#0D47A1")
COLOR_SECONDARY = HexColor("#1976D2")
COLOR_ACCENT    = HexColor("#F57C00")
COLOR_SUCCESS   = HexColor("#2E7D32")
COLOR_DANGER    = HexColor("#B71C1C")
COLOR_WARNING   = HexColor("#E65100")
COLOR_PURPLE    = HexColor("#6A1B9A")
COLOR_PINK      = HexColor("#C2185B")
COLOR_GRAY      = HexColor("#546E7A")
COLOR_LIGHT     = HexColor("#F5F5F5")
COLOR_BORDER    = HexColor("#B0BEC5")
COLOR_TEXT      = HexColor("#263238")

# ---------------------------------------------------------------
# Estilos de texto
# ---------------------------------------------------------------
styles = getSampleStyleSheet()

style_title = ParagraphStyle(
    "TitleCover", parent=styles["Title"],
    fontName="Helvetica-Bold", fontSize=28, leading=34,
    textColor=COLOR_PRIMARY, alignment=TA_CENTER, spaceAfter=20,
)
style_subtitle = ParagraphStyle(
    "SubtitleCover", parent=styles["Heading2"],
    fontName="Helvetica", fontSize=14, leading=18,
    textColor=COLOR_GRAY, alignment=TA_CENTER, spaceAfter=12,
)
style_h1 = ParagraphStyle(
    "H1", parent=styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=18, leading=22,
    textColor=COLOR_PRIMARY, spaceBefore=16, spaceAfter=10,
)
style_h2 = ParagraphStyle(
    "H2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=13, leading=17,
    textColor=COLOR_SECONDARY, spaceBefore=10, spaceAfter=6,
)
style_h3 = ParagraphStyle(
    "H3", parent=styles["Heading3"],
    fontName="Helvetica-Bold", fontSize=11, leading=15,
    textColor=COLOR_WARNING, spaceBefore=8, spaceAfter=4,
)
style_body = ParagraphStyle(
    "Body", parent=styles["BodyText"],
    fontName="Helvetica", fontSize=10, leading=14,
    textColor=COLOR_TEXT, alignment=TA_JUSTIFY, spaceAfter=6,
)
style_note = ParagraphStyle(
    "Note", parent=styles["BodyText"],
    fontName="Helvetica-Oblique", fontSize=9, leading=12,
    textColor=COLOR_GRAY, alignment=TA_LEFT, spaceAfter=4,
)
style_caption = ParagraphStyle(
    "Caption", parent=styles["BodyText"],
    fontName="Helvetica-Oblique", fontSize=9, leading=11,
    textColor=COLOR_GRAY, alignment=TA_CENTER, spaceAfter=10, spaceBefore=2,
)
style_code = ParagraphStyle(
    "Code", parent=styles["BodyText"],
    fontName="Courier", fontSize=8.5, leading=11,
    textColor=COLOR_TEXT, backColor=COLOR_LIGHT,
    borderColor=COLOR_BORDER, borderWidth=0.5, borderPadding=6,
    leftIndent=6, rightIndent=6, spaceAfter=8, spaceBefore=4,
)
style_toc = ParagraphStyle(
    "TOC", parent=styles["BodyText"],
    fontName="Helvetica", fontSize=10, leading=16, textColor=COLOR_TEXT,
)


# ---------------------------------------------------------------
# Helpers de desenho vetorial (ilustracoes didaticas)
# ---------------------------------------------------------------
def rounded_box(d, x, y, w, h, fill, stroke, label, font_size=9, text_color=None):
    """Caixa retangular arredondada com texto centralizado (multi-linhas \\n)."""
    r = Rect(x, y, w, h, rx=4, ry=4)
    r.fillColor = fill
    r.strokeColor = stroke
    r.strokeWidth = 1
    d.add(r)
    lines = label.split("\n")
    total_h = len(lines) * (font_size + 1)
    start_y = y + h/2 + total_h/2 - font_size
    for i, line in enumerate(lines):
        s = String(x + w/2, start_y - i*(font_size + 1), line,
                   fontName="Helvetica-Bold" if i == 0 else "Helvetica",
                   fontSize=font_size,
                   fillColor=text_color or black,
                   textAnchor="middle")
        d.add(s)


def arrow(d, x1, y1, x2, y2, color=black, width=1, dashed=False, label=None):
    """Seta simples com ponta triangular."""
    line = Line(x1, y1, x2, y2)
    line.strokeColor = color
    line.strokeWidth = width
    if dashed:
        line.strokeDashArray = [3, 3]
    d.add(line)
    # ponta de seta
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 5
    ax1 = x2 - size * math.cos(angle - math.pi/6)
    ay1 = y2 - size * math.sin(angle - math.pi/6)
    ax2 = x2 - size * math.cos(angle + math.pi/6)
    ay2 = y2 - size * math.sin(angle + math.pi/6)
    head = Polygon(points=[x2, y2, ax1, ay1, ax2, ay2])
    head.fillColor = color
    head.strokeColor = color
    d.add(head)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2 + 4
        d.add(String(mx, my, label, fontName="Helvetica", fontSize=7,
                     fillColor=color, textAnchor="middle"))


def cylinder(d, x, y, w, h, fill, stroke, label, font_size=8):
    """Cilindro para banco de dados."""
    ellipse_h = 8
    # corpo
    r = Rect(x, y, w, h - ellipse_h)
    r.fillColor = fill
    r.strokeColor = stroke
    d.add(r)
    # topo elipse simulada como poligono
    # linha superior
    d.add(Line(x, y + h - ellipse_h, x, y + h - ellipse_h/2, strokeColor=stroke))
    d.add(Line(x + w, y + h - ellipse_h, x + w, y + h - ellipse_h/2, strokeColor=stroke))
    top = Polygon(points=[
        x, y + h - ellipse_h/2,
        x + w/4, y + h,
        x + 3*w/4, y + h,
        x + w, y + h - ellipse_h/2,
    ])
    top.fillColor = fill
    top.strokeColor = stroke
    d.add(top)
    lines = label.split("\n")
    total_h = len(lines) * (font_size + 1)
    start_y = y + (h - ellipse_h)/2 + total_h/2 - font_size
    for i, line in enumerate(lines):
        d.add(String(x + w/2, start_y - i*(font_size + 1), line,
                     fontName="Helvetica-Bold" if i == 0 else "Helvetica",
                     fontSize=font_size,
                     textAnchor="middle"))


# ---------------------------------------------------------------
# Ilustracao 1: Arquitetura de alto nivel
# ---------------------------------------------------------------
def draw_architecture_overview():
    d = Drawing(480, 340)
    # titulo
    d.add(String(240, 320, "Arquitetura de Alto Nivel",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_PRIMARY, textAnchor="middle"))

    # Usuario
    rounded_box(d, 10, 250, 70, 40, COLOR_LIGHT, COLOR_GRAY, "Usuario", 9)
    # Streamlit
    rounded_box(d, 100, 250, 90, 40, HexColor("#C8E6C9"), COLOR_SUCCESS,
                "Streamlit\n:8501", 9, COLOR_SUCCESS)
    arrow(d, 82, 270, 98, 270, COLOR_GRAY, 1.5)

    # ia-service
    rounded_box(d, 220, 250, 110, 40, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "ia-service\n:8000 (FastAPI)", 9, COLOR_PRIMARY)
    arrow(d, 192, 270, 218, 270, COLOR_GRAY, 1.5, label="POST")

    # Celery
    rounded_box(d, 360, 250, 100, 40, HexColor("#E1BEE7"), COLOR_PURPLE,
                "Celery Worker\n(pipeline)", 9, COLOR_PURPLE)
    arrow(d, 332, 270, 358, 270, COLOR_GRAY, 1.5, label="dispatch")

    # Redis
    cylinder(d, 380, 170, 80, 50, HexColor("#F8BBD0"), COLOR_PINK,
             "Redis :6379\nbroker + pub/sub", 8)
    arrow(d, 410, 248, 410, 222, COLOR_GRAY, 1.5)
    # SSE back
    arrow(d, 385, 222, 275, 248, COLOR_SECONDARY, 1, dashed=True, label="SSE")

    # report-api
    rounded_box(d, 100, 170, 110, 40, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "report-api\n:8001 (read-only)", 9, COLOR_PRIMARY)
    arrow(d, 145, 248, 145, 212, COLOR_GRAY, 1.5)

    # PostgreSQL (compartilhado)
    cylinder(d, 140, 70, 240, 70, HexColor("#E1BEE7"), COLOR_PURPLE,
             "PostgreSQL + pgvector :5432\nanalyses / extraction_results / reports\nlangchain_pg_embedding (HNSW)", 8)
    arrow(d, 260, 248, 260, 142, COLOR_GRAY, 1.5, label="persist")
    arrow(d, 155, 170, 200, 140, COLOR_GRAY, 1)
    arrow(d, 400, 168, 320, 140, COLOR_GRAY, 1, dashed=True, label="RAG")

    # Externos
    rounded_box(d, 10, 170, 70, 40, HexColor("#CFD8DC"), COLOR_GRAY,
                "AWS SQS\n(opcional)", 8, COLOR_GRAY)
    arrow(d, 80, 190, 218, 260, COLOR_GRAY, 1, dashed=True)

    return d


# ---------------------------------------------------------------
# Ilustracao 2: Pipeline de 8 etapas
# ---------------------------------------------------------------
def draw_pipeline():
    d = Drawing(520, 260)
    d.add(String(260, 240, "Pipeline de IA - 8 Etapas Sequenciais",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_WARNING, textAnchor="middle"))

    steps = [
        ("0", "Input\nGuardrails",      HexColor("#FFE0B2")),
        ("1", "Ingestion\n(base64)",    HexColor("#FFE0B2")),
        ("2", "Classification\n(Vision)", HexColor("#FFE0B2")),
        ("3", "Extraction\n(Vision)",   HexColor("#FFCC80")),
        ("3.5", "Guardrail\nExtracao",  HexColor("#FFE0B2")),
        ("4", "RAG\n(pgvector)",        HexColor("#FFE0B2")),
        ("5", "Report +\nRiscos",       HexColor("#FFCC80")),
        ("5.5", "Output\nGuardrails",   HexColor("#FFE0B2")),
        ("6", "QA\n(2 fases)",          HexColor("#FFE0B2")),
        ("7", "Persist +\nWebhook",     HexColor("#FFAB91")),
    ]
    box_w, box_h = 48, 45
    gap = 3
    total_width = len(steps) * (box_w + gap) - gap
    start_x = (520 - total_width) / 2
    y = 170
    for i, (num, label, color) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        rounded_box(d, x, y, box_w, box_h, color, COLOR_WARNING,
                    f"{num}\n{label}", 7, COLOR_WARNING)
        if i < len(steps) - 1:
            arrow(d, x + box_w, y + box_h/2, x + box_w + gap, y + box_h/2,
                  COLOR_WARNING, 1)

    # Loop de refinamento (QA -> Report)
    qa_idx = 8
    report_idx = 6
    qa_x = start_x + qa_idx * (box_w + gap) + box_w/2
    rep_x = start_x + report_idx * (box_w + gap) + box_w/2
    d.add(Line(qa_x, y, qa_x, y - 15, strokeColor=COLOR_DANGER, strokeWidth=1,
               strokeDashArray=[3, 3]))
    d.add(Line(rep_x, y, rep_x, y - 15, strokeColor=COLOR_DANGER, strokeWidth=1,
               strokeDashArray=[3, 3]))
    d.add(Line(rep_x, y - 15, qa_x, y - 15, strokeColor=COLOR_DANGER,
               strokeWidth=1, strokeDashArray=[3, 3]))
    arrow(d, rep_x + 3, y - 15, rep_x, y - 3, COLOR_DANGER, 1)
    d.add(String((rep_x + qa_x) / 2, y - 25,
                 "QA rejeitado -> re-gera (max 2x)",
                 fontName="Helvetica-Oblique", fontSize=7,
                 fillColor=COLOR_DANGER, textAnchor="middle"))

    # Legenda bloqueante x non-blocking
    legend_y = 110
    rounded_box(d, 20, legend_y, 80, 18, HexColor("#FFCC80"), COLOR_WARNING,
                "BLOQUEANTE", 8, COLOR_WARNING)
    d.add(String(110, legend_y + 7, "falha -> pipeline para",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))
    rounded_box(d, 270, legend_y, 80, 18, HexColor("#FFE0B2"), COLOR_WARNING,
                "non-blocking", 8, COLOR_WARNING)
    d.add(String(360, legend_y + 7, "falha -> fallback seguro",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))

    # Nota sobre ground truth
    d.add(String(260, 80, "ExtractionResult = Ground Truth",
                 fontName="Helvetica-Bold", fontSize=9,
                 fillColor=COLOR_DANGER, textAnchor="middle"))
    d.add(String(260, 68, "Todas as etapas seguintes sao validadas contra ele (anti-alucinacao)",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))

    return d


# ---------------------------------------------------------------
# Ilustracao 3: Fluxo Streamlit com SSE
# ---------------------------------------------------------------
def draw_streamlit_flow():
    d = Drawing(500, 340)
    d.add(String(250, 320, "Caminho A - Upload Streamlit (fluxo principal)",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_PRIMARY, textAnchor="middle"))

    # Lanes
    lanes = [
        (60,  "Usuario",   COLOR_GRAY),
        (160, "Streamlit", COLOR_SUCCESS),
        (260, "ia-service", COLOR_PRIMARY),
        (360, "Celery",     COLOR_PURPLE),
        (440, "Redis",      COLOR_PINK),
    ]
    for x, name, color in lanes:
        d.add(Line(x, 30, x, 290, strokeColor=COLOR_BORDER, strokeWidth=0.5,
                   strokeDashArray=[2, 2]))
        rounded_box(d, x - 30, 292, 60, 18, COLOR_LIGHT, color, name, 8, color)

    # Passos
    def step(y, fr, to, label, color=COLOR_TEXT, dashed=False):
        arrow(d, fr, y, to, y, color, 1, dashed=dashed)
        # Label alinhado a direita/esquerda
        if fr < to:
            tx = (fr + to) / 2
        else:
            tx = (fr + to) / 2
        d.add(String(tx, y + 4, label, fontName="Helvetica", fontSize=7,
                     fillColor=color, textAnchor="middle"))

    # 1. upload
    step(275, 60, 160, "1. upload PNG/PDF")
    # 2. POST /analyze/async
    step(255, 160, 260, "2. POST /analyze/async")
    # 3. dispatch
    step(235, 260, 360, "3. dispatch task", COLOR_PURPLE)
    # 4. 202 job_id (retorno)
    step(215, 260, 160, "4. 202 {job_id}", COLOR_SECONDARY)
    # 5. SSE subscribe
    step(195, 160, 260, "5. GET /jobs/{id}/events (SSE)", COLOR_SECONDARY)
    # ia-service SUBSCRIBE redis
    step(175, 260, 440, "6. SUBSCRIBE job:{id}", COLOR_PINK, dashed=True)
    # Celery publica eventos
    step(155, 360, 440, "7. publish(running/done)", COLOR_PURPLE)
    # Redis empurra para ia-service
    step(135, 440, 260, "8. evento", COLOR_PINK, dashed=True)
    # ia-service repassa para Streamlit
    step(115, 260, 160, "9. SSE event", COLOR_SECONDARY, dashed=True)
    # Streamlit renderiza para usuario
    step(95,  160, 60,  "10. atualiza UI", COLOR_SUCCESS)

    # Nota sobre pipeline
    rounded_box(d, 335, 40, 120, 40, HexColor("#FFE0B2"), COLOR_WARNING,
                "PIPELINE\nexecuta em Celery\nemite 8+ eventos", 8, COLOR_WARNING)

    return d


# ---------------------------------------------------------------
# Ilustracao 4: Fluxo SQS + S3 + Webhook
# ---------------------------------------------------------------
def draw_sqs_flow():
    d = Drawing(500, 320)
    d.add(String(250, 300, "Caminho B - AWS SQS + S3 + Webhook (SOAT)",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_GRAY, textAnchor="middle"))

    # SOAT
    rounded_box(d, 20, 240, 80, 40, HexColor("#CFD8DC"), COLOR_GRAY,
                "SOAT\n(publicador)", 9, COLOR_GRAY)
    # SQS
    rounded_box(d, 150, 240, 80, 40, HexColor("#CFD8DC"), COLOR_GRAY,
                "AWS SQS", 9, COLOR_GRAY)
    # Consumer
    rounded_box(d, 280, 240, 100, 40, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "Consumer Thread\n(long polling 20s)", 8, COLOR_PRIMARY)
    # S3
    rounded_box(d, 280, 170, 100, 35, HexColor("#CFD8DC"), COLOR_GRAY,
                "AWS S3", 9, COLOR_GRAY)
    # Pipeline
    rounded_box(d, 280, 100, 100, 45, HexColor("#FFCC80"), COLOR_WARNING,
                "PIPELINE\n(8 etapas)", 9, COLOR_WARNING)
    # Webhook
    rounded_box(d, 400, 100, 80, 45, HexColor("#CFD8DC"), COLOR_GRAY,
                "Webhook\ncallback", 9, COLOR_GRAY)
    # DB
    cylinder(d, 140, 100, 120, 45, HexColor("#E1BEE7"), COLOR_PURPLE,
             "PostgreSQL", 9)

    # Setas numeradas
    arrow(d, 100, 260, 148, 260, COLOR_GRAY, 1.5, label="1. publica")
    arrow(d, 230, 260, 278, 260, COLOR_GRAY, 1.5, label="2. receive")
    arrow(d, 330, 238, 330, 208, COLOR_GRAY, 1.5, label="3. download")
    arrow(d, 330, 168, 330, 148, COLOR_WARNING, 1.5, label="4. run_pipeline")
    arrow(d, 280, 122, 262, 122, COLOR_PURPLE, 1.5, label="5. persist")
    arrow(d, 380, 122, 398, 122, COLOR_GRAY, 1.5, label="6. POST callback")
    arrow(d, 330, 95, 330, 60, COLOR_SUCCESS, 1.5, dashed=True)
    d.add(String(380, 70, "7. delete_message (ACK)",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_SUCCESS,
                 textAnchor="middle"))

    # Nota
    d.add(String(250, 30,
                 "Retry 3x (backoff expo) no download. Webhook nao bloqueia - resultado ja persistido.",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))

    return d


# ---------------------------------------------------------------
# Ilustracao 5: Maquina de estados
# ---------------------------------------------------------------
def draw_state_machine():
    d = Drawing(480, 180)
    d.add(String(240, 165, "Maquina de Estados da Analise",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_PURPLE, textAnchor="middle"))

    # Estados
    rounded_box(d,  30, 80, 90, 40, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "recebido", 10, COLOR_PRIMARY)
    rounded_box(d, 160, 80, 120, 40, HexColor("#FFE0B2"), COLOR_WARNING,
                "em_processamento", 10, COLOR_WARNING)
    rounded_box(d, 330, 120, 110, 35, HexColor("#C8E6C9"), COLOR_SUCCESS,
                "analisado", 10, COLOR_SUCCESS)
    rounded_box(d, 330, 40, 110, 35, HexColor("#FFCDD2"), COLOR_DANGER,
                "erro", 10, COLOR_DANGER)

    # Transicoes
    arrow(d, 120, 100, 158, 100, COLOR_PRIMARY, 1.5, label="start_ingestion")
    arrow(d, 280, 110, 328, 135, COLOR_SUCCESS, 1.5, label="complete")
    arrow(d, 280, 90, 328, 60, COLOR_DANGER, 1.5, label="fail")
    # qualquer estado pode ir para erro
    arrow(d, 90, 80, 330, 55, COLOR_DANGER, 0.8, dashed=True)

    d.add(String(240, 15,
                 "Invariante: apenas 'recebido' pode transitar para 'em_processamento'. "
                 "Qualquer estado pode ir para 'erro'.",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))
    return d


# ---------------------------------------------------------------
# Ilustracao 6: Arquitetura Hexagonal (camadas)
# ---------------------------------------------------------------
def draw_hexagonal():
    d = Drawing(480, 320)
    d.add(String(240, 300, "Arquitetura Hexagonal (Ports & Adapters)",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_PRIMARY, textAnchor="middle"))

    # Camada externa: Infrastructure
    rounded_box(d, 40, 40, 400, 240, HexColor("#FFF3E0"), COLOR_WARNING,
                "", 9)
    d.add(String(70, 260, "INFRASTRUCTURE (Adapters)",
                 fontName="Helvetica-Bold", fontSize=10, fillColor=COLOR_WARNING))
    d.add(String(70, 247, "OpenAIVisionAdapter . OpenAITextAdapter . PGVectorAdapter . SQLAlchemyRepository",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))

    # Camada media: Application
    rounded_box(d, 80, 80, 320, 160, HexColor("#E3F2FD"), COLOR_SECONDARY, "", 9)
    d.add(String(100, 220, "APPLICATION (Use Cases + Ports)",
                 fontName="Helvetica-Bold", fontSize=10, fillColor=COLOR_SECONDARY))
    d.add(String(100, 207, "AnalyzeDiagramUseCase . RetrieveReportUseCase",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))
    d.add(String(100, 195, "Ports: IVisionLLM . ITextLLM . IVectorStore . IRepository",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))

    # Camada interna: Domain
    rounded_box(d, 130, 110, 220, 100, HexColor("#F3E5F5"), COLOR_PURPLE, "", 9)
    d.add(String(150, 190, "DOMAIN (DDD - nucleo puro)",
                 fontName="Helvetica-Bold", fontSize=10, fillColor=COLOR_PURPLE))
    d.add(String(150, 175, "AnalysisAggregate . ReportAggregate",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))
    d.add(String(150, 163, "Value Objects . Domain Events",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))
    d.add(String(150, 151, "GuardrailService . InputGuardrailService",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))
    d.add(String(150, 139, "OutputGuardrailService",
                 fontName="Helvetica", fontSize=8, fillColor=COLOR_TEXT))

    # Setas indicando regra de dependencia (apontam para dentro)
    arrow(d, 20, 160, 78, 160, COLOR_DANGER, 1.5)
    d.add(String(12, 163, "deps", fontName="Helvetica-Bold", fontSize=8,
                 fillColor=COLOR_DANGER, textAnchor="end"))

    # Nota
    d.add(String(240, 20,
                 "Regra: dependencias apontam SEMPRE para dentro. Domain nao importa nada externo.",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))
    return d


# ---------------------------------------------------------------
# Ilustracao 7: Ground Truth (ExtractionResult como ancora)
# ---------------------------------------------------------------
def draw_ground_truth():
    d = Drawing(460, 240)
    d.add(String(230, 220, "Convergencia via Ground Truth",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_DANGER, textAnchor="middle"))

    # Centro: Extraction
    rounded_box(d, 150, 120, 160, 60, HexColor("#FFCC80"), COLOR_WARNING,
                "ExtractionResult\n(GROUND TRUTH)", 10, COLOR_WARNING)
    d.add(String(230, 108, "componentes / relacoes / padroes",
                 fontName="Helvetica", fontSize=7,
                 fillColor=COLOR_GRAY, textAnchor="middle"))

    # Ramos
    rounded_box(d,  30, 50, 110, 40, HexColor("#E1BEE7"), COLOR_PURPLE,
                "RAG\nbusca similares", 9, COLOR_PURPLE)
    rounded_box(d, 175, 30, 110, 50, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "Report\ngrounding <= 20%\n(max alucinacao)", 8, COLOR_PRIMARY)
    rounded_box(d, 320, 50, 110, 40, HexColor("#C8E6C9"), COLOR_SUCCESS,
                "QA\noverlap >= 80%", 9, COLOR_SUCCESS)

    # Setas
    arrow(d, 180, 120, 110, 90, COLOR_PURPLE, 1.5)
    arrow(d, 230, 120, 230, 82, COLOR_PRIMARY, 1.5)
    arrow(d, 280, 120, 350, 90, COLOR_SUCCESS, 1.5)

    # Nota
    d.add(String(230, 10,
                 "Todas as etapas sao validadas contra a extracao - evita alucinacao.",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))
    return d


# ---------------------------------------------------------------
# Ilustracao 8: Camadas de Guardrails
# ---------------------------------------------------------------
def draw_guardrails():
    d = Drawing(480, 250)
    d.add(String(240, 235, "3 Camadas de Guardrails",
                 fontName="Helvetica-Bold", fontSize=12,
                 fillColor=COLOR_DANGER, textAnchor="middle"))

    # Input
    rounded_box(d, 30, 140, 130, 70, HexColor("#FFCDD2"), COLOR_DANGER,
                "INPUT GUARDRAILS", 10, COLOR_DANGER)
    d.add(String(95, 185, "antes do LLM",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_DANGER, textAnchor="middle"))
    d.add(String(95, 172, "- sanitiza filename", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(95, 162, "- prompt injection", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(95, 152, "- schema da extracao", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))

    # Report / Domain
    rounded_box(d, 175, 140, 130, 70, HexColor("#FFE0B2"), COLOR_WARNING,
                "REPORT GUARDRAIL", 10, COLOR_WARNING)
    d.add(String(240, 185, "apos geracao",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_WARNING, textAnchor="middle"))
    d.add(String(240, 172, "- grounding <= 20%", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(240, 162, "- componentes > 0", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(240, 152, "- summary >= 100ch", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))

    # Output
    rounded_box(d, 320, 140, 130, 70, HexColor("#C8E6C9"), COLOR_SUCCESS,
                "OUTPUT GUARDRAILS", 10, COLOR_SUCCESS)
    d.add(String(385, 185, "antes de entregar",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_SUCCESS, textAnchor="middle"))
    d.add(String(385, 172, "- schema + tipos", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(385, 162, "- PII redaction", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(385, 152, "- conteudo proibido", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))

    # Fluxo geral
    arrow(d, 160, 175, 174, 175, COLOR_TEXT, 1.5)
    arrow(d, 305, 175, 319, 175, COLOR_TEXT, 1.5)

    # QA
    rounded_box(d, 175, 60, 130, 50, HexColor("#BBDEFB"), COLOR_PRIMARY,
                "QA (2 fases)\ndeterministico + LLM", 9, COLOR_PRIMARY)
    d.add(String(240, 49, "- overlap >= 80%", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))
    d.add(String(240, 39, "- score >= 0.6", fontName="Helvetica",
                 fontSize=7, fillColor=COLOR_TEXT, textAnchor="middle"))

    arrow(d, 240, 140, 240, 112, COLOR_PRIMARY, 1.5)

    d.add(String(240, 15,
                 "Defesa em profundidade: filtros multiplos, nao apenas prompt engineering.",
                 fontName="Helvetica-Oblique", fontSize=8,
                 fillColor=COLOR_GRAY, textAnchor="middle"))

    return d


# ---------------------------------------------------------------
# Helpers de conteudo
# ---------------------------------------------------------------
def p(text):
    return Paragraph(text, style_body)

def h1(text):
    return Paragraph(text, style_h1)

def h2(text):
    return Paragraph(text, style_h2)

def h3(text):
    return Paragraph(text, style_h3)

def code(text):
    # replace newlines with <br/> for Paragraph
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>"))
    return Paragraph(safe, style_code)

def caption(text):
    return Paragraph(f"<i>Figura: {text}</i>", style_caption)

def drawing_block(drawing, caption_text):
    return KeepTogether([Spacer(1, 4), drawing, caption(caption_text)])

def bullets(items):
    style = ParagraphStyle(
        "Bullet", parent=style_body, leftIndent=18, bulletIndent=6,
        spaceAfter=2
    )
    return [Paragraph(f"&bull; {item}", style) for item in items]


# ---------------------------------------------------------------
# Callback para numeracao de paginas + cabecalho
# ---------------------------------------------------------------
def on_page(canvas_obj, doc):
    canvas_obj.saveState()
    page_num = canvas_obj.getPageNumber()
    # Skip header on cover
    if page_num > 1:
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(COLOR_GRAY)
        canvas_obj.drawString(2*cm, A4[1] - 1.3*cm,
                              "Hackathon FIAP - IADT . Workflow do Sistema")
        canvas_obj.setStrokeColor(COLOR_BORDER)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(2*cm, A4[1] - 1.5*cm, A4[0] - 2*cm, A4[1] - 1.5*cm)
    # Rodape
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(COLOR_GRAY)
    canvas_obj.drawRightString(A4[0] - 2*cm, 1.2*cm, f"Pagina {page_num}")
    canvas_obj.drawString(2*cm, 1.2*cm, "IADT . 2026")
    canvas_obj.restoreState()


# ---------------------------------------------------------------
# Construcao do documento
# ---------------------------------------------------------------
def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title="Workflow do Sistema - Hackathon FIAP IADT",
        author="Time IADT",
    )
    story = []

    # ------------------- CAPA -------------------
    story.append(Spacer(1, 4*cm))
    story.append(Paragraph("DOCUMENTACAO TECNICA", style_subtitle))
    story.append(Paragraph("Workflow do Sistema", style_title))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Analise Automatizada de Diagramas de Arquitetura com IA",
                           style_subtitle))
    story.append(Spacer(1, 2*cm))

    cover_table = Table([
        ["Projeto",    "Hackathon FIAP - Time IADT"],
        ["Versao",     "1.0"],
        ["Data",       "2026-04-16"],
        ["Stack",      "Python, FastAPI, Celery, Redis, PostgreSQL+pgvector, LangChain, OpenAI gpt-4o"],
        ["Padroes",    "DDD + Arquitetura Hexagonal (Ports & Adapters)"],
        ["Servicos",   "ia-service (8000), report-api (8001), streamlit-app (8501), celery-worker, redis, pgvector"],
    ], colWidths=[3.5*cm, 12*cm])
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), COLOR_LIGHT),
        ("TEXTCOLOR",  (0, 0), (0, -1), COLOR_PRIMARY),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",   (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("GRID",       (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(cover_table)
    story.append(PageBreak())

    # ------------------- SUMARIO -------------------
    story.append(h1("Sumario"))
    toc_items = [
        ("1.",  "Visao Geral do Sistema", "cap. 1"),
        ("2.",  "Workflow Principal - Visao de Alto Nivel", "cap. 2"),
        ("3.",  "Workflow Detalhado - Caminho A (Streamlit)", "cap. 3"),
        ("4.",  "Workflow Detalhado - Caminho B (AWS SQS)", "cap. 4"),
        ("5.",  "Pipeline de IA - As 5 Etapas + Guardrails", "cap. 5"),
        ("6.",  "Convergencia e Tratamento de Falhas", "cap. 6"),
        ("7.",  "Persistencia e Observabilidade", "cap. 7"),
        ("8.",  "Workflow de Consulta de Relatorio", "cap. 8"),
        ("9.",  "Resumo Visual do Workflow", "cap. 9"),
        ("10.", "Glossario", "cap. 10"),
    ]
    tbl = Table(
        [[n, t, r] for n, t, r in toc_items],
        colWidths=[1.2*cm, 12.5*cm, 2*cm]
    )
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), COLOR_PRIMARY),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Oblique"),
        ("TEXTCOLOR", (2, 0), (2, -1), COLOR_GRAY),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, COLOR_BORDER),
    ]))
    story.append(tbl)
    story.append(PageBreak())

    # ------------------- CAPITULO 1 -------------------
    story.append(h1("1. Visao Geral do Sistema"))
    story.append(h2("1.1  O que o sistema faz"))
    story.append(p(
        "O sistema automatiza a analise de diagramas de arquitetura de software. "
        "Recebe uma imagem (PNG, JPG, JPEG, GIF, WEBP) ou PDF e devolve um "
        "relatorio tecnico estruturado contendo:"
    ))
    story.extend(bullets([
        "<b>Componentes</b> identificados no diagrama",
        "<b>Relacionamentos</b> entre componentes",
        "<b>Padroes arquiteturais</b> reconhecidos",
        "<b>Riscos</b> em 6 categorias (SPOF, Seguranca, Escalabilidade, "
        "Acoplamento, Observabilidade, Resiliencia) com severidade ALTO/MEDIO/BAIXO",
        "<b>Recomendacoes</b> de melhoria (marcadas com [RAG] quando vindas do historico)",
        "<b>Sumario executivo</b>",
        "<b>Score de QA</b> (0 a 1) validando o proprio relatorio",
    ]))

    story.append(h2("1.2  Atores e componentes"))
    actors = Table([
        ["Ator / Componente", "Papel"],
        ["Usuario final",         "faz upload do diagrama pelo Streamlit"],
        ["Time SOAT",             "publica mensagens no SQS com URL do S3"],
        ["ia-service",            "orquestrador do pipeline"],
        ["Celery Worker",         "executa o pipeline em background"],
        ["Redis",                 "broker do Celery + pub/sub de eventos SSE"],
        ["PostgreSQL + pgvector", "persiste analises, relatorios e embeddings"],
        ["OpenAI (gpt-4o)",       "LLM Vision (extracao) + LLM Text (relatorio, QA)"],
        ["report-api",            "API read-only para consulta de relatorios"],
    ], colWidths=[4.5*cm, 11*cm])
    actors.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(actors)
    story.append(Spacer(1, 10))

    story.append(h2("1.3  Mapa de componentes"))
    story.append(drawing_block(draw_architecture_overview(),
                               "Visao de alto nivel dos servicos e fluxos principais"))

    story.append(h2("1.4  Arquitetura em camadas"))
    story.append(p(
        "O ia-service adota <b>Arquitetura Hexagonal</b> (Ports &amp; Adapters). "
        "As dependencias apontam sempre para dentro: Infrastructure depende de "
        "Application, que depende de Domain. O nucleo do dominio nao conhece "
        "nada externo."
    ))
    story.append(drawing_block(draw_hexagonal(),
                               "Camadas - dependencias sempre apontam para dentro"))

    story.append(h2("1.5  Fluxos de entrada (3 caminhos, mesmo pipeline)"))
    story.extend(bullets([
        "<b>Caminho A - Upload via Streamlit:</b> Streamlit -&gt; POST /analyze/async -&gt; Celery -&gt; pipeline -&gt; SSE",
        "<b>Caminho B - AWS SQS:</b> SOAT -&gt; SQS -&gt; Consumer -&gt; S3 download -&gt; pipeline -&gt; Webhook",
        "<b>Caminho C - API direta (testes):</b> cliente -&gt; POST /analyze (sincrono) -&gt; pipeline -&gt; JSON",
    ]))
    story.append(p(
        "Todos convergem para <font face='Courier'>AnalyzeDiagramUseCase.execute()</font> "
        "(<font face='Courier'>application/use_cases/analyze_diagram.py</font>), "
        "garantindo consistencia de comportamento."
    ))

    story.append(PageBreak())

    # ------------------- CAPITULO 2 -------------------
    story.append(h1("2. Workflow Principal - Visao de Alto Nivel"))
    story.append(h2("2.1  Fluxo ponta-a-ponta"))
    story.append(p(
        "O fluxo parte do upload do diagrama, passa pelas 8 etapas do pipeline "
        "de IA e termina com o relatorio persistido no banco e entregue ao "
        "solicitante (via SSE ou webhook)."
    ))
    story.append(drawing_block(draw_pipeline(),
                               "Pipeline de IA com 8 etapas e loop de refinamento do QA"))

    story.append(h2("2.2  Estados de uma analise"))
    story.append(p(
        "Toda analise tem um ciclo de vida com 4 estados possiveis. A "
        "maquina de estados e protegida pelo <b>AnalysisAggregate</b> (DDD), "
        "que garante invariantes e emite <b>Domain Events</b> a cada transicao."
    ))
    story.append(drawing_block(draw_state_machine(),
                               "Maquina de estados do AnalysisAggregate"))
    story.append(PageBreak())

    # ------------------- CAPITULO 3 -------------------
    story.append(h1("3. Workflow Detalhado - Caminho A (Streamlit)"))
    story.append(p(
        "Este e o fluxo principal. Use este capitulo como referencia para "
        "rastrear e debugar. Cada passo aqui e numerado em ordem temporal."
    ))
    story.append(drawing_block(draw_streamlit_flow(),
                               "Sequencia das mensagens entre Usuario, Streamlit, ia-service, Celery e Redis"))

    # Passos detalhados
    passos_a = [
        ("Passo 1 - Upload do diagrama",
         "O usuario arrasta o arquivo na UI do Streamlit (:8501). O Streamlit le os bytes e mostra preview se for imagem. Ao clicar em <b>Analisar Diagrama</b>, monta um multipart/form-data e dispara a requisicao."),
        ("Passo 2 - POST /analyze/async",
         "O Streamlit envia o arquivo ao ia-service em modo assincrono. O ia-service responde em menos de 100ms com <font face='Courier'>HTTP 202 Accepted</font> e um <font face='Courier'>job_id</font> (UUID) usado para tracking via Redis."),
        ("Passo 3 - ia-service cria job e dispara task Celery",
         "O ia-service gera um <font face='Courier'>job_id</font>, serializa o arquivo como <font face='Courier'>file_hex</font> (hex preserva bytes em JSON) e chama <font face='Courier'>analyze_diagram_task.delay(file_hex, file_name, job_id)</font>. O Celery publica a task no Redis (broker)."),
        ("Passo 4 - Streamlit abre stream SSE",
         "Imediatamente apos receber o <font face='Courier'>job_id</font>, o Streamlit inicia <font face='Courier'>GET /jobs/{job_id}/events</font>. Do lado do ia-service, o endpoint faz <font face='Courier'>SUBSCRIBE</font> no canal Redis <font face='Courier'>job:{id}</font> e repassa cada mensagem como evento SSE."),
        ("Passo 5 - Celery Worker consome a task",
         "O Worker (concurrency=2) faz polling no Redis, pega a task, decodifica <font face='Courier'>file_hex -&gt; bytes</font>, abre a sessao no banco e monta o <b>AnalyzeDiagramUseCase</b> via Composition Root."),
        ("Passo 6 - Worker executa pipeline e publica eventos",
         "Para cada etapa, o worker publica um evento <font face='Courier'>running</font> antes e <font face='Courier'>done</font> apos concluir (com metricas: tempo decorrido, contagens). Em falha bloqueante, publica <font face='Courier'>error</font> e atualiza <font face='Courier'>analysis.status='erro'</font>."),
        ("Passo 7 - Streamlit consome e renderiza",
         "O Streamlit atualiza a UI incrementalmente a cada evento. No evento final <font face='Courier'>step=done</font>, fecha o stream e renderiza o relatorio completo: sumario, componentes (grid), riscos (expanders com badges), recomendacoes (separando [RAG] das demais), score de QA e botao de download."),
    ]
    for titulo, texto in passos_a:
        story.append(h3(titulo))
        story.append(p(texto))
    story.append(PageBreak())

    # ------------------- CAPITULO 4 -------------------
    story.append(h1("4. Workflow Detalhado - Caminho B (AWS SQS)"))
    story.append(p(
        "Fluxo de producao acionado pelo time SOAT. Nao exige o Streamlit - "
        "o retorno e entregue por webhook HTTP."
    ))
    story.append(drawing_block(draw_sqs_flow(),
                               "Consumer SQS com idempotencia, download do S3, pipeline e webhook"))

    passos_b = [
        ("Passo 1 - SOAT publica mensagem no SQS",
         "O SOAT faz upload no S3 e publica JSON na fila SQS com: <font face='Courier'>file_name</font>, <font face='Courier'>s3_url</font> e <font face='Courier'>callback_url</font>."),
        ("Passo 2 - Consumer thread recebe",
         "Thread daemon iniciada no startup do FastAPI. Long polling com <font face='Courier'>WaitTimeSeconds=20</font>, <font face='Courier'>MaxMessages=5</font>, <font face='Courier'>VisibilityTimeout=300s</font>."),
        ("Passo 3 - Idempotencia e poison pill",
         "Verifica <font face='Courier'>sqs_message_id</font> na tabela <font face='Courier'>analyses</font>: se ja existe, descarta. Se <font face='Courier'>ApproximateReceiveCount &gt; 3</font>, loga warning de poison pill."),
        ("Passo 4 - Download do S3",
         "Usa <font face='Courier'>tenacity</font> com 3 tentativas e backoff exponencial (2s -&gt; 4s -&gt; 10s). Falha total marca a analise como erro, envia webhook e deleta a mensagem."),
        ("Passo 5 - Execucao do pipeline",
         "Chama <font face='Courier'>run_pipeline(file_bytes, file_name)</font>, que delega ao mesmo AnalyzeDiagramUseCase. As 8 etapas executam identicamente ao caminho A (sem Celery - a fila ja prove a assincronia)."),
        ("Passo 6 - Webhook de devolutiva",
         "POST para <font face='Courier'>callback_url</font> com JSON de sucesso ou erro. Retry 3x (backoff 2s/4s/8s) em 5xx e timeout; nao retenta 4xx. Falha nao bloqueia - o resultado ja esta persistido."),
        ("Passo 7 - Delete da mensagem no SQS",
         "Somente apos o pipeline concluir e o webhook ser tentado. Se o worker crashar antes, o SQS reentrega apos o visibility timeout (at-least-once delivery)."),
    ]
    for titulo, texto in passos_b:
        story.append(h3(titulo))
        story.append(p(texto))

    story.append(PageBreak())

    # ------------------- CAPITULO 5 -------------------
    story.append(h1("5. Pipeline de IA - 8 Etapas Detalhadas"))
    story.append(p(
        "Executadas <b>sequencialmente</b> pelo AnalyzeDiagramUseCase. A saida "
        "de cada etapa alimenta a proxima. O <b>ExtractionResult</b> serve como "
        "<i>ground truth</i> para todas as validacoes posteriores (anti-alucinacao)."
    ))
    story.append(drawing_block(draw_ground_truth(),
                               "ExtractionResult ancora RAG, Report e QA"))

    story.append(h2("5.1  Etapa 0 - Input Guardrails"))
    story.append(p(
        "<b>Arquivo:</b> <font face='Courier'>domain/shared/input_guardrail.py</font><br/>"
        "Sanitiza o filename (remove path traversal e caracteres perigosos), "
        "limita a 255 caracteres e detecta prompt injection (25+ padroes regex: "
        "override de instrucoes, role-play, exfiltracao, delimitadores)."
    ))
    story.append(p("<b>Resultado:</b> sucesso -&gt; prossegue; falha -&gt; <font face='Courier'>GuardrailError</font> (bloqueia)."))

    story.append(h2("5.2  Etapa 1 - Ingestion"))
    story.append(p(
        "Valida tamanho (&lt;= 20 MB), detecta MIME type, valida extensao "
        "suportada (png, jpg, jpeg, gif, webp, pdf) e converte bytes -&gt; Base64 "
        "via <font face='Courier'>DiagramFile.create()</font>. Cria registro em "
        "<font face='Courier'>analyses</font> e transiciona para <i>em_processamento</i>."
    ))
    story.append(code(
        'DiagramFile {\n'
        '  file_name:      "diagrama.png",\n'
        '  file_type:      "png",\n'
        '  media_type:     "image/png",\n'
        '  content_base64: "iVBORw0KGgo...",\n'
        '  file_size_kb:   512.3\n'
        '}'
    ))

    story.append(h2("5.3  Etapa 2 - Classification (Vision LLM)"))
    story.append(p(
        "Antes de extrair, verifica se a imagem e <b>realmente</b> um diagrama "
        "de arquitetura. O LLM recebe criterios rigorosos de aceitacao (caixas, "
        "setas, componentes tecnicos) e rejeicao (fotos, mockups, organogramas). "
        "Exige <b>confidence &gt;= 0.75</b>."
    ))
    story.append(p(
        "<i>Por que classificar antes de extrair:</i> triagem rapida e barata "
        "evita gastar tokens em imagens irrelevantes."
    ))

    story.append(h2("5.4  Etapa 3 - Extraction (Vision LLM)"))
    story.append(p(
        "<b>Nao usa OCR.</b> O LLM interpreta o diagrama com compreensao "
        "semantica. System prompt define papel de <i>arquiteto senior</i> e "
        "<font face='Courier'>response_format=json_object</font> forca JSON valido. "
        "Retorna 4 campos obrigatorios."
    ))
    story.append(code(
        'ExtractionResult {\n'
        '  components: ["API Gateway", "Auth Service", "User DB", "Redis Cache"],\n'
        '  relationships: [\n'
        '    "Client -> API Gateway: requisicoes HTTP",\n'
        '    "API Gateway -> Auth Service: valida JWT"\n'
        '  ],\n'
        '  patterns: ["Microservices", "API Gateway Pattern"],\n'
        '  raw_description: "Arquitetura de microsservicos com..."\n'
        '}'
    ))
    story.append(p("<b>Persistencia:</b> tabela <font face='Courier'>extraction_results</font> (JSONB)."))

    story.append(h2("5.5  Etapa 3.5 - Guardrail de Extracao"))
    story.append(p(
        "Apos o LLM retornar, valida o <b>schema</b> (chaves, tipos) e varre "
        "os <b>dados</b> em busca de prompt injection nos valores textuais. "
        "Limites: max 200 componentes e 500 relacionamentos."
    ))
    story.append(p(
        "<i>Por que validar depois do LLM:</i> o LLM pode devolver strings "
        "maliciosas que seriam concatenadas em prompts futuros (RAG, Report). "
        "Defesa em profundidade."
    ))

    story.append(h2("5.6  Etapa 4 - RAG (pgvector)"))
    story.append(p(
        "<b>IMPORTANTE: non-blocking.</b> Se falhar, retorna "
        "<font face='Courier'>RagContext.empty()</font> e o pipeline prossegue."
    ))
    story.append(h3("Indexacao"))
    story.append(p(
        "Cria LangChain Document com descricao + componentes + padroes + relacoes. "
        "Gera embedding com <font face='Courier'>text-embedding-3-small</font> "
        "(fallback HuggingFace <font face='Courier'>all-MiniLM-L6-v2</font>) e armazena "
        "em <font face='Courier'>langchain_pg_embedding</font>."
    ))
    story.append(h3("Recuperacao"))
    story.append(p(
        "<font face='Courier'>similarity_search_with_score(k=3, filter={has_report: True})</font>. "
        "Threshold: <b>score &lt; 0.3</b> (distancia coseno) = &gt; 70% similar. "
        "Se nenhum passa -&gt; <font face='Courier'>RagContext.empty()</font>."
    ))
    story.append(h3("Enriquecimento"))
    story.append(p(
        "Um LLM chain sintetiza o contexto historico, identificando padroes de "
        "risco recorrentes. Esse texto e injetado no prompt da proxima etapa."
    ))

    story.append(h2("5.7  Etapa 5 - Report + Riscos (Text LLM)"))
    story.append(p(
        "Gera o relatorio COMPLETO em uma unica chamada, incluindo "
        "classificacao de riscos. Reduz latencia e mantem coerencia entre "
        "riscos e recomendacoes. Riscos sao enums tipados em 6 categorias:"
    ))
    risk_cat = Table([
        ["Categoria",       "O que avalia"],
        ["SPOF",             "ponto unico de falha"],
        ["Seguranca",        "auth, exposicao, endpoints"],
        ["Escalabilidade",   "gargalos, cache, filas sem DLQ"],
        ["Acoplamento",      "dependencias sincronas, interfaces"],
        ["Observabilidade",  "logs, metricas, tracing"],
        ["Resiliencia",      "circuit breaker, retry, fallback"],
    ], colWidths=[3.5*cm, 12*cm])
    risk_cat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_WARNING),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(risk_cat)
    story.append(Spacer(1, 6))
    story.append(p(
        "Recomendacoes com influencia do RAG sao prefixadas com <b>[RAG]</b>. "
        "O campo <font face='Courier'>risk_severity_summary</font> e recalculado "
        "server-side - <b>nao confiamos no LLM para somar</b>."
    ))

    story.append(h2("5.8  Etapa 5.5 - Output Guardrails"))
    story.append(drawing_block(draw_guardrails(),
                               "Tres camadas de guardrails + QA, cobrindo entrada, geracao e saida"))
    story.append(p("Validacoes aplicadas:"))
    story.extend(bullets([
        "<b>Schema:</b> chaves obrigatorias, tipos, severidades validas (ALTO/MEDIO/BAIXO)",
        "<b>Conteudo proibido:</b> discriminatorio, ilegal, engenharia social",
        "<b>PII:</b> CPF, CNPJ, email, telefone, IPv4/v6, API keys (sk-, ghp_, AWS), cartoes -&gt; <font face='Courier'>[REDACTED]</font>",
        "<b>Grounding check:</b> max 20% dos componentes do relatorio podem nao existir na extracao",
    ]))

    story.append(h2("5.9  Etapa 6 - QA (2 fases + loop de refinamento)"))
    story.append(h3("Fase 1 - Deterministicas (sem LLM)"))
    story.extend(bullets([
        "<font face='Courier'>components_identified</font> nao vazio",
        "<font face='Courier'>architectural_risks</font> nao vazio",
        "<font face='Courier'>recommendations</font> nao vazio",
        "<font face='Courier'>executive_summary</font> &gt;= 100 caracteres",
        "<b>Grounding:</b> &gt;= 80% dos componentes do relatorio devem existir na extracao",
    ]))
    story.append(p("Se a Fase 1 falhar, rejeita imediatamente - economia de tokens."))

    story.append(h3("Fase 2 - Auditor LLM adversarial"))
    story.append(p(
        "System prompt define papel de <i>auditor adversarial</i>. Avalia com "
        "criterios ponderados:"
    ))
    criteria = Table([
        ["Criterio",     "Peso", "O que avalia"],
        ["Consistencia", "40%",  "componentes e riscos batem com a extracao"],
        ["Completude",   "30%",  "campos obrigatorios preenchidos"],
        ["Coerencia",    "20%",  "recomendacoes vinculadas aos riscos"],
        ["Qualidade",    "10%",  "linguagem tecnica, sem generalidades"],
    ], colWidths=[3*cm, 1.5*cm, 11*cm])
    criteria.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(criteria)
    story.append(Spacer(1, 6))
    story.append(p("Score minimo obrigatorio: <b>MIN_SCORE = 0.6</b>."))

    story.append(h3("Loop de refinamento"))
    story.append(p(
        "Se rejeitar, os issues sao enviados como feedback na proxima tentativa "
        "com secao <font face='Courier'>CORRIJA OBRIGATORIAMENTE</font>. "
        "<b>Maximo 2 tentativas.</b> Se falhar, <font face='Courier'>QAError</font> "
        "e levantada."
    ))
    story.append(p(
        "<b>Resiliencia:</b> se o LLM de QA estiver indisponivel, assume score "
        "conservador 0.7 (desde que Fase 1 tenha passado)."
    ))

    story.append(h2("5.10  Etapa 7 - Persistencia + Webhook"))
    story.append(p(
        "Ao final (sucesso): INSERT em <font face='Courier'>reports</font>, "
        "UPDATE em <font face='Courier'>analyses</font> (status='analisado'), "
        "publica evento final no Redis; no caminho SQS, dispara POST "
        "<font face='Courier'>callback_url</font>."
    ))
    story.append(PageBreak())

    # ------------------- CAPITULO 6 -------------------
    story.append(h1("6. Convergencia e Tratamento de Falhas"))

    story.append(h2("6.1  Ground Truth como ancora"))
    story.append(p(
        "A saida da Etapa 3 (Extraction) e a fonte de verdade. RAG, Report e "
        "QA recebem a extracao original e sao validados contra ela. Evita "
        "propagacao de alucinacoes."
    ))

    story.append(h2("6.2  Bloqueante x non-blocking"))
    blocking = Table([
        ["Etapas BLOQUEANTES",                "Etapas NON-BLOCKING"],
        ["0. Input Guardrails",                "4. RAG (fallback: RagContext.empty())"],
        ["1. Ingestion",                       "6. QA LLM indisponivel (score 0.7)"],
        ["2. Classification (&lt; 75%)",       "7. Webhook (resultado ja persistido)"],
        ["3. Extraction",                      ""],
        ["3.5 Guardrail Extracao",             ""],
        ["5. Report",                          ""],
        ["5.5 Output Guardrails",              ""],
        ["6. QA (apos 2 tentativas)",          ""],
    ], colWidths=[7.5*cm, 8*cm])
    blocking.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), COLOR_DANGER),
        ("BACKGROUND", (1, 0), (1, 0), COLOR_SUCCESS),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(blocking)
    story.append(Spacer(1, 6))

    story.append(h2("6.3  Tratamento de falhas"))
    story.append(p("Em toda falha bloqueante, o sistema executa:"))
    story.extend(bullets([
        "<font face='Courier'>analysis.fail(step, message)</font> atualiza o agregado",
        "Repositorio persiste <font face='Courier'>status='erro'</font> + <font face='Courier'>error_message</font>",
        "Evento de erro publicado via Redis (frontend informado)",
        "Domain Event <font face='Courier'>AnalysisFailedEvent</font> e emitido",
        "Caminho SQS: webhook com <font face='Courier'>status='erro'</font>",
        "Mensagem SQS <b>nao</b> deletada - volta para retry apos visibility timeout",
    ]))
    story.append(p(
        "<b>Excecoes tipadas:</b> IngestionError, ExtractionError, "
        "ReportGenerationError, RAGError, QAError, GuardrailError. "
        "Cada uma carrega o campo <font face='Courier'>step</font> indicando a origem."
    ))
    story.append(PageBreak())

    # ------------------- CAPITULO 7 -------------------
    story.append(h1("7. Persistencia e Observabilidade"))

    story.append(h2("7.1  Tabelas do PostgreSQL"))
    tables_desc = Table([
        ["Tabela",                   "Conteudo"],
        ["analyses",                  "ciclo de vida (status, file_name, sqs_message_id, error)"],
        ["extraction_results",        "saida do Vision LLM (components, relationships, patterns) em JSONB"],
        ["reports",                   "relatorio completo + metricas de QA"],
        ["langchain_pg_embedding",    "embeddings (vector) + metadata, indice HNSW cosine"],
    ], colWidths=[4.5*cm, 11*cm])
    tables_desc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tables_desc)
    story.append(Spacer(1, 8))

    story.append(h2("7.2  Redis"))
    story.extend(bullets([
        "<b>Broker do Celery</b> (filas de tasks)",
        "<b>Pub/Sub</b> de eventos SSE (canal <font face='Courier'>job:{job_id}</font>)",
        "<b>Event store temporario</b> para polling via <font face='Courier'>GET /jobs/{id}/status</font>",
    ]))

    story.append(h2("7.3  Logs estruturados (structlog)"))
    story.append(p(
        "Todos os servicos emitem JSON com timestamp ISO, nivel, logger_name "
        "e <font face='Courier'>analysis_id</font> via <font face='Courier'>logger.bind()</font>. "
        "Padrao do nome: <b>componente.acao.resultado</b>."
    ))
    story.append(code(
        'vision_llm.extract.done\n'
        'pipeline.qa_rejected.refinement\n'
        'sqs.consumer.poison_pill_detected\n'
        'webhook.send.retry'
    ))

    story.append(h2("7.4  Domain Events emitidos"))
    events = Table([
        ["Evento",                       "Quando"],
        ["DiagramReceivedEvent",          "analise criada"],
        ["DiagramIngestedEvent",          "arquivo validado e convertido"],
        ["ComponentsExtractedEvent",      "Vision LLM extraiu componentes"],
        ["ReportGeneratedEvent",          "relatorio tecnico gerado"],
        ["QAValidationCompletedEvent",    "QA concluiu (aprovado ou rejeitado)"],
        ["AnalysisCompletedEvent",        "pipeline finalizou com sucesso"],
        ["AnalysisFailedEvent",           "qualquer etapa bloqueante falhou"],
    ], colWidths=[5.5*cm, 10*cm])
    events.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(events)
    story.append(PageBreak())

    # ------------------- CAPITULO 8 -------------------
    story.append(h1("8. Consulta de Relatorio (report-api)"))
    story.append(p(
        "Apos o pipeline concluir, clientes consultam via report-api (:8001) "
        "- servico <b>read-only</b>. Nao passa por LLM, le direto do banco."
    ))

    story.append(h2("8.1  GET /reports (lista paginada)"))
    story.append(code(
        'GET http://localhost:8001/reports?limit=20&offset=0\n\n'
        '{\n'
        '  "total":  5,\n'
        '  "limit":  20,\n'
        '  "offset": 0,\n'
        '  "items": [\n'
        '    { "analysis_id": "...", "file_name": "...", "status": "analisado" }\n'
        '  ]\n'
        '}'
    ))

    story.append(h2("8.2  GET /reports/{id} (detalhe)"))
    story.append(p(
        "Retorna o relatorio completo (componentes, riscos, recomendacoes, "
        "sumario, QA). 404 se nao encontrado."
    ))

    story.append(h2("8.3  GET /analyses/{id}/status (acompanhamento)"))
    story.append(p(
        "Servido pelo ia-service (nao pelo report-api). Util para clientes que "
        "nao suportam SSE fazerem polling do status."
    ))
    story.append(code(
        'GET http://localhost:8000/analyses/{analysis_id}/status\n\n'
        '{\n'
        '  "analysis_id":   "uuid",\n'
        '  "status":        "recebido | em_processamento | analisado | erro",\n'
        '  "file_name":     "diagrama.png",\n'
        '  "error_message": null\n'
        '}'
    ))
    story.append(PageBreak())

    # ------------------- CAPITULO 9 -------------------
    story.append(h1("9. Resumo Visual do Workflow"))
    story.append(p(
        "Consolidacao de todos os fluxos em uma pagina. Use esta secao como "
        "cola de referencia rapida."
    ))
    story.append(drawing_block(draw_architecture_overview(),
                               "Arquitetura de alto nivel"))
    story.append(drawing_block(draw_pipeline(),
                               "Pipeline de IA com loop de refinamento"))
    story.append(PageBreak())

    # ------------------- CAPITULO 10 - GLOSSARIO -------------------
    story.append(h1("10. Glossario"))
    glossary = [
        ("Aggregate",
         "Padrao DDD: objeto raiz que protege invariantes de um conjunto de entidades (ex: AnalysisAggregate)."),
        ("Composition Root",
         "Ponto unico onde o grafo de dependencias e montado (composition_root.py). Nenhuma outra camada conhece implementacoes concretas."),
        ("Domain Event",
         "Evento emitido pelo agregado a cada transicao relevante de estado (ex: ReportGeneratedEvent)."),
        ("Grounding Check",
         "Validacao que exige que X% dos componentes do relatorio existam na extracao original. Defesa anti-alucinacao."),
        ("Ground Truth",
         "Fonte de verdade para validar etapas posteriores. No pipeline, e o ExtractionResult (saida do Vision LLM)."),
        ("Guardrail",
         "Camada de protecao para bloquear inputs maliciosos, alucinacoes ou vazamento de PII."),
        ("HNSW",
         "Hierarchical Navigable Small World. Indice vetorial do pgvector para busca por similaridade rapida."),
        ("Non-blocking",
         "Etapa cuja falha NAO interrompe o pipeline (ex: RAG, QA LLM, webhook)."),
        ("Pipeline",
         "Sequencia ordenada das 8 etapas do AnalyzeDiagramUseCase."),
        ("Port / Adapter",
         "Interface abstrata (Port) definida na camada de Application, com implementacao concreta (Adapter) na camada de Infrastructure."),
        ("RAG",
         "Retrieval-Augmented Generation. Recupera analises similares do pgvector e injeta no prompt de geracao."),
        ("SSE",
         "Server-Sent Events. Streaming HTTP unidirecional do ia-service para o cliente (progresso em tempo real)."),
        ("Value Object",
         "Padrao DDD: objeto imutavel definido pelos seus valores (ex: DiagramFile, QAScore, AnalysisId)."),
        ("Visibility Timeout",
         "Tempo que o SQS esconde a mensagem apos o receive. Se o consumer nao deletar, a mensagem volta."),
    ]
    gtable = Table(
        [[k, v] for k, v in glossary],
        colWidths=[4*cm, 11.5*cm]
    )
    gtable.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), COLOR_PRIMARY),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(gtable)

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        "<i>Fim da documentacao. Repositorio: hackathon-iadt.</i>",
        style_caption))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"PDF gerado: {output_path}")


if __name__ == "__main__":
    output = Path(__file__).parent / "workflow.pdf"
    build_pdf(str(output))

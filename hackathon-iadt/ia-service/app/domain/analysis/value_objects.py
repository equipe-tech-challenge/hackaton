"""
Analysis Bounded Context — Value Objects.
Tipos imutáveis que descrevem conceitos do domínio de análise de diagramas.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class AnalysisStatus(str, Enum):
    RECEIVED = "recebido"
    PROCESSING = "em_processamento"
    ANALYZED = "analisado"
    ERROR = "erro"


class FileType(str, Enum):
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    PDF = "pdf"

    @classmethod
    def from_mime(cls, mime_type: str) -> "FileType":
        mapping = {
            "image/png": cls.PNG,
            "image/jpeg": cls.JPEG,
            "image/jpg": cls.JPEG,
            "image/gif": cls.GIF,
            "image/webp": cls.WEBP,
            "application/pdf": cls.PDF,
        }
        result = mapping.get(mime_type)
        if result is None:
            raise ValueError(f"MIME type não suportado: {mime_type}")
        return result

    @property
    def mime_type(self) -> str:
        mapping = {
            FileType.PNG: "image/png",
            FileType.JPEG: "image/jpeg",
            FileType.GIF: "image/gif",
            FileType.WEBP: "image/webp",
            FileType.PDF: "application/pdf",
        }
        return mapping[self]


@dataclass(frozen=True)
class Component:
    """Componente arquitetural identificado no diagrama."""
    name: str

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("Component name cannot be empty")

    def matches(self, other: "Component") -> bool:
        return self.name.lower() == other.name.lower()

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Relationship:
    """Relacionamento entre dois componentes arquiteturais."""
    source: str
    target: str
    description: str

    @classmethod
    def from_string(cls, raw: str) -> "Relationship":
        """
        Parseia formato 'ComponenteA → ComponenteB: descrição'.
        Aceita também '->'.
        """
        import re
        pattern = r"^(.+?)\s*[→\->]+\s*(.+?)(?::\s*(.*))?$"
        match = re.match(pattern, raw.strip())
        if match:
            return cls(
                source=match.group(1).strip(),
                target=match.group(2).strip(),
                description=(match.group(3) or "").strip(),
            )
        # Fallback: armazena raw como descrição
        return cls(source="", target="", description=raw)

    def __str__(self) -> str:
        if self.source and self.target:
            return f"{self.source} → {self.target}: {self.description}"
        return self.description


@dataclass(frozen=True)
class ArchitecturalPattern:
    """Padrão arquitetural identificado (ex: microservices, event-driven)."""
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class DiagramFile:
    """
    Representa o arquivo de diagrama após ingestão (validado e codificado).
    Value object imutável — não tem identidade própria.
    """
    file_name: str
    file_type: FileType
    media_type: str
    content_base64: str
    file_size_kb: float

    MAX_SIZE_MB: int = 20

    @classmethod
    def create(
        cls,
        file_bytes: bytes,
        file_name: str,
    ) -> "DiagramFile":
        """
        Factory method — valida e constrói DiagramFile a partir de bytes brutos.
        Levanta ValueError para entradas inválidas.
        """
        import base64
        import mimetypes

        max_bytes = cls.MAX_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError(
                f"Arquivo excede o limite de {cls.MAX_SIZE_MB}MB."
            )

        mime_type, _ = mimetypes.guess_type(file_name)
        file_type = FileType.from_mime(mime_type or "")

        return cls(
            file_name=file_name,
            file_type=file_type,
            media_type=mime_type,
            content_base64=base64.standard_b64encode(file_bytes).decode("utf-8"),
            file_size_kb=round(len(file_bytes) / 1024, 2),
        )

    def to_dict(self) -> dict:
        return {
            "status": "recebido",
            "file_name": self.file_name,
            "file_type": self.file_type.value,
            "media_type": self.media_type,
            "content_base64": self.content_base64,
            "file_size_kb": self.file_size_kb,
        }

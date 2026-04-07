"""
Report Bounded Context — Value Objects.
Tipos imutáveis que modelam riscos, recomendações e scores de qualidade.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RiskCategory(str, Enum):
    SPOF = "SPOF"
    SECURITY = "Segurança"
    SCALABILITY = "Escalabilidade"
    COUPLING = "Acoplamento"
    OBSERVABILITY = "Observabilidade"
    RESILIENCE = "Resiliência"

    @classmethod
    def all_labels(cls) -> str:
        return ", ".join(c.value for c in cls)


class Severity(str, Enum):
    HIGH = "ALTO"
    MEDIUM = "MÉDIO"
    LOW = "BAIXO"

    @classmethod
    def from_string(cls, value: str) -> "Severity":
        mapping = {v.value.upper(): v for v in cls}
        result = mapping.get(value.upper())
        if result is None:
            return cls.LOW
        return result


@dataclass(frozen=True)
class RiskItem:
    """Risco arquitetural identificado, com categoria, severidade e mitigação."""
    risk_category: RiskCategory
    description: str
    severity: Severity
    affected_components: List[str]
    mitigation: str

    @classmethod
    def from_dict(cls, data: dict) -> "RiskItem":
        return cls(
            risk_category=RiskCategory(data.get("type", RiskCategory.RESILIENCE.value)),
            description=data.get("description", ""),
            severity=Severity.from_string(data.get("severity", "BAIXO")),
            affected_components=list(data.get("affected_components", [])),
            mitigation=data.get("mitigation", ""),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.risk_category.value,
            "description": self.description,
            "severity": self.severity.value,
            "affected_components": list(self.affected_components),
            "mitigation": self.mitigation,
        }


@dataclass(frozen=True)
class Recommendation:
    """Recomendação arquitetural, podendo ser influenciada pelo RAG."""
    text: str
    rag_influenced: bool = False

    @classmethod
    def from_string(cls, text: str) -> "Recommendation":
        return cls(text=text, rag_influenced="[RAG]" in text)

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class RagContext:
    """Contexto recuperado via RAG para enriquecer a geração do relatório."""
    has_context: bool
    enrichment_text: str
    similar_analyses_count: int

    @classmethod
    def empty(cls) -> "RagContext":
        return cls(has_context=False, enrichment_text="", similar_analyses_count=0)

    @classmethod
    def from_dict(cls, data: dict) -> "RagContext":
        return cls(
            has_context=data.get("has_context", False),
            enrichment_text=data.get("rag_enrichment", ""),
            similar_analyses_count=len(data.get("similar_analyses", [])),
        )


@dataclass(frozen=True)
class QAScore:
    """Score de qualidade produzido pelo QA Agent."""
    is_valid: bool
    completeness_score: float
    issues_found: List[str]
    quality_notes: str

    MIN_SCORE = 0.6

    @classmethod
    def from_dict(cls, data: dict) -> "QAScore":
        return cls(
            is_valid=data.get("is_valid", False),
            completeness_score=data.get("completeness_score", 0.0),
            issues_found=list(data.get("issues_found", [])),
            quality_notes=data.get("quality_notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "completeness_score": self.completeness_score,
            "issues_found": list(self.issues_found),
            "quality_notes": self.quality_notes,
            "status": "analisado" if self.is_valid else "erro",
        }

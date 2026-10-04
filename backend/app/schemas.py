import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Register(Credentials):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class ClaimCreate(StrictSchema):
    title: str = Field(min_length=1, max_length=200)
    claim_number: str = Field(default="", max_length=100)
    insurer: str = Field(default="", max_length=200)
    amount: float | None = Field(default=None, ge=0, le=1e9)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value):
        if not value.strip():
            raise ValueError("Claim title cannot be blank")
        return value.strip()


class Review(StrictSchema):
    status: Literal["collecting_evidence", "ready_for_review", "in_review", "reviewed"]
    notes: str = Field(default="", max_length=10000)


class Question(StrictSchema):
    question: str = Field(min_length=3, max_length=1500)

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Question must contain at least three nonblank characters")
        return value.strip()


class DocumentExtraction(StrictSchema):
    document_type: Literal["DENIAL_LETTER", "POLICY", "MEDICAL_BILL", "CLAIM_FORM", "OTHER", "UNKNOWN"]
    fields: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    text: str = Field(default="", max_length=30000)


class VisionDocumentExtraction(DocumentExtraction):
    # Vision must return the transcription field, even when an illegible page legitimately yields empty text.
    text: str = Field(max_length=30000)


class Citation(StrictSchema):
    chunk_id: str
    quote: str = Field(min_length=5, max_length=700)


class Finding(StrictSchema):
    statement: str = Field(min_length=1, max_length=1500)
    kind: Literal["fact", "inference"]
    citations: list[Citation] = Field(min_length=1, max_length=6)


class GroundedResponse(StrictSchema):
    findings: list[Finding] = Field(default_factory=list, max_length=16)
    recommendations: list[Finding] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=16)
    insufficient_evidence: bool
    # Appeal paragraphs must use the same evidence-bearing Finding schema.
    appeal_paragraphs: list[Finding] = Field(default_factory=list, max_length=10)


class EvidenceIssue(StrictSchema):
    index: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=700)


class EvidenceVerification(StrictSchema):
    supported: bool
    unsupported_indexes: list[StrictInt] = Field(default_factory=list, max_length=34)
    issues: list[EvidenceIssue] = Field(default_factory=list, max_length=34)

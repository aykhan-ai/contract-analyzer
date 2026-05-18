"""
SCHEMAS.PY — Pydantic modellər (validation) FastAPI + Pydantic v2
Burada 2 şey müəyyən edilir:
1. API-yə nə GƏLİR (Request)
2. API-dən nə ÇIXIR (Response)
"""

from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum

class DocumentType(str, Enum):
    CONTRACT = "contract"       # hüquqi müqavilə
    TERMS    = "terms"          # Terms of Service + Privacy Policy
    OTHER    = "other"          # digər

class RiskLevel(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"

class FileType(str, Enum):
    PDF   = "pdf"
    DOCX  = "docx"
    TXT   = "txt"
    TEXT  = "text"    # copy-paste
    IMAGE = "image"   # şəkil (maks 6 səhifə)


# REQUEST SCHEMAS — API-yə nə gəlir
class TextUploadRequest(BaseModel):
    """
    Copy-paste upload üçün
    POST /upload/text
    {
        "text": "Müqavilə mətni...",
        "doc_type": "contract"
    }
    """
    text:     str
    doc_type: DocumentType = DocumentType.CONTRACT

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Mətn boş ola bilməz.")
        if len(v) < 50:
            raise ValueError("Mətn çox qısadır. Minimum 50 simvol.")
        if len(v) > 100_000:
            raise ValueError("Mətn çox böyükdür. Maksimum 100,000 simvol.")
        return v


class ImageUploadRequest(BaseModel):
    """
    Şəkil upload metadata-sı üçün
    POST /upload/images
    Faktiki fayllar multipart/form-data ilə gəlir,
    bu schema yalnız əlavə parametrləri yoxlayır
    """
    doc_type:   DocumentType = DocumentType.CONTRACT
    # Şəkil sayı FastAPI endpoint-ində yoxlanır
    # Burada yalnız tip validasiyası var


# RESPONSE SCHEMAS — API-dən nə çıxır
class DocumentResponse(BaseModel):
    """
    Sənəd uğurla yüklənəndə qaytarılır
    """
    id:         int
    file_name:  str
    file_type:  str
    doc_type:   str
    page_count: int
    created_at: str

    model_config = {"from_attributes": True}


class LawViolation(BaseModel):
    """
    Bir qanun pozuntusu — qanun mənbəyi göstərilməklə
    """
    law_name:    str           # "Mülki Məcəllə"
    article_num: Optional[str] = None  # "468.1"
    description: str           # pozuntunun izahı


class ComplianceDetail(BaseModel):
    """
    AZ Qanunu, GDPR və ya CyberSec uyğunluq nəticəsi
    """
    status:     str                       # "UYĞUN" / "QISMƏN UYĞUN" / "UYĞUN DEYİL"
    violations: list[LawViolation] = []   # strukturlaşmış pozuntular


class RiskClause(BaseModel):
    """
    Tək bir riskli maddə
    """
    clause:      str    # maddənin mətni
    risk_level:  str    # HIGH / MEDIUM / LOW
    explanation: str    # niyə risklidir


class ThirdParty(BaseModel):
    """
    3-cü tərəf paylaşımı (Terms/Privacy üçün)
    """
    partner:  str    # "Meta (Facebook)"
    what:     str    # nə paylaşılır
    purpose:  str    # nə məqsədlə


class AnalysisResponse(BaseModel):
    """
    Claude-un tam analiz nəticəsi
    Bütün endpoint-lər bu formatda cavab verir
    """
    id:          int
    document_id: int

    # Risk
    risk_level:  str
    risk_score:  float

    # Müqavilə analizi
    risk_clauses:    list[RiskClause] = []
    obligations:     list[str]        = []
    important_dates: list[str]        = []

    # Terms/Privacy analizi
    data_collected:  list[str]       = []
    third_party:     list[ThirdParty] = []
    user_rights:     list[str]        = []

    # Uyğunluq
    az_law:    Optional[ComplianceDetail] = None
    gdpr:      Optional[ComplianceDetail] = None
    cyber_sec: Optional[ComplianceDetail] = None  # Kibertəhlükəsizlik rəyi

    # İstifadəçiyə sadə izah
    simple_summary: str
    recommendation: str

    # Token izləmə
    tokens_used:    int
    function_calls: int

    created_at: str

    model_config = {"from_attributes": True}


class UploadAndAnalysisResponse(BaseModel):
    """
    Upload + analiz birlikdə qaytarılanda istifadə olunur
    """
    document: DocumentResponse
    analysis: AnalysisResponse


class DocumentListResponse(BaseModel):
    """
    GET /documents — bütün sənədlərin siyahısı
    """
    total:     int
    documents: list[DocumentResponse]


class ErrorResponse(BaseModel):
    """
    Xəta halında qaytarılır
    """
    error:   str
    detail:  Optional[str] = None

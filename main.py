"""
MAIN.PY — FastAPI tətbiqi və endpoint-lər
FastAPI, Pydantic, OpenAPI, Async, StreamingResponse, Dependency Injection

Endpoint-lər:
    POST /upload/file      — PDF, DOCX, TXT yüklə
    POST /upload/text      — copy-paste mətn
    POST /upload/images    — şəkillər (maks 6)
    POST /upload/terms     — Terms / Privacy (streaming)
    GET  /analysis/{id}    — analiz nəticəsi
    GET  /documents        — bütün sənədlər
    GET  /health           — sistem statusu
"""

import json
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, Depends, File, Form,
    HTTPException, UploadFile
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from analyzer import DocumentAnalyzer
from database import Analysis, Document, get_db, init_db
from parser import DocumentParser
from security import PromptInjectionException
from schemas import (
    AnalysisResponse, ComplianceDetail, DocumentListResponse,
    DocumentResponse, DocumentType, LawViolation, RiskClause,
    TextUploadRequest, ThirdParty, UploadAndAnalysisResponse
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title       = "Contract Analyzer API",
    description = "Hüquqi sənəd və müqavilə analiz sistemi",
    version     = "1.0.0",
    lifespan    = lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

parser   = DocumentParser()
analyzer = DocumentAnalyzer()


# KÖMƏKÇI — DB modelini Pydantic response-a çevir
def _to_analysis_response(analysis: Analysis) -> AnalysisResponse:

    def _load(field) -> list:
        if not field:
            return []
        try:
            return json.loads(field)
        except Exception:
            return []

    def _flatten_to_strings(items: list) -> list[str]:
        """Dict-ləri oxunaqlı string-ə çevirir."""
        result = []
        for item in items:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                for key in ("description", "text", "content", "title", "name"):
                    if key in item and isinstance(item[key], str):
                        result.append(item[key])
                        break
                else:
                    parts = [f"{k}: {v}" for k, v in item.items()
                             if isinstance(v, (str, int, float))]
                    if parts:
                        result.append(" — ".join(parts))
            else:
                result.append(str(item))
        return result

    def _to_violations(items: list) -> list[LawViolation]:
        """
        Pozuntu siyahısını LawViolation obyektlərinə çevir.
        Həm köhnə (string), həm yeni (dict) formatı dəstəkləyir.
        """
        result = []
        for item in items:
            if isinstance(item, dict):
                # Yeni format
                result.append(LawViolation(
                    law_name    = item.get("law_name", "Müəyyən edilməyib"),
                    article_num = item.get("article_num"),
                    description = item.get("description", str(item))
                ))
            elif isinstance(item, str):
                # Köhnə format — mənbə yoxdur
                result.append(LawViolation(
                    law_name    = "Müəyyən edilməyib",
                    article_num = None,
                    description = item
                ))
        return result

    risk_clauses = [
        RiskClause(
            clause      = rc.get("clause", ""),
            risk_level  = rc.get("risk_level", "MEDIUM"),
            explanation = rc.get("explanation", "")
        )
        for rc in _load(analysis.risk_clauses)
        if isinstance(rc, dict)
    ]

    third_party = [
        ThirdParty(
            partner = tp.get("partner", ""),
            what    = tp.get("what", ""),
            purpose = tp.get("purpose", "")
        )
        for tp in _load(analysis.third_party)
        if isinstance(tp, dict)
    ]

    az_law = ComplianceDetail(
        status     = analysis.az_law_status,
        violations = _to_violations(_load(analysis.az_law_violations))
    ) if analysis.az_law_status else None

    gdpr = ComplianceDetail(
        status     = analysis.gdpr_status,
        violations = _to_violations(_load(analysis.gdpr_violations))
    ) if analysis.gdpr_status else None

    cyber_sec = ComplianceDetail(
        status     = analysis.cyber_sec_status,
        violations = _to_violations(_load(analysis.cyber_sec_violations))
    ) if analysis.cyber_sec_status else None

    return AnalysisResponse(
        id              = analysis.id,
        document_id     = analysis.document_id,
        risk_level      = analysis.risk_level or "MEDIUM",
        risk_score      = analysis.risk_score or 5.0,
        risk_clauses    = risk_clauses,
        obligations     = _flatten_to_strings(_load(analysis.obligations)),
        important_dates = _flatten_to_strings(_load(analysis.important_dates)),
        data_collected  = _flatten_to_strings(_load(analysis.data_collected)),
        third_party     = third_party,
        user_rights     = _flatten_to_strings(_load(analysis.user_rights)),
        az_law          = az_law,
        gdpr            = gdpr,
        cyber_sec       = cyber_sec,
        simple_summary  = analysis.simple_summary or "",
        recommendation  = analysis.recommendation or "",
        tokens_used     = analysis.tokens_used or 0,
        function_calls  = analysis.function_calls or 0,
        created_at      = str(analysis.created_at)
    )


@app.post(
    "/upload/file",
    response_model = UploadAndAnalysisResponse,
    summary        = "PDF, DOCX və ya TXT fayl yüklə",
    tags           = ["Upload"]
)
async def upload_file(
    file:     UploadFile   = File(...),
    doc_type: DocumentType = Form(DocumentType.CONTRACT),
    db:       Session      = Depends(get_db)
):
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain"
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code = 415,
            detail      = "Yalnız PDF, DOCX və TXT faylları qəbul edilir."
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Fayl boşdur.")

    try:
        parsed = parser.parse_file(
            file_bytes   = file_bytes,
            content_type = file.content_type,
            file_name    = file.filename or "document"
        )
    except PromptInjectionException as e:
        raise HTTPException(
            status_code = 400,
            detail      = f"🚫 Təhlükəsizlik: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    document = Document(
        file_name  = file.filename or "document",
        file_type  = parsed["file_type"],
        doc_type   = doc_type.value,
        raw_text   = parsed["text"],
        page_count = parsed["page_count"]
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    analysis = await analyzer.analyze(
        db=db, document=document, text=parsed["text"]
    )

    return UploadAndAnalysisResponse(
        document = DocumentResponse(
            id         = document.id,
            file_name  = document.file_name,
            file_type  = document.file_type,
            doc_type   = document.doc_type,
            page_count = document.page_count,
            created_at = str(document.created_at)
        ),
        analysis = _to_analysis_response(analysis)
    )

@app.post(
    "/upload/text",
    response_model = UploadAndAnalysisResponse,
    summary        = "Mətni copy-paste ilə yüklə",
    tags           = ["Upload"]
)
async def upload_text(
    request: TextUploadRequest,
    db:      Session = Depends(get_db)
):
    try:
        parsed = parser.parse_text(request.text)
    except PromptInjectionException as e:
        raise HTTPException(
            status_code = 400,
            detail      = f"🚫 Təhlükəsizlik: {str(e)}"
        )

    document = Document(
        file_name  = "copy-paste",
        file_type  = "text",
        doc_type   = request.doc_type.value,
        raw_text   = parsed["text"],
        page_count = parsed["page_count"]
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    analysis = await analyzer.analyze(
        db=db, document=document, text=parsed["text"]
    )

    return UploadAndAnalysisResponse(
        document = DocumentResponse(
            id         = document.id,
            file_name  = document.file_name,
            file_type  = document.file_type,
            doc_type   = document.doc_type,
            page_count = document.page_count,
            created_at = str(document.created_at)
        ),
        analysis = _to_analysis_response(analysis)
    )

@app.post(
    "/upload/images",
    response_model = UploadAndAnalysisResponse,
    summary        = "Müqavilə şəkillərini yüklə (maks 6 səhifə)",
    tags           = ["Upload"]
)
async def upload_images(
    files:    list[UploadFile] = File(...),
    doc_type: DocumentType     = Form(DocumentType.CONTRACT),
    db:       Session          = Depends(get_db)
):
    if not files:
        raise HTTPException(status_code=400, detail="Heç bir şəkil göndərilmədi.")

    if len(files) > 6:
        raise HTTPException(
            status_code = 422,
            detail      = f"Maksimum 6 şəkil yükləyə bilərsiniz. Siz {len(files)} göndərdiniz."
        )

    image_data = []
    for f in files:
        content_type = f.content_type or "image/jpeg"
        file_bytes   = await f.read()
        image_data.append((content_type, file_bytes))

    try:
        parsed = parser.parse_images(image_data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    document = Document(
        file_name  = f"{len(files)} səhifə şəkil",
        file_type  = "image",
        doc_type   = doc_type.value,
        raw_text   = None,
        page_count = parsed["page_count"]
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    analysis = await analyzer.analyze(
        db           = db,
        document     = document,
        image_blocks = parsed["image_blocks"]
    )

    return UploadAndAnalysisResponse(
        document = DocumentResponse(
            id         = document.id,
            file_name  = document.file_name,
            file_type  = document.file_type,
            doc_type   = document.doc_type,
            page_count = document.page_count,
            created_at = str(document.created_at)
        ),
        analysis = _to_analysis_response(analysis)
    )

@app.post(
    "/upload/terms",
    summary = "Terms of Service / Privacy Policy — real vaxtda analiz",
    tags    = ["Upload"]
)
async def upload_terms(
    file:     UploadFile   = File(None),
    text:     str          = Form(""),
    doc_type: DocumentType = Form(DocumentType.TERMS),
    db:       Session      = Depends(get_db)
):
    """
    Server-Sent Events (SSE) ilə real vaxtda status göndərir.
    """
    if not file and not text.strip():
        raise HTTPException(
            status_code = 400,
            detail      = "Fayl və ya mətn göndərin."
        )

    if file:
        file_bytes = await file.read()
        try:
            parsed_doc = parser.parse_file(
                file_bytes   = file_bytes,
                content_type = file.content_type or "application/pdf",
                file_name    = file.filename or "terms"
            )
        except PromptInjectionException as e:
            raise HTTPException(
                status_code = 400,
                detail      = f"🚫 Təhlükəsizlik: {str(e)}"
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        raw_text   = parsed_doc["text"]
        file_name  = file.filename or "terms"
        file_type  = parsed_doc["file_type"]
        page_count = parsed_doc["page_count"]
    else:
        try:
            parsed_doc = parser.parse_text(text)
        except PromptInjectionException as e:
            raise HTTPException(
                status_code = 400,
                detail      = f"🚫 Təhlükəsizlik: {str(e)}"
            )
        raw_text   = parsed_doc["text"]
        file_name  = "copy-paste"
        file_type  = "text"
        page_count = parsed_doc["page_count"]

    document = Document(
        file_name  = file_name,
        file_type  = file_type,
        doc_type   = doc_type.value,
        raw_text   = raw_text,
        page_count = page_count
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return StreamingResponse(
        analyzer.analyze_stream(
            db=db, document=document, text=raw_text
        ),
        media_type = "text/event-stream"
    )

@app.get(
    "/analysis/{analysis_id}",
    response_model = AnalysisResponse,
    summary        = "Analiz nəticəsini gətir",
    tags           = ["Results"]
)
async def get_analysis(
    analysis_id: int,
    db:          Session = Depends(get_db)
):
    analysis = db.query(Analysis).filter(
        Analysis.id == analysis_id
    ).first()

    if not analysis:
        raise HTTPException(
            status_code = 404,
            detail      = f"ID {analysis_id} olan analiz tapılmadı."
        )

    return _to_analysis_response(analysis)

@app.get(
    "/documents",
    response_model = DocumentListResponse,
    summary        = "Bütün sənədlərin siyahısı",
    tags           = ["Results"]
)
async def get_documents(
    skip:     int     = 0,
    limit:    int     = 20,
    doc_type: str     = None,
    db:       Session = Depends(get_db)
):
    query = db.query(Document)

    if doc_type:
        query = query.filter(Document.doc_type == doc_type)

    total     = query.count()
    documents = query.order_by(
        Document.created_at.desc()
    ).offset(skip).limit(limit).all()

    return DocumentListResponse(
        total     = total,
        documents = [
            DocumentResponse(
                id         = d.id,
                file_name  = d.file_name,
                file_type  = d.file_type,
                doc_type   = d.doc_type,
                page_count = d.page_count,
                created_at = str(d.created_at)
            )
            for d in documents
        ]
    )

@app.get(
    "/health",
    summary = "Sistem statusunu yoxla",
    tags    = ["System"]
)
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "status":   "ok",
        "database": db_status,
        "version":  "1.0.0"
    }

#local isletmek
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

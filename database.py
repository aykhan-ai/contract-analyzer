"""
DATABASE.PY — Verilənlər bazası modelləri
SQL, SQLAlchemy ORM
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

from sqlalchemy import (
    create_engine, Column, Integer, String,
    Text, DateTime, Float, ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./contract_analyzer.db")

# Engine və Session
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# CƏDVƏL 1: Document - Yüklənən hər sənəd burada saxlanır
class Document(Base):
    __tablename__ = "documents"

    id          = Column(Integer, primary_key=True, index=True)
    file_name   = Column(String(255))                  # "muqavile.pdf"
    file_type   = Column(String(50))                   # "pdf" / "docx" / "txt" / "text" / "image"
    doc_type    = Column(String(50))                   # "contract" / "terms" / "other"
    raw_text    = Column(Text)                         # çıxarılan mətn (şəkillərdə None)
    page_count  = Column(Integer, default=1)           # şəkil upload üçün vacib
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Bir document-in bir və ya bir neçə analizi ola bilər
    analyses    = relationship("Analysis", back_populates="document")



# CƏDVƏL 2: Analysis - Claude-un hər analiz nəticəsi burada saxlanır
class Analysis(Base):
    __tablename__ = "analyses"

    id               = Column(Integer, primary_key=True, index=True)
    document_id      = Column(Integer, ForeignKey("documents.id"))

    # Risk qiymətləndirməsi
    risk_level       = Column(String(20))              # "HIGH" / "MEDIUM" / "LOW"
    risk_score       = Column(Float)                   # 0.0 - 10.0

    # Analiz nəticələri (JSON string kimi saxlanır)
    risk_clauses     = Column(Text)                    # riskli maddələr
    obligations      = Column(Text)                    # öhdəliklər
    important_dates  = Column(Text)                    # mühüm tarixlər
    data_collected   = Column(Text)                    # toplanan məlumatlar (terms üçün)
    third_party      = Column(Text)                    # 3-cü tərəf paylaşımı
    user_rights      = Column(Text)                    # istifadəçi hüquqları

    # Uyğunluq yoxlaması
    az_law_status     = Column(String(50))              # "UYĞUN" / "QISMƏN" / "UYĞUN DEYİL"
    az_law_violations = Column(Text)                    # pozulan maddələr (JSON)
    gdpr_status       = Column(String(50))
    gdpr_violations   = Column(Text)
    cyber_sec_status  = Column(String(50))              # CyberSec rəyi
    cyber_sec_violations = Column(Text)                 # CyberSec narahatlıqları (JSON)

    # İstifadəçiyə göstəriləcək sadə izah
    simple_summary   = Column(Text)
    recommendation   = Column(Text)                    # "İstifadə et / Ehtiyatla / İstifadə etmə"

    # Token sərfiyyatı (optimallaşdırma üçün izlə)
    tokens_used      = Column(Integer, default=0)
    function_calls   = Column(Integer, default=0)      # neçə function call edildi

    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document         = relationship("Document", back_populates="analyses")



# CƏDVƏL 3: Law - seed_laws.py tərəfindən bir dəfə doldurulan AZ qanunları və GDPR maddələri
class Law(Base):
    __tablename__ = "laws"

    id             = Column(Integer, primary_key=True, index=True)
    standard       = Column(String(50), index=True)    # "AZ_LAW" / "GDPR"
    law_name       = Column(String(255))               # "Mülki Məcəllə"
    article_num    = Column(String(50), index=True)    # "468.1"
    title          = Column(String(255))               # "Müqavilənin pozulması"
    content        = Column(Text)                      # maddənin tam mətni
    category       = Column(String(100), index=True)   # "müqavilə" / "əmək" / "fərdi məlumat"
    risk_weight    = Column(Integer, default=1)        # pozulduqda neçə risk balı əlavə olunur
    updated_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))



# CƏDVƏL 4: LawCache - Eyni sorğunun təkrar Claude-a göndərilməsinin qarşısını alaraq Token sərfiyyatını azaldır
class LawCache(Base):
    __tablename__ = "law_cache"

    id          = Column(Integer, primary_key=True, index=True)
    query_key   = Column(String(255), unique=True, index=True)  # "AZ_LAW_468.1"
    result      = Column(Text)                                   # Claude-un cavabı
    hits        = Column(Integer, default=1)                     # neçə dəfə istifadə edildi
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))



# DB-ni yarat (cədvəllər mövcud deyilsə)
def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Cədvəllər yaradıldı.")


# FastAPI üçün dependency injection hər request üçün session açır, bitdikdə bağlayır
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()

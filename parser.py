"""
PARSER.PY — Sənəd oxuma və mətn çıxarma
File Handling, Pandas ilə mətn təmizlənməsi

Hər fayl tipini oxuyub eyni formata çevirir:
PDF / DOCX / TXT / TEXT → təmiz string
IMAGE → base64 siyahısı (Claude-a birbaşa göndərilir)
"""

import base64
import io
import os
import re

import pandas as pd
import pdfplumber
from docx import Document
from PIL import Image

from security import sanitize_text, PromptInjectionException



# SABİT MƏHDUDIYYƏTLƏR
MAX_IMAGES        = 6
MAX_IMAGE_SIZE_MB = 5
MAX_IMAGE_BYTES   = MAX_IMAGE_SIZE_MB * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}



# Data Quality - MƏTN TƏMİZLƏMƏ — pandas + regex
def clean_text(raw: str) -> str:
    """
    Ham mətni təmizləyir:
    - Artıq boşluqları silir
    - Boş sətirləri azaldır
    - Xüsusi simvolları normallaşdırır
    """
    if not raw:
        return ""

    # pandas
    series = pd.Series([raw])

    # boşluqları sil
    series = series.str.strip()

    # 3+ ardıcıl boş sətri 2-yə endir
    series = series.str.replace(r"\n{3,}", "\n\n", regex=True)

    # Ardıcıl boşluqları tək boşluğa çevir
    series = series.str.replace(r"[ \t]+", " ", regex=True)

    # Xüsusi PDF artefaktlarını sil (qırıq sözlər)
    series = series.str.replace(r"(\w)-\n(\w)", r"\1\2", regex=True)

    result = series.iloc[0]
    return result if result else ""


def extract_articles(text: str) -> list[dict]:
    """
    Mətndən maddələri ayırır
    Pattern: "Maddə 5." və ya "5.1." kimi formatlar
    """
    pattern = r"(Maddə\s+\d+[\.\d]*\.?|^\d+\.\d+\.)"
    parts   = re.split(pattern, text, flags=re.MULTILINE)

    articles = []
    for i in range(1, len(parts) - 1, 2):
        header  = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            articles.append({"header": header, "content": content})

    return articles


# PDF PARSER
def parse_pdf(file_bytes: bytes) -> str:
    """
    PDF-dən mətn çıxarır
    pdfplumber — layout-aware extraction
    """
    text_parts = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"[Səhifə {page_num}]\n{page_text}")

    if not text_parts:
        raise ValueError(
            "PDF-dən mətn çıxarıla bilmədi. "
            "Skan edilmiş sənəd ola bilər — şəkil kimi yükləyin."
        )

    raw = "\n\n".join(text_parts)
    return clean_text(raw)


# DOCX PARSER
def parse_docx(file_bytes: bytes) -> str:
    """
    DOCX-dən mətn çıxarır
    python-docx — paragraf əsaslı oxuma
    """
    doc        = Document(io.BytesIO(file_bytes))
    paragraphs = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            # Başlıqları qoru
            if para.style.name.startswith("Heading"):
                paragraphs.append(f"\n## {text}\n")
            else:
                paragraphs.append(text)

    if not paragraphs:
        raise ValueError("DOCX faylında oxuna bilən mətn tapılmadı.")

    raw = "\n".join(paragraphs)
    return clean_text(raw)


# TXT PARSER
def parse_txt(file_bytes: bytes) -> str:
    """
    TXT faylını oxuyur
    Encoding avtomatik müəyyən edilir
    """
    # Azərbaycan mətnləri üçün UTF-8 və ya latin-1 cəhd et
    for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1251"]:
        try:
            raw = file_bytes.decode(encoding)
            return clean_text(raw)
        except UnicodeDecodeError:
            continue

    raise ValueError("TXT faylının encodingi tanınmadı.")


# TEXT (COPY-PASTE) PARSER
def parse_text(raw_text: str) -> str:
    """
    Copy-paste mətni təmizləyir
    Artıq sadədir — Pydantic artıq yoxlayıb
    """
    return clean_text(raw_text)


# IMAGE PARSER
def parse_images(files: list[tuple[str, bytes]]) -> list[dict]:
    """
    Şəkilləri base64-ə çevirir
    Claude API-nin qəbul etdiyi formata hazırlayır

    files: [(content_type, file_bytes), ...]
    return: [{"type": "image", "source": {...}}, ...]
    """
    # Məhdudiyyət yoxlaması
    if len(files) > MAX_IMAGES:
        raise ValueError(
            f"Maksimum {MAX_IMAGES} şəkil yükləyə bilərsiniz. "
            f"Siz {len(files)} şəkil göndərdiniz."
        )

    image_blocks = []

    for idx, (content_type, file_bytes) in enumerate(files, 1):

        # Fayl tipi yoxlaması
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(
                f"Şəkil {idx}: yalnız JPEG, PNG, WEBP formatları qəbul edilir. "
                f"Göndərilən: {content_type}"
            )

        # Ölçü yoxlaması
        if len(file_bytes) > MAX_IMAGE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"Şəkil {idx}: ölçüsü {size_mb:.1f}MB-dir. "
                f"Maksimum {MAX_IMAGE_SIZE_MB}MB."
            )

        # Şəkili optimallaşdır — böyük şəkilləri kiçilt
        file_bytes = _optimize_image(file_bytes, content_type)

        # Base64-ə çevir
        b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

        image_blocks.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": content_type,
                "data":       b64
            }
        })

    return image_blocks


def _optimize_image(file_bytes: bytes, content_type: str) -> bytes:
    """
    Şəkili Claude üçün optimallaşdırır:
    - Maksimum 1568x1568 piksel (Claude-un optimal ölçüsü)
    - Keyfiyyəti saxlayaraq sıxışdırır
    """
    img = Image.open(io.BytesIO(file_bytes))

    # Maksimum ölçü
    max_size = (1568, 1568)
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.LANCZOS)

    # RGB-yə çevir (RGBA və ya digər modlar üçün)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Yenidən byte-a çevir
    output = io.BytesIO()
    fmt    = "JPEG" if content_type == "image/jpeg" else "PNG"
    img.save(output, format=fmt, quality=85, optimize=True)

    return output.getvalue()


# ANA FUNKSIYA — DocumentParser class OOP
class DocumentParser:
    """
    Bütün fayl tiplərini vahid interfeyslə idarə edir.
    Hər mətnin çıxarılmasından sonra security yoxlaması aparır.
    """

    def _sanitize_and_validate(self, text: str) -> dict:
        """
        Mətni sanitizer-dən keçir.
        Bloklanırsa exception atır.
        Bloklanmırsa təmizlənmiş mətni qaytarır.
        """
        result = sanitize_text(text)

        if result.is_blocked:
            raise PromptInjectionException(
                f"Sənəddə təhlükəsizlik təhdidi tapıldı: {result.block_reason}",
                result
            )

        return {
            "text":         result.cleaned_text,
            "risk_level":   result.risk_level.value,
            "threats":      result.threats_found
        }

    def parse_file(
        self,
        file_bytes:   bytes,
        content_type: str,
        file_name:    str
    ) -> dict:
        """
        Fayl tipini müəyyən edib müvafiq parser-i çağırır,
        sonra security yoxlaması aparır.
        """
        ext = os.path.splitext(file_name)[1].lower()

        if ext == ".pdf" or content_type == "application/pdf":
            text      = parse_pdf(file_bytes)
            file_type = "pdf"

        elif ext == ".docx" or content_type == (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ):
            text      = parse_docx(file_bytes)
            file_type = "docx"

        elif ext == ".txt" or content_type == "text/plain":
            text      = parse_txt(file_bytes)
            file_type = "txt"

        else:
            raise ValueError(
                f"Dəstəklənməyən fayl tipi: {ext}. "
                "Yalnız PDF, DOCX, TXT faylları qəbul edilir."
            )

        # Security yoxlaması
        security_result = self._sanitize_and_validate(text)
        page_count = max(1, len(security_result["text"]) // 3000)

        return {
            "text":               security_result["text"],
            "file_type":          file_type,
            "page_count":         page_count,
            "security_risk":      security_result["risk_level"],
            "threats_filtered":   len(security_result["threats"])
        }

    def parse_text(self, raw_text: str) -> dict:
        """Copy-paste mətn üçün — yenə sanitizer-dən keçir."""
        text = parse_text(raw_text)

        security_result = self._sanitize_and_validate(text)
        page_count = max(1, len(security_result["text"]) // 3000)

        return {
            "text":               security_result["text"],
            "file_type":          "text",
            "page_count":         page_count,
            "security_risk":      security_result["risk_level"],
            "threats_filtered":   len(security_result["threats"])
        }

    def parse_images(self, files: list[tuple[str, bytes]]) -> dict:
        """
        Şəkil upload üçün.

        """
        image_blocks = parse_images(files)

        return {
            "image_blocks":     image_blocks,
            "file_type":        "image",
            "page_count":       len(files),
            "security_risk":    "UNKNOWN",
            "threats_filtered": 0
        }

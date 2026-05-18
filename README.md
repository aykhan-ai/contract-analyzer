# Contract Analyzer

> Hüquqi sənəd və müqavilə analiz sistemi — Claude AI əsaslı.

AI Engineering kursunun 2-ci ay layihəsi. Müqavilələri, istifadə şərtlərini və məxfilik siyasətlərini analiz edir, Azərbaycan qanunvericiliyi, GDPR və kibertəhlükəsizlik standartları ilə uyğunluğunu yoxlayır.

---

## Əsas xüsusiyyətlər

- **4 upload üsulu** — PDF, DOCX, TXT, copy-paste mətn, fotoşəkil (maks 6 səhifə)
- **3 sənəd növü** — müqavilə, istifadə şərtləri + məxfilik siyasəti, digər
- **3 paralel standart** — Azərbaycan qanunvericiliyi, GDPR, kibertəhlükəsizlik mütəxəssis rəyi
- **Function calling** — Claude DB-dən qanun maddələrini real vaxtda çəkir
- **Streaming** — terms/privacy analizində real-time gedişat göstəricisi
- **Prompt injection müdafiəsi** — 20+ pattern detection + prompt sandwiching
- **Frontend** — single HTML file, framework-suz, brauzerdə işləyir

---

## Texnoloji stack

| Qat | Texnologiya |
|---|---|
| AI | Anthropic Claude API (`claude-sonnet-4-6`), function calling, vision |
| Backend | FastAPI, Pydantic v2, async/await, StreamingResponse (SSE) |
| Database | PostgreSQL / SQLite, SQLAlchemy ORM |
| Data | pandas, pdfplumber, python-docx, Pillow |
| Frontend | Vanilla HTML/CSS/JS, fetch + ReadableStream |
| Security | Custom prompt injection detector |

---

## Sənəd strukturu

```
contract_analyzer/
├── main.py            ← FastAPI app + endpoints
├── database.py        ← SQLAlchemy models
├── schemas.py         ← Pydantic models
├── parser.py          ← Fayl oxuma (PDF/DOCX/TXT/şəkil)
├── analyzer.py        ← Claude API + function calling loop
├── tools.py           ← Function calling tool definitions
├── security.py        ← Prompt injection detection
├── seed_laws.py       ← DB-ni laws.json-dan doldurur
├── scrape_laws.py     ← e-qanun.az + cbar.az scraping
├── laws.json          ← Qanun bazası (1700+ maddə)
├── index.html         ← Frontend (tək fayl)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Qurulum

### 1. Repository klonla və mühit yarat

```bash
git clone <repo-url>
cd contract_analyzer

python -m venv venv
source venv/bin/activate           # Linux/Mac
# venv\Scripts\activate            # Windows
```

### 2. Paketləri yüklə

```bash
pip install -r requirements.txt
```

### 3. Mühit dəyişənlərini qur

```bash
cp .env.example .env
```

`.env` faylını aç və `ANTHROPIC_API_KEY` daxil et. PostgreSQL istifadə edirsənsə, `DATABASE_URL`-i də yenilə.

### 4. Database-ni qur

```bash
# Cədvəlləri yarat və qanunları doldur
python seed_laws.py
```

Bu skript:
- DB cədvəllərini yaradır
- `laws.json`-dan 1700+ qanun maddəsini yükləyir
- Statistika göstərir

### 5. Serveri işlət

```bash
uvicorn main:app --reload
```

Server `http://localhost:8000`-də işləyir.

### 6. Frontend-i aç

`index.html` faylını brauzerdə aç. Server avtomatik aşkarlanır.

---

## İstifadə

### REST API

API sənədləşməsi: `http://localhost:8000/docs` (Swagger UI)

| Endpoint | Metod | Təsvir |
|---|---|---|
| `/upload/file` | POST | PDF/DOCX/TXT fayl yüklə |
| `/upload/text` | POST | Copy-paste mətn |
| `/upload/images` | POST | 1-6 şəkil (fiziki müqavilə) |
| `/upload/terms` | POST | Terms/Privacy (streaming) |
| `/analysis/{id}` | GET | Analiz nəticəsini gətir |
| `/documents` | GET | Bütün sənədlərin siyahısı |
| `/health` | GET | Sistem statusu |

### Frontend

4 tab var:
- 📄 **Fayl** — PDF/DOCX/TXT yüklə
- 📋 **Mətn** — copy-paste
- 📷 **Şəkil** — fiziki müqavilə (maks 6 səhifə)
- 🔒 **Şərtlər və Məxfilik** — Terms + Privacy birgə, streaming

---

## Mühit dəyişənləri

| Dəyişən | Standart dəyər | Təsvir |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Tələb olunur**. Claude API açarı |
| `DATABASE_URL` | `sqlite:///./contract_analyzer.db` | DB URL |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | İstifadə olunan model |
| `CLAUDE_MAX_TOKENS` | `8192` | Maks output token |
| `CLAUDE_MAX_FUNC_CALLS` | `6` | Function call loop limiti |
| `MAX_IMAGES` | `6` | Maks şəkil sayı |
| `MAX_IMAGE_SIZE_MB` | `5` | Hər şəkilin maks ölçüsü |
| `DEBUG` | `false` | Debug log-ları |

---

## Qanun bazası

`laws.json` üç bölmədən ibarətdir:

| Standart | Maddə sayı | Mənbə |
|---|---|---|
| `az_law` | ~1700 | Mülki Məcəllə, Əmək Məcəlləsi, Fərdi Məlumatlar Qanunu |
| `gdpr` | 12 | GDPR Articles 5-83 |
| `cyber_sec` | 5 | Kibertəhlükəsizlik mütəxəssis rəyi |

Mənbələr:
- `cbar.az` — Mülki Məcəllə
- `frameworks.e-qanun.az` — Əmək Məcəlləsi, Fərdi Məlumatlar Qanunu

Yenidən scrape etmək üçün:
```bash
python scrape_laws.py    # laws.json yenidən yaradılır
python seed_laws.py      # DB yenilənir
```

---

## Function calling

Claude analiz zamanı 5 funksiya çağıra bilər:

| Funksiya | Təyinat |
|---|---|
| `get_law_article` | AZ qanun maddəsi tap |
| `get_gdpr_article` | GDPR maddəsi tap |
| `check_compliance` | Müqavilə uyğunluğunu yoxla |
| `get_penalty_info` | Sanksiya məlumatı |
| `get_cybersec_opinion` | Kibertəhlükəsizlik rəyi |

Loop limiti: bir analiz üçün maksimum **6 çağırış** (sonsuz loop və token sərfini qoruyur).

---

## Təhlükəsizlik

### Prompt injection müdafiəsi

İki səviyyəli sistem:

**Səviyyə 1 — Input Sanitization** (`security.py`):
- 20+ pattern detection (instruction override, role injection, system tags)
- 2+ yüksək risk pattern → bloklayır
- Şübhəli hissələr `[⚠ FILTERED ⚠]` ilə əvəz edilir

**Səviyyə 2 — Prompt Sandwiching** (`analyzer.py`):
- User mətni `---DOCUMENT START---` / `---DOCUMENT END---` arasında
- System prompt-da dəyişməz qaydalar
- Şəkillərə xüsusi sərt outro

### Diqqət edilməli məsələlər

- API key heç vaxt frontend-də göstərilmir (CORS arxasında qalır)
- Faylların ölçüsü və tipi yoxlanır
- SQLAlchemy parametrli sorğular SQL injection-dan qoruyur
- Hər upload endpoint-i Pydantic validation-dan keçir

---

## JSON cavab formatı

Hər analiz aşağıdakı strukturu qaytarır:

```json
{
  "id": 1,
  "document_id": 1,
  "risk_level": "MEDIUM",
  "risk_score": 5.5,
  "risk_clauses": [
    {
      "clause": "maddə mətni",
      "risk_level": "HIGH",
      "explanation": "niyə risklidir"
    }
  ],
  "obligations": ["öhdəlik 1"],
  "important_dates": ["31.12.2025"],
  "data_collected": ["e-poçt", "məkan"],
  "third_party": [
    {"partner": "Meta", "what": "...", "purpose": "..."}
  ],
  "user_rights": ["silmə hüququ"],
  "az_law": {
    "status": "QISMƏN UYĞUN",
    "violations": [
      {
        "law_name": "Mülki Məcəllə",
        "article_num": "468.1",
        "description": "pozuntu izahı"
      }
    ]
  },
  "gdpr": {...},
  "cyber_sec": {...},
  "simple_summary": "sadə dildə xülasə",
  "recommendation": "Ehtiyatla imzala",
  "tokens_used": 5234,
  "function_calls": 3
}
```

---

## Test ssenariləri

| Sənəd | Endpoint | Gözlənilən nəticə |
|---|---|---|
| Azərbaycan iş müqaviləsi (PDF) | `/upload/file` | AZ qanun pozuntuları, risk maddələri |
| WhatsApp Privacy Policy (copy-paste) | `/upload/terms` | GDPR + cyber_sec uyğunluğu, streaming |
| Fiziki müqavilə (6 şəkil) | `/upload/images` | OCR + risk analizi |
| Prompt injection cəhdi | İstənilən | `400 — Təhlükəsizlik` xətası |

---

## Bilinən məhdudiyyətlər

- Şəkillərin OCR keyfiyyəti şəkil keyfiyyətindən asılıdır
- e-qanun.az HTML strukturu dəyişdikdə scraper yenilənməlidir
- Claude bəzən maddə nömrələrini uydura bilər (function call nəticəsi yox)
- Frontend tək istifadəçi üçündür (autentifikasiya yoxdur)
- Rate limiting yoxdur

---

## Lisenziya

MIT License — bax [LICENSE](LICENSE)

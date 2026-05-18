"""
TOOLS.PY — Claude Function Calling Tools
Dərs 6: Funksiyalar və "Tool" anlayışı
Dərs 10-11: SQL ilə DB sorğuları

Bu fayl 2 hissədən ibarətdir:
1. TOOL DEFINITIONS — Claude-a hansı funksiyaları çağıra biləcəyini izah edir
2. TOOL HANDLERS — Həmin funksiyaların real Python implementasiyası
"""

import json
import os
from typing import Optional

from sqlalchemy.orm import Session

from database import Law

try:
    import redis
except ImportError:
    redis = None


# -------------------------------------------------------
# REDIS CACHE
# Qoşulu deyilsə sistem sakitcə cache-siz işləyir
# (graceful degradation)
# -------------------------------------------------------

REDIS_URL         = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 86400))  # 24 saat
CACHE_PREFIX      = "contract_analyzer:law:"
DEBUG             = os.getenv("DEBUG", "false").lower() == "true"


def _log(msg: str):
    """DEBUG=true olduqda terminala yazır."""
    if DEBUG:
        print(msg, flush=True)


class RedisCache:
    """
    Redis cache wrapper — fault-tolerant.
    Redis qoşulu deyilsə bütün metodlar None/no-op qaytarır.
    Sistem cache olmadan da işləməlidir.
    """

    def __init__(self):
        self.client: Optional["redis.Redis"] = None
        self.enabled                          = False
        self._connect()

    def _connect(self):
        if redis is None:
            print("⚠️  redis paketi quraşdırılmayıb — cache söndürülüb")
            return

        try:
            self.client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self.client.ping()
            self.enabled = True
            print(f"✅ Redis cache aktivdir ({REDIS_URL})")
        except Exception as e:
            print(f"⚠️  Redis qoşulmadı: {type(e).__name__}. Cache söndürülüb.")
            self.client  = None
            self.enabled = False

    def get(self, key: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            value = self.client.get(CACHE_PREFIX + key)
            if value:
                _log(f"🟢 Cache HIT: {key[:60]}")
            else:
                _log(f"🔍 Cache MISS: {key[:60]}")
            return value
        except Exception as e:
            _log(f"❌ Cache GET failed: {type(e).__name__}: {e}")
            return None

    def set(self, key: str, value: str):
        if not self.enabled:
            _log(f"⚠️  Cache disabled — not saving {key[:60]}")
            return
        try:
            result = self.client.setex(
                CACHE_PREFIX + key,
                CACHE_TTL_SECONDS,
                value
            )
            _log(
                f"💾 Cache SET: {CACHE_PREFIX + key[:60]} "
                f"({len(value)} chars, TTL {CACHE_TTL_SECONDS}s) → {result}"
            )
        except Exception as e:
            _log(f"❌ Cache SET failed: {type(e).__name__}: {e}")

    def stats(self) -> dict:
        """Debug üçün — cache statistikası."""
        if not self.enabled:
            return {"enabled": False}
        try:
            keys = self.client.keys(CACHE_PREFIX + "*")
            return {
                "enabled":   True,
                "key_count": len(keys),
                "ttl_hours": CACHE_TTL_SECONDS // 3600
            }
        except Exception:
            return {"enabled": True, "error": "stats unavailable"}


# Qlobal singleton — bir dəfə qoşulur
cache = RedisCache()


# -------------------------------------------------------
# HISSƏ 1: TOOL DEFINITIONS
# Claude bu sxemlərə baxıb özü qərar verir:
# "Mənə bu məlumat lazımdır, bu funksiyanı çağırım"
# -------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_law_article",
        "description": (
            "Azərbaycan qanunvericiliyindən konkret maddə gətirir. "
            "Müqavilədə şübhəli maddə tapıldıqda istifadə et. "
            "Məsələn: iş müqaviləsində işdən çıxarma şərtlərini "
            "Əmək Məcəlləsi ilə müqayisə etmək üçün."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "law_name": {
                    "type": "string",
                    "description": (
                        "Qanunun adı. Mümkün dəyərlər: "
                        "'Mülki Məcəllə', 'Əmək Məcəlləsi', "
                        "'Fərdi Məlumatlar Qanunu', "
                        "'İstehlakçıların Hüquqlarının Müdafiəsi Qanunu'"
                    )
                },
                "article_num": {
                    "type": "string",
                    "description": "Maddə nömrəsi. Məsələn: '68', '419.1', '8'"
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "Axtarış mövzusu — maddə nömrəsi bilinmədikdə. "
                        "Məsələn: 'işdən çıxarma', 'müqavilənin pozulması', "
                        "'fərdi məlumat razılığı'"
                    )
                }
            },
            "required": []
        }
    },

    {
        "name": "get_gdpr_article",
        "description": (
            "GDPR-dən (Avropa Məlumat Mühafizəsi Nizamnaməsi) "
            "müvafiq maddəni gətirir. "
            "Terms of Service və Privacy Policy analizində istifadə et. "
            "Məsələn: məlumat toplanması, silinmə hüququ, "
            "3-cü tərəfə ötürmə kimi mövzular üçün."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "article_num": {
                    "type": "string",
                    "description": "GDPR maddə nömrəsi. Məsələn: '6', '17', '13'"
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "Axtarış mövzusu. Məsələn: "
                        "'consent', 'right to erasure', "
                        "'data transfer', 'children data'"
                    )
                }
            },
            "required": []
        }
    },

    {
        "name": "check_compliance",
        "description": (
            "Müqavilə maddəsinin AZ qanununa və ya GDPR-ə uyğun "
            "olub olmadığını yoxlayır. "
            "Risk səviyyəsini və pozuntu əsasını qaytarır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clause_text": {
                    "type": "string",
                    "description": "Yoxlanılacaq müqavilə maddəsinin mətni"
                },
                "standard": {
                    "type": "string",
                    "description": "Standart: 'AZ_LAW' və ya 'GDPR'",
                    "enum": ["AZ_LAW", "GDPR"]
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Kateqoriya: 'müqavilə', 'əmək', "
                        "'fərdi məlumat', 'istehlakçı'"
                    )
                }
            },
            "required": ["clause_text", "standard"]
        }
    },

    {
        "name": "get_penalty_info",
        "description": (
            "Qanun pozuntusu halında tətbiq edilə biləcək "
            "sanksiya və cərimə məlumatını gətirir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "violation_type": {
                    "type": "string",
                    "description": (
                        "Pozuntu növü. Məsələn: "
                        "'fərdi məlumat pozuntusu', "
                        "'əmək hüququ pozuntusu', "
                        "'istehlakçı hüququ pozuntusu'"
                    )
                },
                "standard": {
                    "type": "string",
                    "description": "'AZ_LAW' və ya 'GDPR'",
                    "enum": ["AZ_LAW", "GDPR"]
                }
            },
            "required": ["violation_type"]
        }
    },

    {
        "name": "get_cybersec_opinion",
        "description": (
            "Kibertəhlükəsizlik mütəxəssisinin rəyini gətirir. "
            "Privacy Policy və Terms of Service analizində istifadə et. "
            "Məsələn: üçüncü tərəflə paylaşım, məcburi arbitraj, "
            "şifrələmə, məlumat saxlanması mövzularında "
            "praktik təhlükəsizlik məsləhəti verir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Mövzu. Məsələn: 'üçüncü tərəf paylaşımı', "
                        "'şifrələmə', 'arbitraj', 'silinmə hüququ', "
                        "'icazələr', 'məlumat minimumlaşdırılması'"
                    )
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Kateqoriya: 'məxfilik', 'təhlükəsizlik', 'hüquqi'"
                    )
                }
            },
            "required": ["topic"]
        }
    }
]


# -------------------------------------------------------
# HISSƏ 2: TOOL HANDLERS
# Claude tool call etdikdə bu funksiyalar işləyir
# DB-dən məlumat çəkir, Claude-a qaytarır
# -------------------------------------------------------

def get_law_article(
    db:          Session,
    law_name:    str = "",
    article_num: str = "",
    topic:       str = ""
) -> str:
    """
    DB-dən AZ qanun maddəsi gətirir.
    Əvvəlcə cache yoxlayır — tapılırsa DB-yə getmir.
    """
    # Cache açarı yarat
    cache_key = f"AZ_{law_name}_{article_num}_{topic}".replace(" ", "_")

    # Cache yoxla
    cached = _get_from_cache(db, cache_key)
    if cached:
        return cached

    # DB-dən axtar
    query = db.query(Law).filter(Law.standard == "AZ_LAW")

    if law_name:
        query = query.filter(Law.law_name.ilike(f"%{law_name}%"))

    if article_num:
        query = query.filter(Law.article_num == article_num)

    if topic:
        query = query.filter(
            Law.title.ilike(f"%{topic}%") |
            Law.content.ilike(f"%{topic}%") |
            Law.category.ilike(f"%{topic}%")
        )

    laws = query.limit(3).all()

    if not laws:
        result = (
            f"'{law_name} {article_num} {topic}' üzrə "
            "DB-də məlumat tapılmadı."
        )
    else:
        parts = []
        for law in laws:
            parts.append(
                f"📌 {law.law_name} — Maddə {law.article_num}\n"
                f"Başlıq: {law.title}\n"
                f"Məzmun: {law.content}\n"
                f"Risk çəkisi: {law.risk_weight}"
            )
        result = "\n\n---\n\n".join(parts)

    # Cache-ə yaz
    _save_to_cache(db, cache_key, result)
    return result


def get_gdpr_article(
    db:          Session,
    article_num: str = "",
    topic:       str = ""
) -> str:
    """DB-dən GDPR maddəsi gətirir."""
    cache_key = f"GDPR_{article_num}_{topic}".replace(" ", "_")

    cached = _get_from_cache(db, cache_key)
    if cached:
        return cached

    query = db.query(Law).filter(Law.standard == "GDPR")

    if article_num:
        query = query.filter(Law.article_num == article_num)

    if topic:
        query = query.filter(
            Law.title.ilike(f"%{topic}%") |
            Law.content.ilike(f"%{topic}%")
        )

    laws = query.limit(3).all()

    if not laws:
        result = f"GDPR Maddə '{article_num} {topic}' tapılmadı."
    else:
        parts = []
        for law in laws:
            parts.append(
                f"📌 GDPR — Article {law.article_num}\n"
                f"Title: {law.title}\n"
                f"Content: {law.content}\n"
                f"Risk weight: {law.risk_weight}"
            )
        result = "\n\n---\n\n".join(parts)

    _save_to_cache(db, cache_key, result)
    return result


def check_compliance(
    db:          Session,
    clause_text: str,
    standard:    str,
    category:    str = ""
) -> str:
    """
    Müqavilə maddəsini qanunla müqayisə edir.
    Bu funksiya DB-dən uyğun qanunları tapıb
    Claude-a kontekst kimi qaytarır.
    Claude özü qərar verir: uyğundur ya yox.
    """
    cache_key = f"COMPLY_{standard}_{category}_{hash(clause_text[:100])}"

    cached = _get_from_cache(db, cache_key)
    if cached:
        return cached

    # Kateqoriyaya görə uyğun qanunları tap
    query = db.query(Law).filter(Law.standard == standard)

    if category:
        query = query.filter(Law.category.ilike(f"%{category}%"))

    # Risk çəkisi yüksək olanları əvvəl göstər
    laws = query.order_by(Law.risk_weight.desc()).limit(5).all()

    if not laws:
        result = f"{standard} üzrə '{category}' kateqoriyasında qanun tapılmadı."
    else:
        parts = [f"Aşağıdakı {standard} tələbləri ilə yoxla:\n"]
        for law in laws:
            parts.append(
                f"• {law.law_name} Maddə {law.article_num}: "
                f"{law.title}\n  {law.content[:300]}..."
            )
        result = "\n".join(parts)

    _save_to_cache(db, cache_key, result)
    return result


def get_penalty_info(
    db:             Session,
    violation_type: str,
    standard:       str = "AZ_LAW"
) -> str:
    """Sanksiya məlumatı gətirir."""
    cache_key = f"PENALTY_{standard}_{violation_type}".replace(" ", "_")

    cached = _get_from_cache(db, cache_key)
    if cached:
        return cached

    query = db.query(Law).filter(
        Law.standard  == standard,
        Law.category  == "sanksiya",
        Law.content.ilike(f"%{violation_type}%")
    )

    laws = query.limit(3).all()

    if not laws:
        result = f"'{violation_type}' üzrə sanksiya məlumatı tapılmadı."
    else:
        parts = []
        for law in laws:
            parts.append(
                f"⚠️ {law.law_name} Maddə {law.article_num}\n"
                f"{law.content}"
            )
        result = "\n\n".join(parts)

    _save_to_cache(db, cache_key, result)
    return result


def get_cybersec_opinion(
    db:       Session,
    topic:    str,
    category: str = ""
) -> str:
    """
    Kibertəhlükəsizlik mütəxəssis rəyini gətirir.
    Privacy/Terms analizində praktik məsləhət verir.
    """
    cache_key = f"CYBER_{category}_{topic}".replace(" ", "_")

    cached = _get_from_cache(db, cache_key)
    if cached:
        return cached

    query = db.query(Law).filter(Law.standard == "CYBER_SEC")

    if category:
        query = query.filter(Law.category.ilike(f"%{category}%"))

    if topic:
        query = query.filter(
            Law.title.ilike(f"%{topic}%") |
            Law.content.ilike(f"%{topic}%")
        )

    # Risk çəkisi yüksək olanları əvvəl
    opinions = query.order_by(Law.risk_weight.desc()).limit(3).all()

    if not opinions:
        result = f"'{topic}' üzrə kibertəhlükəsizlik rəyi tapılmadı."
    else:
        parts = []
        for op in opinions:
            parts.append(
                f"🛡️ Kibertəhlükəsizlik mütəxəssisi (Rəy {op.article_num})\n"
                f"Mövzu: {op.title}\n"
                f"Rəy: {op.content}\n"
                f"Risk dərəcəsi: {op.risk_weight}/5"
            )
        result = "\n\n---\n\n".join(parts)

    _save_to_cache(db, cache_key, result)
    return result


# -------------------------------------------------------
# CACHE KÖMƏKÇI FUNKSİYALAR
# Token sərfiyyatını azaldır
# -------------------------------------------------------

# -------------------------------------------------------
# KÖMƏKÇI — köhnə API saxlanılır, indi Redis istifadə edir
# -------------------------------------------------------

def _get_from_cache(db: Session, key: str) -> Optional[str]:
    """Redis-dən oxu. Tapılmasa None."""
    return cache.get(key)


def _save_to_cache(db: Session, key: str, result: str) -> None:
    """Redis-də saxla (24 saat TTL ilə)."""
    cache.set(key, result)


# -------------------------------------------------------
# TOOL DISPATCHER
# Claude-un tool_use cavabını işləyir
# Hansı funksiyanı çağıracağını avtomatik müəyyən edir
# -------------------------------------------------------

def handle_tool_call(
    db:        Session,
    tool_name: str,
    tool_input: dict
) -> str:
    """
    Claude tool_use bloku qaytaranda bu funksiya çağırılır.

    tool_name:  "get_law_article"
    tool_input: {"law_name": "Əmək Məcəlləsi", "article_num": "68"}

    return: tool-un nəticəsi (string)
    """
    handlers = {
        "get_law_article":      get_law_article,
        "get_gdpr_article":     get_gdpr_article,
        "check_compliance":     check_compliance,
        "get_penalty_info":     get_penalty_info,
        "get_cybersec_opinion": get_cybersec_opinion,
    }

    handler = handlers.get(tool_name)

    if not handler:
        return f"Bilinməyən tool: {tool_name}"

    try:
        return handler(db=db, **tool_input)
    except TypeError as e:
        return f"Tool parametr xətası: {str(e)}"
    except Exception as e:
        return f"Tool icra xətası: {str(e)}"

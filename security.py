"""
SECURITY.PY — Prompt Injection Detection və Sanitization

Bu modul istifadəçi inputunu Claude-a göndərməzdən əvvəl yoxlayır:
1. Şübhəli pattern-ləri tapır (injection cəhdləri)
2. Risk səviyyəsi hesablayır
3. Təhlükəli pattern-ləri təmizləyir və ya bloklayır

İstifadə:
    sanitizer = InputSanitizer()
    result = sanitizer.sanitize(text)
    if result.is_blocked:
        raise SecurityException(result.reason)
"""

import re
from dataclasses import dataclass, field
from enum import Enum


# -------------------------------------------------------
# ŞÜBHƏLİ PATTERN-LƏR
# Hər pattern bir injection cəhdini təmsil edir
# -------------------------------------------------------

# Yüksək risk — bloklamaq lazımdır
HIGH_RISK_PATTERNS = [
    # Klassik instruction override
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|commands?|rules?)",
     "Instruction override cəhdi"),
    (r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)",
     "Instruction override cəhdi"),
    (r"forget\s+(everything|all|previous)\s+(you\s+)?(know|learned|were\s+told)",
     "Memory wipe cəhdi"),

    # Rol dəyişikliyi
    (r"you\s+are\s+(now|currently)\s+(a|an)\s+\w+",
     "Role injection cəhdi"),
    (r"act\s+as\s+(a|an|if)\s+(?!hüquq|legal|analitik)",
     "Role injection cəhdi"),
    (r"pretend\s+(to\s+be|you\s+are)",
     "Role injection cəhdi"),

    # System prompt tagləri
    (r"\[INST\]|\[/INST\]|\[SYSTEM\]|\[/SYSTEM\]",
     "System tag injection"),
    (r"<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\|user\|>|<\|assistant\|>",
     "Special token injection"),
    (r"<system>|</system>|<assistant>|</assistant>",
     "XML tag injection"),

    # Debug/admin mode
    (r"(enter|activate|enable)\s+(debug|admin|developer|god|maintenance)\s+mode",
     "Privileged mode cəhdi"),
    (r"system\s+(override|bypass|prompt|injection)",
     "System override cəhdi"),

    # JSON/output manipulasiyası
    (r"return\s+(only|just|exactly)\s*[:\s]*\{[^}]*risk[^}]*low",
     "Output manipulation cəhdi"),
    (r"set\s+(risk_score|risk_level)\s*[=:]\s*[\"']?(0|low)",
     "Risk score manipulation cəhdi"),
    (r"mark\s+(this|as|the\s+contract)\s+(as\s+)?(safe|low\s+risk|approved)",
     "Risk classification manipulation"),

    # Prompt leak attempts
    (r"(print|output|show|reveal|tell\s+me)\s+(your|the)\s+(system\s+)?prompt",
     "Prompt extraction cəhdi"),
    (r"what\s+(are|were)\s+your\s+(initial\s+)?instructions",
     "Prompt extraction cəhdi"),
]

# Orta risk — log et, davam et, amma diqqətli ol
MEDIUM_RISK_PATTERNS = [
    (r"new\s+(task|instruction|goal):",
     "Yeni təlimat cəhdi"),
    (r"important:\s+(you\s+must|do\s+not)",
     "Şübhəli vurğu"),
    (r"(repeat|say)\s+(after\s+me|the\s+following)",
     "Echo manipulation"),
    (r"override\s+(default|safety|previous)",
     "Override cəhdi"),
    (r"jailbreak|DAN\s+mode|developer\s+mode",
     "Bilinən jailbreak"),
]


# -------------------------------------------------------
# RISK SƏVIYYƏLƏRİ
# -------------------------------------------------------

class SecurityRisk(str, Enum):
    SAFE     = "SAFE"          # heç bir pattern tapılmadı
    LOW      = "LOW"            # 1-2 orta risk pattern
    MEDIUM   = "MEDIUM"         # çox orta risk və ya 1 yüksək risk
    HIGH     = "HIGH"            # 2+ yüksək risk pattern → BLOK
    BLOCKED  = "BLOCKED"         # birbaşa bloklanır


# -------------------------------------------------------
# NƏTİCƏ STRUKTURU
# -------------------------------------------------------

@dataclass
class SanitizationResult:
    original_text:  str
    cleaned_text:   str
    risk_level:     SecurityRisk
    threats_found:  list[dict] = field(default_factory=list)
    is_blocked:     bool = False
    block_reason:   str = ""

    def to_dict(self) -> dict:
        return {
            "risk_level":    self.risk_level.value,
            "threats_count": len(self.threats_found),
            "is_blocked":    self.is_blocked,
            "block_reason":  self.block_reason
        }


# -------------------------------------------------------
# ANA CLASS
# -------------------------------------------------------

class InputSanitizer:
    """
    İstifadəçi inputunu prompt injection üçün yoxlayır.

    Strategiya:
    - HIGH risk pattern-ləri tapsa BLOKLAYIR
    - MEDIUM pattern-ləri tapsa LOG edir, mətni təmizləyir, davam edir
    - Heç nə tapmasa olduğu kimi keçirir
    """

    # 2+ HIGH pattern → blok
    BLOCK_THRESHOLD = 2

    def __init__(self):
        self.high_compiled = [
            (re.compile(p, re.IGNORECASE | re.MULTILINE), desc)
            for p, desc in HIGH_RISK_PATTERNS
        ]
        self.medium_compiled = [
            (re.compile(p, re.IGNORECASE | re.MULTILINE), desc)
            for p, desc in MEDIUM_RISK_PATTERNS
        ]

    def sanitize(self, text: str) -> SanitizationResult:
        """
        Mətni yoxla və təmizlə.
        """
        result = SanitizationResult(
            original_text = text,
            cleaned_text  = text,
            risk_level    = SecurityRisk.SAFE
        )

        # Boş mətnə baxma
        if not text or len(text.strip()) < 10:
            return result

        # 1. HIGH risk pattern-ləri tap
        high_threats = self._scan(text, self.high_compiled, "HIGH")
        result.threats_found.extend(high_threats)

        # 2. MEDIUM risk pattern-ləri tap
        medium_threats = self._scan(text, self.medium_compiled, "MEDIUM")
        result.threats_found.extend(medium_threats)

        # 3. Risk səviyyəsini hesabla
        result.risk_level = self._calculate_risk(high_threats, medium_threats)

        # 4. BLOKLAMA qərarı
        if len(high_threats) >= self.BLOCK_THRESHOLD:
            result.is_blocked   = True
            result.block_reason = (
                f"Mətndə {len(high_threats)} prompt injection cəhdi tapıldı. "
                f"İlk: {high_threats[0]['description']}"
            )
            result.risk_level = SecurityRisk.BLOCKED
            return result

        # 5. TƏMİZLƏMƏ — şübhəli hissələri neytrallaşdır
        result.cleaned_text = self._neutralize(text, high_threats + medium_threats)

        return result

    # -------------------------------------------------------
    # KÖMƏKÇI METODLAR
    # -------------------------------------------------------

    def _scan(self, text: str, patterns: list, severity: str) -> list[dict]:
        """Mətndə pattern-ləri tap, tapılanları qaytar."""
        threats = []

        for pattern, description in patterns:
            for match in pattern.finditer(text):
                threats.append({
                    "severity":     severity,
                    "description":  description,
                    "matched_text": match.group(0)[:100],
                    "position":     match.start()
                })

        return threats

    def _calculate_risk(self, high: list, medium: list) -> SecurityRisk:
        """Tapılan pattern sayına görə risk səviyyəsini təyin et."""
        if len(high) >= self.BLOCK_THRESHOLD:
            return SecurityRisk.BLOCKED
        if len(high) >= 1:
            return SecurityRisk.HIGH
        if len(medium) >= 3:
            return SecurityRisk.MEDIUM
        if len(medium) >= 1:
            return SecurityRisk.LOW
        return SecurityRisk.SAFE

    def _neutralize(self, text: str, threats: list[dict]) -> str:
        """
        Şübhəli hissələri neytrallaşdır.
        Silmir, sadəcə '⚠ FILTERED ⚠' ilə əvəz edir
        ki, Claude görsün və nəzərə almasın.
        """
        if not threats:
            return text

        cleaned = text

        # Mövqeyə görə tərs sırala (sondan əvvələ),
        # ki, index-lər pozulmasın
        sorted_threats = sorted(
            threats,
            key=lambda t: t["position"],
            reverse=True
        )

        for threat in sorted_threats:
            matched = threat["matched_text"]
            replacement = "[⚠ FILTERED: prompt injection cəhdi ⚠]"

            # İlk uyğunluğu əvəz et
            cleaned = cleaned.replace(matched, replacement, 1)

        return cleaned


# -------------------------------------------------------
# EXCEPTION
# -------------------------------------------------------

class PromptInjectionException(Exception):
    """Mətndə prompt injection tapıldıqda atılır."""

    def __init__(self, message: str, result: SanitizationResult):
        super().__init__(message)
        self.result = result


# -------------------------------------------------------
# QLOBAL INSTANS — singleton
# -------------------------------------------------------

sanitizer = InputSanitizer()


def sanitize_text(text: str) -> SanitizationResult:
    """Qısa yol funksiyası — singleton istifadə edir."""
    return sanitizer.sanitize(text)

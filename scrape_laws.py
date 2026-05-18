"""
SCRAPE_LAWS.PY — Azərbaycan qanunlarını avtomatik çəkir
Bir dəfə işləyir, laws.json yaradır.

İstifadə:
    python scrape_laws.py
    python seed_laws.py

Mənbələr:
    Mülki Məcəllə    → cbar.az (təmiz HTML)
    Əmək Məcəlləsi    → e-qanun.az
    Fərdi Məlumatlar → e-qanun.az
"""

import json
import os
import re
import time

import httpx
from bs4 import BeautifulSoup


# -------------------------------------------------------
# MƏCƏLLƏ KONFİQURASIYASI
# -------------------------------------------------------

CODES = [
    {
        "law_name": "Mülki Məcəllə",
        "url":      "https://www.cbar.az/law-169/civil-code-of-the-republic-of-aerbaijan",
        "default_category": "müqavilə",
        "default_risk":     3,
    },
    {
        "law_name": "Əmək Məcəlləsi",
        "url":      "https://frameworks.e-qanun.az/46/f_46943.html",
        "default_category": "əmək",
        "default_risk":     3,
    },
    {
        "law_name": "Fərdi Məlumatlar Haqqında Qanun",
        "url":      "https://frameworks.e-qanun.az/19/f_19675.html",
        "default_category": "fərdi məlumat",
        "default_risk":     4,
    }
]


# Kateqoriya təyin etmək üçün açar sözlər
CATEGORY_KEYWORDS = {
    "müqavilə":      ["müqavilə", "razılaşma", "öhdəlik", "icra", "təminat"],
    "məsuliyyət":    ["məsuliyyət", "zərər", "ödəniş", "kompensasiya"],
    "etibarsızlıq":  ["etibarsız", "ləğv", "təhdid", "aldatma"],
    "əmək":          ["əmək", "iş", "işçi", "işəgötürən", "əmək haqqı"],
    "məzuniyyət":    ["məzuniyyət", "istirahət", "tətil"],
    "xitam":         ["xitam", "işdənçıxarma", "azad"],
    "fərdi məlumat": ["fərdi məlumat", "subyekt", "operator", "razılıq"],
    "ötürmə":        ["ötürmə", "transfer", "xarici", "üçüncü tərəf"],
    "silinmə":       ["silinmə", "məhv", "düzəliş"],
    "sanksiya":      ["cərimə", "sanksiya", "məsuliyyət"]
}

HIGH_RISK_WORDS = [
    "etibarsız", "məsuliyyət", "zərər", "cərimə",
    "sanksiya", "məhkəmə", "pozuntu", "ləğv",
    "razılıq", "uşaq", "yetkinlik", "qadağa"
]


# -------------------------------------------------------
# HTML ÇƏKMƏ
# -------------------------------------------------------

def fetch_html(url: str) -> str:
    """URL-dən HTML çəkir."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    print(f"  📡 Çəkilir: {url}")

    response = httpx.get(
        url,
        headers=headers,
        timeout=60,
        follow_redirects=True
    )
    response.raise_for_status()

    # Encoding-i düzgün təyin et — e-qanun.az bəzən səhv göstərir
    if not response.encoding or response.encoding.lower() in ("ascii", "iso-8859-1"):
        response.encoding = "utf-8"

    print(f"  ✓  Status: {response.status_code}")
    print(f"  ✓  Encoding: {response.encoding}")
    print(f"  ✓  Final URL: {response.url}")
    print(f"  ✓  Ölçü: {len(response.text):,} simvol")

    time.sleep(1)  # Rate limiting

    return response.text


# -------------------------------------------------------
# HTML → MƏTN
# -------------------------------------------------------

def html_to_text(html: str) -> str:
    """HTML-dən təmiz mətn çıxarır."""
    soup = BeautifulSoup(html, "html.parser")

    # Lazımsız elementləri sil
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # Mətni çıxar
    text = soup.get_text(separator="\n")

    # HTML entity və xüsusi simvolları düzəlt
    text = text.replace("\u00A0", " ")    # non-breaking space
    text = text.replace("\u200B", "")      # zero-width space
    text = text.replace("\xa0", " ")

    # Word artefaktları
    text = re.sub(r"<!\[if[^\]]*\]>",  "", text)
    text = re.sub(r"<!\[endif\]>",      "", text)
    text = re.sub(r"\[\d+\]",           "", text)  # qeyd nömrələri [1], [2]

    # Boşluqları normallaşdır
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# -------------------------------------------------------
# MADDƏLƏRİ AYIR — çevik regex
# -------------------------------------------------------

def extract_articles(text: str) -> list[dict]:
    """
    Mətndən maddələri ayırır.
    Müxtəlif formatları dəstəkləyir:
        "Maddə 5."
        "Maddə 5-1."
        "Maddə 419.1."
        "M a d d ə 5 ."  (e-qanun.az-ın formatı)
    """
    # "Maddə" ilə "M a d d ə" formatlarını birləşdir
    text = re.sub(
        r"M\s*a\s*d\s*d\s*ə\s+",
        "Maddə ",
        text
    )

    # Pattern: "Maddə X. Title"
    pattern = re.compile(
        r"Maddə\s+(\d+(?:[-.]\d+)*)\s*[.\s]\s*([^\n]{3,200})",
        re.MULTILINE
    )

    matches = list(pattern.finditer(text))

    if not matches:
        return []

    articles = []

    for i, match in enumerate(matches):
        article_num = match.group(1).strip()
        title       = match.group(2).strip()

        # Title-ı təmizlə
        title = re.sub(r"\s+", " ", title)
        title = title.rstrip(".·•—-").strip()

        # Məzmun: bu match-dən növbətisinə qədər
        start = match.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        # Çox qısa məzmun = TOC linkidir, atla
        if len(content) < 80:
            continue

        # Çox uzun məzmunu kəs
        if len(content) > 4000:
            content = content[:4000] + "..."

        articles.append({
            "article_num": article_num,
            "title":       title[:200],
            "content":     content
        })

    return articles


# -------------------------------------------------------
# KATEQORIYA və RİSK
# -------------------------------------------------------

def determine_category(article: dict, default: str) -> str:
    text = (article["title"] + " " + article["content"]).lower()

    best_cat   = default
    best_score = 0

    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(text.count(kw.lower()) for kw in keywords)
        if score > best_score:
            best_score = score
            best_cat   = cat

    return best_cat


def determine_risk_weight(article: dict, default: int) -> int:
    text = (article["title"] + " " + article["content"]).lower()

    score = sum(1 for word in HIGH_RISK_WORDS if word in text)

    if score >= 4:
        return 5
    elif score >= 2:
        return 4
    elif score >= 1:
        return 3
    else:
        return default


# -------------------------------------------------------
# BİR MƏCƏLLƏNİ EMAL ET
# -------------------------------------------------------

def process_code(code: dict) -> list[dict]:
    print(f"\n📜 {code['law_name']}")
    print(f"   URL: {code['url']}")

    try:
        html = fetch_html(code["url"])
    except httpx.HTTPError as e:
        print(f"  ❌ HTTP xətası: {e}")
        return []
    except Exception as e:
        print(f"  ❌ Xəta: {e}")
        return []

    text = html_to_text(html)
    print(f"  ✓  Təmiz mətn: {len(text):,} simvol")

    articles = extract_articles(text)
    print(f"  ✅ {len(articles)} maddə tapıldı")

    # Hər maddə üçün meta əlavə et
    result = []
    for art in articles:
        result.append({
            "law_name":    code["law_name"],
            "article_num": art["article_num"],
            "title":       art["title"],
            "content":     art["content"],
            "category":    determine_category(art, code["default_category"]),
            "risk_weight": determine_risk_weight(art, code["default_risk"])
        })

    return result


# -------------------------------------------------------
# GDPR — manual
# -------------------------------------------------------

GDPR_ARTICLES = [
    {
        "law_name":    "GDPR",
        "article_num": "5",
        "title":       "Fərdi məlumatların işlənilməsi prinsipləri",
        "content":     "Fərdi məlumatlar: qanuni, ədalətli və şəffaf şəkildə işlənilməli; konkret, aydın və qanuni məqsədlər üçün toplanmalı; adekvat, aidiyyəti olan və zəruri olanla məhdudlaşmalı; dəqiq olmalı və aktual saxlanılmalıdır.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "6",
        "title":       "İşlənilmənin qanuniliyi",
        "content":     "İşlənilmə yalnız aşağıdakılardan ən azı biri tətbiq edildikdə qanunidir: məlumat subyektinin razılığı; müqavilənin icrası; hüquqi öhdəlik; həyati maraqlar; ictimai maraqlar; qanuni maraqlar.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "7",
        "title":       "Razılıq üçün şərtlər",
        "content":     "Razılıq könüllü, konkret, məlumatlandırılmış və birmənalı şəkildə verilməlidir. Əvvəlcədən işarələnmiş xanalar razılıq hesab edilmir. Razılıq istənilən vaxt geri götürülə bilər.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "8",
        "title":       "Uşaqların məlumatları",
        "content":     "Birbaşa uşaqlara təklif olunan xidmətlər üçün işlənilmə yalnız uşağın ən azı 16 yaşı olduqda qanunidir. 16 yaşdan aşağı hallarda valideyn razılığı tələb olunur.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "13",
        "title":       "Təqdim edilməli olan məlumatlar",
        "content":     "Məlumatların toplanması zamanı mülkiyyətçi (controller) bunları təmin etməlidir: eyniləşdirmə məlumatları, məqsədlər, hüquqi əsaslar, resipientlər, saxlanma müddəti, məlumat subyektinin hüquqları.",
        "category":    "fərdi məlumat",
        "risk_weight": 4
    },
    {
        "law_name":    "GDPR",
        "article_num": "17",
        "title":       "Silinmə hüququ (Unudulmaq hüququ)",
        "content":     "Məlumat subyektləri, məlumatlar artıq zəruri olmadıqda və ya razılıq geri götürüldükdə, əsassız gecikmə olmadan fərdi məlumatların silinməsini tələb etmək hüququna malikdirlər.",
        "category":    "fərdi məlumat",
        "risk_weight": 4
    },
    {
        "law_name":    "GDPR",
        "article_num": "20",
        "title":       "Məlumatların daşınması hüququ",
        "content":     "Məlumat subyektləri öz fərdi məlumatlarını strukturlaşdırılmış, geniş istifadə olunan və maşın tərəfindən oxuna bilən formatda almaq hüququna malikdirlər.",
        "category":    "fərdi məlumat",
        "risk_weight": 3
    },
    {
        "law_name":    "GDPR",
        "article_num": "25",
        "title":       "Layihələndirmə və susmaya görə məlumatların qorunması",
        "content":     "Mülkiyyətçilər layihələndirmə mərhələsində məlumatların qorunması prinsiplərini tətbiq etməlidirlər. Susmaya görə (by default), yalnız zəruri olan fərdi məlumatlar işlənilməlidir.",
        "category":    "fərdi məlumat",
        "risk_weight": 4
    },
    {
        "law_name":    "GDPR",
        "article_num": "32",
        "title":       "İşlənilmənin təhlükəsizliyi",
        "content":     "Mülkiyyətçi psevdonimləşdirmə, şifrələmə və əlçatanlığı bərpa etmək imkanı daxil olmaqla, müvafiq texniki və təşkilati tədbirləri həyata keçirməlidir.",
        "category":    "fərdi məlumat",
        "risk_weight": 4
    },
    {
        "law_name":    "GDPR",
        "article_num": "33",
        "title":       "Məlumat sızması barədə bildiriş",
        "content":     "Fərdi məlumatların sızması halında, mülkiyyətçi xəbərdar olduqdan sonra 72 saat ərzində nəzarət orqanını məlumatlandırmalıdır.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "44",
        "title":       "Üçüncü ölkələrə ötürülmə",
        "content":     "Fərdi məlumatların üçüncü ölkəyə ötürülməsi yalnız həmin ölkə adekvat mühafizəni təmin etdikdə və ya müvafiq qorunma tədbirləri mövcud olduqda baş verə bilər.",
        "category":    "fərdi məlumat",
        "risk_weight": 5
    },
    {
        "law_name":    "GDPR",
        "article_num": "83",
        "title":       "GDPR cərimələri",
        "content":     "Pozuntular: əsas prinsiplər üçün 20 milyon avroya qədər və ya illik qlobal dövriyyənin 4%-i; digər pozuntular üçün 10 milyon avroya qədər və ya 2%-i miqdarında.",
        "category":    "sanksiya",
        "risk_weight": 5
    }
]

# -------------------------------------------------------
# GDPR — manual
# -------------------------------------------------------

CYBER_SEC_ADVICES = [
    {
        "law_name":    "Kibertehlukesizlik mutexesisinin reyi",
        "article_num": "1",
        "title":       "Üçüncü tərəflərlə məlumat paylaşımı",
        "content":     "Sənəddə 'tərəfdaşlar', 'reklam şəbəkələri' və ya 'xidmət təminatçıları' ilə məlumat paylaşımı bəndlərini yoxlayın. Məlumatın satışına dair gizli ifadələri (məs: xidməti təkmilləşdirmək adı altında paylaşım) müəyyən edin.",
        "category":    "məxfilik",
        "risk_weight": 5
    },
    {
        "law_name":    "Kibertehlukesizlik mutexesisinin reyi",
        "article_num": "2",
        "title":       "Məlumatların minimuma endirilməsi",
        "content":     "Xidmətin funksionallığı üçün zəruri olmayan icazələri (məs: sadə tətbiqin kontaktlara və ya məkana giriş istəməsi) müəyyən edin. Artıq toplanan hər bir məlumat sızma zamanı əlavə riskdir.",
        "category":    "təhlükəsizlik",
        "risk_weight": 4
    },
    {
        "law_name":    "Kibertehlukesizlik mutexesisinin reyi",
        "article_num": "3",
        "title":       "Məlumatların saxlanma və silinmə siyasəti",
        "content":     "Hesab silindikdən sonra məlumatların serverlərdən tamamilə təmizlənməsi və ya 'müddətsiz' saxlanılması bəndlərinə diqqət edin. 'Unudulmaq hüququnun' texniki olaraq necə icra edildiyini yoxlayın.",
        "category":    "hüquqi",
        "risk_weight": 4
    },
    {
        "law_name":    "Kibertehlukesizlik mutexesisinin reyi",
        "article_num": "4",
        "title":       "Məcburi arbitraj və hüquqi müdafiə",
        "content":     "İstifadəçinin məhkəməyə müraciət etmək və ya toplu iddialara qoşulmaq hüququnu məhdudlaşdıran arbitraj bəndlərini tapın. Bu, şirkətin məsuliyyətdən qaçmaq cəhdidir.",
        "category":    "hüquqi",
        "risk_weight": 5
    },
    {
        "law_name":    "Kibertehlukesizlik mutexesisinin reyi",
        "article_num": "5",
        "title":       "Texniki təhlükəsizlik və şifrələmə",
        "content":     "Məlumatların saxlanması zamanı end-to-end encryption (uclara qədər şifrələmə) və ya digər müasir təhlükəsizlik standartlarının tətbiq olunub-olunmadığına dair öhdəlikləri axtarın.",
        "category":    "təhlükəsizlik",
        "risk_weight": 4
    }
]


# -------------------------------------------------------
# ANA FUNKSIYA
# -------------------------------------------------------

def main():
    print("=" * 60)
    print("🚀 Qanun scraping başlayır...")
    print("=" * 60)

    all_az_laws = []

    for code in CODES:
        articles = process_code(code)
        all_az_laws.extend(articles)

    output = {
        "az_law": all_az_laws,
        "gdpr":   GDPR_ARTICLES,
        "cyber_sec": CYBER_SEC_ADVICES
    }

    output_path = os.path.join(os.path.dirname(__file__), "laws.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"✅ TAMAMLANDI")
    print(f"{'=' * 60}")
    print(f"   AZ qanun maddələri:  {len(all_az_laws)}")
    print(f"   GDPR maddələri:       {len(GDPR_ARTICLES)}")
    print(f"   Kiber tehlukesizlik meslehetleri:       {len(GDPR_ARTICLES)}")
    print(f"   Cəmi:                  {len(all_az_laws) + len(CYBER_SEC_ADVICES)} + {len(GDPR_ARTICLES)}")
    print(f"   Fayl:                  {output_path}")

    if len(all_az_laws) == 0:
        print(f"\n⚠️  XƏBƏRDARLIQ: Heç bir AZ maddə tapılmadı!")
        print(f"   Sayt strukturu dəyişmiş ola bilər.")
        print(f"   URL-ləri yenilə və ya regex-i adaptə et.")
    else:
        print(f"\n💡 Növbəti addım: python seed_laws.py")


if __name__ == "__main__":
    main()

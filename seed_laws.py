"""
SEED_LAWS.PY — Qanun bazasını doldur
Bu skript yalnız BİR DƏFƏ işləyir.

Nə edir:
    laws.json faylını oxuyur
    AZ qanunlarını, GDPR və cyber_sec maddələrini DB-yə yazır
    Artıq mövcud olanları yeniləyir (upsert)
"""

import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from database import Law, SessionLocal, init_db

load_dotenv()


def load_laws_json() -> dict:
    """laws.json faylını oxuyur."""
    json_path = os.path.join(os.path.dirname(__file__), "laws.json")

    if not os.path.exists(json_path):
        print("❌ laws.json faylı tapılmadı!")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_az_laws(db: Session, laws: list) -> int:
    """AZ qanun maddələrini DB-yə yazır."""
    count = 0

    for law_data in laws:
        # Artıq mövcuddurmu yoxla
        existing = db.query(Law).filter(
            Law.standard    == "AZ_LAW",
            Law.law_name    == law_data["law_name"],
            Law.article_num == law_data["article_num"]
        ).first()

        if existing:
            # Yenilə
            existing.title       = law_data["title"]
            existing.content     = law_data["content"]
            existing.category    = law_data["category"]
            existing.risk_weight = law_data["risk_weight"]
            existing.updated_at  = datetime.now(timezone.utc)
            print(f"  🔄 Yeniləndi: {law_data['law_name']} Maddə {law_data['article_num']}")
        else:
            # Yeni əlavə et
            new_law = Law(
                standard    = "AZ_LAW",
                law_name    = law_data["law_name"],
                article_num = law_data["article_num"],
                title       = law_data["title"],
                content     = law_data["content"],
                category    = law_data["category"],
                risk_weight = law_data["risk_weight"]
            )
            db.add(new_law)
            print(f"  ✅ Əlavə edildi: {law_data['law_name']} Maddə {law_data['article_num']}")
            count += 1

    db.commit()
    return count


def seed_gdpr(db: Session, laws: list) -> int:
    """DB-dən GDPR maddələrini DB-yə yazır."""
    count = 0

    for law_data in laws:
        existing = db.query(Law).filter(
            Law.standard    == "GDPR",
            Law.article_num == law_data["article_num"]
        ).first()

        if existing:
            existing.title       = law_data["title"]
            existing.content     = law_data["content"]
            existing.category    = law_data["category"]
            existing.risk_weight = law_data["risk_weight"]
            existing.updated_at  = datetime.now(timezone.utc)
            print(f"  🔄 Yeniləndi: GDPR Article {law_data['article_num']}")
        else:
            new_law = Law(
                standard    = "GDPR",
                law_name    = law_data["law_name"],
                article_num = law_data["article_num"],
                title       = law_data["title"],
                content     = law_data["content"],
                category    = law_data["category"],
                risk_weight = law_data["risk_weight"]
            )
            db.add(new_law)
            print(f"  ✅ Əlavə edildi: GDPR Article {law_data['article_num']}")
            count += 1

    db.commit()
    return count


def seed_cyber_sec(db: Session, laws: list) -> int:
    """Kibertəhlükəsizlik mütəxəssisinin rəylərini DB-yə yazır"""
    count = 0

    for law_data in laws:
        existing = db.query(Law).filter(
            Law.standard    == "CYBER_SEC",
            Law.article_num == law_data["article_num"]
        ).first()

        if existing:
            existing.title       = law_data["title"]
            existing.content     = law_data["content"]
            existing.category    = law_data["category"]
            existing.risk_weight = law_data["risk_weight"]
            existing.updated_at  = datetime.now(timezone.utc)
            print(f"  🔄 Yeniləndi: CyberSec Rəy {law_data['article_num']}")
        else:
            new_law = Law(
                standard    = "CYBER_SEC",
                law_name    = law_data["law_name"],
                article_num = law_data["article_num"],
                title       = law_data["title"],
                content     = law_data["content"],
                category    = law_data["category"],
                risk_weight = law_data["risk_weight"]
            )
            db.add(new_law)
            print(f"  ✅ Əlavə edildi: CyberSec Rəy {law_data['article_num']}")
            count += 1

    db.commit()
    return count


def print_summary(db: Session):
    """DB-dəki qanun statistikasını göstər"""
    print("\n" + "=" * 50)
    print("📊 DB XÜLASƏSİ")
    print("=" * 50)

    # Standarta görə
    for standard in ["AZ_LAW", "GDPR", "CYBER_SEC"]:
        total = db.query(Law).filter(Law.standard == standard).count()
        print(f"\n{standard}: {total} maddə")

        # Kateqoriyaya görə
        from sqlalchemy import func
        cats = (
            db.query(Law.category, func.count(Law.id))
            .filter(Law.standard == standard)
            .group_by(Law.category)
            .all()
        )
        for cat, cnt in cats:
            print(f"  • {cat}: {cnt}")

    print("\n" + "=" * 50)


def main():
    print("🚀 Qanun bazası dolduruluр...\n")

    # DB cədvəllərini yarat
    print("1. DB cədvəlləri yoxlanır...")
    init_db()

    # JSON-u yüklə
    print("2. laws.json oxunur...")
    data = load_laws_json()

    db = SessionLocal()

    try:
        # AZ qanunları
        print("\n3. Azərbaycan qanunları əlavə edilir:")
        az_count = seed_az_laws(db, data.get("az_law", []))

        # GDPR
        print("\n4. GDPR maddələri əlavə edilir:")
        gdpr_count = seed_gdpr(db, data.get("gdpr", []))

        # Kibertəhlükəsizlik mütəxəssis rəyləri
        print("\n5. Kibertəhlükəsizlik rəyləri əlavə edilir:")
        cyber_count = seed_cyber_sec(db, data.get("cyber_sec", []))

        # Statistika
        print_summary(db)

        print(f"\n✅ Tamamlandı!")
        print(f"   Yeni AZ qanun maddəsi:     {az_count}")
        print(f"   Yeni GDPR maddəsi:          {gdpr_count}")
        print(f"   Yeni CyberSec rəyi:         {cyber_count}")
        print("\n💡 İndi serveri işlədə bilərsiniz:")
        print("   uvicorn main:app --reload")

    except Exception as e:
        print(f"\n❌ Xəta: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

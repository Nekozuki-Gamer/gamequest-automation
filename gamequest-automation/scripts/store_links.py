"""
ストアリンク自動付与スクリプト
担当: Dev-1 (プロダクト開発部)

機能:
  - store_links が未設定のゲームを検出
  - Steam / PlayStation Store / Nintendo eShop / Xbox /
    Amazon Japan の検索URLを自動生成
  - Firestore の store_links フィールドを更新
"""

import os
import json
import logging
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ───────────────────────────────────────────
# Firebase 初期化
# ───────────────────────────────────────────
def init_firebase():
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not sa_json:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT が設定されていません")
    sa_dict = json.loads(sa_json)
    cred = credentials.Certificate(sa_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()

# ───────────────────────────────────────────
# ストアリンク生成
# ───────────────────────────────────────────
def build_store_links(game: dict) -> dict:
    """各ストアのリンクを生成"""
    title    = game.get("title", "")
    title_en = game.get("title_en", title)
    app_id   = game.get("steam_app_id", "")
    platforms = game.get("platforms", [])

    links = {}

    # Steam（app_id があれば直接リンク、なければ検索）
    if app_id:
        links["steam"] = f"https://store.steampowered.com/app/{app_id}/"
    elif title_en:
        q = urllib.parse.quote_plus(title_en)
        links["steam"] = f"https://store.steampowered.com/search/?term={q}"

    # PlayStation Store（日本）
    q_ja = urllib.parse.quote_plus(title)
    q_en = urllib.parse.quote_plus(title_en)
    links["playstation"] = (
        f"https://store.playstation.com/ja-jp/search/{q_ja}"
    )

    # Nintendo eShop（日本）
    links["nintendo"] = (
        f"https://www.nintendo.com/jp/search/?q={q_ja}#Nintendo Switch"
    )

    # Xbox / Microsoft Store
    links["xbox"] = (
        f"https://www.microsoft.com/ja-jp/store/search/games?q={q_en}"
    )

    # Amazon Japan
    links["amazon"] = (
        f"https://www.amazon.co.jp/s?k={q_ja}+ゲーム&rh=n%3A637394"
    )

    # Epic Games Store
    links["epic"] = (
        f"https://store.epicgames.com/ja/browse?q={q_en}&sortBy=relevancy"
    )

    return links

# ───────────────────────────────────────────
# Firestore 操作
# ───────────────────────────────────────────
def get_games_without_links(db, limit: int = 50) -> list:
    """store_links が未設定または不完全なゲームを取得"""
    docs = db.collection("games").limit(limit * 2).stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        links = d.get("store_links", {})
        # Steam 以外のリンクがない、または store_links 自体がないもの対象
        if not links or len(links) < 4:
            results.append({"id": doc.id, **d})
        if len(results) >= limit:
            break
    return results

def update_store_links(db, doc_id: str, links: dict):
    db.collection("games").document(doc_id).update({
        "store_links": links,
        "updated_at": datetime.now(timezone.utc),
    })

def log_automation(db, action: str, detail: dict):
    db.collection("automation_logs").add({
        "agent": "Dev-1",
        "department": "プロダクト開発部",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc),
    })

# ───────────────────────────────────────────
# メイン処理
# ───────────────────────────────────────────
def main():
    log.info("=== ストアリンク自動付与 開始 ===")
    db = init_firebase()

    games = get_games_without_links(db, limit=50)
    log.info(f"リンク付与対象ゲーム数: {len(games)}")

    updated = 0
    errors = 0

    for game in games:
        title = game.get("title", "不明")
        try:
            links = build_store_links(game)
            update_store_links(db, game["id"], links)
            updated += 1
            log.info(f"✅ リンク付与: {title} ({len(links)} ストア)")
        except Exception as e:
            log.error(f"リンク付与失敗 [{title}]: {e}")
            errors += 1

    summary = {
        "total": len(games),
        "updated": updated,
        "errors": errors,
    }
    log_automation(db, "store_links_attach", summary)
    log.info(f"=== 完了: 付与={updated} エラー={errors} ===")

if __name__ == "__main__":
    main()

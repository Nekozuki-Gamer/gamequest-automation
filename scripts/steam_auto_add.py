"""
Steam API → Firebase ゲーム自動追加スクリプト
担当: Kira-1 (データ収集・リサーチ部)

機能:
  - Steam の新着・人気ゲームを取得
  - ゲーム詳細情報（価格・画像・説明等）を取得
  - Firestore の games コレクションに追加（重複スキップ）
  - 追加ログを automation_logs に記録
"""

import os
import json
import time
import logging
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

# ───────────────────────────────────────────
# ロギング設定
# ───────────────────────────────────────────
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
# Steam API ヘルパー
# ───────────────────────────────────────────
STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")
STEAM_STORE_API = "https://store.steampowered.com/api"
STEAM_API_BASE  = "https://api.steampowered.com"

def get_featured_games():
    """Steam の注目ゲーム一覧を取得"""
    url = f"{STEAM_STORE_API}/featuredcategories/?cc=jp&l=japanese"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        app_ids = []
        for category in ["top_sellers", "new_releases", "specials"]:
            items = data.get(category, {}).get("items", [])
            for item in items[:10]:
                if item.get("id"):
                    app_ids.append(str(item["id"]))
        return list(set(app_ids))
    except Exception as e:
        log.error(f"注目ゲーム取得失敗: {e}")
        return []

def get_top_sellers():
    """Steam トップセラーを取得"""
    url = f"{STEAM_STORE_API}/featuredcategories/?cc=jp&l=japanese"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [
            str(item["id"])
            for item in data.get("top_sellers", {}).get("items", [])[:20]
            if item.get("id")
        ]
    except Exception as e:
        log.error(f"トップセラー取得失敗: {e}")
        return []

def get_game_detail(app_id: str) -> dict | None:
    """Steam ゲーム詳細情報を取得"""
    url = f"{STEAM_STORE_API}/appdetails/?appids={app_id}&cc=jp&l=japanese"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get(app_id, {}).get("success"):
            return None
        d = data[app_id]["data"]
        if d.get("type") not in ("game", "dlc"):
            return None

        # 価格情報
        price_info = d.get("price_overview", {})
        price_jpy   = price_info.get("final", 0) // 100  # 円 (Steam は 1/100 単位)
        price_orig  = price_info.get("initial", 0) // 100
        discount    = price_info.get("discount_percent", 0)
        is_free     = d.get("is_free", False)

        # ジャンル
        genres = [g["description"] for g in d.get("genres", [])]

        # プラットフォーム
        platforms = []
        plat = d.get("platforms", {})
        if plat.get("windows"): platforms.append("Windows")
        if plat.get("mac"):     platforms.append("Mac")
        if plat.get("linux"):   platforms.append("Linux")

        return {
            "steam_app_id": app_id,
            "title": d.get("name", ""),
            "title_en": d.get("name", ""),
            "description": d.get("short_description", ""),
            "description_long": d.get("detailed_description", ""),
            "developer": ", ".join(d.get("developers", [])),
            "publisher": ", ".join(d.get("publishers", [])),
            "genres": genres,
            "platforms": platforms,
            "release_date": d.get("release_date", {}).get("date", ""),
            "image_url": d.get("header_image", ""),
            "screenshots": [
                s.get("path_full", "")
                for s in d.get("screenshots", [])[:5]
            ],
            "price_jpy": 0 if is_free else price_jpy,
            "price_original_jpy": 0 if is_free else price_orig,
            "discount_percent": discount,
            "is_free": is_free,
            "metacritic": d.get("metacritic", {}).get("score"),
            "store_links": {
                "steam": f"https://store.steampowered.com/app/{app_id}/",
            },
            "status": "active",
            "source": "steam_auto",
            "needs_article": True,   # 記事生成フラグ
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    except Exception as e:
        log.error(f"appid={app_id} 詳細取得失敗: {e}")
        return None

# ───────────────────────────────────────────
# Firestore 操作
# ───────────────────────────────────────────
def get_existing_steam_ids(db) -> set:
    """既存の steam_app_id 一覧を取得（重複チェック用）"""
    docs = db.collection("games").where("steam_app_id", "!=", "").stream()
    return {doc.to_dict().get("steam_app_id") for doc in docs}

def add_game(db, game: dict) -> str:
    """ゲームを Firestore に追加してドキュメントIDを返す"""
    ref = db.collection("games").add(game)
    return ref[1].id

def log_automation(db, action: str, detail: dict):
    """自動化ログを Firestore に記録"""
    db.collection("automation_logs").add({
        "agent": "Kira-1",
        "department": "データ収集・リサーチ部",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc),
    })

# ───────────────────────────────────────────
# メイン処理
# ───────────────────────────────────────────
def main():
    log.info("=== Steam ゲーム自動追加 開始 ===")
    db = init_firebase()

    # 既存ID取得
    existing_ids = get_existing_steam_ids(db)
    log.info(f"既存ゲーム数: {len(existing_ids)}")

    # Steam から対象 app_id を収集
    app_ids = list(set(get_featured_games() + get_top_sellers()))
    log.info(f"Steam から取得した app_id 数: {len(app_ids)}")

    added = []
    skipped = []
    errors = []

    for app_id in app_ids:
        if app_id in existing_ids:
            skipped.append(app_id)
            continue

        time.sleep(1.5)  # Steam API レート制限回避

        game = get_game_detail(app_id)
        if not game:
            errors.append(app_id)
            continue

        try:
            doc_id = add_game(db, game)
            added.append({"app_id": app_id, "title": game["title"], "doc_id": doc_id})
            log.info(f"✅ 追加: {game['title']} (appid={app_id})")
        except Exception as e:
            log.error(f"Firestore 書き込み失敗 appid={app_id}: {e}")
            errors.append(app_id)

    # サマリーログ
    summary = {
        "total_fetched": len(app_ids),
        "added": len(added),
        "skipped": len(skipped),
        "errors": len(errors),
        "added_games": added,
        "error_ids": errors,
    }
    log_automation(db, "steam_auto_add", summary)

    log.info(f"=== 完了: 追加={len(added)} スキップ={len(skipped)} エラー={len(errors)} ===")

if __name__ == "__main__":
    main()

"""
価格自動更新スクリプト
担当: Sol-1 (営業・収益化部)

機能:
  - Firestore の全ゲームの Steam 価格を3時間ごとに更新
  - セール情報（discount_percent）も同時更新
  - 価格変動があれば price_history に記録
  - 更新ログを automation_logs に記録
"""

import os
import json
import time
import logging
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

STEAM_STORE_API = "https://store.steampowered.com/api"

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
# Steam 価格取得（バッチ対応）
# ───────────────────────────────────────────
def get_prices_batch(app_ids: list[str]) -> dict:
    """最大100件まとめて価格取得"""
    results = {}
    chunk_size = 100
    for i in range(0, len(app_ids), chunk_size):
        chunk = app_ids[i:i + chunk_size]
        ids_str = ",".join(chunk)
        url = f"{STEAM_STORE_API}/appdetails/?appids={ids_str}&cc=jp&filters=price_overview,is_free"
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            for app_id in chunk:
                entry = data.get(app_id, {})
                if entry.get("success"):
                    d = entry["data"]
                    if d.get("is_free"):
                        results[app_id] = {
                            "price_jpy": 0,
                            "price_original_jpy": 0,
                            "discount_percent": 0,
                            "is_free": True,
                        }
                    elif "price_overview" in d:
                        p = d["price_overview"]
                        results[app_id] = {
                            "price_jpy": p.get("final", 0) // 100,
                            "price_original_jpy": p.get("initial", 0) // 100,
                            "discount_percent": p.get("discount_percent", 0),
                            "is_free": False,
                        }
        except Exception as e:
            log.error(f"価格バッチ取得失敗 (chunk {i}): {e}")
        time.sleep(1)
    return results

# ───────────────────────────────────────────
# Firestore 操作
# ───────────────────────────────────────────
def get_all_steam_games(db) -> list:
    """Steam app_id を持つゲームを全件取得"""
    docs = db.collection("games").where("steam_app_id", "!=", "").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

def update_game_price(db, doc_id: str, old_price: int, new_data: dict):
    """価格更新 + 変動があれば履歴記録"""
    update_payload = {
        **new_data,
        "updated_at": datetime.now(timezone.utc),
    }
    db.collection("games").document(doc_id).update(update_payload)

    # 価格変動があれば履歴に追加
    if old_price != new_data.get("price_jpy"):
        db.collection("games").document(doc_id).collection("price_history").add({
            "price_jpy": new_data["price_jpy"],
            "discount_percent": new_data.get("discount_percent", 0),
            "recorded_at": datetime.now(timezone.utc),
        })

def log_automation(db, action: str, detail: dict):
    db.collection("automation_logs").add({
        "agent": "Sol-1",
        "department": "営業・収益化部",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc),
    })

# ───────────────────────────────────────────
# メイン処理
# ───────────────────────────────────────────
def main():
    log.info("=== 価格自動更新 開始 ===")
    db = init_firebase()

    games = get_all_steam_games(db)
    log.info(f"更新対象ゲーム数: {len(games)}")

    if not games:
        log.info("対象ゲームなし。終了。")
        return

    # app_id → ゲーム情報のマップ作成
    app_id_map = {
        g["steam_app_id"]: g
        for g in games
        if g.get("steam_app_id")
    }
    app_ids = list(app_id_map.keys())

    # 一括価格取得
    prices = get_prices_batch(app_ids)
    log.info(f"Steam から取得した価格数: {len(prices)}")

    updated = 0
    on_sale = 0
    errors = 0
    sale_games = []

    for app_id, price_data in prices.items():
        game = app_id_map.get(app_id)
        if not game:
            continue
        try:
            old_price = game.get("price_jpy", 0)
            update_game_price(db, game["id"], old_price, price_data)
            updated += 1

            # セール中を記録
            if price_data.get("discount_percent", 0) > 0:
                on_sale += 1
                sale_games.append({
                    "title": game.get("title"),
                    "discount": price_data["discount_percent"],
                    "price_jpy": price_data["price_jpy"],
                })
                log.info(
                    f"🏷️  セール: {game.get('title')} "
                    f"-{price_data['discount_percent']}% → ¥{price_data['price_jpy']:,}"
                )
        except Exception as e:
            log.error(f"更新失敗 appid={app_id}: {e}")
            errors += 1

    summary = {
        "total": len(app_ids),
        "updated": updated,
        "on_sale": on_sale,
        "errors": errors,
        "sale_games": sale_games,
    }
    log_automation(db, "price_auto_update", summary)
    log.info(f"=== 完了: 更新={updated} セール中={on_sale} エラー={errors} ===")

if __name__ == "__main__":
    main()

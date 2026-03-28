"""
Claude API 記事自動生成 → 承認キュースクリプト
担当: Mei-1 (コンテンツ運営部 編集長)

機能:
  - needs_article=True のゲームを Firestore から取得
  - Claude API でゲーム紹介記事を自動生成
  - approval_queue コレクションに保存 (step: pending_editor)
  - 生成後 needs_article=False に更新
"""

import os
import json
import time
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import anthropic

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
# Claude API で記事生成
# ───────────────────────────────────────────
def generate_article(game: dict) -> dict:
    """Claude API でゲーム紹介記事を生成"""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    title       = game.get("title", "不明なゲーム")
    description = game.get("description", "")
    genres      = ", ".join(game.get("genres", []))
    developer   = game.get("developer", "不明")
    release     = game.get("release_date", "不明")
    price       = game.get("price_jpy", 0)
    platforms   = ", ".join(game.get("platforms", []))
    is_free     = game.get("is_free", False)
    metacritic  = game.get("metacritic")

    price_str = "基本プレイ無料" if is_free else f"¥{price:,}"
    meta_str  = f"Metacritic スコア: {metacritic}" if metacritic else ""

    prompt = f"""あなたはゲーム情報サイト「GameQuest AI」のコンテンツ担当AIです。
以下のゲーム情報をもとに、日本語のゲーム紹介記事を作成してください。

【ゲーム情報】
タイトル: {title}
説明: {description}
ジャンル: {genres}
開発者: {developer}
リリース日: {release}
価格: {price_str}
対応プラットフォーム: {platforms}
{meta_str}

【記事の要件】
- タイトル（h2相当）を含む
- 導入文（2〜3文）
- ゲームの特徴（箇条書き3〜5項目）
- こんな人におすすめ（1〜2文）
- まとめ（1〜2文）
- 文字数: 300〜500文字
- 読者に伝わるわかりやすい日本語
- SEOを意識したキーワードを自然に含む

以下のJSON形式で返してください（```json``` ブロック不要、純粋なJSONのみ）:
{{
  "article_title": "記事タイトル",
  "article_body": "記事本文（マークダウン形式）",
  "seo_keywords": ["キーワード1", "キーワード2", "キーワード3"],
  "summary": "記事の一言要約"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # JSON パース（クリーニング）
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ───────────────────────────────────────────
# Firestore 操作
# ───────────────────────────────────────────
def get_games_needing_articles(db, limit: int = 10) -> list:
    """記事生成が必要なゲームを取得"""
    docs = (
        db.collection("games")
        .where("needs_article", "==", True)
        .where("status", "==", "active")
        .limit(limit)
        .stream()
    )
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

def push_to_approval_queue(db, game: dict, article: dict) -> str:
    """承認キューに追加"""
    payload = {
        "type": "article",
        "step": "pending_editor",
        "game_id": game["id"],
        "game_title": game.get("title", ""),
        "game_image": game.get("image_url", ""),
        "article_title": article["article_title"],
        "article_body": article["article_body"],
        "seo_keywords": article.get("seo_keywords", []),
        "summary": article.get("summary", ""),
        "generated_by": "Mei-1",
        "department": "コンテンツ運営部",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "editor_comment": "",
        "ceo_comment": "",
    }
    ref = db.collection("approval_queue").add(payload)
    return ref[1].id

def mark_article_generated(db, game_id: str):
    """needs_article を False に更新"""
    db.collection("games").document(game_id).update({
        "needs_article": False,
        "article_generated_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

def log_automation(db, action: str, detail: dict):
    db.collection("automation_logs").add({
        "agent": "Mei-1",
        "department": "コンテンツ運営部",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc),
    })

# ───────────────────────────────────────────
# メイン処理
# ───────────────────────────────────────────
def main():
    log.info("=== 記事自動生成 開始 ===")
    db = init_firebase()

    games = get_games_needing_articles(db, limit=10)
    log.info(f"記事生成対象ゲーム数: {len(games)}")

    generated = []
    errors = []

    for game in games:
        title = game.get("title", "不明")
        log.info(f"記事生成中: {title}")
        try:
            article = generate_article(game)
            queue_id = push_to_approval_queue(db, game, article)
            mark_article_generated(db, game["id"])
            generated.append({
                "game_id": game["id"],
                "title": title,
                "queue_id": queue_id,
                "article_title": article["article_title"],
            })
            log.info(f"✅ 承認キューに追加: {article['article_title']}")
            time.sleep(2)  # API レート制限回避
        except Exception as e:
            log.error(f"記事生成失敗 [{title}]: {e}")
            errors.append({"game_id": game["id"], "title": title, "error": str(e)})

    summary = {
        "total": len(games),
        "generated": len(generated),
        "errors": len(errors),
        "generated_articles": generated,
        "error_items": errors,
    }
    log_automation(db, "article_auto_generate", summary)
    log.info(f"=== 完了: 生成={len(generated)} エラー={len(errors)} ===")

if __name__ == "__main__":
    main()

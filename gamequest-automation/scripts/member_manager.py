"""
Firebase 会員管理ユーティリティ
担当: Noel-1 (モデレーション部)

使い方:
  # 会員一覧表示
  python scripts/member_manager.py list

  # 会員をBANする
  python scripts/member_manager.py ban <uid> --reason "規約違反"

  # BANを解除する
  python scripts/member_manager.py unban <uid>

  # 特定会員の詳細表示
  python scripts/member_manager.py info <uid>

  # 統計サマリー表示
  python scripts/member_manager.py stats

  # 非アクティブ会員レポート（90日間ログインなし）
  python scripts/member_manager.py inactive
"""

import os
import sys
import json
import argparse
import logging
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime, timezone, timedelta

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
        # ローカル実行用: config/service_account.json を参照
        sa_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "service_account.json"
        )
        if os.path.exists(sa_path):
            cred = credentials.Certificate(sa_path)
        else:
            raise ValueError(
                "FIREBASE_SERVICE_ACCOUNT 環境変数または "
                "config/service_account.json が必要です"
            )
    else:
        sa_dict = json.loads(sa_json)
        cred = credentials.Certificate(sa_dict)

    firebase_admin.initialize_app(cred)
    return firestore.client()

# ───────────────────────────────────────────
# 会員操作
# ───────────────────────────────────────────
def list_members(db, limit: int = 50):
    """会員一覧を表示"""
    print(f"\n{'='*60}")
    print(f"  GameQuest AI 会員一覧 (最大 {limit} 件)")
    print(f"{'='*60}")

    docs = db.collection("users").limit(limit).stream()
    members = []
    for doc in docs:
        d = doc.to_dict()
        d["uid"] = doc.id
        members.append(d)

    if not members:
        print("  会員が見つかりません")
        return

    for m in members:
        status = "🚫 BAN" if m.get("is_banned") else "✅ 正常"
        created = m.get("created_at", "不明")
        if hasattr(created, "strftime"):
            created = created.strftime("%Y-%m-%d")
        print(f"  {status} | {m.get('email','不明')} | UID: {m['uid'][:12]}... | 登録: {created}")

    print(f"\n  合計: {len(members)} 件")

def ban_member(db, uid: str, reason: str):
    """会員をBANする"""
    # Firebase Auth でアカウント無効化
    auth.update_user(uid, disabled=True)

    # Firestore にBAN情報を記録
    db.collection("users").document(uid).update({
        "is_banned": True,
        "ban_reason": reason,
        "banned_at": datetime.now(timezone.utc),
        "banned_by": "Noel-1",
        "updated_at": datetime.now(timezone.utc),
    })

    # モデレーションログ記録
    db.collection("moderation_logs").add({
        "action": "ban",
        "uid": uid,
        "reason": reason,
        "agent": "Noel-1",
        "department": "モデレーション部",
        "timestamp": datetime.now(timezone.utc),
    })

    log.info(f"✅ UID={uid} をBANしました。理由: {reason}")
    print(f"\n✅ UID={uid} をBANしました。")
    print(f"   理由: {reason}")

def unban_member(db, uid: str):
    """BANを解除する"""
    # Firebase Auth でアカウント有効化
    auth.update_user(uid, disabled=False)

    # Firestore のBAN情報をクリア
    db.collection("users").document(uid).update({
        "is_banned": False,
        "ban_reason": None,
        "unbanned_at": datetime.now(timezone.utc),
        "unbanned_by": "Noel-1",
        "updated_at": datetime.now(timezone.utc),
    })

    # モデレーションログ記録
    db.collection("moderation_logs").add({
        "action": "unban",
        "uid": uid,
        "agent": "Noel-1",
        "department": "モデレーション部",
        "timestamp": datetime.now(timezone.utc),
    })

    log.info(f"✅ UID={uid} のBANを解除しました")
    print(f"\n✅ UID={uid} のBANを解除しました。")

def member_info(db, uid: str):
    """特定会員の詳細を表示"""
    doc = db.collection("users").document(uid).get()
    if not doc.exists:
        print(f"\n❌ UID={uid} が見つかりません")
        return

    d = doc.to_dict()
    print(f"\n{'='*60}")
    print(f"  会員詳細: {d.get('email', '不明')}")
    print(f"{'='*60}")
    print(f"  UID          : {uid}")
    print(f"  メール       : {d.get('email', '不明')}")
    print(f"  表示名       : {d.get('displayName', '未設定')}")
    print(f"  ステータス   : {'🚫 BAN' if d.get('is_banned') else '✅ 正常'}")
    if d.get("is_banned"):
        print(f"  BAN理由      : {d.get('ban_reason', '不明')}")
    created = d.get("created_at", "不明")
    if hasattr(created, "strftime"):
        created = created.strftime("%Y-%m-%d %H:%M")
    print(f"  登録日時     : {created}")
    print(f"  投稿数       : {d.get('post_count', 0)}")

    # 最近の投稿を取得
    posts = (
        db.collection("threads")
        .where("uid", "==", uid)
        .limit(5)
        .stream()
    )
    post_list = [p.to_dict() for p in posts]
    if post_list:
        print(f"\n  最近の投稿 ({len(post_list)}件):")
        for p in post_list:
            print(f"    - {p.get('title', p.get('content', ''))[:40]}")

def stats(db):
    """統計サマリーを表示"""
    print(f"\n{'='*60}")
    print("  GameQuest AI 会員統計")
    print(f"{'='*60}")

    total = len(list(db.collection("users").stream()))
    banned = len(list(
        db.collection("users").where("is_banned", "==", True).stream()
    ))
    games = len(list(db.collection("games").stream()))
    articles = len(list(db.collection("articles").stream()))
    pending = len(list(
        db.collection("approval_queue")
        .where("step", "in", ["pending_editor", "ceo_review"])
        .stream()
    ))

    print(f"  総会員数        : {total:,} 人")
    print(f"  BAN中           : {banned:,} 人")
    print(f"  正常会員        : {total - banned:,} 人")
    print(f"  登録ゲーム数    : {games:,} タイトル")
    print(f"  公開記事数      : {articles:,} 件")
    print(f"  承認待ち記事    : {pending:,} 件")
    print(f"\n  最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def inactive_report(db, days: int = 90):
    """非アクティブ会員レポート"""
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"\n{'='*60}")
    print(f"  非アクティブ会員 ({days}日間ログインなし)")
    print(f"{'='*60}")

    docs = (
        db.collection("users")
        .where("last_login", "<", threshold)
        .limit(100)
        .stream()
    )
    inactive = [{"uid": doc.id, **doc.to_dict()} for doc in docs]

    if not inactive:
        print("  非アクティブ会員はいません")
        return

    for m in inactive:
        last_login = m.get("last_login", "不明")
        if hasattr(last_login, "strftime"):
            last_login = last_login.strftime("%Y-%m-%d")
        print(f"  {m.get('email', '不明')} | 最終ログイン: {last_login}")

    print(f"\n  合計: {len(inactive)} 件")

# ───────────────────────────────────────────
# CLI エントリポイント
# ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="GameQuest AI 会員管理ユーティリティ"
    )
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="会員一覧表示")
    p_list.add_argument("--limit", type=int, default=50)

    # ban
    p_ban = subparsers.add_parser("ban", help="会員BAN")
    p_ban.add_argument("uid", help="対象UID")
    p_ban.add_argument("--reason", default="規約違反", help="BAN理由")

    # unban
    p_unban = subparsers.add_parser("unban", help="BAN解除")
    p_unban.add_argument("uid", help="対象UID")

    # info
    p_info = subparsers.add_parser("info", help="会員詳細")
    p_info.add_argument("uid", help="対象UID")

    # stats
    subparsers.add_parser("stats", help="統計サマリー")

    # inactive
    p_inactive = subparsers.add_parser("inactive", help="非アクティブ会員")
    p_inactive.add_argument("--days", type=int, default=90)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    db = init_firebase()

    if args.command == "list":
        list_members(db, args.limit)
    elif args.command == "ban":
        ban_member(db, args.uid, args.reason)
    elif args.command == "unban":
        unban_member(db, args.uid)
    elif args.command == "info":
        member_info(db, args.uid)
    elif args.command == "stats":
        stats(db)
    elif args.command == "inactive":
        inactive_report(db, args.days)

if __name__ == "__main__":
    main()

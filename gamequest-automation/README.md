# GameQuest AI — 自動化システム

Firebase + GitHub Actions + Claude API による完全自動化基盤です。

---

## 構成

```
gamequest-automation/
├── .github/workflows/
│   ├── steam_auto_add.yml      # 毎日 JST 9:00 実行
│   ├── article_generator.yml   # 毎日 JST 10:00 実行
│   ├── price_updater.yml       # 3時間ごと実行
│   └── store_links.yml         # 毎日 JST 11:00 実行
├── scripts/
│   ├── steam_auto_add.py       # Steam ゲーム自動追加
│   ├── article_generator.py    # Claude API 記事自動生成
│   ├── price_updater.py        # 価格自動更新
│   ├── store_links.py          # ストアリンク自動付与
│   └── member_manager.py       # 会員管理ユーティリティ（手動）
├── config/
│   └── service_account.json    # ★ローカル実行用（gitignore済）
├── requirements.txt
└── README.md
```

---

## セットアップ手順

### 1. GitHubリポジトリ作成 & プッシュ

```bash
cd gamequest-automation
git init
git add .
git commit -m "Initial commit: GameQuest 自動化システム"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/gamequest-automation.git
git push -u origin main
```

### 2. GitHub Secrets 設定

GitHubリポジトリ → Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 値 | 取得場所 |
|---|---|---|
| `FIREBASE_SERVICE_ACCOUNT` | サービスアカウントJSONの中身 | Firebase Console → プロジェクト設定 → サービスアカウント → 新しい秘密鍵を生成 |
| `STEAM_API_KEY` | Steam API キー | https://steamcommunity.com/dev/apikey |
| `ANTHROPIC_API_KEY` | Claude API キー | https://console.anthropic.com/ |

#### FIREBASE_SERVICE_ACCOUNT の設定方法
1. Firebase Console (console.firebase.google.com) にアクセス
2. プロジェクト設定（歯車アイコン）→ サービスアカウント
3. 「新しい秘密鍵を生成」→ JSONファイルをダウンロード
4. そのJSONファイルの**中身をまるごとコピー**してSecretに貼り付け

---

## 各スクリプトの動作

### steam_auto_add.py（毎日 JST 9:00）
- Steam のトップセラー・注目ゲームを自動取得
- 新規ゲームを Firestore `games` コレクションに追加
- `needs_article: true` フラグを立てて記事生成を促す
- 重複チェックあり（同じゲームは追加しない）

### article_generator.py（毎日 JST 10:00）
- `needs_article: true` のゲームを検出
- Claude API でゲーム紹介記事を自動生成（日本語）
- Firestore `approval_queue` に `step: pending_editor` で保存
- **あなたが統合HQシステムで承認 → 即サイト公開**

### price_updater.py（3時間ごと）
- 全ゲームの Steam 価格をリアルタイム更新
- セール情報（割引率）も同時更新
- 価格変動履歴を `price_history` サブコレクションに記録

### store_links.py（毎日 JST 11:00）
- ストアリンク未設定ゲームを検出
- Steam / PS Store / Nintendo eShop / Xbox / Amazon / Epic の
  リンクを自動生成してFirestoreに書き込み
- サイト側でそのまま表示される

---

## 会員管理（手動実行）

```bash
# セットアップ
pip install -r requirements.txt
export FIREBASE_SERVICE_ACCOUNT='{"type":"service_account",...}'

# 会員一覧
python scripts/member_manager.py list

# 会員をBAN
python scripts/member_manager.py ban UID123abc --reason "スパム行為"

# BAN解除
python scripts/member_manager.py unban UID123abc

# 特定会員の詳細
python scripts/member_manager.py info UID123abc

# 統計サマリー
python scripts/member_manager.py stats

# 90日間ログインなし会員レポート
python scripts/member_manager.py inactive --days 90
```

---

## Firestore コレクション構造

| コレクション | 用途 |
|---|---|
| `games` | ゲーム情報（自動追加・価格更新） |
| `games/{id}/price_history` | 価格変動履歴 |
| `approval_queue` | 記事承認キュー |
| `articles` | 公開済み記事 |
| `users` | 会員情報 |
| `moderation_logs` | BAN/UNBAN ログ |
| `automation_logs` | 自動化実行ログ |

---

## 承認フロー（記事）

```
自動生成 (article_generator.py)
    ↓
approval_queue (step: pending_editor)
    ↓
統合HQシステム → 編集長レビュー
    ↓
approval_queue (step: ceo_review)
    ↓
CEO決裁（あなた）→ 承認ボタン
    ↓
articles コレクションに書き込み → サイト即時反映
```

---

## 月間コスト試算

| 項目 | 費用 |
|---|---|
| GitHub Actions | **無料**（月2000分まで） |
| Firebase Firestore | **無料**（Spark プラン範囲内） |
| Claude API（記事生成・月30件想定） | **約300〜500円** |
| Steam API | **無料** |
| **合計** | **月500円以下** |

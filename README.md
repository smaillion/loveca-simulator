# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

ラブライブ！シリーズ オフィシャルカードゲーム（ラブカ）のための、ローカルカードデータベース、デッキ分析、ルール検証ツールです。

公式日本語データを唯一の権威ソースとして扱います。内部の英語名は安定した実装識別子であり、公式用語の置き換えではありません。

## 現在の状態

`v0.4.0-alpha.2` の収録内容:

- 公式 `card_list` からの正式カード importer
- SQLite Schema v2 のローカルカード DB
- デッキ保存機能付き Deck Builder
- `decklist.v0` ベースの Deck Analyzer
- FastAPI + React SPA の可視化ルール検証 UI
- Replay 可能な Action-only GameState

現在のルール検証 UI で確認できる範囲:

- 先攻後攻決定、初手、マリガン、初期 Energy
- Member 登場、満員時の置き換え、`バトンタッチ`
- Live Set、同数補充、Live 公開、エール
- Heart 割り当て、特殊 Blade Heart の一部自動処理
- 成功 Live の移動、次ターン先攻判定、3 枚成功による勝敗
- 未自動化のカード効果は `ManualAdjustmentAction` で再現

未実装または未収録:

- 全カード効果の自動化
- AI、Monte Carlo、勝率エンジン
- オンライン対戦、アカウント、同期機能

## 画面イメージ

開始画面: 保存済みデッキを選び、そのまま対局作成まで進められます。

![開始画面](docs/images/home-desktop.png)

Deck Builder: 右側でカード検索と絞り込み、中央で構築内容と分析結果を確認します。

![Deck Builder](docs/images/deck-builder-desktop.png)

ルール検証 UI: 盤面、Action/Event Log、手動調整を同じ画面で追えます。

![ルール検証 UI](docs/images/match-actions-desktop.png)

## 動作環境

- Python `3.11+`
- Node.js `20` / `22` / `24+`
- SQLite は追加セットアップ不要

インストール:

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

## ローカル起動

1. カード DB を初期化します。

```powershell
loveca cards init --database data/loveca.sqlite3
```

2. 公式カードを取得して正規化成果物を作ります。

```powershell
loveca cards import-official `
  --output-root data/imports/official `
  --delay 1
```

3. 正規化済みカードを SQLite に取り込みます。

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-full.md
```

4. フロントエンドをビルドします。

```powershell
cd web
npm run build
cd ..
```

5. 必要ならカード画像をローカルにキャッシュします。

```powershell
loveca cards cache-images `
  --database data/loveca.sqlite3 `
  --cache-dir data/card_images `
  --delay 1
```

6. Web UI を起動します。

```powershell
loveca web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
```

ブラウザで <http://127.0.0.1:8765> を開きます。

`8765` が使用中なら `--port 8766` のように変更してください。

## よく使うコマンド

Deck Analyzer:

```powershell
loveca decks analyze `
  --database data/loveca.sqlite3 `
  --deck data/decks/your-deck.json `
  --output text
```

増分インポート:

```powershell
loveca cards import-official `
  --output-root data/imports/official-bp06 `
  --mode incremental-set `
  --card-set BP06 `
  --delay 1
```

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP06 `
  --report logs/import-bp06.md
```

## テスト

Python テスト:

```powershell
python -m pytest
```

フロントエンドテスト:

```powershell
cd web
npm run test -- --run
npm run build
```

## リポジトリの見どころ

- `src/loveca/cards/`: importer、catalog、画像キャッシュ
- `src/loveca/decks/`: deck format、analyzer、saved deck library
- `src/loveca/simulation/`: GameState、Action、runtime、effects
- `src/loveca/webapp.py`: FastAPI と SPA 配信
- `web/`: React ベースのルール検証 UI
- `docs/`, `specs/`: 設計文書と仕様

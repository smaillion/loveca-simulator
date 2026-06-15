# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

ラブライブ！シリーズ オフィシャルカードゲーム（ラブカ）のための、ローカルカードデータベース、デッキ分析、ルール検証ツールです。

公式日本語データを唯一の権威ソースとして扱います。内部の英語名は安定した実装識別子であり、公式用語の置き換えではありません。

## 現在の状態

`v0.4.0-alpha.3` の収録内容:

- 公式 `card_list` からの正式カード importer
- `＋` / `+` 混在を避けるカード番号正規化
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
- 一部のカード効果は限定的な構造化 prompt に対応
- 広範なカード効果提示・選択体系はまだ再設計中で、未自動化部分は `ManualAdjustmentAction` で補完

Deck Builder の現在の到達点:

- 保存済みデッキの作成、読み込み、更新、削除
- `Member` / `Live` / `Energy` の分割表示
- `Member 48` / `Live 12` / `Energy 12` の構築数チェック
- 作品、ユニット、Heart 色、Blade、Live 必要 Heart、Score、Blade Heart による絞り込み
- カード詳細ダイアログでの印刷版選択とカード画像確認
- デッキ分析 dashboard による cost、Heart、score、特殊 Blade Heart、効果タイミングの確認

未実装または未収録:

- 全カード効果の自動化
- 全量カードプールに対する完全な効果 prompt coverage
- AI、Monte Carlo、勝率エンジン
- オンライン対戦、アカウント、同期機能

## 既知の制限

- 全カード効果の prompt / 自動実行 coverage はまだありません。
- FAQ / 個別裁定に依存する効果はまだ仕様化していません。
- 既存のローカル DB に全角 `＋` のカード番号が残っている場合は、正式 importer で再導入して更新してください。
- Web/API テストには `httpx2` が必要です。環境に未導入の場合、`tests/test_catalog_api.py` と `tests/test_webapp.py` は収集段階で停止します。

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

## 変更履歴

リリースごとの詳細は [CHANGELOG.md](./CHANGELOG.md) を参照してください。

## リポジトリの見どころ

- `src/loveca/cards/`: importer、catalog、画像キャッシュ
- `src/loveca/decks/`: deck format、analyzer、saved deck library
- `src/loveca/simulation/`: GameState、Action、runtime、effects
- `src/loveca/webapp.py`: FastAPI と SPA 配信
- `web/`: React ベースのルール検証 UI
- `docs/`, `specs/`: 設計文書と仕様

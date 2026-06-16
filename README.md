# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

ラブライブ！シリーズ オフィシャルカードゲーム（ラブカ）のための、ローカルカードデータベース、デッキ分析、ルール検証ツールです。

公式日本語データを唯一の権威ソースとして扱います。内部の英語名は安定した実装識別子であり、公式用語の置き換えではありません。

## 現在の状態

`v0.4.2-alpha.1` の収録内容:

- 公式 `card_list` からの正式カード importer
- `＋` / `+` 混在を避けるカード番号正規化
- SQLite Schema v2 のローカルカード DB
- デッキ保存機能付き Deck Builder
- `decklist.v0` ベースの Deck Analyzer
- FastAPI + React SPA の可視化ルール検証 UI
- Replay 可能な Action-only GameState
- 925 件の effect registry entry
  - 466 件は `test_validated_executable`
  - 459 件は timing prompt / 未対応処理用の `manual_resolution`
- 将来の低コスト online 同期に向けた state hash / compatibility metadata の基礎
- GitHub Pages browser preview 用の静的 SPA release workflow
  - preview data package は解析済みカード / skill data のみを含む
  - カード画像は同梱せず、公式 `image_url` を参照する

現在の開発主線:

- Roadmap 上は Phase 5 Effect DSL / 構造化効果実行に集中しています。
- Phase 1 / 2 / 3 は基本実装済みで、維持と改善の段階です。
- Phase 4 の Human-vs-Human 検証器と Phase 7 の UI は先行実装済みです。
- Phase 9 / 10 の低コスト online 検証は、Phase 5 と並行して早めに進めます。
- Simple AI、AI-vs-AI、Monte Carlo、勝率エンジンは最低優先度に下げています。

現在のルール検証 UI で確認できる範囲:

- 先攻後攻決定、初手、マリガン、初期 Energy
- Member 登場、満員時の置き換え、`バトンタッチ`
- Live Set、同数補充、Live 公開、エール
- Heart 割り当て、特殊 Blade Heart の一部自動処理
- 成功 Live の移動、次ターン先攻判定、3 枚成功による勝敗
- 一部のカード効果は、手札 / Energy / Stage Member / Heart 色 / 山札上確認を含む限定的な構造化 prompt に対応
- 双方が選択する一部の効果は multi-player pending choice で順番に処理可能
- 複数 group に分けて Stage Member を選び、それぞれに同じ一時 modifier を適用する効果に対応
- registry entry ベースの `test_validated_executable` coverage は 50.38% まで拡張済み
- 自動実行できない効果は `ManualAdjustmentAction` で補完
- 処理不能な効果は、デバッグ用に `effect_skipped_due_to_error` として明示記録しながらスキップ可能

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
- GitHub Pages preview は解析済み data package を同梱した場合、FastAPI なしでカードカタログ閲覧、browser local deck 保存、MVP deck 分析まで動作します。対戦 runtime の browser adapter は次の実装対象です。

## 既知の制限

- 全カード効果の自動実行 coverage はまだありません。
- 現在の broad prompt coverage は timing-only manual fallback を多く含みます。
- 最新の Phase 5 sandbox では `skip` mode の `illegal_action` は 0 です。直近の `30 decks x 50 matches` 回帰は `block` mode で 35 `mandatory_manual_resolution` / 9 `max_actions` / 6 完走、`skip` mode で 10 完走 / 40 `max_actions` でした。grouped Stage Member choice 対応後の `30 decks x 20 matches --manual-policy block` smoke は 2 完走 / 11 `mandatory_manual_resolution` / 7 `max_actions` / `illegal_action = 0` で、`PL!SP-bp4-023:1` は blocker から消えました。さらに `PL!N-bp4-031:1` と Baton Touch 登場した蓮ノ空 Member 2 人条件の required Heart 減少を構造化した後の 20-match block smoke は 2 完走 / 9 `mandatory_manual_resolution` / 9 `max_actions` でした。長局化と複雑な Live 系 manual effect が主な残課題です。
- FAQ / 個別裁定に依存する効果はまだ仕様化していません。
- importer、parser、カード番号正規化、SQLite schema、または effect registry の互換性に関わる更新後は、既存の `data/loveca.sqlite3` を再利用せず、公式 importer でカード DB を再構築または再導入してください。保存済みデッキは `decklist.v0` のユーザーデータなので、カード DB とは分けて保持できます。
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

バージョン更新後に importer / parser / schema が変わった場合は、古い `data/loveca.sqlite3` をバックアップまたは削除してから、この手順でカード DB を作り直してください。古い DB を使い続けると、カード番号、画像、effect registry、online compatibility fingerprint が一致しないことがあります。

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

## カード DB と asset 配布方針

将来的には、構築済みの SQLite カード DB、effect registry、manifest、checksum を含む versioned asset package を配布し、ユーザーが公式サイトから毎回全量取得しなくても起動できる形にできます。

ただし、公式効果テキスト全文、公式 PDF 由来の大量データ、ダウンロード済みカード画像ファイルは再配布可否の確認が必要です。GitHub Pages preview で公開する asset は、解析済みカード data、解析済み skill data、manifest、checksum、プロジェクト独自 metadata に限定し、カード画像は同梱せず公式 `image_url` を参照する方針です。

private tester 向けに事前構築 DB を渡す場合も、release version、schema version、parser version、card database fingerprint、effect registry hash を明示し、互換性が崩れる更新後は再導入が必要です。

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

AI sandbox の 20 deck x 20 match ブラックボックス smoke も pytest に含まれています。
ローカル正式カード DB がない環境では skip されます。個別に監査レポートを生成する場合:

```powershell
$env:PYTHONPATH="src;."
python -m tools.ai_sandbox.blackbox_playtest `
  --database data/loveca.sqlite3 `
  --output logs/ai_sandbox/manual-run `
  --decks 20 `
  --matches 20 `
  --manual-policy block
```

`--manual-policy skip` を指定すると、未対応の強制能力を
`effect_skipped_due_to_error` として記録しながら次の処理へ進めます。
これはルール確認用のデバッグ機能であり、正式な能力解決ではありません。

Phase 5 の手動効果検証には semantic user-agent sandbox も使えます。これは通常行動は
deterministic sandbox policy で進め、`manual_resolution` 効果だけを semantic provider に
渡して、現在の `ManualAdjustmentAction` で人間相当の処理が可能かを測る補助ツールです。
registry coverage には加算しません。未設定時は `mock` provider になり、実効果は解決せず
report と schema gap の出力だけを確認します。

```powershell
$env:PYTHONPATH="src;."
python -m tools.ai_sandbox.semantic_playtest `
  --database data/loveca.sqlite3 `
  --output logs/semantic_sandbox/manual-run `
  --decks 30 `
  --matches 20 `
  --max-actions 260 `
  --manual-fallback skip
```

OpenAI-compatible provider を使う場合は以下を設定します。

```powershell
$env:LOVECA_SEMANTIC_AGENT_PROVIDER="openai_compatible"
$env:LOVECA_SEMANTIC_AGENT_MODEL="..."
$env:LOVECA_SEMANTIC_AGENT_API_BASE="..."
$env:LOVECA_SEMANTIC_AGENT_API_KEY="..."
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

- `TODO.md`: 低優先度の既知タスク
- `src/loveca/cards/`: importer、catalog、画像キャッシュ
- `src/loveca/decks/`: deck format、analyzer、saved deck library
- `src/loveca/simulation/`: GameState、Action、runtime、effects
- `src/loveca/webapp.py`: FastAPI と SPA 配信
- `web/`: React ベースのルール検証 UI
- `docs/`, `specs/`: 設計文書と仕様
- `docs/14-database-migration-and-update-guide.md`: SQLite の再構築、増分更新、runtime lifecycle 指針
- `docs/15-project-guidance.md`: changelog 言語などの保守指針
- `docs/16-low-cost-online-battle-plan.md`: 低コストなネットワーク対戦検証モードの計画
- `docs/17-browser-only-preview-and-pages-release.md`: GitHub Pages browser preview と静的 data package の計画

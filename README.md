# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

ラブライブ！シリーズ オフィシャルカードゲーム（ラブカ）のための、ローカルカードデータベース、デッキ分析、ルール検証ツールです。

公式日本語データを唯一の権威ソースとして扱います。内部の英語名は安定した実装識別子であり、公式用語の置き換えではありません。

## 現在の状態

`v0.76` の収録内容:

- 公式 `card_list` からの正式カード importer
- `＋` / `+` 混在を避けるカード番号正規化
- SQLite Schema v2 のローカルカード DB
- デッキ保存機能付き Deck Builder
- `decklist.v0` ベースの Deck Analyzer
- FastAPI + React SPA の可視化ルール検証 UI
- Replay 可能な Action-only GameState
- 925 件の effect registry entry
  - 628 件は `test_validated_executable`
  - 297 件は timing prompt / 未対応処理用の `manual_resolution`
- 将来の低コスト online 同期に向けた state hash / compatibility metadata の基礎
- Hosted Online MVP の room API
  - room code による host / guest 参加
  - HTTP polling による状態同期
  - Python Rule Engine をサーバー側で再利用
  - 24 時間 TTL の一時 room
- locked authoritative card SQLite
  - CI、Docker、Pages data export は repository 内の `data/loveca.sqlite3` を使用
  - `data/loveca-db-manifest.json` が DB / effect registry fingerprint を記録
- GitHub Pages browser preview 用の静的 SPA release workflow
  - preview data package は解析済みカード / skill data のみを含む
  - カード画像は同梱せず、公式 `image_url` を参照する
  - 初回起動時に 5 個の合法な `decklist.v0` preview sample deck を browser localStorage に作成
  - decklist.v0 JSON の import / export に対応

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
- 分岐ごとに異なる Stage Member 候補を持つ効果選択に対応
- registry entry ベースの `test_validated_executable` coverage は 67.89% まで拡張済み
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
- 本格的な online 運用、アカウント、ユーザー同期、不正対策
- GitHub Pages preview は解析済み data package を同梱した場合、FastAPI なしでカードカタログ閲覧、browser local deck 保存、MVP deck 分析まで動作します。対戦は runtime config の `apiBaseUrl` を設定した場合のみ Hosted FastAPI に接続できます。

## フィードバックと対戦相手募集

バグ報告、ルール挙動の相談、online 対戦相手探しは [Discord](https://discord.gg/8uYQH7z8) を使ってください。報告時は、できれば利用中の版、ローカル / Hosted / Pages preview のどれか、再現手順、decklist.v0 JSON、Replay JSON、スクリーンショットを添えてください。

## 既知の制限

- これは開発中の alpha 版です。公式アプリではなく、ルール検証とプレイテスト feedback を集めるためのツールです。
- 全カード効果の自動実行 coverage はまだありません。未対応効果は `ManualAdjustmentAction`、構造化 pending choice、またはデバッグ用 skip で進行する場合があります。
- Phase 5 sandbox では `illegal_action` は大きく減っていますが、長局では `mandatory_manual_resolution` や `max_actions` が残っています。最新の詳細は `CHANGELOG.md` と `TODO.md` を確認してください。
- FAQ / 個別裁定に依存する効果はまだ仕様化していません。
- `data/loveca.sqlite3` は repository 内の locked authoritative card DB です。公式カード追加や parser / schema / effect registry の互換性変更後は、maintainer が DB と `data/loveca-db-manifest.json` を再生成して commit します。ユーザーや CI が online 用に別 DB を import してはいけません。保存済みデッキは `decklist.v0` のユーザーデータなので、カード DB とは分けて保持できます。
- Web/API テストには `httpx2` が必要です。環境に未導入の場合、`tests/test_catalog_api.py` と `tests/test_webapp.py` は収集段階で停止します。
- Hosted Online MVP は低コスト検証用です。ルール判定は FastAPI 側の Python engine が行いますが、アカウント、恒久保存、厳密な不正対策はありません。
- GitHub Pages browser preview はカード閲覧、Deck Builder、decklist.v0 import / export、MVP deck 分析を主目的にしています。対戦は Hosted API が設定された環境でのみ利用できます。

## UI 機能と使い方

### ホーム / 対戦開始

- 画面右上の言語切り替えで、簡体中文 UI と日本語 UI を切り替えられます。選択は browser localStorage に保存されます。
- 保存済みデッキ、または Deck Builder から戻した編集中デッキを選び、ローカル検証用の対戦を作成できます。
- Hosted API が設定されている環境では、room code を発行して host / guest がそれぞれデッキを持ち寄る online room を作成・参加できます。Online match では自分の盤面が常に画面下側に表示され、Action Dock は現在の room token で送信できる action だけを表示します。
- Browser preview では、同梱済みカードデータ、5 個の合法な初期 `decklist.v0` sample deck、localStorage 保存、decklist.v0 import / export、MVP deck 分析を利用できます。対戦は runtime config の `apiBaseUrl` が設定されている場合だけ Hosted API に接続します。

### カードカタログ

- 読み取り専用のカード一覧です。検索欄とカード種別、作品、ユニットの filter でカードを絞り込めます。
- 一覧からカードを選ぶと、カード画像、Cost / Blade / Score、Heart、作品 / ユニット、公式効果テキスト、review candidate、source observation を確認できます。
- 画像はローカル cache がある場合は `/api/card-images/*` を優先し、なければ公式 `image_url` に fallback します。

### Deck Builder

- 保存済みデッキの作成、読み込み、上書き保存、名前変更、削除ができます。
- decklist.v0 JSON の import / export に対応しているため、browser preview とローカル環境の間でデッキを移動できます。
- `Member` / `Live` / `Energy` を分けて表示し、`Member 48` / `Live 12` / `Energy 12` と同名カード上限を UI 上で確認しながら編集できます。
- カード検索は、カード名 / カード番号の検索、カード種別、作品、ユニット、Member の基本 Heart / Cost / Blade / Blade Heart、Live の必要 Heart / Score / Blade Heart で絞り込めます。検索結果は card code、card name、card type、Member cost、Blade、Live 必要 Heart、Live score、現在の投入枚数で並び替えできます。
- 検索結果のカードは詳細 dialog で画像と主要 stat を確認でき、追加ボタンでデッキへ投入できます。
- 右側の分析 dashboard は自動更新され、構築合法性、枚数問題、Member cost curve、基本 Heart、Live 必要 Heart、Score、特殊 Blade Heart、効果 timing / execution summary を確認できます。
- Deck Builder で選んだデッキは「対戦に使う」操作でホームへ戻し、ローカル対戦または online room の deck source として使えます。

### ルール検証 UI

- Match 画面では、双方のステージ、手札・山札・控え室などの zone count、Live / Energy / Heart 状態、現在 phase、turn number を同じ画面で追跡できます。
- Action Dock には現在実行可能な action が表示され、Member 登場、Baton Touch、Live Set、mulligan、Heart 割り当て、pending effect 解決などを UI から送信できます。
- 一部の効果は構造化 prompt として表示され、対象カード選択、choice branch、inspection / reveal の並べ替えや移動先選択を UI 上で処理できます。
- 自動実行できない効果は `ManualAdjustmentAction` drawer で、カード移動、Heart 補正、Live success 補正、任意メモを入力して検証を継続できます。
- Action/Event Log、Live judgment detail、effect activation summary、カード詳細 dialog を使って、rule engine が何を処理したかを確認できます。
- ローカル match と online room match は Replay JSON export に対応しています。Browser preview 単体では Replay export は無効です。

## 画面イメージ

開始画面: 保存済みデッキを選び、そのまま対局作成まで進められます。

![開始画面](docs/images/home-desktop.png)

Deck Builder: 右側でカード検索と絞り込み、中央で構築内容と分析結果を確認します。

![Deck Builder](docs/images/deck-builder-desktop.png)

ルール検証 UI: 盤面、Action/Event Log、手動調整を同じ画面で追えます。

![ルール検証 UI](docs/images/match-actions-desktop.png)

## カード DB と asset 配布方針

将来的には、構築済みの SQLite カード DB、effect registry、manifest、checksum を含む versioned asset package を配布し、ユーザーが公式サイトから毎回全量取得しなくても起動できる形にできます。

ただし、公式効果テキスト全文、公式 PDF 由来の大量データ、ダウンロード済みカード画像ファイルは再配布可否の確認が必要です。GitHub Pages preview で公開する asset は、解析済みカード data、解析済み skill data、manifest、checksum、プロジェクト独自 metadata に限定し、カード画像は同梱せず公式 `image_url` を参照する方針です。

公開 preview は専用の `preview` ブランチから配信します。このブランチでは review 済みの `data/loveca.sqlite3` を直接コミットし、GitHub Pages workflow はその SQLite から静的 JSON を生成します。`develop` の頻繁な更新では Pages を再構築せず、preview を更新したいタイミングだけ `preview` ブランチへ反映します。

browser preview の deck は localStorage に保存されます。Deck はカード番号と枚数中心の小さな JSON なので、5 個の合法な初期 `decklist.v0` sample deck と通常のユーザー deck では容量は小さく収まります。移行や共有が必要な場合は、Deck Builder の JSON import / export を使用してください。

private tester 向けに事前構築 DB を渡す場合も、release version、schema version、parser version、card database fingerprint、effect registry hash を明示し、互換性が崩れる更新後は再導入が必要です。

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
- `docs/18-hosted-online-smoke-checklist.md`: Hosted Online MVP の merge / deploy 前 smoke checklist

## ローカル環境構築と開発コマンド

### 動作環境

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

### ローカル起動

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

### Docker API サーバー

Cloudflare Worker gateway、Caddy、小型 VM で Hosted Online MVP を試す場合は、FastAPI backend だけを Docker で起動できます。

前提:

- locked `data/loveca.sqlite3` が repository に commit されていること
- `runtime/` と `logs/` はホスト側に保持すること
- GitHub Pages から接続する場合は `LOVECA_ALLOWED_ORIGINS` に Pages URL を設定すること

ローカル build:

```powershell
docker build -t loveca-simulator-api:local .
```

compose 起動:

```powershell
$env:LOVECA_ALLOWED_ORIGINS="https://smaillion.github.io,http://127.0.0.1:8765,http://localhost:8765"
docker compose -f compose.api.yml up -d --build
```

health check:

```powershell
curl http://127.0.0.1:8765/api/health
```

推奨する低コスト構成では、Cloudflare Worker の `workers.dev` URL を安定 API gateway として使います。VPS 側は Caddy で secret 管理された origin hostname の `/api/*` を公開し、`127.0.0.1:8765` に reverse proxy します。

GitHub Actions:

- `.github/workflows/api-image.yml` は Docker image を build します。
- Pull Request では build 検証のみ行います。
- `api-image.yml` は `develop` / `preview` への push または手動実行で GHCR に `ghcr.io/smaillion/loveca-simulator-api` として push します。
- `.github/workflows/deploy-api.yml` は `develop` への push または手動実行で GHCR image を build / push し、SSH で VPS 上の compose service を更新します。
- `.github/workflows/deploy-worker.yml` は `develop` / `preview` の Worker 変更、または手動実行で Cloudflare Worker gateway を更新します。
- `.github/workflows/pages-preview.yml` は `preview` への push または手動実行で GitHub Pages preview を公開します。
- `main` への push は現段階では自動 publish / deploy を行いません。production 相当の release promotion は maintainer の明示的な手動実行または専用 release 手順で行います。

Deploy に必要な GitHub Secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`
- `ORIGIN_API_BASE_URL`
- `LOVECA_ALLOWED_ORIGINS`
- `CLOUDFLARE_API_TOKEN`

GitHub Pages から Hosted API に接続する場合は、repository variable `VITE_PUBLIC_API_BASE_URL` に Cloudflare Worker URL を設定してください。

### よく使うコマンド

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

### テスト

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

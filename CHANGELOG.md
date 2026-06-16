# 変更履歴 / 变更记录

## Unreleased

### 追加 / 新增

- GitHub Pages browser preview release workflow を追加し、`develop` への push または手動実行で静的 SPA を Pages artifact として公開できるようにした。
- `scripts/export-preview-data.py` を追加し、ローカル SQLite カード DB から browser preview 用の静的 JSON data package を生成できるようにした。preview package は解析済みカード / skill data と公式画像 URL 参照のみを含み、カード画像ファイルは同梱しない。
- `VITE_BROWSER_PREVIEW=true` で catalog / facets / card detail を `preview-data/*.json` から読む browser catalog adapter を追加し、GitHub Pages 上でカードカタログを閲覧できるようにした。
- `VITE_BROWSER_PREVIEW=true` で deck 保存 / 読み込み / 更新 / リネーム / 削除を browser localStorage に保存し、MVP deck 分析を TypeScript adapter で実行できるようにした。
- Browser-only preview の設計文書を追加し、IndexedDB / localStorage、deck import/export、play history export、public data policy の境界を整理。
- effect registry を 925 件に拡張し、同文の top-deck reorder、Live-success reorder、起動 self-Wait / ready-other Member pattern を追加。
- `test_validated_executable` effect を 466 件まで拡張し、registry entry ベースの coverage が 50.38% に到達。
- grouped Stage Member choice を追加し、`PL!SP-bp4-023:1` のように「指定名 Member 1 人」と「それ以外の Liella! Member 1 人」を別 group で選び、両方に Live 期間 Blade modifier を適用できるようにした。
- Live-specific temporary modifier として、Live score、必要 Heart 増減、必要 Heart 置換の基礎を追加。
- `ライブ開始時` / `ライブ成功時` の exact-text pattern を追加し、公開した山札上カードによる score 加算、成功 Live 枚数による必要 Heart 変更、Stage Heart / Blade 条件などを構造化。
- 成功 Live 2 枚以上を条件に Live score と必要 Heart を同時に置換する `ライブ開始時` pattern を構造化。
- Liella! の center Member cost が相手 center Member より高い場合に Live score を +1 する `ライブ開始時` pattern を構造化。
- Hasunosora / Liella! / Nijigasaki の Live-start 条件を追加し、Stage Heart 合計、控室 Live 名称、必要 Heart 条件、名前違い Member 数による score / required Heart 変更を構造化。
- Aqours の Stage Member 全体が Live 終了時まで Blade を得る `ライブ開始時` pattern を構造化。
- Nijigasaki の控室不同名 Live 数による score bonus、Liella! 左サイド Member の Heart 条件 Blade 付与、Hasunosora の Stage / 控室不同名 Member 条件による必要 Heart 減少を構造化。
- `ライブ開始時` の draw-then-discard、移動済み Liella! / 5yncri5e! Member 参照、成功 Live score threshold、CatChu! Energy ready + all-active score bonus を構造化。
- 成功 Live 名称参照による score / 必要 Heart 加算と、Liella! Stage+控室不同名条件による必要 Heart 置換を構造化。
- 手札 6 枚以下を条件に控え室の Member を回収する `ライブ成功時` pattern を構造化。
- center area の μ's Member が持つ `heart03` 2 個ごとに必要 Heart を減らす `ライブ開始時` pattern を構造化。
- Stage 上の指定 Member 2 人の cost 関係を参照して必要 Heart を減らす `ライブ開始時` pattern を構造化。
- 蓮ノ空 Member 1 人の元々持つ Heart を Live 終了時まで `heart01` に置換する `ライブ開始時` pattern を構造化。
- Stage 上の指定名 Member に Live 終了時まで Heart / Blade を付与する `ライブ開始時` pattern を構造化。
- Nijigasaki の効果で本ターン中に Wait Energy / Wait Member を Active にした履歴を追跡し、その履歴に応じて Live score を +1 / +2 する `ライブ開始時` pattern を構造化。
- ready-history support 後の 20-match block smoke で 13 `mandatory_manual_resolution` / 5 `max_actions` / 2 完走を確認し、`PL!N-pb1-037:1` が blocker から消え、次の高頻度 blocker が Yell 中の Blade Heart 色変換であることを記録。
- 指定名 Member modifier 後の 20-match block smoke で 12 `mandatory_manual_resolution` / 6 `max_actions` / 2 完走を確認し、その時点の高頻度 blocker が Nijigasaki ready-history score modifier であることを記録。
- base Heart 置換後の 20-match block smoke で 12 `mandatory_manual_resolution` / 5 `max_actions` / 3 完走を確認し、`PL!HS-bp5-021:1` が blocker から消えたことを記録。
- Phase 5 sandbox `30 decks x 50 matches` を再実行し、`block` mode は 35 `mandatory_manual_resolution` / 9 `max_actions` / 6 完走、`skip` mode は `illegal_action = 0` / 40 `max_actions` / 10 完走であることを記録。
- grouped Stage Member choice 後の 20-match block smoke で 2 完走 / 11 `mandatory_manual_resolution` / 7 `max_actions` / `illegal_action = 0` を確認し、`PL!SP-bp4-023:1` が blocker から消えたことを記録。
- Semantic user-agent sandbox を追加し、deterministic black-box sandbox とは別に、未構造化 `manual_resolution` 効果を現在の `ManualAdjustmentAction` で人間相当のテスターが処理できるかを測れるようにした。`mock` provider は CI / smoke 用で、実 provider は OpenAI-compatible Chat Completions 設定を使う。
- `PL!N-bp4-031:1` を draw 3 後に hand から 3 枚を選んで deck top に戻す post-action choice として構造化し、`move_selected_to_deck_top` が hand 由来の選択にも対応するようにした。対応後の 20-match block smoke は 2 完走 / 9 `mandatory_manual_resolution` / 9 `max_actions`。
- Baton Touch でこのターン登場した蓮ノ空 Member 2 人以上を条件に required Heart を減らす `PL!HS-bp2-023:1` / `PL!HS-bp2-025:1` を構造化し、Baton-specific turn history を GameState に追加。
- 以前の Phase 5 sandbox `30 decks x 50 matches --manual-policy skip --max-actions 260` 回帰では 12 局完走、38 `max_actions`、`illegal_action = 0` を確認。
- Energy 11 枚以上を条件に控室から Live カードを回収する `登場` pattern を構造化。
- AI sandbox report に skipped effect ID 集計を追加し、`skip` mode の blocker 分析をしやすくした。
- AI sandbox の deck 生成を work-key grouped / Heart-fit 寄りに調整し、Live 判定に近い blocker を見つけやすくした。
- AI sandbox report に各 match の成功 Live 枚数を追加し、長局化が deck construction 由来か未解決 effect 由来かを切り分けやすくした。
- on-play ready / wait、Waiting Room recovery、draw-then-discard、conditional mill、Energy placement、temporary Blade / Heart / score modifier pattern を追加。
- 分岐選択の `登場`、単純 mill 5、ステージ Member 数参照の draw-then-discard を exact-text pattern として構造化。
- opponent hand reveal + conditional draw の `登場` pattern を構造化。
- multi-player pending choice を追加し、双方が順番に選択する effect を replay-safe に処理できるようにした。
- 双方が控室から cost 2 以下 Member をウェイト登場させる effect と、双方が手札を 3 枚まで調整してから 3 枚引く effect を構造化。
- AI sandbox の 20 deck x 20 match black-box smoke を pytest flow に追加。
- AI sandbox に `--manual-policy skip` を追加し、未対応の強制効果を `effect_skipped_due_to_error` として記録しながら継続できるようにした。
- `【登場】自分のデッキの上からカードを3枚見る。…` の top-3 reorder pattern を構造化 `inspect_top_select` に昇格。
- `登場` / `起動` を中心とする timing-only `manual_resolution` fallback を追加し、未自動化効果も prompt として記録できる範囲を拡張。
- `loveca effects candidates` を追加し、ローカルカード DB から exact-text の registry candidate を JSON 出力できるようにした。
- 将来の低コスト online 同期に向けて、`ActionEnvelope`、canonical MatchState hash、deck / registry / card DB fingerprint、replay metadata を追加。
- 構造化効果 prompt に Heart 色選択、count 選択、Stage Member 選択、Energy 選択を追加。
- `ライブ成功時` の効果 trigger 境界を追加し、成功 Live 移動後に replay-safe な pending / auto resolve を行えるようにした。
- 効果による Heart 獲得、score 変更、Energy の Active / Wait 変更を構造化 operation として追加。
- 処理できない pending effect をデバッグ用に `skip_effect` で飛ばし、replay-safe な `effect_skipped_due_to_error` event として記録できるようにした。
- Hosted Online MVP の準備として FastAPI backend 用 `Dockerfile`、`compose.api.yml`、`.dockerignore` を追加。
- API Docker image を GHCR に build / push する GitHub Actions workflow を追加。
- Hosted Online MVP の room API を追加し、room code による host / guest 参加、HTTP polling、remote Action submit、room replay、TTL cleanup に対応。
- GitHub Pages preview が `VITE_HOSTED_API_BASE_URL` を受け取り、Hosted FastAPI に接続できるようにした。
- VPS / Cloudflare Tunnel 運用向けに、GHCR image を build / push して SSH で compose service を更新する手動 deploy workflow を追加。
- Hosted Online MVP の merge / deploy 前チェックとして、API、Docker、二ブラウザ、VPS / Cloudflare Tunnel の smoke checklist を追加。

中文:

- 新增 GitHub Pages browser preview 发布 workflow，可在 `develop` push 或手动执行时发布静态 SPA。
- 新增 `scripts/export-preview-data.py`，可从本地 SQLite 卡牌库导出 browser preview 用静态 JSON 数据包。preview package 只包含解析后的卡牌 / 技能数据和官方图片 URL 引用，不打包卡图文件。
- 新增 `VITE_BROWSER_PREVIEW=true` 下的 browser catalog adapter，从 `preview-data/*.json` 读取 catalog / facets / card detail，使 GitHub Pages 上可以浏览卡库。
- 新增 `VITE_BROWSER_PREVIEW=true` 下的 browser deck library，将牌组保存 / 读取 / 更新 / 重命名 / 删除写入 localStorage，并用 TypeScript adapter 执行 MVP deck 分析。
- 新增 Browser-only preview 设计文档，整理 IndexedDB / localStorage、牌组导入导出、游玩履历导出和 public data policy 边界。
- 将 effect registry 扩展到 925 条，新增同文 top-deck reorder、Live 成功 reorder、起动 self-Wait / ready-other Member 模式。
- 将 `test_validated_executable` 技能扩展到 466 条，按 registry entry 计算达到 50.38% 覆盖率。
- 新增 grouped Stage Member choice，支持像 `PL!SP-bp4-023:1` 这样把“指定名 Member 1 人”和“除此以外的 Liella! Member 1 人”分组选择，并对两个目标应用 Live 期间 Blade modifier。
- 新增 Live 专用临时 modifier 基础，覆盖 Live score、所需 Heart 增减和所需 Heart 替换。
- 新增 `ライブ開始時` / `ライブ成功時` exact-text pattern，结构化支持公开牌堆顶后的 score 加算、按成功 Live 数改变所需 Heart、Stage Heart / Blade 条件等。
- 结构化支持以成功 Live 2 张以上为条件，同时修改 Live score 并替换所需 Heart 的 `ライブ開始時` pattern。
- 结构化支持 Liella! center 成员 cost 高于对手 center 成员时 Live score +1 的 `ライブ開始時` pattern。
- 新增 Hasunosora / Liella! / Nijigasaki 的 Live-start 条件，结构化支持 Stage Heart 合计、控室 Live 名称、所需 Heart 条件和不同名成员数量导致的 score / required Heart 变化。
- 结构化支持 Aqours Stage Member 全体到 Live 结束前获得 Blade 的 `ライブ開始時` pattern。
- 结构化支持 Nijigasaki 控室不同名 Live 数加分、Liella! 左侧 Member Heart 条件获得 Blade、Hasunosora Stage / 控室不同名 Member 条件减少所需 Heart。
- 结构化支持 `ライブ開始時` 抽牌后弃牌、移动过的 Liella! / 5yncri5e! 成员参照、成功 Live score 阈值，以及 CatChu! Energy ready + 全部 Active 后加分。
- 结构化支持成功 Live 名称参照带来的 score / 所需 Heart 增加，以及 Liella! Stage+控室不同名条件下的所需 Heart 替换。
- 结构化支持以手牌 6 张以下为条件，从控室回收 Member 的 `ライブ成功時` pattern。
- 结构化支持中心 μ's Member 每 2 个 `heart03` 减少 1 个任意色所需 Heart 的 `ライブ開始時` pattern。
- 结构化支持参照 Stage 上两名指定 Member cost 关系来减少所需 Heart 的 `ライブ開始時` pattern。
- 结构化支持将 1 名莲之空 Member 原本持有的 Heart 到 Live 结束前替换为 `heart01` 的 `ライブ開始時` pattern。
- 结构化支持 Stage 上指定姓名 Member 到 Live 结束前获得 Heart / Blade 的 `ライブ開始時` pattern。
- 结构化支持追踪本回合内由 Nijigasaki 技能将 Wait Energy / Wait Member 变为 Active 的历史，并据此让 Live score +1 / +2 的 `ライブ開始時` pattern。
- ready-history support 后的 20-match block smoke 结果为 13 局 `mandatory_manual_resolution` / 5 局 `max_actions` / 2 局完走，确认 `PL!N-pb1-037:1` 已从 blocker 消失，下一类高频 blocker 是 Yell 中的 Blade Heart 颜色转换。
- 指定姓名 Member modifier 后的 20-match block smoke 结果为 12 局 `mandatory_manual_resolution` / 6 局 `max_actions` / 2 局完走，并记录当时的高频 blocker 为 Nijigasaki ready-history score modifier。
- base Heart 替换后 20-match block smoke 结果为 12 局 `mandatory_manual_resolution` / 5 局 `max_actions` / 3 局完走，并确认 `PL!HS-bp5-021:1` 已从 blocker 中消失。
- 重新执行 Phase 5 sandbox `30 decks x 50 matches`，记录 `block` mode 为 35 局 `mandatory_manual_resolution` / 9 局 `max_actions` / 6 局完走，`skip` mode 为 `illegal_action = 0` / 40 局 `max_actions` / 10 局完走。
- grouped Stage Member choice 后的 20-match block smoke 结果为 2 局完走 / 11 局 `mandatory_manual_resolution` / 7 局 `max_actions` / `illegal_action = 0`，并确认 `PL!SP-bp4-023:1` 已从 blocker 中消失。
- 新增 semantic user-agent sandbox，可以在 deterministic 黑盒 sandbox 之外，单独衡量未结构化 `manual_resolution` 技能是否能被类似人工测试者通过当前 `ManualAdjustmentAction` 表达。`mock` provider 用于 CI / smoke，真实 provider 使用 OpenAI-compatible Chat Completions 配置。
- 将 `PL!N-bp4-031:1` 结构化为抽 3 张后，从手牌选择 3 张按顺序放回牌堆顶的 post-action choice，并让 `move_selected_to_deck_top` 支持从手牌选择。对应后的 20-match block smoke 为 2 局完走 / 9 局 `mandatory_manual_resolution` / 9 局 `max_actions`。
- 结构化支持 `PL!HS-bp2-023:1` / `PL!HS-bp2-025:1`：本回合通过 Baton Touch 登场的莲之空 Member 达到 2 人以上时减少 required Heart，并在 GameState 中新增 Baton-specific turn history。
- 之前的 Phase 5 sandbox `30 decks x 50 matches --manual-policy skip --max-actions 260` 回归结果为 12 局完走、38 局 `max_actions`、`illegal_action = 0`。
- 结构化支持以 Energy 11 张以上为条件，从控室回收 Live 卡的 `登場` pattern。
- AI sandbox report 新增 skipped effect ID 集计，方便分析 `skip` mode 的剩余 blocker。
- AI sandbox 的 deck 生成调整为更偏向同作品 / Heart 匹配，便于发现更接近 Live 判定的 blocker。
- AI sandbox report 新增每局成功 Live 数，便于区分长局问题是 deck 构筑导致还是未解决 effect 导致。
- 新增登场 ready / wait、控室回收、抽牌后弃牌、条件 mill、Energy 放置，以及临时 Blade / Heart / score 修正模式。
- 将二选一 `登場`、单纯 mill 5、按场上 Member 数抽牌后弃牌升级为 exact-text 结构化模式。
- 将 opponent hand reveal + 条件抽牌的 `登場` 模式升级为结构化处理。
- 新增 multi-player pending choice，使双方顺序选择的 effect 可以 replay-safe 地处理。
- 将双方从控室登场 cost 2 以下 Member、双方把手牌调整到 3 张后再抽 3 的 effect 结构化。
- 将 AI sandbox 的 20 deck x 20 match 黑盒 smoke 纳入 pytest flow。
- 为 AI sandbox 新增 `--manual-policy skip`，可把未支持的强制技能记录为 `effect_skipped_due_to_error` 后继续推进。
- 将 `【登場】自分のデッキの上からカードを3枚見る。…` 的 top-3 reorder 模式升级为结构化 `inspect_top_select`。
- 新增以 `登場` / `起動` 为中心的 timing-only `manual_resolution` fallback，扩大未自动化技能也能被提示和记录的范围。
- 新增 `loveca effects candidates`，可从本地卡库以 JSON 输出 exact-text registry 候选。
- 为未来低成本 online 同步新增 `ActionEnvelope`、canonical MatchState hash、deck / registry / card DB fingerprint 和 replay metadata。
- 结构化技能 prompt 增加 Heart 颜色选择、数量选择、Stage Member 选择和 Energy 选择。
- 新增 `ライブ成功時` 技能触发边界，成功 Live 移动后可进行可回放的 pending / 自动结算。
- 将技能产生的 Heart 获得、score 修改、Energy Active / Wait 改变建模为结构化 operation。
- 新增调试用 `skip_effect`，无法处理的 pending effect 可被跳过并生成 replay-safe 的 `effect_skipped_due_to_error` event。
- 为 Hosted Online MVP 准备新增 FastAPI backend 用 `Dockerfile`、`compose.api.yml` 和 `.dockerignore`。
- 新增 GitHub Actions workflow，用于构建 API Docker image 并推送到 GHCR。
- 新增 Hosted Online MVP 的 room API，支持 room code 创建 / 加入、HTTP polling、远程提交 Action、room replay 和 TTL cleanup。
- GitHub Pages preview 现在可以读取 `VITE_HOSTED_API_BASE_URL`，连接 Hosted FastAPI。
- 面向 VPS / Cloudflare Tunnel 运行方式，新增手动 deploy workflow，可构建 / 推送 GHCR image 并通过 SSH 更新 compose service。
- 新增 Hosted Online MVP 合并 / 部署前 smoke checklist，覆盖 API、Docker、双浏览器、VPS / Cloudflare Tunnel 检查。

### 変更 / 变更

- `ManualAdjustmentAction` の役割をさらに絞り、既知の Energy / inspection / color / target 選択を通常の手動調整に流さない方針を強化。
- 効果 execution MVP spec を現在の Phase 5 実装状態に合わせて更新。
- Phase 8 AI の優先度を下げ、Phase 9 / 10 の低コスト online 検証を早期並行 track として roadmap に反映。
- 分岐選択効果の UI を二段式に更新し、初回は `selected_branch` を、後続処理では分岐ごとの選択カードを送信するようにした。
- FastAPI に `LOVECA_ALLOWED_ORIGINS` ベースの CORS 設定を追加し、GitHub Pages SPA から Hosted API へ接続しやすくした。

中文:

- 进一步收窄 `ManualAdjustmentAction` 的职责，已知的 Energy / 检查牌堆 / 颜色 / 目标选择不再走普通手动调整。
- 更新 Effect Execution MVP spec，使其符合当前 Phase 5 实装状态。
- 下调 Phase 8 AI 优先级，并将 Phase 9 / 10 低成本 online 验证写成提前并行路线。
- 将分支选择技能 UI 改为两段式，第一次提交 `selected_branch`，后续再提交该分支需要的选卡。
- FastAPI 增加基于 `LOVECA_ALLOWED_ORIGINS` 的 CORS 配置，方便 GitHub Pages SPA 连接 Hosted API。

### 修正 / 修复

- `choose_effect_branch` 効果で UI が `selected_branch` を送らず、`effect branch selection is required` になる問題を修正。
- 構造化 effect inspection の途中で処理できなくなった場合に、resolution area のカードが残って次へ進めなくなる問題を、debug skip cleanup で回避できるようにした。

中文:

- 修复 `choose_effect_branch` 技能 UI 未提交 `selected_branch`，导致 `effect branch selection is required` 的问题。
- 结构化技能检查途中无法处理时，可通过 debug skip 清理 resolution area，避免状态卡死。

## v0.4.0-alpha.3 - 2026-06-15

### 追加 / 新增

- 効果実行の今後の設計に向けた、全量カードテキストベースの効果セマンティクス監査文書を追加。
- 構造化 prompt、山札上確認、選択、Energy Deck 配置効果を扱う effect registry MVP を拡張。
- Deck Builder に作品、ユニット、Heart 色、Blade、Live 必要 Heart、Score、Blade Heart の絞り込みを追加。
- Deck Builder の分析に、効果タイミングと実行方式の集計を追加。
- Deck Builder のカード詳細ダイアログで印刷版を選択し、カード画像を確認できるようにした。

中文:

- 新增面向后续技能执行设计的全量技能语义审查文档。
- 扩展 effect registry MVP，覆盖结构化提示、牌堆顶检查、选择和 Energy Deck 放置效果。
- Deck Builder 增加作品、组合、Heart 颜色、Blade、Live 所需 Heart、Score、Blade Heart 筛选。
- Deck Builder 分析增加技能时点和执行方式统计。
- Deck Builder 详情弹窗支持选择印刷版本并确认卡图。

### 変更 / 变更

- Deck Builder の構築済みデッキ表示を `Member` / `Live` / `Energy` に分割。
- Deck Builder の状態表示と分析パネルを responsive dashboard 形式に再設計。
- Deck Builder の検索結果に、ページングを維持したまま広めのスクロール領域を復元。
- 構築済みデッキの常時サムネイルをやめ、数値分布をラベル付き chip 表示に変更。
- カード番号の全角 `＋` を importer / database 境界で ASCII `+` に正規化。
- インストール済み checkout からでも formal importer が spike parser を見つけやすいよう改善。
- Ruff による Python コード整形と生成キャッシュ整理を実施。

中文:

- Deck Builder 已组牌组改为 `Member` / `Live` / `Energy` 分区。
- Deck Builder 状态栏和分析面板重做为响应式 dashboard。
- Deck Builder 搜索结果恢复较大的滚动区域，同时保留分页。
- 已组牌组不再常驻显示缩略图，数字分布改成带标签的 chip。
- importer / database 边界统一把卡号中的全角 `＋` 转为 ASCII `+`。
- 改善 formal importer 在安装式 checkout 中定位 spike parser 的能力。
- 使用 Ruff 整理 Python 代码并清理生成缓存。

### 修正 / 修复

- Deck Builder の属性フィルターが表示だけで実際には適用されない問題を修正。
- Energy カードに同名 4 枚制限が誤って適用される問題を修正。
- match / deck 画面でローカルカード画像が不必要に fallback 表示になる問題を修正。
- 日本語 UI で一部テキストが layout からはみ出る問題を修正。
- `+` 接尾辞の正規化により、近いカード番号のカードが見えなくなる問題を修正。

中文:

- 修复 Deck Builder 属性筛选只有 UI 但未实际应用的问题。
- 修复 Energy 卡错误套用同卡 4 张限制的问题。
- 修复 match / deck 画面本地卡图错误降级显示的问题。
- 修复日语 UI 中部分文本溢出布局的问题。
- 修复带 `+` 后缀的相近卡号因正规化问题导致不可见的问题。

### 既知の制限 / 已知限制

- 全カード効果の自動化はまだ未完成。
- 未対応または曖昧なカード効果には `ManualAdjustmentAction` が必要。
- オンライン対戦、AI、Monte Carlo、勝率シミュレーションはまだ対象外。

中文:

- 全卡技能自动化尚未完成。
- 未支持或规则含义仍不明确的技能仍需要 `ManualAdjustmentAction`。
- 在线对战、AI、Monte Carlo 和胜率模拟仍不在当前范围。

# 変更履歴 / 变更记录

## Unreleased

### 追加 / 新增

- GitHub Pages browser preview release workflow を追加し、`develop` への push または手動実行で静的 SPA を Pages artifact として公開できるようにした。
- `scripts/export-preview-data.py` を追加し、ローカル SQLite カード DB から browser preview 用の静的 JSON data package を生成できるようにした。preview package は解析済みカード / skill data と公式画像 URL 参照のみを含み、カード画像ファイルは同梱しない。
- Browser-only preview の設計文書を追加し、IndexedDB / localStorage、deck import/export、play history export、public data policy の境界を整理。
- effect registry を 925 件に拡張し、同文の top-deck reorder、Live-success reorder、起動 self-Wait / ready-other Member pattern を追加。
- `test_validated_executable` effect を 392 件まで拡張し、現在のローカルカードプールの粗い全効果数に対して 20.07% coverage に到達。
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

中文:

- 新增 GitHub Pages browser preview 发布 workflow，可在 `develop` push 或手动执行时发布静态 SPA。
- 新增 `scripts/export-preview-data.py`，可从本地 SQLite 卡牌库导出 browser preview 用静态 JSON 数据包。preview package 只包含解析后的卡牌 / 技能数据和官方图片 URL 引用，不打包卡图文件。
- 新增 Browser-only preview 设计文档，整理 IndexedDB / localStorage、牌组导入导出、游玩履历导出和 public data policy 边界。
- 将 effect registry 扩展到 925 条，新增同文 top-deck reorder、Live 成功 reorder、起动 self-Wait / ready-other Member 模式。
- 将 `test_validated_executable` 技能扩展到 392 条，按当前本地卡池粗略全技能数量计算达到 20.07% 覆盖率。
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

### 変更 / 变更

- `ManualAdjustmentAction` の役割をさらに絞り、既知の Energy / inspection / color / target 選択を通常の手動調整に流さない方針を強化。
- 効果 execution MVP spec を現在の Phase 5 実装状態に合わせて更新。
- Phase 8 AI の優先度を下げ、Phase 9 / 10 の低コスト online 検証を早期並行 track として roadmap に反映。
- 分岐選択効果の UI を二段式に更新し、初回は `selected_branch` を、後続処理では分岐ごとの選択カードを送信するようにした。

中文:

- 进一步收窄 `ManualAdjustmentAction` 的职责，已知的 Energy / 检查牌堆 / 颜色 / 目标选择不再走普通手动调整。
- 更新 Effect Execution MVP spec，使其符合当前 Phase 5 实装状态。
- 下调 Phase 8 AI 优先级，并将 Phase 9 / 10 低成本 online 验证写成提前并行路线。
- 将分支选择技能 UI 改为两段式，第一次提交 `selected_branch`，后续再提交该分支需要的选卡。

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

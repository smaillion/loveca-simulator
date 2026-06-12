# Terminology Review

## Purpose

This artifact tracks official Japanese terminology normalization for the project.

It follows [016 Terminology Normalization](../specs/016-terminology-normalization.spec.md). It intentionally avoids storing bulk official rule or card text.

## Review Rules

* Japanese official terminology is authoritative.
* English internal names are stable engineering labels, not replacements for Japanese official text.
* `source_confirmed` means the term appears in an official indexed source reviewed during this pass.
* `ambiguous` means the provisional term may be an alias, shorthand, or unresolved exact wording.

## Reviewed Terms

| term_id | official_japanese | canonical_internal_name | category | display_ja | display_en | display_zh | aliases | source_reference | validation_status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `card_type_member` | メンバー | `member` | `card_types` | メンバー | Member | 成员 | メンバーカード | `beginner_guide`, `card_list` | `source_confirmed` | Confirmed as card/game term. |
| `card_type_live` | ライブ | `live` | `card_types` | ライブ | Live | 演唱会 | ライブカード | `beginner_guide`, `card_list` | `source_confirmed` | Confirmed as card/game term. |
| `card_type_energy` | エネルギー | `energy` | `card_types` | エネルギー | Energy | 能量 | エネルギーカード | `card_list`, `deck_recipe` | `source_confirmed` | Confirmed as card type/resource term. |
| `zone_deck` | デッキ | `deck` | `zones` | デッキ | Deck | 牌库 | メインデッキ | `beginner_guide`, `deck_recipe` | `source_confirmed` | Main deck terminology still needs exact rule-source distinction. |
| `zone_energy_deck` | エネルギーデッキ | `energy_deck` | `zones` | エネルギーデッキ | Energy Deck | 能量牌库 | エネルギーカードデッキ | `rule_pdf_1_06`, `deck_recipe` | `source_confirmed` | Exact construction constraints require rule review. |
| `zone_hand` | 手札 | `hand` | `zones` | 手札 | Hand | 手牌 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `zone_stage` | ステージ | `stage` | `zones` | ステージ | Stage | 舞台 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `zone_waiting_room` | 控え室 | `waiting_room` | `zones` | 控え室 | Waiting Room | 休息室 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `zone_success_live_area` | 成功ライブカード置き場 | `success_live_area` | `zones` | 成功ライブカード置き場 | Success Live Area | 成功演唱会区 | 成功ライブ置き場 | `rule_pdf_1_06`, `card_list` | `source_confirmed` | Provisional `成功ライブ置き場` should be treated as alias until comprehensive rules confirm exact wording. |
| `action_enter_play` | 登場 | `on_play` | `action_terms` | 登場 | Enter play | 登场 | - | `card_list` | `source_confirmed` | Used as effect timing/action term. |
| `timing_live_start` | ライブ開始時 | `live_start` | `timing_terms` | ライブ開始時 | Live start | 演唱会开始时 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `timing_live_success` | ライブ成功時 | `live_success` | `timing_terms` | ライブ成功時 | Live success | 演唱会成功时 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `effect_activated` | 起動 | `activated` | `effect_keywords` | 起動 | Activated | 起动 | 起動能力 | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed in card text and indexed rule snippets. |
| `effect_auto` | 自動 | `auto` | `effect_keywords` | 自動 | Automatic | 自动 | 自動能力 | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed in card text and indexed rule snippets. |
| `effect_continuous` | 常時 | `continuous` | `effect_keywords` | 常時 | Continuous | 常时 | 常時能力 | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed in card text and indexed rule snippets. |
| `limit_once_per_turn` | ターン1回 | `once_per_turn` | `effect_keywords` | ターン1回 | Once per turn | 每回合一次 | - | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed in card text and indexed rule snippets. |
| `phase_first_normal` | 先攻通常フェイズ | `first_player_normal_phase` | `turn_phase_terms` | 先攻通常フェイズ | First-player normal phase | 先攻通常阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Official turn phase. |
| `phase_second_normal` | 後攻通常フェイズ | `second_player_normal_phase` | `turn_phase_terms` | 後攻通常フェイズ | Second-player normal phase | 后攻通常阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Official turn phase. |
| `phase_active` | アクティブフェイズ | `active_phase` | `turn_phase_terms` | アクティブフェイズ | Active phase | 活动阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Normal phase subphase. |
| `phase_energy` | エネルギーフェイズ | `energy_phase` | `turn_phase_terms` | エネルギーフェイズ | Energy phase | 能量阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Normal phase subphase. |
| `phase_draw` | ドローフェイズ | `draw_phase` | `turn_phase_terms` | ドローフェイズ | Draw phase | 抽牌阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Normal phase subphase. |
| `phase_main` | メインフェイズ | `main_phase` | `turn_phase_terms` | メインフェイズ | Main phase | 主要阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Normal phase subphase. |
| `phase_live` | ライブフェイズ | `live_phase` | `turn_phase_terms` | ライブフェイズ | Live phase | Live 阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Shared Live phase after both normal phases. |
| `phase_live_card_set` | ライブカードセットフェイズ | `live_card_set_phase` | `turn_phase_terms` | ライブカードセットフェイズ | Live card set phase | Live 卡设置阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Live phase subphase. |
| `phase_first_performance` | 先攻パフォーマンスフェイズ | `first_player_performance_phase` | `turn_phase_terms` | 先攻パフォーマンスフェイズ | First-player performance phase | 先攻表演阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Live phase subphase. |
| `phase_second_performance` | 後攻パフォーマンスフェイズ | `second_player_performance_phase` | `turn_phase_terms` | 後攻パフォーマンスフェイズ | Second-player performance phase | 后攻表演阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Live phase subphase. |
| `phase_live_judgment` | ライブ勝敗判定フェイズ | `live_judgment_phase` | `turn_phase_terms` | ライブ勝敗判定フェイズ | Live judgment phase | Live 胜负判定阶段 | - | `rule_pdf_1_06` | `source_confirmed` | Live phase subphase. |
| `status_wait` | ウェイト | `wait` | `status_terms` | ウェイト | Wait | 等待 | - | `card_list` | `source_confirmed` | Confirmed in card text snippets. |
| `action_position_change` | ポジションチェンジ | `position_change` | `action_terms` | ポジションチェンジ | Position change | 位置变更 | - | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed in card text and indexed rule snippets. |
| `resource_blade` | ブレード | `blade` | `resource_terms` | ブレード | Blade | 应援棒 | ペンライト | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Blade/Penlight should be modeled as one project concept unless later source review proves a rule distinction. Blade is the Member Yell reveal count, not a Live score or Energy attribute. |
| `resource_blade_heart` | ブレードハート | `blade_heart` | `resource_terms` | ブレードハート | Blade Heart | Blade Heart | - | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Blade Heart is separate from Blade reveal count. It identifies Heart icons processed through Yell and may appear on Member or Live card data. |
| `resource_special_blade_heart` | 特別なブレードハート | `special_blade_heart` | `resource_terms` | 特別なブレードハート | Special Blade Heart | 特殊 Blade Heart | 特殊ハート | `quick_manual_mus`, `card_detail_html_review` | `source_confirmed` | Live-card-specific fixed effects activated when the card is revealed by Yell. Official card detail HTML labels the field `特殊ハート`. |
| `special_blade_heart_all` | ALLブレード | `all_color` | `resource_terms` | ALLブレード | All-color Blade Heart | 任意色 Blade Heart | ALL1 | `quick_manual_mus`, `card_detail_html_review` | `source_confirmed` | Treated as an arbitrary Heart color during Live success judgment. |
| `special_blade_heart_draw` | ドロー | `draw` | `resource_terms` | ドロー | Draw | 抽牌 | ドロー1 | `quick_manual_mus`, `card_detail_html_review` | `source_confirmed` | Resolves after all Yell processing has finished. |
| `special_blade_heart_score` | スコア | `score` | `resource_terms` | スコア | Score | 得分 | スコア1 | `quick_manual_mus`, `card_detail_html_review` | `source_confirmed` | Adds to the score total during Live win/loss judgment. |
| `resource_heart` | ハート | `heart` | `resource_terms` | ハート | Heart | 心 | 必要ハート | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Confirmed as card/rule attribute. |
| `heart_color_any` | 色を指定しないハートアイコン | `heart_any` | `resource_terms` | 任意色 | Any color | 任意颜色 | `heart0`, ALL1 | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Use source slot `heart0` only for Live required Heart or all-color Blade Heart icons. |
| `heart_color_pink` | 桃 | `heart_pink` | `resource_terms` | 桃 | Pink | 粉色 | `heart01` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart01`. |
| `heart_color_red` | 赤 | `heart_red` | `resource_terms` | 赤 | Red | 红色 | `heart02` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart02`. |
| `heart_color_yellow` | 黄 | `heart_yellow` | `resource_terms` | 黄 | Yellow | 黄色 | `heart03` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart03`. |
| `heart_color_green` | 緑 | `heart_green` | `resource_terms` | 緑 | Green | 绿色 | `heart04` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart04`, aligned to the ordered official color list. |
| `heart_color_blue` | 青 | `heart_blue` | `resource_terms` | 青 | Blue | 蓝色 | `heart05` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart05`, aligned to the ordered official color list. |
| `heart_color_purple` | 紫 | `heart_purple` | `resource_terms` | 紫 | Purple | 紫色 | `heart06` | `rule_pdf_1_06`, `card_detail_html_review` | `source_confirmed` | Official HTML source slot `heart06`. |
| `resource_score` | スコア | `score` | `resource_terms` | スコア | Score | 分数 | 合計スコア | `card_list`, `rule_pdf_1_06` | `source_confirmed` | Exact scoring process requires rule review. |

## Follow-Up Items

* Confirm exact comprehensive-rule wording for remaining zone aliases before UI display labels are finalized.
* Add deck construction terms such as main deck size, Live count, Member count, and Energy deck constraints only after direct official confirmation.

## Engineering Identity Mappings

These are stable architecture identifiers, not replacements for official Japanese terminology.

| identifier | meaning | source basis | decision status |
| --- | --- | --- | --- |
| `card_code` | Gameplay Card rule identity, excluding rarity and printing suffixes | cross-product card-list review | `architecture_frozen` |
| `card_id` | complete official Card Printing identifier | official card detail field `カード番号` | `architecture_frozen` |
| `card_instance_id` | runtime copy identity inside GameState | rule and replay architecture | `architecture_frozen` |
| `text_revision_id` | immutable revision of official Japanese card text | source audit and errata requirements | `architecture_frozen` |
| `card_set_code` | official card-list grouping such as `BP01` or `PR` | official card-list query structure | `architecture_frozen` |

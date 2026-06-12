# MVP Rule Subset Review

## Purpose

This artifact defines the source-reviewed planning baseline for the first Deck Analyzer MVP and Battle Simulator MVP rule subset.

It avoids storing bulk official rule text. Each row records source references and implementation-planning status only.

## Source Priority

1. `rule_qa`
2. `beginner_guide`
3. `card_list`
4. `deck_recipe`

See [source-review-status.md](source-review-status.md) for current source access notes.

## MVP Rule Candidates

The `official wording reference` column points to official Japanese sources by source ID. It deliberately does not copy bulk official rule text into this repository.

| rule_id | MVP area | official wording reference | normalized term mappings | impacted specs | simulator support status | decision | unresolved questions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mvp_deck_legality_basic` | deck legality basics | `rule_pdf_1_06`, `loveca_point_system`, `card_list` | `zone_deck`, `card_type_member`, `card_type_live`, `zone_energy_deck`, `card_type_energy` | `000`, `001`, `002`, `011`, `016` | `structural_executable_after_rule_confirmation` | In MVP, validate exact main deck counts, Energy deck count, same-card-number copy limit, and Loveca point total. | Replacement effects that alter construction remain out of MVP unless explicitly reviewed. |
| `mvp_match_setup` | match setup | `rule_pdf_1_06` | `zone_deck`, `zone_energy_deck`, `zone_hand` | `002`, `003`, `011`, `012` | `structural_executable_after_rule_confirmation` | Include source-confirmed setup structure: deck placement, main deck shuffle, opening hand, mulligan, and initial Energy area setup. | Starting-player selection procedure and any alternate-format setup remain to be reviewed. |
| `mvp_opening_hand` | opening hand | `rule_pdf_1_06` | `zone_hand`, `zone_deck` | `002`, `003`, `008`, `011` | `structural_executable_after_rule_confirmation` | Include opening hand size of 6 from the main deck. | Hidden-information logging format must be decided before replay implementation. |
| `mvp_mulligan` | mulligan | `rule_pdf_1_06` | `zone_hand`, `zone_deck` | `002`, `003`, `008`, `010`, `011` | `structural_executable_after_rule_confirmation` | Include deterministic mulligan support: choose any number from hand, set aside, draw the same number, return set-aside cards to deck, and shuffle if cards were moved. | Exact action names and UI prompt wording remain future implementation details. |
| `mvp_turn_progression` | turn progression | `rule_pdf_1_06` | `turn_phase_terms` | `002`, `003`, `005`, `011`, `012`, `016` | `structural_executable_after_rule_confirmation` | Include explicit phase transitions as Actions using confirmed phase order: first normal phase, second normal phase, then Live phase. | Priority/action-window details inside phases remain out of MVP unless needed for basic play. |
| `mvp_draw` | drawing | `beginner_guide`, `rule_qa` | `zone_deck`, `zone_hand` | `002`, `003`, `005`, `008`, `011` | `structural_executable_after_rule_confirmation` | Include draw as structural automated process. | Deck exhaustion/recycle behavior needs rule confirmation before automation. |
| `mvp_play_member` | playing Members | `beginner_guide`, `card_list`, `rule_qa` | `card_type_member`, `zone_stage`, `card_type_energy`, `action_enter_play` | `002`, `003`, `005`, `011`, `012`, `016` | `structural_executable_after_rule_confirmation` | Include basic Member play with cost and stage placement. | Baton/pass/replacement edge cases are out of MVP unless confirmed and simple. |
| `mvp_play_live` | playing Lives | `rule_pdf_1_06`, `card_list` | `card_type_live`, `timing_live_start`, `zone_success_live_area` | `002`, `003`, `005`, `011`, `012`, `016` | `structural_executable_after_rule_confirmation` | Include basic Live card set and performance flow confirmed by the official Live phase structure. | Exact maximum Live set count and non-Live set behavior should be captured in simulator spec before implementation. |
| `mvp_energy_payment` | basic Energy payment | `rule_pdf_1_06`, `card_list` | `card_type_energy`, `zone_energy_deck` | `002`, `003`, `005`, `011`, `015`, `016` | `structural_executable_after_rule_confirmation` | Include basic structural payment/readiness: Energy cards are used as one-card payment units, and active Energy changes to Wait when paid. | Exact Ready/Active naming normalization should be finalized in `016`. |
| `mvp_live_success_check` | basic Live success | `rule_pdf_1_06`, `quick_manual_mus`, `card_list` | `resource_heart`, `resource_blade`, `resource_blade_heart`, `resource_special_blade_heart`, `timing_live_start`, `timing_live_success` | `002`, `003`, `005`, `011`, `015`, `016` | `structural_executable_after_rule_confirmation` | Include source-confirmed separation of Member Blade reveal count, normal Blade Heart icons, special Blade Heart effects, owned Hearts, required Heart by color, and Live score. The fixed ALL, Draw, and Score special Blade Hearts are part of structural Live processing rather than free-form Effect DSL. | Exact edge cases for simultaneous multiple Live requirements, multiple special Blade Hearts, and FAQ-sensitive interactions remain out of MVP. |
| `mvp_score_victory` | score/victory tracking | `beginner_guide`, `card_list`, `rule_qa`, `rule_pdf_1_06` | `resource_score`, `zone_success_live_area` | `002`, `003`, `005`, `011`, `016` | `structural_executable_after_rule_confirmation` | Include victory tracking for source-confirmed normal game threshold only. | Normal vs simplified/half-deck victory thresholds must be separated. |
| `mvp_zone_movement` | zone movement | `rule_pdf_1_06`, `card_list` | `zone_deck`, `zone_energy_deck`, `zone_hand`, `zone_stage`, `zone_waiting_room`, `zone_success_live_area` | `002`, `003`, `005`, `008`, `011`, `016` | `structural_executable_after_rule_confirmation` | Include basic zone movement through Actions for Deck, Energy Deck, Hand, Stage, Live Area, Waiting Room, Success Live Area, Energy Area, and Resolution Area where needed by MVP Live flow. | Exact public UI names for secondary zones remain terminology-normalization work. |

## Explicitly Out of MVP

| out_of_scope_id | area | reason | future owner |
| --- | --- | --- | --- |
| `oom_full_effect_automation` | full semantic effect automation | Requires reviewed Effect DSL coverage. | `007`, `015` |
| `oom_replacement_effects` | replacement effects | Complex timing and event substitution require rules review. | `002`, `007`, `015` |
| `oom_continuous_effects` | continuous effects | Requires state invariant and duration model. | `002`, `007`, `015` |
| `oom_faq_sensitive_interactions` | FAQ-sensitive interactions | Requires Q&A/ruling review. | `002`, `015` |
| `oom_opponent_choice_effects` | opponent-choice effects | Requires controller choice protocol. | `012`, `015` |
| `oom_online_multiplayer` | online multiplayer behavior | Future architecture only. | `003`, `008`, `012`, future online specs |

## Acceptance Checklist

* Deck Analyzer and Battle Simulator use the same terminology IDs.
* Each implemented MVP rule links to source-confirmed terminology.
* Each automated simulator rule has a source reference and unresolved-question check.
* Each unsupported or ambiguous rule is explicitly marked out of MVP or requiring review.
* Public artifacts avoid bulk official text.

# Effect Modeling and Taxonomy

## 1. Purpose

This document defines the architecture strategy for semantic card effect modeling.

It applies to both first-class products:

* Deck Analyzer
* Battle Simulator

Both products must share the same underlying card database, domain model, rule model, effect model, validation logic, randomness model, and replay-friendly action model.

This document does not define database schema, API contracts, implementation classes, scraper behavior, UI behavior, or executable effect code.

## 2. Problem Statement

Card data contains two different kinds of information.

### Numeric and Structural Card Data

Numeric and structural card data includes:

* card type
* cost
* Heart
* Blade
* Live required Heart
* score
* basic Live success and score calculation

This data is mostly deterministic and mathematical. It can often be modeled directly and used by validation, deck analysis, and simulator rules.

### Semantic Card Effects

Semantic card effects include text-driven behavior such as:

* drawing cards
* searching the deck
* recovering from Waiting Room
* gaining Blade
* gaining Heart
* modifying score
* readying Energy
* changing position
* applying Wait
* triggering on Live start
* triggering on Live success
* conditional effects
* optional effects
* continuous effects
* replacement effects

These effects cannot remain plain text forever because the analyzer, simulator, and AI need semantic understanding. However, the project should not attempt to fully automate every semantic effect in the first MVP.

The correct strategy is layered modeling.

## 3. Required Layered Effect Model

Card effects must be modeled in four separate layers.

### Layer 1: raw_effect_text

The canonical Japanese official effect text.

Purpose:

* preserve the official source record
* support display and manual resolution
* provide auditability for parsing and review
* avoid losing nuance before structured modeling is reliable

This layer is always required when official effect text exists.

### Layer 2: effect_tags

Human-reviewed or parser-suggested semantic tags.

Examples:

* draw
* search
* live_support
* energy
* waiting_room
* score_modifier
* position

Purpose:

* support deck analysis before full automation
* support Simple AI heuristics
* support search and filtering
* identify cards that need manual review

Effect tags are not executable rules.

### Layer 3: Structured Effect DSL

A machine-readable representation of effect semantics.

Purpose:

* prepare for automated simulation
* make triggers, conditions, costs, choices, targets, actions, and durations explicit
* support review workflows
* avoid hard-coding individual card behavior into the engine

The DSL is interpreted data. It must remain traceable to raw Japanese effect text.

### Layer 4: Executable Effect Implementation

Validated engine behavior that can automatically resolve an effect or part of an effect.

Purpose:

* automate simulator behavior where reliable
* support AI and replay
* support future online authoritative validation

Executable behavior should only be trusted after validation and review. It should never replace the raw Japanese official text.

## 4. Simulation Support Status

Every card effect must have a simulation support status.

### unsupported

Only raw official text is stored.

The effect is not usable by analyzer or simulator beyond display.

### tagged_only

The effect has semantic tags but no executable DSL.

Deck Analyzer may use the tags for search, summaries, or heuristic scoring. Battle Simulator should not auto-resolve the effect.

### manual_resolution

The simulator can display the raw Japanese effect text and ask the player to resolve it manually.

This is acceptable for the MVP, especially for complex or uncommon effects.

### partially_executable

Some parts of the effect can be executed automatically, but some choices, conditions, or steps require manual handling.

The engine must make the automatic and manual boundaries explicit.

### fully_executable

The effect can be executed automatically by the engine.

This status means the engine can resolve the effect under supported assumptions, but it does not necessarily mean the effect has received manual review.

### test_validated_executable

The effect can be executed automatically and is covered by automated rule-test validation.

This status is stronger than `fully_executable`, but it is not the same as human-reviewed behavior.

### reviewed_executable

The effect can be executed automatically and has been manually reviewed.

This is the highest-confidence status. It should be preferred for competitive simulation, regression tests, and future online authoritative behavior.

## 5. Effect Instance Concept

An effect instance represents one modeled effect on one card.

Conceptual fields include:

* effect_id
* card_code
* text_revision_id
* effect_index
* raw_text
* effect_type
* timing
* frequency_limit
* is_optional
* cost
* condition
* choice
* target
* actions
* duration
* modifier
* source_zone
* affected_zone
* simulation_support
* parse_confidence
* review_status
* parser_version
* raw_text_hash

These are conceptual fields for future specifications. They are not a database schema or implementation class.

## 6. Effect Types

The first structured model should support approximately six effect types.

### triggered

An effect that triggers from a game event.

Examples:

* when this Member enters play
* when a Live starts
* when a Live succeeds

### activated

An effect the player chooses to activate, usually during a valid timing window.

Activated effects may include cost payment.

### continuous

An effect that continuously modifies state while its condition is true.

Continuous effects require careful duration and state-invariant handling.

### replacement

An effect that replaces or modifies another event or rule process.

Replacement effects may be complex and can remain manual in the MVP.

### static

A non-triggered rule-like ability that defines a property, restriction, or standing modifier.

### manual

An effect intentionally not executable yet.

The simulator displays the raw Japanese text and requires manual handling.

## 7. Timing Types

The first structured model should support approximately six timing categories.

### on_play

Triggered when a card, usually a Member, is played or enters the relevant zone.

### activated_main

Activated manually during a main or action timing window.

### auto_event

Triggered by a broader event such as card movement, phase change, or another game event.

### live_start

Triggered when a Live starts.

### live_success

Triggered when a Live succeeds.

### always

Continuous or static effects that are active while their conditions are true.

## 8. Action Categories

The first structured model should support approximately fourteen action categories.

### draw_card

Draw one or more cards from deck to hand.

### look_at_top_cards

Look at a number of cards from the top of the deck.

This usually requires private information handling and player choice.

### select_card_to_hand

Select a card matching a filter and add it to hand.

This may come from deck, revealed cards, or another zone.

### discard_from_hand

Move a card from hand to Waiting Room or another discard-like zone.

### move_card

Generic zone movement.

This should be used carefully with source, destination, visibility, and ordering rules.

### ready_energy

Change Energy from inactive or rested state to active or ready state.

### pay_energy

Pay Energy as a cost.

### position_change

Move or swap Member position on stage according to game rules.

### apply_wait

Apply Wait state to a Member.

### gain_blade

Modify Blade value temporarily or persistently according to effect duration.

### gain_heart

Modify Heart contribution temporarily or persistently according to effect duration.

### modify_score

Modify Live score or successful Live score calculation.

### return_from_waiting_room

Move a card from Waiting Room to hand, deck, stage, or another zone.

### stack_deck

Put cards on top or bottom of deck in a specified or chosen order.

## 9. Condition Categories

The first structured model should support approximately eight condition categories.

### zone_contains

A condition checking whether a zone contains cards matching a filter.

Examples:

* stage contains a specific character
* Waiting Room contains a specific group

### card_attribute_match

A condition checking card metadata.

Examples:

* group is Liella!
* card type is Member
* character is a specific idol

### cost_threshold

A condition checking whether cost total or individual cost satisfies a threshold.

### count_threshold

A condition checking the number of cards, Members, Lives, or revealed cards.

### score_threshold

A condition checking score total, successful Live score total, or Live-related score.

### this_turn_event

A condition depending on events that happened this turn.

Examples:

* a Member entered stage this turn
* a card moved this turn

### revealed_card_condition

A condition based on currently revealed cards.

Examples:

* revealed by Yell or Live process
* revealed from deck top
* revealed hand condition

### opponent_state_condition

A condition based on opponent board, zones, or successful Lives.

## 10. Conceptual DSL Flow

The future Effect DSL should follow this conceptual flow:

```text
Trigger -> Condition -> Cost -> Choice -> Target -> Action -> Duration
```

This flow is a modeling principle, not an execution implementation.

The model should support:

* triggers based on events and timing
* conditions based on game state or recent events
* costs that are paid before resolution when required
* choices made by players or controllers
* targets selected under legality constraints
* actions resolved through the rule engine
* durations for temporary or continuous modifiers

`card_code` identifies the Gameplay Card. `text_revision_id` and `raw_text_hash` identify the exact official Japanese text being interpreted. Printing `card_id` must not own effect interpretations.

## 11. Conceptual Example

The following example illustrates the intended shape of a future structured effect record.

It is not a final schema, API definition, or implementation contract.

```json
{
  "effect_id": "effect_1",
  "card_code": "example_card",
  "text_revision_id": "example_card_text_r1",
  "effect_index": 1,
  "raw_text": "このメンバーが登場した時、カードを1枚引く。",
  "effect_type": "triggered",
  "timing": "on_play",
  "frequency_limit": "none",
  "is_optional": false,
  "trigger": {
    "event": "member_played",
    "source": "self"
  },
  "condition": {},
  "cost": [],
  "choice": null,
  "target": null,
  "actions": [
    {
      "type": "draw_card",
      "player": "controller",
      "amount": 1
    }
  ],
  "duration": null,
  "modifier": null,
  "source_zone": "stage",
  "affected_zone": "hand",
  "simulation_support": "fully_executable",
  "parse_confidence": 0.95,
  "review_status": "unreviewed",
  "parser_version": "effect-parser-v0",
  "raw_text_hash": "hash"
}
```

## 12. Analyzer Usage

Deck Analyzer may use:

* numeric and structural card data
* effect tags
* simulation support status
* reviewed structured effects when available

Deck Analyzer should not assume that raw text alone is executable.

Analyzer outputs should distinguish:

* confirmed structural facts
* tag-based heuristics
* modeled effects
* unsupported or manual effects

This is necessary so consistency scoring and improvement suggestions do not overstate confidence.

## 13. Simulator Usage

Battle Simulator may use:

* numeric and structural card data directly where rules are supported
* raw Japanese text for manual resolution
* structured DSL for partially or fully executable effects
* reviewed executable effects for high-confidence automation

The simulator should not auto-resolve effects with `unsupported`, `tagged_only`, or `manual_resolution` support status.

Manual resolution is acceptable for MVP, but the simulator must record the result as structured `ManualAdjustmentAction` records. Note-only annotations are not replay-safe, and manual resolution must not mutate GameState directly.

## 14. AI Usage

Simple AI may use effect tags as heuristic hints.

Examples:

* prefer cards tagged as draw when hand size is low
* prefer live_support when attempting a Live
* prefer energy-related effects when resources are constrained

Simple AI must not assume tagged effects are executable. It must choose from legal actions generated by the rule engine and must not bypass validation.

Future AI may use structured and reviewed executable effects more deeply.

## 15. Review and Confidence

Effect modeling should track confidence and review state.

Important concepts:

* parse_confidence
* review_status
* parser_version
* raw_text_hash
* simulation_support

These concepts help answer:

* Was this effect parser-generated or manually reviewed?
* Does the modeled text still match the official raw text?
* Is this effect safe to automate?
* Can simulator behavior be trusted for this card?

Initial review roles:

* `parser`
* `contributor`
* `reviewer`
* `rules_reviewer`
* `maintainer`

Initial review states:

* `unparsed`
* `parsed_draft`
* `schema_validated`
* `test_validated`
* `human_reviewed`
* `rules_reviewed`
* `approved`
* `deprecated`

Complex timing, replacement effects, continuous effects, opponent choice, and FAQ/ruling-sensitive behavior require `rules_reviewer` review before `reviewed_executable`. Maintainer approval is required for public release or official recommended executable card pools.

LLM-assisted parsing may be used to generate draft tags or Effect DSL records, but LLM output is not authoritative. A card effect must not become `reviewed_executable` without human review. Automated rule-test validation alone may support `test_validated_executable`, but it is not enough for reviewed status.

Recommended pipeline:

```text
Official raw text
-> Card Text Revision
-> LLM-assisted draft parse
-> effect_tags
-> Effect DSL draft
-> schema validation
-> rule validation
-> test_validated_executable, when automated rule tests cover behavior
-> manual review
-> reviewed executable effect
```

## 16. MVP Boundary

The MVP should not require full automatic effect execution.

Acceptable MVP behavior:

* structural rules execute normally
* basic Live success is supported
* effect tags support analyzer and Simple AI heuristics
* raw Japanese text is displayed for unsupported or manual effects
* players can manually resolve complex effects
* logs record when manual resolution was required
* AI vs AI debug runs choose an explicit policy for manual effects

Not required for MVP:

* complete DSL coverage
* fully automated semantic effect execution
* reviewed executable status for every card
* replacement effect automation
* automatic handling of every optional or conditional effect

## 17. Anti-Patterns to Avoid

Avoid:

* treating raw effect text as the only model forever
* treating tags as executable rules
* auto-resolving unreviewed complex effects without support status
* hard-coding individual card IDs into the rule engine
* mixing parser output with trusted reviewed behavior
* hiding manual resolution from action logs
* allowing AI to use effect assumptions that the simulator cannot validate

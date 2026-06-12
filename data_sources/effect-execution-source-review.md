# Effect Execution MVP Source Review

## Purpose

This artifact records the official-rule basis for the first executable-effect slice. It contains references and conclusions, not bulk official rule or card text.

Canonical source:

* `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`
* Official comprehensive rules version 1.06, dated 2026-04-28
* Official Japanese card text stored through Card Text Revision

## Confirmed Timing Rules

| concept | official references | implementation conclusion |
| --- | --- | --- |
| Ability types | 9.1.1-9.1.1.2 | Activated and automatic abilities are distinct. Automatic abilities enter a waiting state when their event occurs. |
| Main Phase activation | 7.7.2, 7.7.2.1, 9.5.2 | The turn player may play an activated ability during Main Phase play timing. |
| Cost before resolution | 9.6.2 | Costs are validated and paid before the ability effect resolves. |
| Waiting automatic abilities | 9.5.3, 9.7.2-9.7.3 | Waiting automatic abilities are resolved through check timing. When several are waiting for one master, that player chooses their order. |
| Source moved before resolution | 9.6.2.4.2 | An ability still resolves if its source card has left its former zone after the ability was played. |
| `登場` | 11.4.1-11.4.2 | The trigger occurs when the Member moves into a Member Area from outside the Member Area. |
| `ライブ開始時` | 8.3.6-8.3.9, 11.5.1-11.5.2.1 | It occurs separately during the current player's Performance, after Live cards are revealed and only when at least one Live card remains. |
| Baton Touch event | 9.6.2.3.2.1 | Performing the cost reduction creates a `バトンタッチした` event that may trigger automatic abilities. |
| Once per turn | 11.2.1-11.2.2 | The same ability cannot be played again in the same turn after it has been played once. |

## Initial Card Decisions

| card code | effect | support | notes |
| --- | --- | --- | --- |
| `LL-bp1-001` | `登場` Member recovery | `test_validated_executable` | Requires one legal Member choice from the owner's Waiting Room. |
| `LL-bp1-001` | Live-start hand cost and score increase | `manual_resolution` | Combined named-card cost remains outside the restricted executor. |
| `PL!-bp3-001` | Main Phase activated draw/discard | `test_validated_executable` | Source Wait is paid first; draw occurs before the discard choice. |
| `PL!-bp3-001` | Live-start ready one Member | `test_validated_executable` | Optional and limited to a waiting Member on the owner's Stage. |
| `PL!N-bp1-001` | Live-start Energy payment and Blade gain | `test_validated_executable` | Optional; one Active Energy is paid and the modifier lasts through that Live. |
| `PL!HS-sd1-001` | Baton Touch automatic Energy ready | `test_validated_executable` | Trigger condition checks the replacement Member's cost and `蓮ノ空` Work association. |

## Deferred Rules

The following remain outside this MVP:

* continuous and replacement effects
* opponent-controlled targets
* effect-generated Member play
* arbitrary top-deck inspection and reordering
* simultaneous effects owned by different players beyond the current deterministic player boundary
* FAQ-sensitive interactions

## Stage Attachment And Movement Review

Official comprehensive rules 4.5.5, 10.5.3-10.5.5, 11.10, and 11.11
confirm the Stage model used by the rule debugger:

* Member and Energy cards may be placed under a top Member.
* Cards under a Member have no Active or Wait orientation.
* A top Member moving between Member Areas carries its attached cards.
* A top Member leaving the Stage causes attached Members to enter Waiting
  Room and attached Energy to return to the Energy Deck.
* Position Change swaps complete Member groups when the destination is
  occupied.
* Formation Change reassigns all current Stage Member groups atomically.

Representative official card and FAQ observations:

| card code | observed requirement |
| --- | --- |
| `PL!HS-pb1-002` | Multiple Member cards may accumulate under one Member and be counted individually. |
| `PL!-bp6-003` | A Member card may move from hand to under a Member and later enter an empty Member Area. |
| `PL!N-pb1-011` | Energy under a Member contributes to a continuous effect but is not available as Energy payment. |
| `PL!N-bp3-007` | A top Member may leave as an ability cost before another Member enters the same area and receives attached Energy. |
| `PL!HS-pb1-006` | Position Change swaps with a Member already in the destination area. |
| `PL!SP-sd2-001` | Formation Change permits a full Stage rearrangement with one Member per area. |

The Stage foundation does not automatically execute attachment-related card
effects. A dedicated card-by-card review remains required before registry
entries may attach a Member from hand or move a Member from under another
Member into a top Stage position.

## Review Status

The rule timing above is source-confirmed. Automated effect entries remain `test_validated_executable` until a human card-by-card rules review promotes them.

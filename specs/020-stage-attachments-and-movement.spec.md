# 020 Stage Attachments And Movement Specification

## 1. Purpose

This specification defines the replay-safe representation of cards under a
Member and movement between Member Areas.

It does not add executable card effects or change the card database schema.

## 2. Stage Representation

Each player retains three top-Member slots: left, center, and right.

Each slot also owns an ordered serialization collection of attached card
instance IDs. The collection order is deterministic storage only and has no
rules meaning.

Only Member and Energy cards may be attached. Attachments require a top
Member in the same slot and cannot simultaneously exist in another zone.

## 3. Attached Card Rules

Attached cards are not top Members and are not legal Stage Member targets
unless an effect explicitly refers to cards under a Member.

Attached Energy:

* is not in the Energy Area
* does not count toward Energy totals
* cannot pay costs
* has no Active or Wait orientation while attached

Attached Members do not contribute their Heart, Blade, position keywords, or
abilities as top Stage Members.

## 4. Movement And Departure

A top Member moving to another Member Area carries every attached card.

Position Change moves to an empty area or swaps two complete Member groups
when the destination is occupied.

Formation Change atomically assigns every current top Member group to a
unique Member Area.

When a top Member leaves the Stage:

* attached Members move to Waiting Room
* attached Energy returns to the Energy Deck
* the complete cleanup is recorded in the same Action transaction

## 5. Manual Action Boundary

The initial structured adjustment operations are:

* `attach_card_under_member`
* `move_attached_card`
* `position_change`
* `formation_change`

Generic `move_card` must reject attached cards. UI code must not directly
edit attachment collections.

Attachment-related card effects are not automatically executable in this
slice. Their trigger consequences require card-by-card review before registry
entries may use these operations.

## 6. Replay And Compatibility

Attachment fields must be serializable and deterministic. Existing runtime
v2 snapshots without the field load with empty attachment collections.

No runtime SQLite schema change is required because snapshots already store
versioned GameState JSON.

## 7. Dependencies

Depends on:

* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)

# Hasunosora Online Fix Regression Notes

Deck file:

- `data_samples/decks/hasunosora-online-fix-regression.decklist.v0.json`

Recommended use:

- Use this deck for both players in local or online room testing.
- It is legal: 48 Member + 12 Live + 12 Energy.
- The Energy Deck intentionally uses 12 copies of `LL-E-001` to exercise the rule that Energy cards are not limited by the normal 4-copy rule.

## Checks Covered

### 1. `PL!HS-bp2-026` みらくりえーしょん

Set the stage as:

- Left: `安養寺 姫芽`
- Center: `藤島 慈`
- Right: `大沢瑠璃乃`

Then set `PL!HS-bp2-026` as the Live card.

Expected:

- At Live start, the Live score modifier should apply.
- The card's score should be counted as base score 5 + effect score 2.

### 2. `PL!HS-sd1-005` 徒町小鈴 Baton condition

Positive case:

- Baton Touch from a non-`徒町小鈴` Hasunosora Member such as `村野さやか` or `夕霧綴理` into `PL!HS-sd1-005`.

Expected:

- `PL!HS-sd1-005` on-play effect can trigger.

Negative case:

- Baton Touch from another `徒町小鈴` into `PL!HS-sd1-005`.

Expected:

- The `PL!HS-sd1-005` effect should not trigger.

### 3. Face-down Live privacy in online play

During Live Card Phase:

- Player 1 sets a Live card.
- Check Player 2's view before reveal.

Expected:

- Player 2 should not see the face of Player 1's set Live card before it is revealed.

### 4. Opponent Waiting Room visibility

Open the opponent area on mobile or online view.

Expected:

- Opponent Waiting Room can be inspected, because it is a public zone.

### 5. One-sided match point tie

Use manual adjustment if needed:

- Put one player at 2 / 3 successful Lives.
- Make the next Live judgment a tied total score.

Expected:

- Only the player who was not already at match point gains a successful Live.
- The match-point player should not gain the third successful Live from that tied judgment.

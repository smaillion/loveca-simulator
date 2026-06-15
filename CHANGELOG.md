# Changelog

## v0.4.0-alpha.3 - 2026-06-15

### Added

- Added a formal effect semantics audit document for future skill execution work.
- Added a broader effect registry MVP covering structured prompts, inspection choices, and Energy Deck placement effects.
- Added Deck Builder catalog filters for work, unit, Heart color, Blade, Live required Heart, score, and Blade Heart fields.
- Added Deck Builder analysis summaries for effect timing and execution mode coverage.
- Added local Deck Builder card preview support with selectable printings in the detail dialog.

### Changed

- Refined Deck Builder layout with separate Member, Live, and Energy deck sections.
- Redesigned Deck Builder status and analysis panels as responsive dashboard cards.
- Restored a larger scroll area for Deck Builder search results while keeping pagination.
- Improved Deck Builder readability by removing always-visible deck thumbnails and replacing numeric distributions with labeled chips.
- Normalized card business identifiers so fullwidth `＋` is imported and stored as ASCII `+`.
- Improved official importer resilience when running from an installed checkout.
- Refined Python code style with Ruff and removed generated Python cache directories from the workspace.

### Fixed

- Fixed Deck Builder filters that were visible but not applied to the catalog query.
- Fixed Energy card copy limit handling so Energy cards are not limited by the 4-copy rule.
- Fixed local card images falling back incorrectly in match/deck contexts.
- Fixed several layout overflow issues in Japanese UI text.
- Fixed missing card visibility for card IDs that differ only by `+` suffix normalization.

### Known Limitations

- Full-card effect automation is still incomplete.
- Manual resolution remains required for unsupported or ambiguous card effects.
- Online multiplayer, AI, Monte Carlo, and win-rate simulation are still out of scope.


// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { getPreviewCatalogCard, listPreviewCatalogCards } from "./browser-preview-api";
import {
  analyzePreviewDeck,
  getPreviewSavedDeck,
  listPreviewSavedDecks,
} from "./browser-preview-decks";
import type { CardType, CatalogCardDetail, CatalogCardSummary, DeckList } from "./types";

vi.mock("./browser-preview-api", () => ({
  getPreviewCatalogCard: vi.fn(),
  listPreviewCatalogCards: vi.fn(),
}));

const STORAGE_KEY = "loveca-browser-deck-library.v0";

const { catalogCards, catalogDetails } = createPreviewCatalogFixture();

describe("browser preview sample decks", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(listPreviewCatalogCards).mockResolvedValue({
      items: catalogCards,
      total: catalogCards.length,
      limit: 100_000,
      offset: 0,
    });
    vi.mocked(getPreviewCatalogCard).mockImplementation((cardCode) => {
      const detail = catalogDetails.get(cardCode);
      if (!detail) throw new Error(`missing fixture card: ${cardCode}`);
      return Promise.resolve(detail);
    });
  });

  it("seeds exactly 5 legal preview sample decks into fresh localStorage", async () => {
    const savedDecks = await listPreviewSavedDecks();

    expect(savedDecks).toHaveLength(5);
    expect(savedDecks.map((deck) => deck.path)).toEqual([
      "preview-sample-01.json",
      "preview-sample-02.json",
      "preview-sample-03.json",
      "preview-sample-04.json",
      "preview-sample-05.json",
    ]);

    for (const summary of savedDecks) {
      const deck = await getPreviewSavedDeck(summary.path);
      const analysis = await analyzePreviewDeck(deck);

      expect(analysis.is_legal).toBe(true);
      expect(analysis.card_type_counts.main_deck.member).toBe(48);
      expect(analysis.card_type_counts.main_deck.live).toBe(12);
      expect(analysis.card_type_counts.energy_deck.energy).toBe(12);
      expect(Object.values(analysis.copy_counts).every((quantity) => quantity <= 4)).toBe(true);
    }
  });

  it("deduplicates multiple printings by card_code before building samples", async () => {
    await listPreviewSavedDecks();
    const deck = await getPreviewSavedDeck("preview-sample-01.json");

    expect(deck.main_deck).toHaveLength(15);
    expect(new Set(deck.main_deck.map((entry) => entry.card_code)).size).toBe(15);
    const analysis = await analyzePreviewDeck(deck);
    expect(analysis.issues.some((issue) => issue.code === "copy_limit")).toBe(false);
  });

  it("replaces stale generated samples while preserving user-created decks", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: STORAGE_KEY,
        seeded_preview_decks: true,
        decks: [
          {
            path: "preview-sample-01.json",
            deck: illegalOldSampleDeck(),
            updated_at: "2026-01-01T00:00:00.000Z",
          },
          {
            path: "my-imported-deck.json",
            deck: legalUserDeck(),
            updated_at: "2026-01-02T00:00:00.000Z",
          },
        ],
      }),
    );

    const savedDecks = await listPreviewSavedDecks();
    const sampleDecks = savedDecks.filter((deck) => /^preview-sample-\d+\.json$/.test(deck.path));

    expect(sampleDecks).toHaveLength(5);
    expect(savedDecks.some((deck) => deck.path === "my-imported-deck.json")).toBe(true);

    const migratedSample = await getPreviewSavedDeck("preview-sample-01.json");
    const migratedAnalysis = await analyzePreviewDeck(migratedSample);
    expect(migratedAnalysis.is_legal).toBe(true);

    const userDeck = await getPreviewSavedDeck("my-imported-deck.json");
    expect(userDeck.name).toBe("User Imported Deck");
    expect(userDeck).toEqual(legalUserDeck());
  });
});

function createPreviewCatalogFixture(): {
  catalogCards: CatalogCardSummary[];
  catalogDetails: Map<string, CatalogCardDetail>;
} {
  const uniqueCards = [
    ...Array.from({ length: 12 }, (_, index) => summaryCard("member", `M${String(index + 1).padStart(3, "0")}`)),
    ...Array.from({ length: 3 }, (_, index) => summaryCard("live", `L${String(index + 1).padStart(3, "0")}`)),
    summaryCard("energy", "E001"),
  ];
  const duplicatePrintings = [
    summaryCard("member", "M001", "BP99"),
    summaryCard("member", "M002", "BP99"),
    summaryCard("member", "M003", "BP99"),
    summaryCard("live", "L001", "BP99"),
  ];
  return {
    catalogCards: [...uniqueCards, ...duplicatePrintings],
    catalogDetails: new Map(uniqueCards.map((card) => [card.card_code, detailCard(card)])),
  };
}

function summaryCard(cardType: CardType, cardCode: string, setCode = "BP01"): CatalogCardSummary {
  return {
    gameplay_card_id: Number(cardCode.replace(/\D/g, "")),
    card_code: cardCode,
    name_ja: `${cardCode} Name`,
    card_type: cardType,
    validation_status: "validated",
    card_id: `${setCode}-${cardCode}`,
    card_set_code: setCode,
    rarity_ja: null,
    image_url: null,
    cost: cardType === "member" ? 1 : null,
    blade: cardType === "member" ? 1 : null,
    member_blade_heart_color_slot: null,
    score: cardType === "live" ? 1 : null,
    live_blade_heart_color_slot: null,
    basic_heart_by_color: cardType === "member" ? { heart01: 1 } : {},
    basic_heart_total: cardType === "member" ? 1 : 0,
    required_heart_by_color: cardType === "live" ? { heart01: 1 } : {},
    required_heart_total: cardType === "live" ? 1 : 0,
    has_live_blade_heart: false,
    printing_count: 1,
    revision_count: 0,
    observation_count: 0,
    pending_candidate_count: 0,
    unresolved_reference_count: 0,
    review_issue_count: 0,
  };
}

function detailCard(summary: CatalogCardSummary): CatalogCardDetail {
  return {
    card: {
      gameplay_card_id: summary.gameplay_card_id,
      card_code: summary.card_code,
      name_ja: summary.name_ja,
      card_type: summary.card_type,
      validation_status: summary.validation_status,
      cost: summary.cost,
      blade: summary.blade,
      member_blade_heart_color_slot: summary.member_blade_heart_color_slot,
      score: summary.score,
      live_blade_heart_color_slot: summary.live_blade_heart_color_slot,
      heart_values: {
        basic: summary.basic_heart_by_color,
        required: summary.required_heart_by_color,
      },
      special_blade_hearts: [],
      works: [],
      units: [],
      review_candidates: [],
      printing_references: [],
      effect_registry_status: "supported",
      effect_registry_errors: [],
      effects: [],
    },
    printings: [
      {
        card_id: summary.card_id ?? summary.card_code,
        card_set_code: summary.card_set_code ?? "BP01",
        rarity_ja: null,
        image_url: null,
        source_url: null,
        fetched_at: null,
        parser_version: null,
        raw_product_label_ja: null,
        language: null,
        raw_fields: null,
        parse_notes: null,
      },
    ],
    source_observations: [],
    text_revisions: [],
  };
}

function illegalOldSampleDeck(): DeckList {
  return {
    version: "decklist.v0",
    name: "Illegal Old Sample",
    main_deck: [{ card_code: "M001", quantity: 60, preferred_printing_id: "BP01-M001" }],
    energy_deck: [{ card_code: "E001", quantity: 12, preferred_printing_id: "BP01-E001" }],
  };
}

function legalUserDeck(): DeckList {
  return {
    version: "decklist.v0",
    name: "User Imported Deck",
    main_deck: [
      ...Array.from({ length: 12 }, (_, index) => ({
        card_code: `M${String(index + 1).padStart(3, "0")}`,
        quantity: 4,
        preferred_printing_id: `BP01-M${String(index + 1).padStart(3, "0")}`,
      })),
      ...Array.from({ length: 3 }, (_, index) => ({
        card_code: `L${String(index + 1).padStart(3, "0")}`,
        quantity: 4,
        preferred_printing_id: `BP01-L${String(index + 1).padStart(3, "0")}`,
      })),
    ],
    energy_deck: [{ card_code: "E001", quantity: 12, preferred_printing_id: "BP01-E001" }],
  };
}

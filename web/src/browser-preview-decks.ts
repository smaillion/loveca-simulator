import { getPreviewCatalogCard } from "./browser-preview-api";
import type {
  CatalogCardDetail,
  DeckAnalysisResponse,
  DeckEntry,
  DeckList,
  SavedDeckResponse,
  SavedDeckSummary,
} from "./types";

const STORAGE_KEY = "loveca-browser-deck-library.v0";

interface StoredDeckRecord {
  path: string;
  deck: DeckList;
  updated_at: string;
}

interface StoredDeckLibrary {
  version: "loveca-browser-deck-library.v0";
  decks: StoredDeckRecord[];
}

export function listPreviewSavedDecks(): Promise<SavedDeckSummary[]> {
  const library = readDeckLibrary();
  return Promise.resolve(
    library.decks
      .slice()
      .sort((left, right) => left.path.localeCompare(right.path))
      .map((record) => toSavedDeckSummary(record.path, record.deck)),
  );
}

export function getPreviewSavedDeck(deckId: string): Promise<DeckList> {
  const record = findStoredDeck(deckId);
  return Promise.resolve(cloneDeck(record.deck));
}

export function createPreviewSavedDeck(input: {
  deck: DeckList;
  name?: string | null;
  overwrite?: boolean;
}): Promise<SavedDeckResponse> {
  const library = readDeckLibrary();
  const deck = withDeckName(input.deck, input.name);
  const path = uniqueDeckPath(library, slugify(deck.name ?? "untitled"), Boolean(input.overwrite));
  const record = { path, deck, updated_at: nowIso() };
  const next = {
    ...library,
    decks: [...library.decks.filter((item) => item.path !== path), record],
  };
  writeDeckLibrary(next);
  return Promise.resolve({ path, deck: cloneDeck(deck) });
}

export function updatePreviewSavedDeck(
  deckId: string,
  input: {
    deck: DeckList;
    name?: string | null;
    overwrite?: boolean;
  },
): Promise<SavedDeckResponse> {
  const library = readDeckLibrary();
  const index = library.decks.findIndex((record) => record.path === deckId);
  if (index < 0) {
    throw new Error(`saved deck not found: ${deckId}`);
  }
  const deck = withDeckName(input.deck, input.name);
  const nextDecks = library.decks.slice();
  nextDecks[index] = { path: deckId, deck, updated_at: nowIso() };
  writeDeckLibrary({ ...library, decks: nextDecks });
  return Promise.resolve({ path: deckId, deck: cloneDeck(deck) });
}

export function renamePreviewSavedDeck(
  deckId: string,
  input: { name: string },
): Promise<SavedDeckResponse> {
  const library = readDeckLibrary();
  const record = library.decks.find((item) => item.path === deckId);
  if (!record) {
    throw new Error(`saved deck not found: ${deckId}`);
  }
  const nextPath = uniqueDeckPath(library, slugify(input.name), false, deckId);
  const deck = withDeckName(record.deck, input.name);
  const nextDecks = library.decks
    .filter((item) => item.path !== deckId)
    .concat({ path: nextPath, deck, updated_at: nowIso() });
  writeDeckLibrary({ ...library, decks: nextDecks });
  return Promise.resolve({ path: nextPath, deck: cloneDeck(deck) });
}

export function deletePreviewSavedDeck(deckId: string): Promise<{ status: string }> {
  const library = readDeckLibrary();
  const nextDecks = library.decks.filter((record) => record.path !== deckId);
  if (nextDecks.length === library.decks.length) {
    throw new Error(`saved deck not found: ${deckId}`);
  }
  writeDeckLibrary({ ...library, decks: nextDecks });
  return Promise.resolve({ status: "deleted" });
}

export async function analyzePreviewDeck(deck: DeckList): Promise<DeckAnalysisResponse> {
  const details = new Map<string, CatalogCardDetail>();
  const issues: DeckAnalysisResponse["issues"] = [];
  const mainCount = sumQuantity(deck.main_deck);
  const energyCount = sumQuantity(deck.energy_deck);
  const cardTypeCounts: Record<string, Record<string, number>> = {
    main_deck: { member: 0, live: 0, energy: 0 },
    energy_deck: { member: 0, live: 0, energy: 0 },
  };
  const copyCounts: Record<string, number> = {};
  const memberCostCurve: Record<string, number> = {};
  const memberBasicHeartDistribution: Record<string, number> = {};
  const liveRequiredHeartDistribution: Record<string, number> = {};
  const memberBladeSummary: Record<string, number> = { total: 0, average: 0 };
  const liveScoreDistribution: Record<string, number> = {};
  const specialBladeHeartSummary: Record<string, number> = {};
  const effectTimingSummary: Record<string, number> = {};
  const effectExecutionSummary: Record<string, number> = {};

  if (mainCount !== 60) {
    issues.push(issue("main_deck_count", "Main deck must contain 60 cards.", "main_deck", null));
  }
  if (energyCount !== 12) {
    issues.push(issue("energy_deck_count", "Energy deck must contain 12 cards.", "energy_deck", null));
  }

  for (const entry of deck.main_deck) {
    copyCounts[entry.card_code] = (copyCounts[entry.card_code] ?? 0) + entry.quantity;
    const detail = await loadDetail(entry.card_code, details, issues);
    if (!detail) continue;
    const cardType = detail.card.card_type;
    cardTypeCounts.main_deck[cardType] = (cardTypeCounts.main_deck[cardType] ?? 0) + entry.quantity;
    validatePreferredPrinting(entry, detail, issues);
    if (cardType === "energy") {
      issues.push(issue("wrong_section_card_type", "Energy cards must be in the energy deck.", "main_deck", entry.card_code));
      continue;
    }
    if (cardType === "member") {
      addCount(memberCostCurve, String(detail.card.cost ?? "unknown"), entry.quantity);
      addWeightedHeartMap(memberBasicHeartDistribution, detail.card.heart_values.basic ?? {}, entry.quantity);
      memberBladeSummary.total += (detail.card.blade ?? 0) * entry.quantity;
    }
    if (cardType === "live") {
      addWeightedHeartMap(liveRequiredHeartDistribution, detail.card.heart_values.required ?? {}, entry.quantity);
      addCount(liveScoreDistribution, String(detail.card.score ?? "unknown"), entry.quantity);
      for (const special of detail.card.special_blade_hearts) {
        addCount(specialBladeHeartSummary, special.source_alt || special.effect_type, entry.quantity);
      }
    }
    addEffectCounts(detail, entry.quantity, effectTimingSummary, effectExecutionSummary);
  }

  for (const entry of deck.energy_deck) {
    const detail = await loadDetail(entry.card_code, details, issues);
    if (!detail) continue;
    const cardType = detail.card.card_type;
    cardTypeCounts.energy_deck[cardType] = (cardTypeCounts.energy_deck[cardType] ?? 0) + entry.quantity;
    validatePreferredPrinting(entry, detail, issues);
    if (cardType !== "energy") {
      issues.push(issue("wrong_section_card_type", "Only Energy cards may be in the energy deck.", "energy_deck", entry.card_code));
    }
  }

  const memberCount = cardTypeCounts.main_deck.member ?? 0;
  const liveCount = cardTypeCounts.main_deck.live ?? 0;
  if (memberCount !== 48) {
    issues.push(issue("member_count", "Main deck must contain exactly 48 Member cards.", "main_deck", null));
  }
  if (liveCount !== 12) {
    issues.push(issue("live_count", "Main deck must contain exactly 12 Live cards.", "main_deck", null));
  }
  for (const [cardCode, quantity] of Object.entries(copyCounts)) {
    if (quantity > 4) {
      issues.push(issue("copy_limit", "Member and Live cards are limited to 4 copies by card code.", "main_deck", cardCode));
    }
  }
  memberBladeSummary.average = memberCount > 0 ? memberBladeSummary.total / memberCount : 0;

  return {
    deck_name: deck.name,
    is_legal: issues.filter((item) => item.severity === "error").length === 0,
    issues,
    card_type_counts: cardTypeCounts,
    copy_counts: copyCounts,
    member_cost_curve: memberCostCurve,
    member_basic_heart_distribution: memberBasicHeartDistribution,
    live_required_heart_distribution: liveRequiredHeartDistribution,
    member_blade_summary: memberBladeSummary,
    live_score_distribution: liveScoreDistribution,
    special_blade_heart_summary: specialBladeHeartSummary,
    effect_timing_summary: effectTimingSummary,
    effect_execution_summary: effectExecutionSummary,
  };
}

function readDeckLibrary(): StoredDeckLibrary {
  const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
  if (!raw) return { version: STORAGE_KEY, decks: [] };
  try {
    const parsed = JSON.parse(raw) as StoredDeckLibrary;
    if (parsed.version !== STORAGE_KEY || !Array.isArray(parsed.decks)) {
      return { version: STORAGE_KEY, decks: [] };
    }
    return parsed;
  } catch {
    return { version: STORAGE_KEY, decks: [] };
  }
}

function writeDeckLibrary(library: StoredDeckLibrary): void {
  globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(library));
}

function findStoredDeck(deckId: string): StoredDeckRecord {
  const record = readDeckLibrary().decks.find((item) => item.path === deckId);
  if (!record) throw new Error(`saved deck not found: ${deckId}`);
  return record;
}

function uniqueDeckPath(
  library: StoredDeckLibrary,
  slug: string,
  overwrite: boolean,
  currentPath?: string,
): string {
  const path = `${slug || "untitled"}.json`;
  const exists = library.decks.some((record) => record.path === path && record.path !== currentPath);
  if (exists && !overwrite) {
    throw new Error(`saved deck already exists: ${path}`);
  }
  return path;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}._-]+/gu, "-")
    .replace(/^[-._]+|[-._]+$/g, "") || "untitled";
}

function withDeckName(deck: DeckList, name: string | null | undefined): DeckList {
  return cloneDeck({ ...deck, name: name !== undefined ? name : deck.name });
}

function cloneDeck(deck: DeckList): DeckList {
  return JSON.parse(JSON.stringify(deck)) as DeckList;
}

function toSavedDeckSummary(path: string, deck: DeckList): SavedDeckSummary {
  return {
    name: deck.name,
    path,
    version: deck.version,
    main_card_count: sumQuantity(deck.main_deck),
    energy_card_count: sumQuantity(deck.energy_deck),
  };
}

function sumQuantity(entries: DeckEntry[]): number {
  return entries.reduce((total, entry) => total + entry.quantity, 0);
}

async function loadDetail(
  cardCode: string,
  cache: Map<string, CatalogCardDetail>,
  issues: DeckAnalysisResponse["issues"],
): Promise<CatalogCardDetail | null> {
  const cached = cache.get(cardCode);
  if (cached) return cached;
  try {
    const detail = await getPreviewCatalogCard(cardCode);
    cache.set(cardCode, detail);
    return detail;
  } catch {
    issues.push(issue("unknown_card", "Unknown card code.", null, cardCode));
    return null;
  }
}

function validatePreferredPrinting(
  entry: DeckEntry,
  detail: CatalogCardDetail,
  issues: DeckAnalysisResponse["issues"],
): void {
  if (!entry.preferred_printing_id) return;
  if (!detail.printings.some((printing) => printing.card_id === entry.preferred_printing_id)) {
    issues.push(issue("preferred_printing_mismatch", "Preferred printing must belong to the same card code.", null, entry.card_code));
  }
}

function addWeightedHeartMap(
  target: Record<string, number>,
  values: Record<string, number>,
  quantity: number,
): void {
  for (const [key, value] of Object.entries(values)) {
    if (value > 0) addCount(target, key, value * quantity);
  }
}

function addEffectCounts(
  detail: CatalogCardDetail,
  quantity: number,
  timing: Record<string, number>,
  execution: Record<string, number>,
): void {
  for (const effect of detail.card.effects) {
    addCount(timing, effect.timing || effect.trigger, quantity);
    addCount(execution, effect.execution_mode, quantity);
  }
}

function addCount(target: Record<string, number>, key: string, amount: number): void {
  target[key] = (target[key] ?? 0) + amount;
}

function issue(
  code: string,
  message: string,
  section: string | null,
  cardCode: string | null,
): DeckAnalysisResponse["issues"][number] {
  return { severity: "error", code, message, section, card_code: cardCode };
}

function nowIso(): string {
  return new Date().toISOString();
}

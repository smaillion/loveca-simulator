import type {
  CatalogCardDetail,
  CatalogCardSummary,
  CatalogFacetsResponse,
  CatalogListResponse,
  CatalogReviewCandidateList,
} from "./types";

interface PreviewCardsPayload {
  items: CatalogCardDetail[];
}

let cardsPromise: Promise<CatalogCardDetail[]> | null = null;
let facetsPromise: Promise<CatalogFacetsResponse> | null = null;

export function listPreviewCatalogCards(input: {
  q?: string;
  cardType?: string;
  productCode?: string;
  workKey?: string;
  unitKey?: string;
  basicHeartColor?: string;
  memberCostMin?: number;
  memberCostMax?: number;
  memberBladeMin?: number;
  memberBladeMax?: number;
  memberBladeHeartColor?: string;
  requiredHeartColor?: string;
  requiredHeartMin?: number;
  requiredHeartMax?: number;
  liveScoreMin?: number;
  liveScoreMax?: number;
  hasLiveBladeHeart?: boolean;
  liveBladeHeartColor?: string;
  reviewOnly?: boolean;
  limit?: number;
  offset?: number;
} = {}): Promise<CatalogListResponse> {
  return loadPreviewCards().then((cards) => {
    const filtered = cards
      .filter((detail) => matchesPreviewDetailFilters(detail, input))
      .map(cardDetailToSummary)
      .filter((card) => matchesPreviewCatalogFilters(card, input));
    const offset = input.offset ?? 0;
    const limit = input.limit ?? 100;
    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    };
  });
}

function matchesPreviewDetailFilters(
  detail: CatalogCardDetail,
  input: {
    workKey?: string;
    unitKey?: string;
  },
): boolean {
  if (input.workKey && !detail.card.works.some((work) => work.work_key === input.workKey)) {
    return false;
  }
  if (input.unitKey && !detail.card.units.some((unit) => unit.unit_key === input.unitKey)) {
    return false;
  }
  return true;
}

export function listPreviewCatalogFacets(): Promise<CatalogFacetsResponse> {
  return loadPreviewFacets();
}

export function getPreviewCatalogCard(cardCode: string): Promise<CatalogCardDetail> {
  return loadPreviewCards().then((cards) => {
    const detail = cards.find((card) => card.card.card_code === cardCode);
    if (!detail) {
      throw new Error(`preview card not found: ${cardCode}`);
    }
    return detail;
  });
}

export function listPreviewCatalogReviewCandidates(input: {
  limit?: number;
  offset?: number;
} = {}): Promise<CatalogReviewCandidateList> {
  return Promise.resolve({
    items: [],
    total: 0,
    limit: input.limit ?? 100,
    offset: input.offset ?? 0,
  });
}

function loadPreviewCards(): Promise<CatalogCardDetail[]> {
  cardsPromise ??= fetchPreviewJson<PreviewCardsPayload>("preview-data/cards.json")
    .then((payload) => payload.items ?? []);
  return cardsPromise;
}

function loadPreviewFacets(): Promise<CatalogFacetsResponse> {
  facetsPromise ??= fetchPreviewJson<CatalogFacetsResponse>("preview-data/facets.json");
  return facetsPromise;
}

async function fetchPreviewJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(
        "preview data is not bundled. Run the GitHub Pages workflow with parsed card data enabled.",
      );
    }
    throw new Error(response.statusText);
  }
  return response.json().catch(() => {
    throw new Error(
      `Expected JSON from ${path}, but received a non-JSON response. `
      + "Build or deploy the preview data package before using the static preview.",
    );
  }) as Promise<T>;
}

function cardDetailToSummary(detail: CatalogCardDetail): CatalogCardSummary {
  const primaryPrinting = detail.printings[0] ?? null;
  const basicHeartByColor = detail.card.heart_values.basic ?? {};
  const requiredHeartByColor = detail.card.heart_values.required ?? {};
  return {
    gameplay_card_id: detail.card.gameplay_card_id,
    card_code: detail.card.card_code,
    name_ja: detail.card.name_ja,
    card_type: detail.card.card_type,
    validation_status: detail.card.validation_status,
    card_id: primaryPrinting?.card_id ?? null,
    card_set_code: primaryPrinting?.card_set_code ?? null,
    rarity_ja: primaryPrinting?.rarity_ja ?? null,
    image_url: primaryPrinting?.image_url ?? null,
    cost: detail.card.cost,
    blade: detail.card.blade,
    member_blade_heart_color_slot: detail.card.member_blade_heart_color_slot,
    score: detail.card.score,
    live_blade_heart_color_slot: detail.card.live_blade_heart_color_slot,
    basic_heart_by_color: basicHeartByColor,
    basic_heart_total: sumValues(basicHeartByColor),
    required_heart_by_color: requiredHeartByColor,
    required_heart_total: sumValues(requiredHeartByColor),
    has_live_blade_heart: Boolean(detail.card.live_blade_heart_color_slot),
    printing_count: detail.printings.length,
    revision_count: detail.text_revisions.length,
    observation_count: detail.source_observations.length,
    pending_candidate_count: detail.card.review_candidates.length,
    unresolved_reference_count: 0,
    review_issue_count: detail.card.review_candidates.length,
  };
}

function matchesPreviewCatalogFilters(
  card: CatalogCardSummary,
  input: {
    q?: string;
    cardType?: string;
    productCode?: string;
    workKey?: string;
    unitKey?: string;
    basicHeartColor?: string;
    memberCostMin?: number;
    memberCostMax?: number;
    memberBladeMin?: number;
    memberBladeMax?: number;
    memberBladeHeartColor?: string;
    requiredHeartColor?: string;
    requiredHeartMin?: number;
    requiredHeartMax?: number;
    liveScoreMin?: number;
    liveScoreMax?: number;
    hasLiveBladeHeart?: boolean;
    liveBladeHeartColor?: string;
    reviewOnly?: boolean;
  },
): boolean {
  if (input.reviewOnly && card.review_issue_count === 0) return false;
  if (input.cardType && card.card_type !== input.cardType) return false;
  if (input.productCode && card.card_set_code !== input.productCode) return false;
  if (input.q && !matchesQuery(card, input.q)) return false;
  if (input.basicHeartColor && !hasPositive(card.basic_heart_by_color, input.basicHeartColor)) {
    return false;
  }
  if (input.memberCostMin !== undefined && !minNumber(card.cost, input.memberCostMin)) return false;
  if (input.memberCostMax !== undefined && !maxNumber(card.cost, input.memberCostMax)) return false;
  if (input.memberBladeMin !== undefined && !minNumber(card.blade, input.memberBladeMin)) return false;
  if (input.memberBladeMax !== undefined && !maxNumber(card.blade, input.memberBladeMax)) return false;
  if (
    input.memberBladeHeartColor &&
    card.member_blade_heart_color_slot !== input.memberBladeHeartColor
  ) {
    return false;
  }
  if (input.requiredHeartColor && !hasPositive(card.required_heart_by_color, input.requiredHeartColor)) {
    return false;
  }
  if (input.requiredHeartMin !== undefined && card.required_heart_total < input.requiredHeartMin) {
    return false;
  }
  if (input.requiredHeartMax !== undefined && card.required_heart_total > input.requiredHeartMax) {
    return false;
  }
  if (input.liveScoreMin !== undefined && !minNumber(card.score, input.liveScoreMin)) return false;
  if (input.liveScoreMax !== undefined && !maxNumber(card.score, input.liveScoreMax)) return false;
  if (
    input.hasLiveBladeHeart !== undefined &&
    card.has_live_blade_heart !== input.hasLiveBladeHeart
  ) {
    return false;
  }
  if (input.liveBladeHeartColor && card.live_blade_heart_color_slot !== input.liveBladeHeartColor) {
    return false;
  }
  return true;
}

function matchesQuery(card: CatalogCardSummary, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    card.card_code,
    card.card_id,
    card.name_ja,
    card.card_set_code,
    card.rarity_ja,
  ].some((value) => value?.toLocaleLowerCase().includes(needle));
}

function hasPositive(values: Record<string, number>, key: string): boolean {
  return (values[key] ?? 0) > 0;
}

function minNumber(value: number | null, minimum: number): boolean {
  return value !== null && value >= minimum;
}

function maxNumber(value: number | null, maximum: number): boolean {
  return value !== null && value <= maximum;
}

function sumValues(values: Record<string, number>): number {
  return Object.values(values).reduce((total, value) => total + value, 0);
}

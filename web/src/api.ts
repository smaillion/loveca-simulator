import type {
  CatalogCardDetail,
  CatalogFacetsResponse,
  CatalogListResponse,
  CatalogReviewCandidateList,
  DeckAnalysisResponse,
  DeckList,
  SavedDeckResponse,
  SavedDeckSummary,
  MatchPayload,
  MatchSummary,
} from "./types";
import {
  getPreviewCatalogCard,
  listPreviewCatalogCards,
  listPreviewCatalogFacets,
  listPreviewCatalogReviewCandidates,
} from "./browser-preview-api";

const viteEnv = (import.meta as unknown as {
  env?: Record<string, string | boolean | undefined>;
}).env;
const browserPreview = viteEnv?.VITE_BROWSER_PREVIEW === "true";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export function listMatches(): Promise<MatchSummary[]> {
  return request("/api/matches");
}

export function getMatch(matchId: string): Promise<MatchPayload> {
  return request(`/api/matches/${matchId}`);
}

export function createMatch(input: {
  player1Name: string;
  player1Deck: DeckList;
  player2Name: string;
  player2Deck: DeckList;
  seed?: number;
}): Promise<MatchPayload> {
  return request("/api/matches", {
    method: "POST",
    body: JSON.stringify({
      player_1: {
        name: input.player1Name,
        deck: input.player1Deck,
      },
      player_2: {
        name: input.player2Name,
        deck: input.player2Deck,
      },
      seed: input.seed,
    }),
  });
}

export function submitAction(
  matchId: string,
  input: {
    action_type: string;
    expected_revision: number;
    player_id?: string | null;
    payload?: Record<string, unknown>;
  },
): Promise<MatchPayload> {
  return request(`/api/matches/${matchId}/actions`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listCatalogCards(input: {
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
  if (browserPreview) {
    return listPreviewCatalogCards(input);
  }
  const params = new URLSearchParams();
  if (input.q) params.set("q", input.q);
  if (input.cardType) params.set("card_type", input.cardType);
  if (input.productCode) params.set("product_code", input.productCode);
  if (input.workKey) params.set("work_key", input.workKey);
  if (input.unitKey) params.set("unit_key", input.unitKey);
  if (input.basicHeartColor) params.set("basic_heart_color", input.basicHeartColor);
  if (input.memberCostMin !== undefined) params.set("member_cost_min", String(input.memberCostMin));
  if (input.memberCostMax !== undefined) params.set("member_cost_max", String(input.memberCostMax));
  if (input.memberBladeMin !== undefined) params.set("member_blade_min", String(input.memberBladeMin));
  if (input.memberBladeMax !== undefined) params.set("member_blade_max", String(input.memberBladeMax));
  if (input.memberBladeHeartColor) params.set("member_blade_heart_color", input.memberBladeHeartColor);
  if (input.requiredHeartColor) params.set("required_heart_color", input.requiredHeartColor);
  if (input.requiredHeartMin !== undefined) params.set("required_heart_min", String(input.requiredHeartMin));
  if (input.requiredHeartMax !== undefined) params.set("required_heart_max", String(input.requiredHeartMax));
  if (input.liveScoreMin !== undefined) params.set("live_score_min", String(input.liveScoreMin));
  if (input.liveScoreMax !== undefined) params.set("live_score_max", String(input.liveScoreMax));
  if (input.hasLiveBladeHeart !== undefined) params.set("has_live_blade_heart", String(input.hasLiveBladeHeart));
  if (input.liveBladeHeartColor) params.set("live_blade_heart_color", input.liveBladeHeartColor);
  if (input.reviewOnly) params.set("review_only", "true");
  if (input.limit !== undefined) params.set("limit", String(input.limit));
  if (input.offset !== undefined) params.set("offset", String(input.offset));
  const query = params.toString();
  return request(`/api/catalog/cards${query ? `?${query}` : ""}`);
}

export function listCatalogFacets(): Promise<CatalogFacetsResponse> {
  if (browserPreview) {
    return listPreviewCatalogFacets();
  }
  return request("/api/catalog/facets");
}

export function getCatalogCard(cardCode: string): Promise<CatalogCardDetail> {
  if (browserPreview) {
    return getPreviewCatalogCard(cardCode);
  }
  return request(`/api/catalog/cards/${encodeURIComponent(cardCode)}`);
}

export function listCatalogReviewCandidates(input: {
  limit?: number;
  offset?: number;
} = {}): Promise<CatalogReviewCandidateList> {
  if (browserPreview) {
    return listPreviewCatalogReviewCandidates(input);
  }
  const params = new URLSearchParams();
  if (input.limit !== undefined) params.set("limit", String(input.limit));
  if (input.offset !== undefined) params.set("offset", String(input.offset));
  const query = params.toString();
  return request(`/api/catalog/review-candidates${query ? `?${query}` : ""}`);
}

export function listSavedDecks(): Promise<SavedDeckSummary[]> {
  return request("/api/decks");
}

export function getSavedDeck(deckId: string): Promise<DeckList> {
  return request(`/api/decks/${encodeURIComponent(deckId)}`);
}

export function createSavedDeck(input: {
  deck: DeckList;
  name?: string | null;
  overwrite?: boolean;
}): Promise<SavedDeckResponse> {
  return request("/api/decks", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateSavedDeck(
  deckId: string,
  input: {
    deck: DeckList;
    name?: string | null;
    overwrite?: boolean;
  },
): Promise<SavedDeckResponse> {
  return request(`/api/decks/${encodeURIComponent(deckId)}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function renameSavedDeck(
  deckId: string,
  input: { name: string },
): Promise<SavedDeckResponse> {
  return request(`/api/decks/${encodeURIComponent(deckId)}/rename`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteSavedDeck(deckId: string): Promise<{ status: string }> {
  return request(`/api/decks/${encodeURIComponent(deckId)}`, {
    method: "DELETE",
  });
}

export function analyzeDeck(
  deck: DeckList,
): Promise<DeckAnalysisResponse> {
  return request("/api/decks/analyze", {
    method: "POST",
    body: JSON.stringify({ deck }),
  });
}

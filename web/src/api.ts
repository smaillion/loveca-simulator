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
  RoomPayload,
} from "./types";
import {
  getPreviewCatalogCard,
  listPreviewCatalogCards,
  listPreviewCatalogFacets,
  listPreviewCatalogReviewCandidates,
} from "./browser-preview-api";
import {
  analyzePreviewDeck,
  createPreviewSavedDeck,
  deletePreviewSavedDeck,
  getPreviewSavedDeck,
  listPreviewSavedDecks,
  renamePreviewSavedDeck,
  updatePreviewSavedDeck,
} from "./browser-preview-decks";

const viteEnv = (import.meta as unknown as {
  env?: Record<string, string | boolean | undefined>;
}).env;

export interface RuntimeConfig {
  mode: "preview" | "release";
  browserPreview: boolean;
  apiBaseUrl: string;
  cardDatabaseFingerprint: string;
}

const fallbackRuntimeConfig: RuntimeConfig = {
  mode: viteEnv?.VITE_BROWSER_PREVIEW === "true" ? "preview" : "release",
  browserPreview: viteEnv?.VITE_BROWSER_PREVIEW === "true",
  apiBaseUrl: normalizeBaseUrl(
    typeof viteEnv?.VITE_PUBLIC_API_BASE_URL === "string"
      ? viteEnv.VITE_PUBLIC_API_BASE_URL
      : typeof viteEnv?.VITE_HOSTED_API_BASE_URL === "string"
        ? viteEnv.VITE_HOSTED_API_BASE_URL
        : "",
  ),
  cardDatabaseFingerprint: "",
};

let runtimeConfig = fallbackRuntimeConfig;
let runtimeConfigPromise: Promise<RuntimeConfig> | null = null;

export function getRuntimeConfigSnapshot(): RuntimeConfig {
  return runtimeConfig;
}

export function browserPreviewEnabled(): boolean {
  return runtimeConfig.browserPreview;
}

export function loadRuntimeConfig(): Promise<RuntimeConfig> {
  runtimeConfigPromise ??= fetch("runtime-config.json", {
    cache: "no-store",
    headers: { Accept: "application/json" },
  })
    .then(async (response) => {
      if (!response.ok) return fallbackRuntimeConfig;
      const payload = await response.json();
      return normalizeRuntimeConfig(payload);
    })
    .catch(() => fallbackRuntimeConfig)
    .then((config) => {
      runtimeConfig = config;
      return config;
    });
  return runtimeConfigPromise;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiResourceUrl(url), {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function normalizeRuntimeConfig(payload: unknown): RuntimeConfig {
  const value = (payload ?? {}) as Record<string, unknown>;
  const mode = value.mode === "release" ? "release" : "preview";
  return {
    mode,
    browserPreview:
      typeof value.browserPreview === "boolean"
        ? value.browserPreview
        : fallbackRuntimeConfig.browserPreview,
    apiBaseUrl: normalizeBaseUrl(
      typeof value.apiBaseUrl === "string"
        ? value.apiBaseUrl
        : fallbackRuntimeConfig.apiBaseUrl,
    ),
    cardDatabaseFingerprint:
      typeof value.cardDatabaseFingerprint === "string"
        ? value.cardDatabaseFingerprint
        : "",
  };
}

export function apiResourceUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  if (!path.startsWith("/api/")) return path;
  if (!runtimeConfig.apiBaseUrl) return path;
  return `${runtimeConfig.apiBaseUrl}${path}`;
}

export function hostedOnlineAvailable(): boolean {
  return runtimeConfig.apiBaseUrl.length > 0;
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

export function createRoom(input: {
  playerName: string;
  deck: DeckList;
  seed?: number;
}): Promise<RoomPayload> {
  if (!runtimeConfig.apiBaseUrl) {
    return Promise.reject(new Error("Hosted API base URL is not configured."));
  }
  return request("/api/rooms", {
    method: "POST",
    body: JSON.stringify({
      player_name: input.playerName,
      deck: input.deck,
      seed: input.seed,
    }),
  });
}

export function joinRoom(input: {
  roomCode: string;
  playerName: string;
  deck: DeckList;
}): Promise<RoomPayload> {
  if (!runtimeConfig.apiBaseUrl) {
    return Promise.reject(new Error("Hosted API base URL is not configured."));
  }
  return request(`/api/rooms/${encodeURIComponent(input.roomCode)}/join`, {
    method: "POST",
    body: JSON.stringify({
      player_name: input.playerName,
      deck: input.deck,
    }),
  });
}

export function getRoom(roomCode: string, playerToken: string): Promise<RoomPayload> {
  if (!runtimeConfig.apiBaseUrl) {
    return Promise.reject(new Error("Hosted API base URL is not configured."));
  }
  const params = new URLSearchParams({ player_token: playerToken });
  return request(`/api/rooms/${encodeURIComponent(roomCode)}?${params.toString()}`);
}

export function submitRoomAction(
  roomCode: string,
  playerToken: string,
  input: {
    action_type: string;
    expected_revision: number;
    player_id?: string | null;
    payload?: Record<string, unknown>;
  },
): Promise<MatchPayload> {
  if (!runtimeConfig.apiBaseUrl) {
    return Promise.reject(new Error("Hosted API base URL is not configured."));
  }
  return request(`/api/rooms/${encodeURIComponent(roomCode)}/actions`, {
    method: "POST",
    body: JSON.stringify({
      player_token: playerToken,
      action: input,
    }),
  });
}

export function roomReplayUrl(roomCode: string, playerToken: string): string {
  const params = new URLSearchParams({ player_token: playerToken });
  return apiResourceUrl(`/api/rooms/${encodeURIComponent(roomCode)}/replay?${params.toString()}`);
}

export function matchReplayUrl(matchId: string): string {
  return apiResourceUrl(`/api/matches/${matchId}/replay`);
}

export function cardImageUrl(cardId: string): string {
  return apiResourceUrl(`/api/card-images/${encodeURIComponent(cardId)}`);
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
  if (runtimeConfig.browserPreview) {
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
  if (runtimeConfig.browserPreview) {
    return listPreviewCatalogFacets();
  }
  return request("/api/catalog/facets");
}

export function getCatalogCard(cardCode: string): Promise<CatalogCardDetail> {
  if (runtimeConfig.browserPreview) {
    return getPreviewCatalogCard(cardCode);
  }
  return request(`/api/catalog/cards/${encodeURIComponent(cardCode)}`);
}

export function listCatalogReviewCandidates(input: {
  limit?: number;
  offset?: number;
} = {}): Promise<CatalogReviewCandidateList> {
  if (runtimeConfig.browserPreview) {
    return listPreviewCatalogReviewCandidates(input);
  }
  const params = new URLSearchParams();
  if (input.limit !== undefined) params.set("limit", String(input.limit));
  if (input.offset !== undefined) params.set("offset", String(input.offset));
  const query = params.toString();
  return request(`/api/catalog/review-candidates${query ? `?${query}` : ""}`);
}

export function listSavedDecks(): Promise<SavedDeckSummary[]> {
  if (runtimeConfig.browserPreview) {
    return listPreviewSavedDecks();
  }
  return request("/api/decks");
}

export function getSavedDeck(deckId: string): Promise<DeckList> {
  if (runtimeConfig.browserPreview) {
    return getPreviewSavedDeck(deckId);
  }
  return request(`/api/decks/${encodeURIComponent(deckId)}`);
}

export function createSavedDeck(input: {
  deck: DeckList;
  name?: string | null;
  overwrite?: boolean;
}): Promise<SavedDeckResponse> {
  if (runtimeConfig.browserPreview) {
    return createPreviewSavedDeck(input);
  }
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
  if (runtimeConfig.browserPreview) {
    return updatePreviewSavedDeck(deckId, input);
  }
  return request(`/api/decks/${encodeURIComponent(deckId)}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function renameSavedDeck(
  deckId: string,
  input: { name: string },
): Promise<SavedDeckResponse> {
  if (runtimeConfig.browserPreview) {
    return renamePreviewSavedDeck(deckId, input);
  }
  return request(`/api/decks/${encodeURIComponent(deckId)}/rename`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteSavedDeck(deckId: string): Promise<{ status: string }> {
  if (runtimeConfig.browserPreview) {
    return deletePreviewSavedDeck(deckId);
  }
  return request(`/api/decks/${encodeURIComponent(deckId)}`, {
    method: "DELETE",
  });
}

export function analyzeDeck(
  deck: DeckList,
): Promise<DeckAnalysisResponse> {
  if (runtimeConfig.browserPreview) {
    return analyzePreviewDeck(deck);
  }
  return request("/api/decks/analyze", {
    method: "POST",
    body: JSON.stringify({ deck }),
  });
}

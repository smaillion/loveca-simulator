import type {
  CatalogCardDetail,
  CatalogFacetsResponse,
  CatalogListResponse,
  CatalogReviewCandidateList,
  DeckAnalysisResponse,
  DeckList,
  SavedDeckResponse,
  SavedDeckSummary,
  MatchListResponse,
  MatchPayload,
  MatchSummary,
  RoomPayload,
  SharedDeckResponse,
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
  publicMatchHistory: boolean;
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
  publicMatchHistory: !normalizeBaseUrl(
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

export function resetRuntimeConfigForTests(config: RuntimeConfig = fallbackRuntimeConfig): void {
  runtimeConfig = config;
  runtimeConfigPromise = null;
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
  const resolvedUrl = apiResourceUrl(url);
  const response = await fetch(resolvedUrl, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? response.statusText);
  }
  return response.json().catch(() => {
    throw new Error(`Expected JSON from ${resolvedUrl}, but received a non-JSON response.`);
  }) as Promise<T>;
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
    publicMatchHistory:
      typeof value.publicMatchHistory === "boolean"
        ? value.publicMatchHistory
        : fallbackRuntimeConfig.publicMatchHistory,
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
  return canUseHostedApi(runtimeConfig);
}

function canUseHostedApi(config: RuntimeConfig): boolean {
  return config.apiBaseUrl.length > 0 || !shouldUsePreviewData(config);
}

function requireHostedApi(): void {
  if (!canUseHostedApi(runtimeConfig)) {
    throw new Error("Hosted API base URL is not configured.");
  }
}

function shouldUsePreviewData(config: RuntimeConfig): boolean {
  return config.browserPreview
    || (config.mode === "preview" && !config.apiBaseUrl)
    || (!config.apiBaseUrl && staticLocalBuildLikely())
    || (
      typeof window !== "undefined"
      && window.location.hostname.endsWith("github.io")
      && !config.apiBaseUrl
    );
}

function staticLocalBuildLikely(): boolean {
  if (typeof window === "undefined") return false;
  const { port, protocol } = window.location;
  if (protocol === "file:") return true;
  if (port === "4173") return true;
  return false;
}

export function listMatches(input: {
  page?: number;
  perPage?: number;
} = {}): Promise<MatchListResponse> {
  const page = input.page ?? 1;
  const perPage = input.perPage ?? 10;
  const query = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  return request<MatchListResponse | MatchSummary[]>(`/api/matches?${query}`).then(
    (payload) => {
      if (Array.isArray(payload)) {
        return {
          items: payload,
          page,
          per_page: perPage,
          total: payload.length,
          max_total: 25,
        };
      }
      return payload;
    },
  );
}

export function getMatch(matchId: string, matchToken?: string | null): Promise<MatchPayload> {
  const params = matchToken ? `?${new URLSearchParams({ match_token: matchToken })}` : "";
  return request(`/api/matches/${matchId}${params}`);
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
  matchToken?: string | null,
): Promise<MatchPayload> {
  const params = matchToken ? `?${new URLSearchParams({ match_token: matchToken })}` : "";
  return request(`/api/matches/${matchId}/actions${params}`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createRoom(input: {
  playerName: string;
  deck: DeckList;
  seed?: number;
}): Promise<RoomPayload> {
  requireHostedApi();
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
  requireHostedApi();
  return request(`/api/rooms/${encodeURIComponent(input.roomCode)}/join`, {
    method: "POST",
    body: JSON.stringify({
      player_name: input.playerName,
      deck: input.deck,
    }),
  });
}

export function getRoom(roomCode: string, playerToken: string): Promise<RoomPayload> {
  requireHostedApi();
  const params = new URLSearchParams({ player_token: playerToken });
  return request(`/api/rooms/${encodeURIComponent(roomCode)}?${params.toString()}`);
}

export function leaveRoom(
  roomCode: string,
  playerToken: string,
  init?: Pick<RequestInit, "keepalive">,
): Promise<RoomPayload> {
  requireHostedApi();
  return request(`/api/rooms/${encodeURIComponent(roomCode)}/leave`, {
    method: "POST",
    keepalive: init?.keepalive,
    body: JSON.stringify({ player_token: playerToken }),
  });
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
  requireHostedApi();
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

export function matchReplayUrl(matchId: string, matchToken?: string | null): string {
  const params = matchToken ? `?${new URLSearchParams({ match_token: matchToken })}` : "";
  return apiResourceUrl(`/api/matches/${matchId}/replay${params}`);
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
  return loadRuntimeConfig().then((config) => {
    if (shouldUsePreviewData(config)) {
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
  });
}

export function listCatalogFacets(): Promise<CatalogFacetsResponse> {
  return loadRuntimeConfig().then((config) => {
    if (shouldUsePreviewData(config)) {
      return listPreviewCatalogFacets();
    }
    return request("/api/catalog/facets");
  });
}

export function getCatalogCard(cardCode: string): Promise<CatalogCardDetail> {
  return loadRuntimeConfig().then((config) => {
    if (shouldUsePreviewData(config)) {
      return getPreviewCatalogCard(cardCode);
    }
    return request(`/api/catalog/cards/${encodeURIComponent(cardCode)}`);
  });
}

export function listCatalogReviewCandidates(input: {
  limit?: number;
  offset?: number;
} = {}): Promise<CatalogReviewCandidateList> {
  return loadRuntimeConfig().then((config) => {
    if (shouldUsePreviewData(config)) {
      return listPreviewCatalogReviewCandidates(input);
    }
    const params = new URLSearchParams();
    if (input.limit !== undefined) params.set("limit", String(input.limit));
    if (input.offset !== undefined) params.set("offset", String(input.offset));
    const query = params.toString();
    return request(`/api/catalog/review-candidates${query ? `?${query}` : ""}`);
  });
}

export function listSavedDecks(): Promise<SavedDeckSummary[]> {
  return listPreviewSavedDecks();
}

export function getSavedDeck(deckId: string): Promise<DeckList> {
  return getPreviewSavedDeck(deckId);
}

export function createSavedDeck(input: {
  deck: DeckList;
  name?: string | null;
  overwrite?: boolean;
}): Promise<SavedDeckResponse> {
  return createPreviewSavedDeck(input);
}

export function updateSavedDeck(
  deckId: string,
  input: {
    deck: DeckList;
    name?: string | null;
    overwrite?: boolean;
  },
): Promise<SavedDeckResponse> {
  return updatePreviewSavedDeck(deckId, input);
}

export function renameSavedDeck(
  deckId: string,
  input: { name: string },
): Promise<SavedDeckResponse> {
  return renamePreviewSavedDeck(deckId, input);
}

export function deleteSavedDeck(deckId: string): Promise<{ status: string }> {
  return deletePreviewSavedDeck(deckId);
}

export function uploadSharedDeck(deck: DeckList): Promise<SharedDeckResponse> {
  return loadRuntimeConfig().then((config) => {
    if (!canUseHostedApi(config)) {
      throw new Error("Hosted API base URL is not configured.");
    }
    return request("/api/deck-shares", {
      method: "POST",
      body: JSON.stringify({ deck }),
    });
  });
}

export function downloadSharedDeck(shareId: string): Promise<SharedDeckResponse> {
  return loadRuntimeConfig().then((config) => {
    if (!canUseHostedApi(config)) {
      throw new Error("Hosted API base URL is not configured.");
    }
    return request(`/api/deck-shares/${encodeURIComponent(shareId)}`);
  });
}

export function analyzeDeck(
  deck: DeckList,
): Promise<DeckAnalysisResponse> {
  return loadRuntimeConfig().then((config) => {
    if (shouldUsePreviewData(config)) {
      return analyzePreviewDeck(deck);
    }
    return request("/api/decks/analyze", {
      method: "POST",
      body: JSON.stringify({ deck }),
    });
  });
}

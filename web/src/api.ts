import type { MatchPayload, MatchSummary } from "./types";

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
  player2Name: string;
  seed?: number;
}): Promise<MatchPayload> {
  return request("/api/matches", {
    method: "POST",
    body: JSON.stringify({
      player_1: {
        name: input.player1Name,
        deck_path: "examples/decks/sample-deck.json",
      },
      player_2: {
        name: input.player2Name,
        deck_path: "examples/decks/sample-deck.json",
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

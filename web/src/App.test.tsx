import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, {
  EffectResolutionAction,
  InspectionChoiceAction,
  ManualDrawer,
  MemberPlayAction,
  SelectionAction,
  StageAttachments,
  availableValue,
  canResolveEffect,
  formatEffectText,
  formatHeartSummary,
  localPerspectivePlayerId,
  resolveMemberPlaySelection,
} from "./App";
import { resetRuntimeConfigForTests } from "./api";
import { CatalogPreviewDialog } from "./deck-builder";
import type { CatalogCardDetail, CatalogCardSummary, DeckList, MatchState } from "./types";

const placements = [
  {
    card_instance_id: "member-a",
    slot: "center",
    payment_cost: 4,
    use_baton_touch: false,
    replaced_card_instance_id: "old-center",
    replaced_member_cost: 2,
  },
  {
    card_instance_id: "member-a",
    slot: "center",
    payment_cost: 2,
    use_baton_touch: true,
    replaced_card_instance_id: "old-center",
    replaced_member_cost: 2,
  },
  {
    card_instance_id: "member-a",
    slot: "left",
    payment_cost: 4,
    use_baton_touch: false,
    replaced_card_instance_id: null,
    replaced_member_cost: 0,
  },
  {
    card_instance_id: "member-b",
    slot: "right",
    payment_cost: 1,
    use_baton_touch: false,
    replaced_card_instance_id: null,
    replaced_member_cost: 0,
  },
];

const SAMPLE_DECK = {
  version: "decklist.v0" as const,
  name: "Test Deck",
  main_deck: [],
  energy_deck: [],
};

const ANALYSIS_RESPONSE = {
  deck_name: "Test Deck",
  is_legal: false,
  issues: [
    {
      severity: "error",
      code: "main_deck_count",
      message: "Main deck must contain 60 cards.",
      section: "main_deck",
      card_code: null,
    },
  ],
  card_type_counts: { main_deck: { member: 0, live: 0 }, energy_deck: { energy: 0 } },
  copy_counts: {},
  member_cost_curve: {},
  member_basic_heart_distribution: { heart01: 2 },
  live_required_heart_distribution: { heart0: 3, heart06: 1 },
  member_blade_summary: {},
  live_score_distribution: {},
  special_blade_heart_summary: {},
  effect_timing_summary: { on_play: 1, activated: 2 },
  effect_execution_summary: { prompt_then_resolve: 3, manual_resolution: 1 },
};

const CATALOG_SUMMARY = {
  gameplay_card_id: 1,
  card_code: "LL-TEST-001",
  name_ja: "テストカード",
  card_type: "member",
  validation_status: "source_confirmed",
  card_id: "LL-TEST-001-PR",
  card_set_code: "PR",
  rarity_ja: "PR",
  image_url: null,
  cost: 1,
  blade: 2,
  member_blade_heart_color_slot: "heart01",
  score: null,
  live_blade_heart_color_slot: null,
  basic_heart_by_color: { heart01: 1 },
  basic_heart_total: 1,
  required_heart_by_color: {},
  required_heart_total: 0,
  has_live_blade_heart: false,
  printing_count: 1,
  revision_count: 1,
  observation_count: 1,
  pending_candidate_count: 0,
  unresolved_reference_count: 0,
  review_issue_count: 0,
};

const CATALOG_DETAIL = {
  card: {
    gameplay_card_id: 1,
    card_code: "LL-TEST-001",
    name_ja: "テストカード",
    card_type: "member",
    validation_status: "source_confirmed",
    cost: 1,
    blade: 2,
    member_blade_heart_color_slot: "heart01",
    score: null,
    live_blade_heart_color_slot: null,
    heart_values: { basic: { heart01: 1 } },
    special_blade_hearts: [],
    works: [],
    units: [],
    review_candidates: [],
    printing_references: [],
    effect_registry_status: "supported",
    effect_registry_errors: [],
    effects: [
      {
        effect_id: "LL-TEST-001:1",
        label_ja: "【登場】【heart05】テスト。",
        effect_type: "triggered",
        timing: "on_play",
        trigger: "member_played",
        execution_mode: "prompt_then_resolve",
        frequency_limit: "none",
        is_optional: false,
        simulation_support: "test_validated_executable",
        review_status: "test_validated",
      },
    ],
  },
  printings: [
    {
      card_id: "LL-TEST-001-PR",
      card_set_code: "PR",
      rarity_ja: "PR",
      image_url: null,
      source_url: "https://llofficial-cardgame.com",
      fetched_at: "2026-06-14T00:00:00+00:00",
      parser_version: "test",
      raw_product_label_ja: "PR",
      language: "ja",
      raw_fields: {},
      parse_notes: {},
    },
  ],
  source_observations: [
    {
      source_observation_id: 1,
      source_url: "https://llofficial-cardgame.com",
      source_version: "test",
      fetched_at: "2026-06-14T00:00:00+00:00",
      parser_version: "test",
      language: "ja",
      raw_product_label_ja: "PR",
      card_id: "LL-TEST-001-PR",
      raw_fields: {},
      parse_notes: {},
    },
  ],
  text_revisions: [
    {
      revision_id: 1,
      revision_number: 1,
      raw_effect_text_ja: "【登場】【heart01】を得る。",
      raw_text_hash: "hash",
      revision_status: "current",
      first_observed_at: "2026-06-14T00:00:00+00:00",
      last_observed_at: "2026-06-14T00:00:00+00:00",
      source_url: "https://llofficial-cardgame.com",
    },
  ],
};

const LIVE_SUMMARY = {
  ...CATALOG_SUMMARY,
  gameplay_card_id: 2,
  card_code: "LL-LIVE-001",
  name_ja: "テストライブ",
  card_type: "live",
  card_id: "LL-LIVE-001-L",
  cost: null,
  blade: null,
  member_blade_heart_color_slot: null,
  score: 5,
  live_blade_heart_color_slot: "heart0",
  basic_heart_by_color: {},
  basic_heart_total: 0,
  required_heart_by_color: { heart0: 6 },
  required_heart_total: 6,
  has_live_blade_heart: true,
};

const MATCH_PAYLOAD = {
  state: {
    match_id: "match-1",
    rule_version: "1.06",
    seed: 42,
    revision: 0,
    phase: "setup_choose_first",
    first_player_id: null,
    second_player_id: null,
    turn_number: 1,
    next_first_player_id: null,
    success_live_moved_player_ids: [],
    success_live_moved_instance_ids: {},
    live_success_effects_queued: false,
    active_player_id: null,
    players: {
      player_1: createPlayerState("player_1", "Player 1"),
      player_2: createPlayerState("player_2", "Player 2"),
    },
    cards: {},
    effect_registry_version: null,
    effect_definitions: {},
    pending_effects: [],
    effect_usage: [],
    pending_choice: null,
    live_winner_ids: [],
    live_judgment_summary: null,
    game_result: null,
    completed_reason: null,
  },
  events: [],
  legal_actions: [],
};

function roomPayload(status: "waiting_for_guest" | "active" | "expired") {
  return {
    room_code: "ABC123",
    status,
    player_id: "player_1",
    player_token: "host-token",
    match_id: status === "active" ? "match-1" : null,
    host_name: "Host",
    guest_name: status === "active" ? "Guest" : null,
    created_at: "2026-06-17T00:00:00+00:00",
    updated_at: "2026-06-17T00:00:00+00:00",
    expires_at: "2026-06-18T00:00:00+00:00",
    host_last_seen_at: "2026-06-17T00:00:00+00:00",
    guest_last_seen_at: status === "active" ? "2026-06-17T00:00:00+00:00" : null,
    closed_at: status === "expired" ? "2026-06-17T00:01:00+00:00" : null,
    close_reason: status === "expired" ? "player_left" : null,
    match: status === "active" ? MATCH_PAYLOAD : null,
  };
}

const INSPECTION_CARDS = {
  "player_1-M001": {
    instance_id: "player_1-M001",
    owner_id: "player_1",
    orientation: "active" as const,
    face_up: true,
    card: {
      card_id: "PL-BP6-002-R",
      card_code: "PL!-bp6-002",
      image_url: null,
      name_ja: "確認メンバー",
      card_type: "member" as const,
      cost: 0,
      blade: 1,
      score: null,
      basic_hearts: { heart01: 1 },
      required_hearts: {},
      blade_heart_color_slot: null,
      special_blade_hearts: [],
      raw_effect_text_ja: "【登場】デッキの上から2枚見る。",
      text_revision_id: 1,
      raw_text_hash: "hash-source",
      work_keys: ["muse"],
      ability_bucket: "other" as const,
      effect_ids: ["PL!-bp6-002:1"],
      effect_registry_status: "supported" as const,
      effect_registry_errors: [],
    },
  },
  "player_1-M002": {
    instance_id: "player_1-M002",
    owner_id: "player_1",
    orientation: "active" as const,
    face_up: true,
    card: {
      card_id: "KEEP-001",
      card_code: "KEEP-001",
      image_url: null,
      name_ja: "候補カード",
      card_type: "member" as const,
      cost: 1,
      blade: 0,
      score: null,
      basic_hearts: {},
      required_hearts: {},
      blade_heart_color_slot: null,
      special_blade_hearts: [],
      raw_effect_text_ja: "【常時】テスト。",
      text_revision_id: 2,
      raw_text_hash: "hash-keep",
      work_keys: ["muse"],
      ability_bucket: "static_only" as const,
      effect_ids: [],
      effect_registry_status: "unregistered" as const,
      effect_registry_errors: [],
    },
  },
  "player_1-M003": {
    instance_id: "player_1-M003",
    owner_id: "player_1",
    orientation: "active" as const,
    face_up: true,
    card: {
      card_id: "REJECT-001",
      card_code: "REJECT-001",
      image_url: null,
      name_ja: "条件外カード",
      card_type: "member" as const,
      cost: 1,
      blade: 0,
      score: null,
      basic_hearts: {},
      required_hearts: {},
      blade_heart_color_slot: null,
      special_blade_hearts: [],
      raw_effect_text_ja: "【登場】テスト。",
      text_revision_id: 3,
      raw_text_hash: "hash-reject",
      work_keys: ["muse"],
      ability_bucket: "other" as const,
      effect_ids: [],
      effect_registry_status: "unregistered" as const,
      effect_registry_errors: [],
    },
  },
};

const INSPECTION_MATCH_PAYLOAD = {
  state: {
    ...MATCH_PAYLOAD.state,
    match_id: "match-inspection",
    phase: "first_main",
    revision: 3,
    active_player_id: "player_1",
    cards: INSPECTION_CARDS,
    effect_definitions: {
      "PL!-bp6-002:1": {
        effect_id: "PL!-bp6-002:1",
        card_code: "PL!-bp6-002",
        text_revision_id: 1,
        raw_text_hash: "hash-source",
        effect_index: 1,
        label_ja: "【登場】自分のデッキの上からカードを2枚見る。",
        effect_type: "triggered",
        timing: "on_play",
        trigger: "member_played",
        execution_mode: "prompt_then_resolve" as const,
        frequency_limit: "none",
        is_optional: false,
        simulation_support: "test_validated_executable",
        review_status: "test_validated",
      },
    },
    pending_effects: [
      {
        invocation_id: "effect-001",
        effect_id: "PL!-bp6-002:1",
        source_card_instance_id: "player_1-M001",
        player_id: "player_1",
        trigger_event: "member_played",
        trigger_data: {},
        resolution_stage: "after_cost" as const,
      },
    ],
    pending_choice: {
      choice_type: "effect_inspection_selection" as const,
      player_id: "player_1",
      message_ja: "確認したカードの処理を選んでください。",
      message_zh: "请选择检查后的卡牌处理结果。",
      options: {
        invocation_id: "effect-001",
        effect_id: "PL!-bp6-002:1",
        source_card_instance_id: "player_1-M001",
        inspected_card_instance_ids: ["player_1-M002", "player_1-M003"],
        candidate_card_instance_ids: ["player_1-M002"],
        minimum: 0,
        maximum: 1,
        requires_order: false,
        selected_destination: "hand",
        unselected_destination: "waiting_room",
        reveal_selected_to_opponent: true,
      },
    },
  },
  events: [],
  legal_actions: [
    {
      action_type: "resolve_effect_choice",
      player_id: "player_1",
      label_zh: "提交技能检查结果",
      label_ja: "能力による確認結果を確定",
      options: {
        invocation_id: "effect-001",
        effect_id: "PL!-bp6-002:1",
        source_card_instance_id: "player_1-M001",
        inspected_card_instance_ids: ["player_1-M002", "player_1-M003"],
        candidate_card_instance_ids: ["player_1-M002"],
        minimum: 0,
        maximum: 1,
        requires_order: false,
        selected_destination: "hand",
        unselected_destination: "waiting_room",
        reveal_selected_to_opponent: true,
      },
    },
  ],
};

function createPlayerState(playerId: string, name: string) {
  return {
    player_id: playerId,
    name,
    main_deck: [],
    energy_deck: [],
    hand: [],
    member_area: { left: null, center: null, right: null },
    member_area_attachments: { left: [], center: [], right: [] },
    member_areas_entered_this_turn: [],
    member_areas_moved_this_turn: [],
    energy_area: [],
    live_area: [],
    waiting_room: [],
    resolution_area: [],
    success_live_area: [],
    manual_modifiers: [],
    refresh_count: 0,
    live_result: {
      blade_count: 0,
      revealed_instance_ids: [],
      member_hearts: {},
      manual_hearts: {},
      yell_hearts: {},
      available_hearts: {},
      all_color_hearts: 0,
      special_blade_heart_results: [],
      draw_count: 0,
      live_allocations: [],
      score_bonus: 0,
      base_score: 0,
      requirements_satisfied: null,
      total_score: 0,
    },
  };
}

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    json: async () => data,
  } as Response;
}

function createFetchMock(overrides: {
  matches?: unknown;
  savedDecks?: unknown;
  matchCreate?: unknown;
  matchAction?: unknown;
  runtimeConfig?: unknown;
  roomCreate?: unknown;
  roomPoll?: unknown;
  roomLeave?: unknown;
  catalogCards?: unknown;
  catalogDetail?: unknown;
  catalogFacets?: unknown;
  reviewCandidates?: unknown;
  deckAnalysis?: unknown;
  savedDeckGet?: unknown;
  deckSaveResponse?: unknown;
  deckShareUpload?: unknown;
  deckShareDownload?: unknown;
  adminStorage?: unknown;
  adminCleanup?: unknown;
  adminDeckShares?: unknown;
  adminProgress?: unknown;
}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input.toString();
    const parsedUrl = new URL(url, "http://localhost");
    const path = `${parsedUrl.pathname}${parsedUrl.search}`;
    const method = init?.method ?? "GET";
    if (url === "runtime-config.json" && method === "GET") {
      return jsonResponse(
        overrides.runtimeConfig ?? {
          mode: "release",
          browserPreview: false,
          apiBaseUrl: "",
          publicMatchHistory: true,
          cardDatabaseFingerprint: "",
        },
      );
    }
    if (path === "/api/matches" && method === "GET") {
      return jsonResponse(overrides.matches ?? []);
    }
    if (path === "/api/matches" && method === "POST") {
      return jsonResponse(overrides.matchCreate ?? MATCH_PAYLOAD);
    }
    if (path.startsWith("/api/matches/") && path.endsWith("/actions") && method === "POST") {
      return jsonResponse(overrides.matchAction ?? MATCH_PAYLOAD);
    }
    if (path === "/api/rooms" && method === "POST") {
      return jsonResponse(overrides.roomCreate ?? roomPayload("waiting_for_guest"));
    }
    if (path.startsWith("/api/rooms/") && path.includes("/leave") && method === "POST") {
      return jsonResponse(overrides.roomLeave ?? roomPayload("expired"));
    }
    if (path.startsWith("/api/rooms/") && method === "GET") {
      return jsonResponse(overrides.roomPoll ?? roomPayload("active"));
    }
    if (path === "/api/deck-shares" && method === "POST") {
      return jsonResponse(
        overrides.deckShareUpload ?? {
          share_id: "11111111-1111-4111-8111-111111111111",
          deck: SAMPLE_DECK,
          created_at: "2026-06-19T00:00:00+00:00",
        },
      );
    }
    if (path.startsWith("/api/deck-shares/") && method === "GET") {
      return jsonResponse(
        overrides.deckShareDownload ?? {
          share_id: path.split("/").pop(),
          deck: SAMPLE_DECK,
          created_at: "2026-06-19T00:00:00+00:00",
        },
      );
    }
    if (path === "/api/admin/runtime/storage" && method === "GET") {
      return jsonResponse(overrides.adminStorage ?? { file_bytes: 123, matches: { rows: 1 } });
    }
    if (path === "/api/admin/runtime/cleanup" && method === "POST") {
      return jsonResponse(
        overrides.adminCleanup ?? {
          deleted_count: 0,
          storage: overrides.adminStorage ?? { file_bytes: 100, matches: { rows: 0 } },
        },
      );
    }
    if (path === "/api/admin/deck-shares" && method === "GET") {
      return jsonResponse(overrides.adminDeckShares ?? { items: [], total: 0 });
    }
    if (path === "/api/admin/runtime/progress" && method === "GET") {
      return jsonResponse(overrides.adminProgress ?? { total_matches: 0, phase_distribution: [] });
    }
    if (path === "/api/decks" && method === "GET") {
      return jsonResponse(
        overrides.savedDecks ?? [
          {
            name: "Test Deck",
            path: "data/decks/test.json",
            version: "decklist.v0",
            main_card_count: 0,
            energy_card_count: 0,
          },
        ],
      );
    }
    if (path === "/api/decks/analyze" && method === "POST") {
      return jsonResponse(overrides.deckAnalysis ?? ANALYSIS_RESPONSE);
    }
    if (path === "/api/decks" && method === "POST") {
      return jsonResponse(
        overrides.deckSaveResponse ?? {
          path: "data/decks/test.json",
          deck: {
            version: "decklist.v0",
            name: "Test Deck",
            main_deck: [
              {
                card_code: "LL-TEST-001",
                quantity: 1,
                preferred_printing_id: "LL-TEST-001-PR",
              },
            ],
            energy_deck: [],
          },
        },
      );
    }
    if (path.startsWith("/api/decks/")) {
      if (method === "GET") {
        return jsonResponse(overrides.savedDeckGet ?? SAMPLE_DECK);
      }
      if (method === "PUT" || method === "POST" || method === "DELETE") {
        return jsonResponse({ status: "ok", path: "data/decks/test.json", deck: SAMPLE_DECK });
      }
    }
    if (path.startsWith("/api/catalog/facets")) {
      return jsonResponse(
        overrides.catalogFacets ?? {
          works: [{ work_key: "love_live", canonical_name_ja: "ラブライブ！" }],
          units: [{ unit_key: "muse", canonical_name_ja: "μ's" }],
        },
      );
    }
    if (path.startsWith("/api/catalog/cards/")) {
      return jsonResponse(overrides.catalogDetail ?? CATALOG_DETAIL);
    }
    if (path.startsWith("/api/catalog/cards?")) {
      return jsonResponse(
        overrides.catalogCards ?? {
          items: [CATALOG_SUMMARY],
          total: 1,
          limit: 80,
          offset: 0,
        },
      );
    }
    if (path.startsWith("/api/catalog/review-candidates")) {
      return jsonResponse(
        overrides.reviewCandidates ?? { items: [], total: 0, limit: 100, offset: 0 },
      );
    }
    return jsonResponse([]);
  });
}

function seedSavedDecks(decks: Array<{ path: string; deck: DeckList }>): void {
  localStorage.setItem(
    "loveca-browser-deck-library.v0",
    JSON.stringify({
      version: "loveca-browser-deck-library.v0",
      decks: decks.map((item) => ({
        ...item,
        updated_at: "2026-06-16T00:00:00.000Z",
      })),
    }),
  );
}

function stubMobileViewport(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

describe("App", () => {
  beforeEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    resetRuntimeConfigForTests();
    localStorage.clear();
    window.history.pushState({}, "", "/");
    localStorage.setItem("loveca-ui-locale", "zh");
    vi.stubGlobal("fetch", createFetchMock({}));
  });

  it("defaults to Japanese and opens the alpha notice before the usage guide", async () => {
    localStorage.removeItem("loveca-ui-locale");

    render(<App />);

    expect(screen.getByText("LoveCA ルール検証ツール")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "Alpha 版のご案内" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "カードを閲覧" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "始める" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Alpha 版のご案内" })).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("dialog", { name: "まず下のボタンを見ます" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "使い方を閉じる" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "まず下のボタンを見ます" })).not.toBeInTheDocument(),
    );
  });

  it("renders the local match creation workflow", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);

    render(<App />);

    expect(screen.getByText("创建规则验证对局")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    expect(screen.getAllByText("Test Deck").length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText("自动生成")).toHaveValue("");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("runtime-config.json", expect.anything()));
    expect(
      vi.mocked(fetch).mock.calls.some(
        ([input]) => input.toString().startsWith("/api/matches"),
      ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "读取" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/matches?page=1&per_page=10",
        expect.anything(),
      ),
    );
  });

  it("does not request match history in browser preview without a hosted API", async () => {
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "preview",
        browserPreview: true,
        apiBaseUrl: "",
        publicMatchHistory: false,
        cardDatabaseFingerprint: "",
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("runtime-config.json", expect.anything()),
    );
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          new URL(input.toString(), "http://localhost").pathname === "/api/matches"
          && (init?.method ?? "GET") === "GET",
      ),
    ).toBe(false);
  });

  it("loads saved deck sources on the browser preview start screen", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "preview",
        browserPreview: true,
        apiBaseUrl: "",
        publicMatchHistory: false,
        cardDatabaseFingerprint: "",
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    expect(screen.getAllByText("Test Deck").length).toBeGreaterThan(0);
    expect(
      fetchMock.mock.calls.some(
        ([input]) => input.toString().startsWith("/api/matches"),
      ),
    ).toBe(false);
  });

  it("opens the SPA admin console and calls the hosted admin API from runtime config", async () => {
    const runtimeConfig = {
      mode: "release",
      browserPreview: false,
      apiBaseUrl: "https://api.test",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      adminStorage: { file_bytes: 456, matches: { rows: 2 } },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "管理" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "管理" }));
    expect(screen.getByText("管理者认证")).toBeInTheDocument();
    expect(screen.getByLabelText("Admin API URL")).toHaveValue("https://api.test");
    fireEvent.change(screen.getByLabelText("Admin key"), { target: { value: "secret-key" } });
    fireEvent.click(screen.getByRole("button", { name: "认证并打开" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "https://api.test/api/admin/runtime/storage",
        expect.objectContaining({
          headers: expect.objectContaining({
            "X-LoveCA-Admin-Key": "secret-key",
          }),
        }),
      ),
    );
    expect(await screen.findByText(/file_bytes/)).toBeInTheDocument();
  });

  it("allows the Pages admin console to override the hosted API URL", async () => {
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "preview",
        browserPreview: true,
        apiBaseUrl: "",
        publicMatchHistory: false,
        cardDatabaseFingerprint: "test",
      },
      adminStorage: { file_bytes: 789, matches: { rows: 3 } },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "管理" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "管理" }));
    fireEvent.change(screen.getByLabelText("Admin API URL"), {
      target: { value: "https://api.test/" },
    });
    fireEvent.change(screen.getByLabelText("Admin key"), { target: { value: "secret-key" } });
    fireEvent.click(screen.getByRole("button", { name: "认证并打开" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "https://api.test/api/admin/runtime/storage",
        expect.objectContaining({
          headers: expect.objectContaining({
            "X-LoveCA-Admin-Key": "secret-key",
          }),
        }),
      ),
    );
    expect(localStorage.getItem("loveca-api-base-url-override.v0")).toBe("https://api.test");
  });

  it("opens the Pages admin console from query parameters", async () => {
    window.history.pushState(
      {},
      "",
      "/?admin=1&adminApiBaseUrl=https%3A%2F%2Fapi.test",
    );
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "preview",
        browserPreview: true,
        apiBaseUrl: "",
        publicMatchHistory: false,
        cardDatabaseFingerprint: "test",
      },
      adminStorage: { file_bytes: 901, matches: { rows: 4 } },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("管理者认证")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Admin API URL")).toHaveValue("https://api.test"),
    );
    fireEvent.change(screen.getByLabelText("Admin key"), { target: { value: "secret-key" } });
    fireEvent.click(screen.getByRole("button", { name: "认证并打开" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "https://api.test/api/admin/runtime/storage",
        expect.objectContaining({
          headers: expect.objectContaining({
            "X-LoveCA-Admin-Key": "secret-key",
          }),
        }),
      ),
    );
  });

  it("creates a match with inline deck payloads instead of a hardcoded deck path", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const fetchMock = createFetchMock({});
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/matches",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const matchCreateCall = fetchMock.mock.calls.find(
      ([input, init]) => input.toString() === "/api/matches" && init?.method === "POST",
    );
    expect(matchCreateCall).toBeTruthy();
    const requestBody = JSON.parse(String(matchCreateCall?.[1]?.body));
    expect(requestBody.player_1.deck).toEqual(SAMPLE_DECK);
    expect(requestBody.player_2.deck).toEqual(SAMPLE_DECK);
    expect(requestBody.player_1.deck_path).toBeUndefined();
    expect(requestBody.player_2.deck_path).toBeUndefined();
  });

  it("passes the simple AI controller when the computer match mode is selected", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const fetchMock = createFetchMock({});
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "对电脑" }));
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/matches",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const matchCreateCall = fetchMock.mock.calls.find(
      ([input, init]) => input.toString() === "/api/matches" && init?.method === "POST",
    );
    const requestBody = JSON.parse(String(matchCreateCall?.[1]?.body));
    expect(requestBody.controllers).toEqual({
      player_1: "human",
      player_2: "simple_ai",
    });
  });

  it.each([
    ["no_safe_ai_action", "电脑找不到可安全执行的合法操作。"],
    ["overlap_source_requires_manual_review", "重叠登场涉及未确认能力，电脑已暂停，请手动确认。"],
  ])("shows persisted simple AI blocker context and a recovery action: %s", async (reason, summary) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const blockedMatch = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        revision: 9,
        phase: "first_main",
        active_player_id: "player_1",
        controllers: { player_1: "human", player_2: "simple_ai" },
      },
      events: [
        {
          event_type: "ai_blocked",
          player_id: "player_2",
          source: "system",
          data: {
            reason,
            state_revision: 9,
            phase: "first_main",
            turn_number: 1,
            pending_effects: [
              {
                source_card_name_ja: "安養寺 姫芽",
                trigger: "activated",
                timing: "activated",
                label_ja: "【起動】テスト能力",
              },
            ],
            pending_choice: null,
          },
        },
      ],
      legal_actions: [
        {
          action_type: "end_main_phase",
          player_id: "player_1",
          label_zh: "结束主要阶段",
          label_ja: "メインフェイズを終了",
          options: {},
        },
      ],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate: blockedMatch }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "对电脑" }));
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    expect(
      await screen.findByText(summary),
    ).toBeInTheDocument();
    expect(screen.getByText("安養寺 姫芽 · activated · 【起動】テスト能力")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看可处理操作" })).toBeInTheDocument();
  });

  it("explains that an incompatible ruleset is read-only in both languages", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    vi.stubGlobal("fetch", createFetchMock({ matchCreate: {
      ...MATCH_PAYLOAD,
      ruleset_compatibility: {
        can_execute: false, status: "ruleset_mismatch", mismatches: ["ruleset_fingerprint"],
      },
    } }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("规则版本不兼容，此对局仅供查看");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByRole("alert")).toHaveTextContent("この対戦は閲覧専用です");
  });

  it("shows a localized concise Simple AI decision reason", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "first_main",
        active_player_id: "player_1",
        controllers: { player_1: "human", player_2: "simple_ai" },
        controller_policy_versions: { player_2: "simple_ai_v1" },
      },
      events: [
        {
          event_type: "ai_action_selected",
          player_id: "player_2",
          source: "system",
          data: {
            action_type: "play_member",
            reason: "play_member_for_live_plan",
            policy_version: "simple_ai_v1",
          },
        },
      ],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "对电脑" }));
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    expect(
      await screen.findByText("选择 · play_member · 按当前 Live 计划登场"),
    ).toBeInTheDocument();
  });

  it("localizes the experimental AI resource-cycle reason", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "ai_action_selected", player_id: "player_1", source: "system",
      data: { action_type: "set_live_cards", reason: "cycle_spare_members_to_find_live",
        policy_version: "simple_ai_v1_2" },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await screen.findByText("选择 · set_live_cards · 用富余 Member 换牌寻找 Live");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByText("選択 · set_live_cards · 余剰メンバーをセットして Live を探す"))
      .toBeInTheDocument();
  });

  it("hides the opponent hand on the match board by default", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const ownHandId = "player_1-H001";
    const opponentHandId = "player_2-H001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        players: {
          player_1: {
            ...createPlayerState("player_1", "Player 1"),
            hand: [ownHandId],
          },
          player_2: {
            ...createPlayerState("player_2", "Player 2"),
            hand: [opponentHandId],
          },
        },
        cards: {
          [ownHandId]: {
            instance_id: ownHandId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "自分の手札" },
          },
          [opponentHandId]: {
            instance_id: opponentHandId,
            owner_id: "player_2",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "相手の秘密手札" },
          },
        },
      },
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getAllByText("自分の手札").length).toBeGreaterThan(0));
    expect(screen.queryByText("相手の秘密手札")).not.toBeInTheDocument();
    expect(screen.getByLabelText("隐藏的对手手牌")).toBeInTheDocument();
  });

  it("shows revealed card snapshots even when the card is hidden from state", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = {
      ...MATCH_PAYLOAD,
      events: [
        {
          event_type: "effect_resolved",
          player_id: "player_2",
          source: "player",
          data: {
            reveal_selected_to_opponent: true,
            revealed_cards: [
              {
                instance_id: "player_2-secret-reveal",
                owner_id: "player_2",
                card_code: "TEST-REVEAL-001",
                card_id: "TEST-REVEAL-001-R",
                name_ja: "公開テストカード",
                card_type: "member",
                image_url: null,
              },
            ],
          },
        },
      ],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getByText("公开卡牌")).toBeInTheDocument());
    expect(screen.getByText("公開テストカード")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /公開テストカード/ }));
    expect(screen.getByRole("heading", { name: "公開テストカード" })).toBeInTheDocument();
  });

  it("shows a readable reason for unsupported overlap observers", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "effect_not_activatable", player_id: "player_1", source: "system",
      data: { effect_id: "AUDIT", reason: "overlap_entry_observer_requires_timing_review" },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await waitFor(() => expect(screen.getByText("技能未自动处理")).toBeInTheDocument());
    expect(screen.getByText("该登场观察者的重叠时点尚待审核，请手动确认。")).toBeInTheDocument();
  });

  it.each([
    ["energy_deck_insufficient_at_resolution", "结算时能量牌库不足，未放置能量。",
      "解決時にエネルギーデッキが足りないため、エネルギーを置きませんでした。"],
    ["overlap_source_member_departed", "来源 Member 已离场，此加成不作用于控室或重新登场的卡牌。",
      "誘発元のメンバーは一度ステージを離れたため、控え室や再登場したカードには加算しません。"],
    ["original_source_stage_member_departed", "来源 Member 曾离开 Stage，不复原控室或重新登场的卡牌；能力已结束。",
      "誘発元が一度ステージを離れたため、控え室や再登場したカードをアクティブにせず解決しました。"],
    ["original_source_stage_member_departed", "来源 Member 曾离开 Stage，不向控室或重新登场的卡牌添加 Heart；能力已结束。",
      "誘発元が一度ステージを離れたため、控え室や再登場したカードにハートを加えず解決しました。", "gain_heart"],
    ["original_source_stage_member_departed", "来源 Member 曾离开 Stage，不向控室或重新登场的卡牌添加 Blade；能力已结束。",
      "誘発元が一度ステージを離れたため、控え室や再登場したカードにブレードを加えず解決しました。", "gain_blade"],
    ["no_legal_stage_member_at_resolution", "结算时没有合法的场上 Member，此项效果不适用，能力已结束。",
      "解決時に対象にできるメンバーがいないため、この効果を適用せず解決しました。"],
  ])("shows why a triggered operation did not apply (%s)", async (reason, zh, ja, operation = "") => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "effect_operation_not_applied", player_id: "player_1", source: "system",
      data: { effect_id: "AUDIT-result", reason, operation },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await waitFor(() => expect(screen.getByText("技能部分未执行")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("自动效果结果")).toBeInTheDocument());
    expect(screen.getAllByText(zh).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getAllByText(ja).length)
      .toBeGreaterThan(0);
  });

  it.each([true, false])("shows the moved-source ready result (%s)", async (changed) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "effect_source_member_readied", player_id: "player_1", source: "system",
      data: { effect_id: "PL!SP-bp7-008:2", changed },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    await waitFor(() => expect(screen.getByText("自动效果结果")).toBeInTheDocument());
    expect(screen.getAllByText(changed ? "移动触发：原来源 Member 已变为 Active。" : "原来源 Member 已是 Active，能力正常结束。").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getAllByText(changed ? "エリア移動で誘発し、元のメンバーをアクティブにしました。" : "元のメンバーは既にアクティブです。能力を解決しました。").length).toBeGreaterThan(0);
  });

  it("explains departure modifier cleanup without exposing modifier payloads", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "stage_card_modifiers_cleared", player_id: "player_1", source: "system",
      data: { reason: "member_replaced", removed_count: 2 },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await screen.findByText("卡牌离开 Stage，解除 2 项卡牌专属补正。");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByText("ステージを離れたカードの補正を2件解除しました。"))
      .toBeInTheDocument();
  });

  it.each(["effect:PL!N-pb1-012:1", "energy_phase"])("only shows an Energy result notice for an effect (%s)", async (reason) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const matchCreate = { ...MATCH_PAYLOAD, events: [{
      event_type: "energy_added", player_id: "player_1", source: "system",
      data: { reason, instance_ids: ["energy-public"], orientation: "wait" },
    }] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await screen.findAllByText("第 1 回合");
    if (reason.startsWith("effect:")) {
      await waitFor(() => expect(screen.getByText("能量补充 WAIT: 1")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "日本語" }));
      expect(screen.getByText("エネルギー追加 WAIT: 1")).toBeInTheDocument();
    } else {
      expect(screen.queryByText("自动效果结果")).not.toBeInTheDocument();
    }
  });

  it("lets the local player expand their waiting room", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const waitingId = "player_1-W001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        players: {
          player_1: {
            ...createPlayerState("player_1", "Player 1"),
            waiting_room: [waitingId],
          },
          player_2: createPlayerState("player_2", "Player 2"),
        },
        cards: {
          [waitingId]: {
            instance_id: waitingId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "控室確認カード" },
          },
        },
      },
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getAllByText("查看控室").length).toBeGreaterThan(0));
    const viewer = container.querySelector(".waiting-room-viewer") as HTMLDetailsElement;
    expect(viewer.open).toBe(false);
    fireEvent.click(screen.getAllByText("查看控室")[0]);
    expect(viewer.open).toBe(true);
    expect(screen.getAllByText("控室確認カード").length).toBeGreaterThan(0);
  });

  it("lets the local player inspect the opponent waiting room from the mobile opponent panel", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const waitingId = "player_2-W001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        players: {
          player_1: createPlayerState("player_1", "Player 1"),
          player_2: {
            ...createPlayerState("player_2", "Player 2"),
            waiting_room: [waitingId],
          },
        },
        cards: {
          [waitingId]: {
            instance_id: waitingId,
            owner_id: "player_2",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "相手控室カード" },
          },
        },
      },
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getByRole("button", { name: "对手区域" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "对手区域" }));
    await waitFor(() => expect(screen.getAllByText("相手控室カード").length).toBeGreaterThan(0));
  });

  it("switches the local visible hand to the current local operator", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const player1HandId = "player_1-H001";
    const player2HandId = "player_2-H001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        active_player_id: "player_2",
        players: {
          player_1: {
            ...createPlayerState("player_1", "Player 1"),
            hand: [player1HandId],
          },
          player_2: {
            ...createPlayerState("player_2", "Player 2"),
            hand: [player2HandId],
          },
        },
        cards: {
          [player1HandId]: {
            instance_id: player1HandId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "Player 1 hidden hand" },
          },
          [player2HandId]: {
            instance_id: player2HandId,
            owner_id: "player_2",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "Player 2 visible hand" },
          },
        },
      },
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getAllByText("Player 2 visible hand").length).toBeGreaterThan(0));
    expect(screen.queryByText("Player 1 hidden hand")).not.toBeInTheDocument();
    expect(screen.getByLabelText("隐藏的对手手牌")).toBeInTheDocument();
  });

  it("uses the single local legal-action owner as the local perspective when phase active player is absent", () => {
    expect(
      localPerspectivePlayerId(
        {
          ...MATCH_PAYLOAD.state,
          active_player_id: null,
          first_player_id: "player_1",
        },
        [
          {
            action_type: "submit_mulligan",
            player_id: "player_2",
            label_zh: "调度",
            label_ja: "引き直し",
            options: {},
          },
        ],
      ),
    ).toBe("player_2");
  });

  it("prefers the single local legal-action owner over the phase active player for local perspective", () => {
    expect(
      localPerspectivePlayerId(
        {
          ...MATCH_PAYLOAD.state,
          active_player_id: "player_1",
          first_player_id: "player_1",
        },
        [
          {
            action_type: "submit_mulligan",
            player_id: "player_2",
            label_zh: "调度",
            label_ja: "引き直し",
            options: {},
          },
        ],
      ),
    ).toBe("player_2");
  });

  it("uses a member-play style mobile confirm row for mulligan selection", () => {
    const onSubmit = vi.fn();
    render(
      <SelectionAction
        title="选择需要调度的手牌"
        ids={["player_1-M002"]}
        selected={[]}
        state={{
          ...MATCH_PAYLOAD.state,
          cards: INSPECTION_CARDS,
        } as never}
        mobileMode
        mobileHint="手牌下方的「调度候选」用于选择要换掉的手牌。"
        mobileConfirmLabel="确认调度"
        mobileSummary="可选择任意张"
        mobileEmptyLabel="不调度手牌"
        onToggle={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByText("不调度手牌")).toBeInTheDocument();
    expect(screen.getByText("可选择任意张 · 0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认调度" }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("keeps live-set card choices available inside the mobile confirm area", () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SelectionAction
        title="选择最多 3 张卡设置到 Live 区"
        ids={["player_1-M002"]}
        selected={[]}
        state={{
          ...MATCH_PAYLOAD.state,
          cards: INSPECTION_CARDS,
        } as never}
        maximum={3}
        mobileMode
        mobileInlineChoices
        mobileHint="手牌下方的「セット候補」で选择 Live 卡。"
        mobileConfirmLabel="确认设置"
        mobileSummary="可设置 0 到 3 张"
        mobileEmptyLabel="未选择 Live 卡"
        onToggle={onToggle}
        onSubmit={vi.fn()}
      />,
    );

    expect(container.querySelector(".mobile-inline-choices .selection-cards")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "候補カード" }));
    expect(onToggle).toHaveBeenCalledWith("player_1-M002");
  });

  it("closes the mobile live dialog after starting the next turn", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const turnCompletePayload = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "turn_complete",
        active_player_id: null,
        first_player_id: "player_1",
        second_player_id: "player_2",
        turn_number: 1,
      },
      legal_actions: [
        {
          action_type: "start_next_turn",
          player_id: null,
          label_zh: "开始下一回合",
          label_ja: "次のターンを開始",
          options: {},
        },
      ],
    };
    const nextTurnPayload = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "first_active",
        active_player_id: "player_1",
        first_player_id: "player_1",
        second_player_id: "player_2",
        turn_number: 2,
        revision: 1,
      },
      legal_actions: [],
    };
    const fetchMock = createFetchMock({
      matchCreate: turnCompletePayload,
      matchAction: nextTurnPayload,
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(container.querySelector(".mobile-match-dialog")).not.toBeNull());
    const dialogNextTurnButton = container.querySelector(
      ".mobile-match-dialog .primary-button",
    ) as HTMLButtonElement | null;
    expect(dialogNextTurnButton).not.toBeNull();
    fireEvent.click(dialogNextTurnButton!);

    await waitFor(() => expect(container.querySelector(".mobile-match-dialog")).toBeNull());
    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        input.toString().includes("/api/matches/match-1/actions")
        && init?.method === "POST"
      ),
    ).toBe(true);
  });

  it("confirms success Live choices inside the mobile live dialog", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const liveId = "player_1-LIVE-SUCCESS";
    const liveJudgmentPayload = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "live_judgment",
        active_player_id: null,
        first_player_id: "player_1",
        second_player_id: "player_2",
        cards: {
          [liveId]: {
            instance_id: liveId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...LIVE_SUMMARY, name_ja: "成功確認ライブ" },
          },
        },
        pending_choice: {
          choice_type: "success_live",
          player_id: "player_1",
          message_zh: "选择成功 Live",
          message_ja: "成功ライブを選択",
          options: { card_instance_ids: [liveId] },
        },
      },
      legal_actions: [
        {
          action_type: "resolve_live_requirements",
          player_id: "player_1",
          label_zh: "选择成功 Live",
          label_ja: "成功ライブを選択",
          options: { card_instance_ids: [liveId] },
        },
      ],
    };
    const fetchMock = createFetchMock({
      matchCreate: liveJudgmentPayload,
      matchAction: {
        ...liveJudgmentPayload,
        state: { ...liveJudgmentPayload.state, revision: 1 },
        legal_actions: [],
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(container.querySelector(".mobile-match-dialog")).not.toBeNull());
    expect(screen.getAllByText("成功確認ライブ").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "确认成功 Live" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/matches/match-1/actions",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining(`"success_live_instance_id":"${liveId}"`),
        }),
      ),
    );
  });

  it("keeps hand activated effects visible on mobile when member play is also legal", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const activatedCardId = "player_1-ACT001";
    const stageActivationId = "player_1-STAGE-ACT001";
    const playCandidateId = "member-a";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "first_main",
        active_player_id: "player_1",
        first_player_id: "player_1",
        second_player_id: "player_2",
        players: {
          ...MATCH_PAYLOAD.state.players,
          player_1: {
            ...createPlayerState("player_1", "Player 1"),
            hand: [activatedCardId, playCandidateId],
            member_area: { left: stageActivationId, center: null, right: null },
          },
        },
        cards: {
          [activatedCardId]: {
            instance_id: activatedCardId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: {
              ...INSPECTION_CARDS["player_1-M002"].card,
              card_code: "PL!HS-bp6-014",
              card_id: "PL!HS-bp6-014-R",
              name_ja: "起動テスト",
              raw_effect_text_ja:
                "【起動】このカードを手札から控え室に置く：カードを1枚引き、ライブ終了時まで、自分のステージにいる「藤島 慈」か「大沢瑠璃乃」のうち1人は【ブレード】を得る。この能力は、このカードが手札にある場合のみ起動できる。",
              effect_ids: ["PL!HS-bp6-014:1"],
            },
          },
          [playCandidateId]: {
            instance_id: playCandidateId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: {
              ...INSPECTION_CARDS["player_1-M002"].card,
              card_code: "LL-PLAY-001",
              card_id: "LL-PLAY-001-R",
              name_ja: "登場候補",
              cost: 0,
            },
          },
          [stageActivationId]: {
            instance_id: stageActivationId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: {
              ...INSPECTION_CARDS["player_1-M002"].card,
              card_code: "LL-STAGE-ACT-001",
              card_id: "LL-STAGE-ACT-001-R",
              name_ja: "場の起動",
            },
          },
        },
        effect_definitions: {
          "PL!HS-bp6-014:1": {
            effect_id: "PL!HS-bp6-014:1",
            card_code: "PL!HS-bp6-014",
            text_revision_id: 51,
            raw_text_hash: "hash-hand-activation",
            effect_index: 1,
            label_ja:
              "【起動】このカードを手札から控え室に置く：カードを1枚引き、ライブ終了時まで、自分のステージにいる「藤島 慈」か「大沢瑠璃乃」のうち1人は【ブレード】を得る。この能力は、このカードが手札にある場合のみ起動できる。",
            effect_type: "activated",
            timing: "activated_main",
            trigger: "player_activation",
            execution_mode: "prompt_then_resolve",
            frequency_limit: "none",
            is_optional: false,
            simulation_support: "test_validated_executable",
            review_status: "test_validated",
          },
        },
      },
      legal_actions: [
        {
          action_type: "activate_effect",
          player_id: "player_1",
          label_zh: "发动技能",
          label_ja: "能力を使用",
          options: {
            activations: [
              {
                effect_id: "PL!HS-bp6-014:1",
                source_card_instance_id: activatedCardId,
                label_ja:
                  "【起動】このカードを手札から控え室に置く：カードを1枚引き、ライブ終了時まで、自分のステージにいる「藤島 慈」か「大沢瑠璃乃」のうち1人は【ブレード】を得る。この能力は、このカードが手札にある場合のみ起動できる。",
                trigger: "player_activation",
                timing: "activated_main",
                execution_mode: "prompt_then_resolve",
                frequency_limit: "none",
                simulation_support: "test_validated_executable",
              },
              {
                effect_id: "LL-STAGE-ACT-001:1",
                source_card_instance_id: stageActivationId,
                label_ja: "【起動】場にいるこのメンバーをウェイトにする。",
                trigger: "player_activation",
                timing: "activated_main",
                execution_mode: "auto_resolve",
                frequency_limit: "turn_once",
                simulation_support: "test_validated_executable",
              },
            ],
          },
        },
        {
          action_type: "play_member",
          player_id: "player_1",
          label_zh: "登场",
          label_ja: "登場",
          options: {
            active_energy_instance_ids: [],
            placements: [
              {
                card_instance_id: activatedCardId,
                slot: "right",
                payment_cost: 0,
                use_baton_touch: false,
                replaced_card_instance_id: null,
                replaced_member_cost: 0,
              },
              {
                card_instance_id: playCandidateId,
                slot: "center",
                payment_cost: 0,
                use_baton_touch: false,
                replaced_card_instance_id: null,
                replaced_member_cost: 0,
              },
            ],
          },
        },
        {
          action_type: "end_main_phase",
          player_id: "player_1",
          label_zh: "结束主要阶段",
          label_ja: "メインフェイズ終了",
          options: {},
        },
      ],
    };
    const fetchMock = createFetchMock({ matchCreate });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "起动" })).toBeInTheDocument(),
    );
    expect(container.querySelector(".mobile-skill-entry-floating")).toBeNull();
    expect(screen.getAllByRole("button", { name: "确认登场" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "登场候选" }).length).toBeGreaterThan(1);
    expect(container.querySelector(".mobile-hand-candidate-bar")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "起动" }));

    await waitFor(() => expect(container.querySelector(".mobile-action-dialog")).not.toBeNull());
    expect(screen.getByText("可发动技能")).toBeInTheDocument();
    const actionDialog = container.querySelector(".mobile-action-dialog") as HTMLElement;
    expect(actionDialog.textContent).toContain("起動テスト");
    expect(
      screen.getByText((content) => content.includes("このカードを手札から控え室に置く")),
    ).toBeInTheDocument();
  });

  it("marks registered hand activated effects as unavailable on mobile when no legal activation exists", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const activatedCardId = "player_1-ACT001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "first_main",
        active_player_id: "player_1",
        first_player_id: "player_1",
        second_player_id: "player_2",
        players: {
          ...MATCH_PAYLOAD.state.players,
          player_1: {
            ...createPlayerState("player_1", "Player 1"),
            hand: [activatedCardId],
            member_area: { left: null, center: null, right: null },
          },
        },
        cards: {
          [activatedCardId]: {
            instance_id: activatedCardId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: {
              ...INSPECTION_CARDS["player_1-M002"].card,
              card_code: "PL!HS-bp6-014",
              card_id: "PL!HS-bp6-014-R",
              name_ja: "起動テスト",
              cost: 0,
              effect_ids: ["PL!HS-bp6-014:1"],
              raw_effect_text_ja:
                "【起動】このカードを手札から控え室に置く：カードを1枚引き、ライブ終了時まで、自分のステージにいる「藤島 慈」か「大沢瑠璃乃」のうち1人は【ブレード】を得る。この能力は、このカードが手札にある場合のみ起動できる。",
            },
          },
        },
        effect_definitions: {
          "PL!HS-bp6-014:1": {
            effect_id: "PL!HS-bp6-014:1",
            card_code: "PL!HS-bp6-014",
            text_revision_id: 51,
            raw_text_hash: "hash-hand-activation",
            effect_index: 1,
            label_ja:
              "【起動】このカードを手札から控え室に置く：カードを1枚引き、ライブ終了時まで、自分のステージにいる「藤島 慈」か「大沢瑠璃乃」のうち1人は【ブレード】を得る。この能力は、このカードが手札にある場合のみ起動できる。",
            effect_type: "activated",
            timing: "activated_main",
            trigger: "player_activation",
            execution_mode: "prompt_then_resolve",
            frequency_limit: "none",
            is_optional: false,
            simulation_support: "test_validated_executable",
            review_status: "test_validated",
          },
        },
      },
      legal_actions: [
        {
          action_type: "play_member",
          player_id: "player_1",
          label_zh: "登场",
          label_ja: "登場",
          options: {
            active_energy_instance_ids: [],
            placements: [
              {
                card_instance_id: activatedCardId,
                slot: "center",
                payment_cost: 0,
                use_baton_touch: false,
                replaced_card_instance_id: null,
                replaced_member_cost: 0,
              },
            ],
          },
        },
        {
          action_type: "end_main_phase",
          player_id: "player_1",
          label_zh: "结束主要阶段",
          label_ja: "メインフェイズ終了",
          options: {},
        },
      ],
    };
    const fetchMock = createFetchMock({ matchCreate });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "确认登场" }).length).toBeGreaterThan(0),
    );
    expect(screen.getByText("不可")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "起动" })).not.toBeInTheDocument();
  });

  it("does not show the mobile skill entry for generic manual adjustment during mulligan", async () => {
    stubMobileViewport();
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const hand = MATCH_PAYLOAD.state.players.player_1.hand;
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "setup_mulligan_first",
        active_player_id: "player_1",
        pending_choice: {
          choice_type: "mulligan",
          player_id: "player_1",
          message_ja: "引き直すカードを選んでください。",
          message_zh: "请选择要调度的手牌。",
          options: { hand_instance_ids: hand },
        },
      },
      legal_actions: [
        {
          action_type: "submit_mulligan",
          player_id: "player_1",
          label_zh: "确认调度",
          label_ja: "引き直し確定",
          options: { hand_instance_ids: hand },
        },
        {
          action_type: "manual_adjustment",
          player_id: "player_1",
          label_zh: "人工规则调整",
          label_ja: "手動調整",
          options: { adjustment_types: [] },
        },
      ],
    };
    const fetchMock = createFetchMock({ matchCreate });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getByRole("button", { name: "确认调度" })).toBeInTheDocument());
    expect(container.querySelector(".mobile-skill-entry-dock")).toBeNull();
    expect(container.querySelector(".mobile-manual-adjust-fab")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /处理能力|能力を処理/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "人工规则调整" })).toBeInTheDocument();
  });

  it("shows readable prompts for automatic effects and special yell results in the event log", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const sourceId = "player_1-M001";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        cards: {
          [sourceId]: {
            instance_id: sourceId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "自動能力カード" },
          },
        },
      },
      events: [
        {
          event_type: "effect_auto_resolved",
          player_id: "player_1",
          source: "system",
          data: {
            effect_id: "LL-TEST-001:1",
            source_card_instance_id: sourceId,
          },
        },
        {
          event_type: "yell_completed",
          player_id: "player_1",
          source: "system",
          data: {
            special_blade_heart_results: [
              { card_instance_id: "yell-1", source_alt: "ドロー1", effect_type: "draw", value: 1 },
            ],
          },
        },
      ],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getByText("技能自动发动")).toBeInTheDocument());
    expect(screen.getByText("自动处理 · 自動能力カード · LL-TEST-001:1")).toBeInTheDocument();
    expect(screen.getByText("应援结算完成")).toBeInTheDocument();
    expect(screen.getByText("特殊应援: ドロー1 draw+1")).toBeInTheDocument();
  });

  it("shows the actual third-entry observer source after it has left Stage", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const sourceId = "third-entry-source";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: { ...MATCH_PAYLOAD.state,
        players: { ...MATCH_PAYLOAD.state.players, player_1: {
          ...MATCH_PAYLOAD.state.players.player_1, waiting_room: [sourceId],
        } }, cards: {
        [sourceId]: { instance_id: sourceId, owner_id: "player_1", orientation: "active",
          face_up: true, card: { ...CATALOG_DETAIL.card, card_code: "PL!N-bp3-005", name_ja: "宮下 愛" } },
      } },
      events: [{ event_type: "effect_auto_resolved", player_id: "player_1", source: "system",
        data: { effect_id: "PL!N-bp3-005:1", source_card_instance_id: sourceId } }],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const createButton = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);
    await screen.findByText("自动处理 · 宮下 愛 · PL!N-bp3-005:1");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByText("自動処理 · 宮下 愛 · PL!N-bp3-005:1")).toBeInTheDocument();
  });

  it.each([0, 1])("shows source Live score comparison results in both languages (+%s)", async (delta) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const other = delta ? 3 : 4;
    const data = { invocation_id: "blade-score", effect_id: "PL!N-bp7-027:1",
      source_card_instance_id: "player_1-M001", selected_blade: 4, other_max_blade: other,
      condition_met: delta > 0, source_available: true, score_delta: delta };
    const matchCreate = { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_blade_comparison_resolved", player_id: "player_1", source: "system", data },
      { event_type: "effect_resolved", player_id: "player_1", source: "system", data },
    ] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    expect((await screen.findAllByText(`Blade 4 / 其他最高 ${other} · 来源 Live 分数 +${delta}`)).length).toBeGreaterThan(0);
    expect(await screen.findByText("自动效果结果")).toBeInTheDocument();
    expect(await screen.findByText(delta ? "条件满足" : "条件未满足")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect((await screen.findAllByText(`ブレード 4 / ほかの最大 ${other} · 誘発元のスコア +${delta}`)).length).toBeGreaterThan(0);
  });

  it.each([[0, true], [1, true], [0, false]] as const)("shows milled Member Blade colors and source Heart +%s (source=%s)", async (delta, available) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const data = { invocation_id: "milled-colors", effect_id: "PL!N-bp7-020:1",
      source_card_instance_id: "player_1-M001", blade_heart_color_slots: delta || !available ? ["heart01", "heart04"] : ["heart04"],
      source_available: available, condition_met: delta > 0 || !available, heart_delta: delta, color_slot: "heart04" };
    const matchCreate = { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_milled_blade_colors_resolved", player_id: "player_1", source: "system", data },
      { event_type: "effect_auto_resolved", player_id: "player_1", source: "system", data },
    ] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    const colors = data.blade_heart_color_slots.length;
    expect((await screen.findAllByText(`Member Blade Heart ${colors} 种颜色 · 来源绿 Heart +${delta}`)).length).toBeGreaterThan(0);
    if (!available) expect(await screen.findByText("原来源角色已离场，未加成")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect((await screen.findAllByText(`メンバーのブレードハート ${colors} 色 · 誘発元の緑ハート +${delta}`)).length).toBeGreaterThan(0);
  });

  it.each([[true, 1, true], [false, 0, false], [true, 0, false]] as const)("shows conditional extra draw %s count %s", async (condition, count, discard) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const data = { effect_id: "PL!N-sd2-007:1", invocation_id: "extra-draw", condition_met: condition,
      extra_drawn_count: count, discard_required: discard };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate: { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_opponent_success_draw_resolved", player_id: "player_1", source: "system", data },
      { event_type: "effect_resolved", player_id: "player_1", source: "system", data },
    ] } }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    expect((await screen.findAllByText(`对方本回合成功：${condition ? "是" : "否"} · 追加抽 ${count} 张 · ${discard ? "需弃 1 张" : "无需弃牌"}`)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect((await screen.findAllByText(`相手の今ターン成功：${condition ? "あり" : "なし"} · 追加${count}枚ドロー · ${discard ? "手札を1枚控室へ" : "手札を控室に置かない"}`)).length).toBeGreaterThan(0);
  });

  it.each([[1, 1, true], [1, 0, false], [0, 0, true]] as const)("shows bottom Live Heart result count %s delta %s", async (count, delta, available) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const data = { effect_id: "PL!S-bp7-015:1", invocation_id: "bottom-heart", source_card_instance_id: "player_1-M001",
      source_available: available, condition_met: delta > 0 || !available, heart_delta: delta, milled_count: count };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate: { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_bottom_live_heart_resolved", player_id: "player_1", source: "system", data },
      { event_type: "effect_auto_resolved", player_id: "player_1", source: "system", data },
    ] } }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    expect((await screen.findAllByText(`牌库底 ${count} 张置控室 · 原来源红 Heart +${delta}`)).length).toBeGreaterThan(0);
    if (!available) expect(await screen.findByText("原来源角色已离场，未加成")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect((await screen.findAllByText(`デッキの下から${count}枚を控室へ · 元の発生源の赤ハート +${delta}`)).length).toBeGreaterThan(0);
  });

  it.each([[1, true], [0, true], [0, false]] as const)("shows granted Muse aura result %s source %s", async (delta, available) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const data = { effect_id: "PL!-pb2-005:1", invocation_id: "aura", source_card_instance_id: "player_1-M001",
      source_available: available, condition_met: delta > 0 || !available, aura_delta: delta };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate: { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_muse_blade_aura_resolved", player_id: "player_1", source: "system", data },
      { event_type: "effect_auto_resolved", player_id: "player_1", source: "system", data },
    ] } }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    const zh = delta ? "μ's角色常时Blade +1 · 来源在场期间，至Live结束" : available
      ? "成功区条件未满足，未获得常时能力" : "原来源角色已离场，未获得常时能力";
    expect((await screen.findAllByText(zh)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    const ja = delta ? "μ'sメンバー常時ブレード +1 · 発生源がステージにいる間、ライブ終了時まで" : available
      ? "成功置き場の条件を満たさず、常時能力を得ない" : "元の発生源が離れ、常時能力を得ない";
    expect((await screen.findAllByText(ja)).length).toBeGreaterThan(0);
  });

  it.each([0, 1])("shows simultaneous Waiting Room Live recovery counts (%s)", async (count) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const data = { invocation_id: "both-recovery", effect_id: "PL!N-bp4-007:1",
      card_instance_ids_by_player: { player_1: count ? ["returned-1"] : [], player_2: ["returned-2"] } };
    const matchCreate = { ...MATCH_PAYLOAD, events: [
      { event_type: "effect_waiting_lives_recovered", player_id: "player_1", source: "system", data },
      { event_type: "effect_resolved", player_id: "player_1", source: "system", data },
    ] };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    const expected = `${MATCH_PAYLOAD.state.players.player_1.name}: ${count} Live / ${MATCH_PAYLOAD.state.players.player_2.name}: 1 Live`;
    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
  });

  it("shows an automatic result notice for milled cards even when the conditional follow-up does not happen", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const sourceId = "player_1-M001";
    const milledIds = ["player_1-milled-1", "player_1-milled-2", "player_1-milled-3"];
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        cards: {
          ...MATCH_PAYLOAD.state.cards,
          [sourceId]: {
            instance_id: sourceId,
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "自動判定カード" },
          },
          [milledIds[0]]: {
            instance_id: milledIds[0],
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, card_type: "member", name_ja: "ミルメンバーA" },
          },
          [milledIds[1]]: {
            instance_id: milledIds[1],
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, card_type: "member", name_ja: "ミルメンバーB" },
          },
          [milledIds[2]]: {
            instance_id: milledIds[2],
            owner_id: "player_1",
            orientation: "active",
            face_up: true,
            card: { ...CATALOG_DETAIL.card, card_type: "live", name_ja: "ミルLive" },
          },
        },
      },
      events: [
        {
          event_type: "effect_cards_milled",
          player_id: "player_1",
          source: "system",
          data: {
            invocation_id: "auto-result-test",
            effect_id: "LL-TEST-MILL:1",
            milled_card_instance_ids: milledIds,
          },
        },
        {
          event_type: "effect_auto_resolved",
          player_id: "player_1",
          source: "system",
          data: {
            invocation_id: "auto-result-test",
            effect_id: "LL-TEST-MILL:1",
            source_card_instance_id: sourceId,
          },
        },
      ],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("玩家 1 牌组")).toBeInTheDocument());
    const createButton = screen.getByRole("button", { name: "创建对局" });
    await waitFor(() => expect(createButton).not.toBeDisabled());
    fireEvent.click(createButton);

    await waitFor(() => expect(screen.getByText("自动效果结果")).toBeInTheDocument());
    expect(screen.getByText("自動判定カード · LL-TEST-MILL:1")).toBeInTheDocument();
    expect(screen.getByText("送入控室: ミルメンバーA / ミルメンバーB / ミルLive")).toBeInTheDocument();
    expect(screen.getByText("追加处理: 无")).toBeInTheDocument();
    expect(screen.getAllByText("ミルLive").length).toBeGreaterThan(0);
  });

  it.each(["zh", "ja"])("explains attachment promotion without implying an on-play trigger (%s)", async (locale) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const id = "promoted-member";
    const matchCreate = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        cards: {
          ...MATCH_PAYLOAD.state.cards,
          [id]: {
            instance_id: id, owner_id: "player_1", orientation: "active", face_up: true,
            card: { ...CATALOG_DETAIL.card, name_ja: "移動したメンバー" },
          },
        },
      },
      events: [{
        event_type: "effect_member_promoted_from_attachment", player_id: "player_1", source: "system",
        data: { invocation_id: "promotion", effect_id: "PL!-bp6-003:2", card_instance_id: id,
                source_zone: "source_attachments", slot: "right", member_area_entry_event: false },
      }],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    await screen.findByText("下方 Member 移到空区域: 移動したメンバー");
    if (locale === "ja") {
      fireEvent.click(screen.getByRole("button", { name: "日本語" }));
      expect(await screen.findByText("下のメンバーを空きエリアへ: 移動したメンバー")).toBeInTheDocument();
      expect(screen.getByText("エリア間移動のため登場能力は誘発しません")).toBeInTheDocument();
    } else {
      expect(screen.getByText("场内移动，不触发登場能力")).toBeInTheDocument();
    }
  });

  it("leaves the hosted room before returning from an online match", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = {
      mode: "release" as const,
      browserPreview: false,
      apiBaseUrl: "https://api.test",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      roomCreate: roomPayload("active"),
    });
    vi.stubGlobal("fetch", fetchMock);
    resetRuntimeConfigForTests(runtimeConfig);

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线测试房间")).toBeInTheDocument());
    const createRoomButton = screen.getByRole("button", { name: "房间创建" });
    await waitFor(() => expect(createRoomButton).not.toBeDisabled());
    fireEvent.click(createRoomButton);

    await waitFor(() => expect(screen.getByTitle("退出在线房间")).toBeInTheDocument());
    expect(screen.getByTitle("对局结束后可导出完整回放，避免泄露隐藏牌")).toBeDisabled();
    expect(screen.queryByTitle("导出在线回放 JSON")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("退出在线房间"));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "https://api.test/api/rooms/ABC123/leave",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ player_token: "host-token" }),
        }),
      ),
    );
  });

  it("enables full online replay download only after completion", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = { mode: "release" as const, browserPreview: false,
      apiBaseUrl: "https://api.test", publicMatchHistory: false, cardDatabaseFingerprint: "test" };
    const completedRoom = { ...roomPayload("active"), match: {
      ...MATCH_PAYLOAD, state: { ...MATCH_PAYLOAD.state, phase: "complete" }, legal_actions: [],
    } };
    vi.stubGlobal("fetch", createFetchMock({ runtimeConfig, roomCreate: completedRoom, roomPoll: completedRoom }));
    resetRuntimeConfigForTests(runtimeConfig);
    render(<App />);
    await waitFor(() => expect(screen.getByText("在线测试房间")).toBeInTheDocument());
    const create = screen.getByRole("button", { name: "房间创建" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    await waitFor(() => expect(screen.getByTitle("导出在线回放 JSON")).toHaveAttribute(
      "href", "https://api.test/api/rooms/ABC123/replay?player_token=host-token",
    ));
  });

  it.each([true, false])("stops corrupt-snapshot retries but keeps transient fallback (%s)", async (terminal) => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = { mode: "release" as const, browserPreview: false,
      apiBaseUrl: "https://api.test", publicMatchHistory: false, cardDatabaseFingerprint: "test" };
    const instances: MockSource[] = [];
    class MockSource extends EventTarget {
      close = vi.fn();
      onerror: ((event: Event) => void) | null = null;
      constructor() { super(); instances.push(this); }
    }
    vi.stubGlobal("EventSource", MockSource);
    vi.stubGlobal("fetch", createFetchMock({ runtimeConfig, roomCreate: roomPayload("active") }));
    resetRuntimeConfigForTests(runtimeConfig);
    const intervalSpy = vi.spyOn(window, "setInterval");
    const view = render(<App />);
    try {
      const create = await screen.findByRole("button", { name: "房间创建" });
      await waitFor(() => expect(create).not.toBeDisabled());
      fireEvent.click(create);
      await waitFor(() => expect(instances.length).toBe(1));
      const source = instances[0];
      await act(async () => {
        source.dispatchEvent(new MessageEvent("room_error", { data: JSON.stringify({
          code: terminal ? "invalid_match_snapshot" : "temporary",
          detail: "temporary room failure",
        }) }));
      });
      expect(source.close).toHaveBeenCalled();
      if (terminal) {
        expect(screen.getByText("保存的对局数据已损坏，已停止重试。请新建对局。")).toBeInTheDocument();
        await act(async () => {
          source.onerror?.(new Event("error"));
          source.dispatchEvent(new MessageEvent("room_error", { data: "temporary late failure" }));
        });
      } else {
        expect(screen.queryByText("保存的对局数据已损坏，已停止重试。请新建对局。")).not.toBeInTheDocument();
      }
      const fallbackCalls = intervalSpy.mock.calls.filter((call) => call[1] === 8000);
      expect(fallbackCalls.length).toBe(terminal ? 0 : 1);
    } finally {
      view.unmount();
      intervalSpy.mockRestore();
    }
  });

  it("stops HTTP fallback polling when the snapshot cannot be read", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = { mode: "release" as const, browserPreview: false,
      apiBaseUrl: "https://api.test", publicMatchHistory: false, cardDatabaseFingerprint: "test" };
    const base = createFetchMock({ runtimeConfig, roomCreate: roomPayload("active") });
    vi.stubGlobal("EventSource", undefined);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/rooms/ABC123") && (init?.method ?? "GET") === "GET") {
        return new Response(JSON.stringify({ code: "invalid_match_snapshot", detail: "invalid saved data" }), { status: 409 });
      }
      return base(input, init);
    }));
    resetRuntimeConfigForTests(runtimeConfig);
    const intervalSpy = vi.spyOn(window, "setInterval");
    const clearSpy = vi.spyOn(window, "clearInterval");
    const view = render(<App />);
    try {
      const create = await screen.findByRole("button", { name: "房间创建" });
      await waitFor(() => expect(create).not.toBeDisabled());
      fireEvent.click(create);
      await screen.findByText("保存的对局数据已损坏，已停止重试。请新建对局。");
      const index = intervalSpy.mock.calls.findIndex((call) => call[1] === 8000);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(clearSpy).toHaveBeenCalledWith(intervalSpy.mock.results[index].value);
    } finally {
      view.unmount();
      intervalSpy.mockRestore();
      clearSpy.mockRestore();
    }
  });

  it("shows hosted room controls for same-origin release API builds", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = {
      mode: "release" as const,
      browserPreview: false,
      apiBaseUrl: "",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      roomCreate: roomPayload("active"),
    });
    vi.stubGlobal("fetch", fetchMock);
    resetRuntimeConfigForTests(runtimeConfig);

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线测试房间")).toBeInTheDocument());
    const createRoomButton = screen.getByRole("button", { name: "房间创建" });
    await waitFor(() => expect(createRoomButton).not.toBeDisabled());
    fireEvent.click(createRoomButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/rooms",
        expect.objectContaining({
          method: "POST",
        }),
      ),
    );
  });

  it("shows a waiting dock when the online opponent must act", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = {
      mode: "release" as const,
      browserPreview: false,
      apiBaseUrl: "https://api.test",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const opponentWaitingMatch = {
      ...MATCH_PAYLOAD,
      state: {
        ...MATCH_PAYLOAD.state,
        phase: "first_main",
        active_player_id: "player_2",
      },
      legal_actions: [],
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      roomCreate: {
        ...roomPayload("active"),
        match: opponentWaitingMatch,
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    resetRuntimeConfigForTests(runtimeConfig);

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线测试房间")).toBeInTheDocument());
    const createRoomButton = screen.getByRole("button", { name: "房间创建" });
    await waitFor(() => expect(createRoomButton).not.toBeDisabled());
    fireEvent.click(createRoomButton);

    await waitFor(() => expect(screen.getByText("正在等待对手选择操作")).toBeInTheDocument());
  });

  it("sends a keepalive hosted-room leave request on page unload", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const runtimeConfig = {
      mode: "release" as const,
      browserPreview: false,
      apiBaseUrl: "https://api.test",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      roomCreate: roomPayload("active"),
    });
    vi.stubGlobal("fetch", fetchMock);
    resetRuntimeConfigForTests(runtimeConfig);
    const addEventListenerSpy = vi.spyOn(window, "addEventListener");

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线测试房间")).toBeInTheDocument());
    const createRoomButton = screen.getByRole("button", { name: "房间创建" });
    await waitFor(() => expect(createRoomButton).not.toBeDisabled());
    fireEvent.click(createRoomButton);
    await waitFor(() => expect(screen.getByTitle("退出在线房间")).toBeInTheDocument());
    await waitFor(() =>
      expect(addEventListenerSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function)),
    );

    window.dispatchEvent(new Event("beforeunload"));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "https://api.test/api/rooms/ABC123/leave",
        expect.objectContaining({
          method: "POST",
          keepalive: true,
        }),
      ),
    );
  });

  it("switches the operational UI to Japanese and persists the choice", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "日本語" }));

    expect(screen.getByText("ルール検証対戦を作成")).toBeInTheDocument();
    expect(localStorage.getItem("loveca-ui-locale")).toBe("ja");
  });

  it("renders Heart slots and effect tokens as localized color names", () => {
    expect(
      formatHeartSummary({ heart01: 2, heart04: 1, heart05: 3 }, "zh"),
    ).toBe("粉色 2 / 绿色 1 / 蓝色 3");
    expect(formatHeartSummary({ heart0: 1, heart06: 2 }, "ja")).toBe(
      "任意色 1 / 紫 2",
    );
    expect(formatEffectText("heart01を2つ、heart05を1つ得る。", "ja")).toBe(
      "ピンクを2つ、青を1つ得る。",
    );
    expect(formatEffectText("【heart01】と【heart06】を得る。", "zh")).toBe(
      "【粉色】と【紫色】を得る。",
    );
  });

  it("falls back when the previously selected Member card or area is no longer legal", () => {
    expect(availableValue("center", ["left", "right"])).toBe("left");
    expect(availableValue("member-old", ["member-new"])).toBe("member-new");
    expect(availableValue("right", ["left", "right"])).toBe("right");
  });

  it("deduplicates Member instances and prefers center, then Baton Touch", () => {
    const selection = resolveMemberPlaySelection(placements, "", "", "");

    expect(selection.memberIds).toEqual(["member-a", "member-b"]);
    expect(selection.selectedMemberId).toBe("member-a");
    expect(selection.selectedSlot).toBe("center");
    expect(selection.selectedMode).toBe("baton");
    expect(selection.placement?.payment_cost).toBe(2);
  });

  it("falls back to the next legal area when center is unavailable", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => item.slot !== "center"),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.selectedSlot).toBe("left");
    expect(selection.selectedMode).toBe("normal");
  });

  it("automatically uses normal play when Baton Touch is unavailable", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => !item.use_baton_touch),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.availableModes).toEqual(["normal"]);
    expect(selection.selectedMode).toBe("normal");
  });

  it("drops stale Member, area, and mode selections after legal actions change", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => item.card_instance_id === "member-b"),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.selectedMemberId).toBe("member-b");
    expect(selection.selectedSlot).toBe("right");
    expect(selection.selectedMode).toBe("normal");
  });

  it("keeps the chosen Member play area when switching to another legal hand card", () => {
    const onAction = vi.fn();
    const state = {
      ...MATCH_PAYLOAD.state,
      active_player_id: "player_1",
      phase: "first_main",
      cards: INSPECTION_CARDS,
      players: {
        ...MATCH_PAYLOAD.state.players,
        player_1: {
          ...createPlayerState("player_1", "Player 1"),
          hand: ["player_1-M002", "player_1-M003"],
          member_area: { left: null, center: "player_1-M001", right: null },
        },
      },
    };
    const action = {
      action_type: "play_member",
      player_id: "player_1",
      label_zh: "登场 Member",
      label_ja: "メンバーをプレイ",
      options: {
        active_energy_instance_ids: [],
        placements: [
          {
            card_instance_id: "player_1-M002",
            slot: "left",
            payment_cost: 0,
            use_baton_touch: false,
            replaced_card_instance_id: null,
            replaced_member_cost: 0,
          },
          {
            card_instance_id: "player_1-M002",
            slot: "right",
            payment_cost: 0,
            use_baton_touch: false,
            replaced_card_instance_id: null,
            replaced_member_cost: 0,
          },
          {
            card_instance_id: "player_1-M003",
            slot: "left",
            payment_cost: 0,
            use_baton_touch: false,
            replaced_card_instance_id: null,
            replaced_member_cost: 0,
          },
          {
            card_instance_id: "player_1-M003",
            slot: "right",
            payment_cost: 0,
            use_baton_touch: false,
            replaced_card_instance_id: null,
            replaced_member_cost: 0,
          },
        ],
      },
    };

    const { container } = render(
      <MemberPlayAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
      />,
    );

    const rightSlot = container.querySelector<HTMLButtonElement>(
      '.member-slot-choice[data-slot="right"]',
    );
    const nextMember = container.querySelector<HTMLButtonElement>(
      '[data-instance-id="player_1-M003"] .card-tile',
    );
    const submitButton = container.querySelector<HTMLButtonElement>(
      ".member-payment-summary .primary-button",
    );

    expect(rightSlot).not.toBeNull();
    expect(nextMember).not.toBeNull();
    expect(submitButton).not.toBeNull();

    fireEvent.click(rightSlot!);
    fireEvent.click(nextMember!);

    expect(
      container.querySelector('.member-slot-choice[data-slot="right"]'),
    ).toHaveClass("selected");

    fireEvent.click(submitButton!);

    expect(onAction).toHaveBeenCalledWith("play_member", "player_1", {
      card_instance_id: "player_1-M003",
      slot: "right",
      use_baton_touch: false,
      energy_instance_ids: [],
    });
  });

  it("requires effect card and Energy selections before resolution", () => {
    expect(canResolveEffect(1, 1, 0, 0, 0)).toBe(false);
    expect(canResolveEffect(1, 1, 1, 1, 0)).toBe(false);
    expect(canResolveEffect(1, 1, 1, 1, 1)).toBe(true);
    expect(canResolveEffect(0, 0, 0, 0, 0)).toBe(true);
    expect(canResolveEffect(1, 2, 2, 0, 0)).toBe(true);
  });

  it("shows attached Member and Energy cards under a Stage Member", () => {
    const onCard = vi.fn();
    const state = {
      cards: {
        "attached-member": {
          instance_id: "attached-member",
          owner_id: "player_1",
          orientation: "wait",
          face_up: true,
          card: {
            card_id: "member-printing",
            card_code: "member-code",
            card_type: "member",
            name_ja: "下のメンバー",
          },
        },
        "attached-energy": {
          instance_id: "attached-energy",
          owner_id: "player_1",
          orientation: "active",
          face_up: true,
          card: {
            card_id: "energy-printing",
            card_code: "energy-code",
            card_type: "energy",
            name_ja: "エネルギー",
          },
        },
      },
    };

    render(
      <StageAttachments
        ids={["attached-member", "attached-energy"]}
        state={state as never}
        onCard={onCard}
      />,
    );

    expect(screen.getByText("下方 2")).toBeInTheDocument();
    expect(screen.getByText("角色 1 · 能量 1")).toBeInTheDocument();
    screen.getByText("下のメンバー").click();
    expect(onCard).toHaveBeenCalledWith(state.cards["attached-member"]);
  });

  it("opens the catalog browser and shows a selected card detail", async () => {
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogCards: { items: [CATALOG_SUMMARY], total: 1, limit: 200, offset: 0 },
      }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "浏览卡牌库" }));

    await waitFor(() => expect(screen.getByText("全卡浏览与人工审核")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("テストカード")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("【登場】【粉色】を得る。")).toBeInTheDocument());
    expect(screen.queryByText(/heart01/)).not.toBeInTheDocument();
  });

  it("shows separate rows for distinct card ids in the catalog browser", async () => {
    const printingRows = [
      {
        ...CATALOG_SUMMARY,
        card_id: "PL!SP-bp1-032-PE",
        rarity_ja: "PE",
      },
      {
        ...CATALOG_SUMMARY,
        card_id: "PL!SP-bp1-032-PE＋",
        rarity_ja: "PE＋",
      },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      const parsedUrl = new URL(url, "http://localhost");
      const method = init?.method ?? "GET";
      if (url === "runtime-config.json" && method === "GET") {
        return jsonResponse({
          mode: "release",
          browserPreview: false,
          apiBaseUrl: "",
          publicMatchHistory: true,
          cardDatabaseFingerprint: "",
        });
      }
      if (parsedUrl.pathname === "/api/matches" && method === "GET") {
        return jsonResponse([]);
      }
      if (url === "/api/decks" && method === "GET") {
        return jsonResponse([]);
      }
      if (url.startsWith("/api/catalog/facets")) {
        return jsonResponse({ works: [], units: [] });
      }
      if (url.startsWith("/api/catalog/review-candidates")) {
        return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
      }
      if (url.startsWith("/api/catalog/cards/")) {
        return jsonResponse(CATALOG_DETAIL);
      }
      if (url.startsWith("/api/catalog/cards?")) {
        return jsonResponse({
          items: printingRows,
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "浏览卡牌库" }));

    await waitFor(() => expect(screen.getByText("全卡浏览与人工审核")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("PL!SP-bp1-032-PE")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("PL!SP-bp1-032-PE＋")).toBeInTheDocument());
  });

  it("opens the deck builder and saves a local deck", async () => {
    vi.stubGlobal("fetch", createFetchMock({}));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    expect(screen.getByText("Deck Builder 使用说明")).toBeInTheDocument();
    expect(screen.getByText("4. 查看分析结果")).toBeInTheDocument();
    expect(screen.getByText("6. 分享并进入对战")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("テストカード")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "加入主牌组" }));
    await waitFor(() => expect(screen.getAllByText("LL-TEST-001").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText("当前牌组分析")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("当前牌组不合法")).toBeInTheDocument());
    expect(screen.getByText("粉色 2")).toBeInTheDocument();
    expect(screen.getByText("任意色 3 / 紫色 1")).toBeInTheDocument();
    expect(screen.getByText("技能时点")).toBeInTheDocument();
    expect(
      screen.getByText((content) => content.includes("登場 1") && content.includes("起動 2")),
    ).toBeInTheDocument();
    expect(screen.getByText("技能处理方式")).toBeInTheDocument();
    expect(
      screen.getByText(
        (content) => content.includes("提示后处理 3") && content.includes("人工处理 1"),
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("牌组名称"), { target: { value: "Test Deck" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(screen.getByText("牌组已保存。")).toBeInTheDocument());
  });

  it("shows deck JSON import and export controls in the current deck toolbar", async () => {
    vi.stubGlobal("fetch", createFetchMock({}));

    const { container } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    const toolbar = container.querySelector(".deck-toolbar");
    expect(toolbar).toBeTruthy();
    expect(toolbar?.textContent).toContain("导入 JSON");
    expect(toolbar?.textContent).toContain("导出 JSON");
  });

  it("uploads a deck share and imports a shared deck into the local browser library", async () => {
    const runtimeConfig = {
      mode: "release" as const,
      browserPreview: false,
      apiBaseUrl: "https://api.test",
      publicMatchHistory: false,
      cardDatabaseFingerprint: "test",
    };
    const sharedDeck: DeckList = {
      version: "decklist.v0",
      name: "Shared Deck",
      main_deck: [
        {
          card_code: "LL-TEST-001",
          quantity: 1,
          preferred_printing_id: "LL-TEST-001-PR",
        },
      ],
      energy_deck: [],
    };
    const fetchMock = createFetchMock({
      runtimeConfig,
      catalogCards: { items: [CATALOG_SUMMARY], total: 1, limit: 24, offset: 0 },
      deckShareDownload: {
        share_id: "22222222-2222-4222-8222-222222222222",
        deck: sharedDeck,
        created_at: "2026-06-19T00:00:00+00:00",
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    resetRuntimeConfigForTests(runtimeConfig);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));
    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("テストカード")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "加入主牌组" }));
    fireEvent.click(screen.getByRole("button", { name: "上传分享" }));
    await waitFor(() =>
      expect(screen.getByText(/分享 UUID 已生成/)).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.test/api/deck-shares",
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.change(screen.getByPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"), {
      target: { value: "22222222-2222-4222-8222-222222222222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下载到本地" }));
    await waitFor(() =>
      expect(screen.getByText("共享牌组已下载到本地列表。")).toBeInTheDocument(),
    );
    expect(screen.getByText("Shared Deck (22222222)")).toBeInTheDocument();
  });

  it("splits the built deck into Member, Live, and compact Energy sections without thumbnails", async () => {
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogCards: {
          items: [CATALOG_SUMMARY, LIVE_SUMMARY],
          total: 2,
          limit: 24,
          offset: 0,
        },
      }),
    );

    const { container } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    const addMainButtons = await screen.findAllByRole("button", { name: "加入主牌组" });
    fireEvent.click(addMainButtons[0]);
    fireEvent.click(addMainButtons[1]);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Member 1 / 48" })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Live 1 / 12" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Energy 0 / 12" })).toBeInTheDocument();
    expect(container.querySelector(".deck-section .deck-card-thumbnail")).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "详情" })[0]);
    await waitFor(() => expect(screen.getByText("当前印刷版本")).toBeInTheDocument());
  });

  it("filters the deck-builder catalog visually and shows attribute summaries on rows", async () => {
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogCards: {
          items: [CATALOG_SUMMARY, LIVE_SUMMARY],
          total: 2,
          limit: 24,
          offset: 0,
        },
      }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("テストカード")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("テストライブ")).toBeInTheDocument());
    expect(screen.getByText("Cost 1")).toBeInTheDocument();
    expect(screen.getByText("应援棒 2")).toBeInTheDocument();
    expect(screen.getByText("基本 Heart 粉色 1")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("基本 Heart 颜色"), { target: { value: "heart01" } });
    fireEvent.change(screen.getByLabelText("角色费用最小"), { target: { value: "1" } });

    await waitFor(() => expect(screen.getAllByText("テストカード").length).toBeGreaterThan(0));
    expect(screen.queryByText("テストライブ")).not.toBeInTheDocument();
  });

  it("aggregates Member and Live catalog rows by rule card while keeping Energy rows separate", async () => {
    const duplicateMember = {
      ...CATALOG_SUMMARY,
      card_id: "LL-TEST-001-R",
      rarity_ja: "R",
    };
    const secondEnergy = {
      ...CATALOG_SUMMARY,
      card_code: "LL-ENERGY-001",
      card_id: "LL-ENERGY-001-P",
      name_ja: "エネルギーカード",
      card_type: "energy",
      rarity_ja: "P",
      cost: null,
      blade: null,
      member_blade_heart_color_slot: null,
      score: null,
      live_blade_heart_color_slot: null,
    };
    const thirdEnergy = {
      ...secondEnergy,
      card_id: "LL-ENERGY-001-R",
      rarity_ja: "R",
    };
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogCards: {
          items: [CATALOG_SUMMARY, duplicateMember, secondEnergy, thirdEnergy],
          total: 4,
          limit: 24,
          offset: 0,
        },
      }),
    );

    const { container } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    await waitFor(() => expect(container.querySelectorAll(".catalog-row").length).toBe(3));
    expect(screen.getAllByText("エネルギーカード").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("button", { name: "加入能量组" }).length).toBe(2);
  });

  it("opens an enlarged card preview from the deck builder catalog", async () => {
    vi.stubGlobal("fetch", createFetchMock({}));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "详情" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    await waitFor(() => expect(screen.getByText("当前印刷版本")).toBeInTheDocument());
    expect(screen.getByText("技能执行支持")).toBeInTheDocument();
    expect(
      screen.getByText("登場 · 提示后处理 · test_validated_executable · test_validated"),
    ).toBeInTheDocument();
    expect(screen.getByText("【登場】【粉色】を得る。")).toBeInTheDocument();
    expect(screen.getByText("【登場】【蓝色】テスト。")).toBeInTheDocument();
    expect(screen.queryByText(/heart0[1-6]/)).not.toBeInTheDocument();
    expect(screen.getAllByText("テストカード").length).toBeGreaterThan(0);
  });

  it("switches the card face printing inside the deck-builder preview dialog", async () => {
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogDetail: {
          ...CATALOG_DETAIL,
          printings: [
            ...CATALOG_DETAIL.printings,
            {
              ...CATALOG_DETAIL.printings[0],
              card_id: "LL-TEST-001-SR",
              rarity_ja: "SR",
              image_url: "https://example.test/sr.png",
            },
          ],
        },
      }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    await waitFor(() => expect(screen.getByLabelText("选择卡面")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("选择卡面"), {
      target: { value: "LL-TEST-001-SR" },
    });

    await waitFor(() =>
      expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-001-SR"),
    );
    await waitFor(() =>
      expect(screen.getByAltText("テストカード")).toHaveAttribute(
        "src",
        "/api/card-images/LL-TEST-001-SR",
      ),
    );
  });

  it("keeps an explicitly selected face when refreshed catalog data changes the default", () => {
    const detail = {
      ...CATALOG_DETAIL,
      printings: [
        ...CATALOG_DETAIL.printings,
        { ...CATALOG_DETAIL.printings[0], card_id: "LL-TEST-001-SR", rarity_ja: "SR" },
        { ...CATALOG_DETAIL.printings[0], card_id: "LL-TEST-001-R", rarity_ja: "R" },
      ],
    } as CatalogCardDetail;
    const summary = CATALOG_SUMMARY as CatalogCardSummary;
    const { rerender } = render(
      <CatalogPreviewDialog locale="zh" detail={detail} summary={summary} onClose={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("选择卡面"), {
      target: { value: "LL-TEST-001-SR" },
    });
    expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-001-SR");

    rerender(
      <CatalogPreviewDialog
        locale="zh"
        detail={{ ...detail, printings: [...detail.printings].reverse() }}
        summary={{ ...summary, card_id: "LL-TEST-001-R" }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-001-SR");
    expect(screen.getByAltText("テストカード")).toHaveAttribute(
      "src", "/api/card-images/LL-TEST-001-SR",
    );
  });

  it("uses late catalog defaults until the user explicitly picks a face", () => {
    const detail = {
      ...CATALOG_DETAIL,
      printings: [
        ...CATALOG_DETAIL.printings,
        { ...CATALOG_DETAIL.printings[0], card_id: "LL-TEST-001-SR", rarity_ja: "SR" },
      ],
    } as CatalogCardDetail;
    const { rerender } = render(
      <CatalogPreviewDialog locale="zh" detail={detail} summary={null} onClose={() => {}} />,
    );
    expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-001-PR");
    rerender(
      <CatalogPreviewDialog
        locale="zh" detail={detail}
        summary={{ ...CATALOG_SUMMARY, card_id: "LL-TEST-001-SR" } as CatalogCardSummary}
        onClose={() => {}}
      />,
    );
    expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-001-SR");
  });

  it("initializes a fresh face selection when previewing another card", () => {
    const detail = {
      ...CATALOG_DETAIL,
      printings: [
        ...CATALOG_DETAIL.printings,
        { ...CATALOG_DETAIL.printings[0], card_id: "LL-TEST-001-SR", rarity_ja: "SR" },
      ],
    } as CatalogCardDetail;
    const { rerender } = render(
      <CatalogPreviewDialog key={detail.card.card_code} locale="zh" detail={detail}
        summary={CATALOG_SUMMARY as CatalogCardSummary} onClose={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("选择卡面"), {
      target: { value: "LL-TEST-001-SR" },
    });
    const other = {
      ...detail,
      card: { ...detail.card, card_code: "LL-TEST-002", name_ja: "別のカード" },
      printings: detail.printings.map((printing) => ({
        ...printing, card_id: printing.card_id.replace("001", "002"),
      })),
    };
    rerender(
      <CatalogPreviewDialog key={other.card.card_code} locale="zh" detail={other}
        summary={null} onClose={() => {}} />,
    );
    expect(screen.getByLabelText("选择卡面")).toHaveValue("LL-TEST-002-PR");
    expect(screen.getByAltText("別のカード")).toHaveAttribute(
      "src", "/api/card-images/LL-TEST-002-PR",
    );
  });

  it("blocks adding the 49th Member card to the main deck", async () => {
    const fullMemberDeck = {
      version: "decklist.v0" as const,
      name: "Full Members",
      main_deck: Array.from({ length: 48 }, (_, index) => ({
        card_code: `LL-MEMBER-${index + 1}`,
        quantity: 1,
        preferred_printing_id: null,
      })),
      energy_deck: [],
    };
    vi.stubGlobal(
      "fetch",
      createFetchMock({}),
    );
    seedSavedDecks([{ path: "full-members.json", deck: fullMemberDeck }]);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("Full Members")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Full Members"));
    await waitFor(() => expect(screen.getAllByText("Member 48 / 48").length).toBeGreaterThan(0));
    const addButtons = screen.getAllByRole("button", { name: "加入主牌组" });
    expect(addButtons[0]).toBeDisabled();
  });

  it("allows more than four copies for energy cards", async () => {
    const energySummary = {
      ...CATALOG_SUMMARY,
      card_code: "LL-ENERGY-001",
      card_id: "LL-ENERGY-001-N",
      name_ja: "エネルギーカード",
      card_type: "energy",
      cost: null,
      blade: null,
      member_blade_heart_color_slot: null,
      score: null,
      live_blade_heart_color_slot: null,
    };
    const energyDetail = {
      ...CATALOG_DETAIL,
      card: {
        ...CATALOG_DETAIL.card,
        card_code: "LL-ENERGY-001",
        name_ja: "エネルギーカード",
        card_type: "energy",
        cost: null,
        blade: null,
        member_blade_heart_color_slot: null,
        score: null,
        live_blade_heart_color_slot: null,
      },
      printings: [
        {
          ...CATALOG_DETAIL.printings[0],
          card_id: "LL-ENERGY-001-N",
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      createFetchMock({
        catalogCards: { items: [energySummary], total: 1, limit: 24, offset: 0 },
        catalogDetail: energyDetail,
      }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    const addButton = screen.getByRole("button", { name: "加入能量组" });
    fireEvent.click(addButton);
    fireEvent.click(addButton);
    fireEvent.click(addButton);
    fireEvent.click(addButton);
    fireEvent.click(addButton);

    await waitFor(() => expect(screen.getAllByText("Energy 5 / 12").length).toBeGreaterThan(0));
    expect(addButton).not.toBeDisabled();
  });

  it("paginates the catalog card list in the deck builder", async () => {
    const fetchMock = createFetchMock({
      catalogCards: {
        items: [CATALOG_SUMMARY],
        total: 30,
        limit: 24,
        offset: 0,
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("第 1 / 2 页 · 共 30 张")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => input.toString().includes("offset=24")),
      ).toBe(true),
    );
  });

  it("sends attribute filters from the deck builder catalog", async () => {
    const fetchMock = createFetchMock({
      catalogCards: { items: [CATALOG_SUMMARY], total: 1, limit: 24, offset: 0 },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "牌组编辑器" }));

    await waitFor(() => expect(screen.getByText("牌组编辑与保存")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("基本 Heart 颜色"), { target: { value: "heart01" } });
    fireEvent.change(screen.getByLabelText("应援棒最小"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("所需 Heart 颜色"), { target: { value: "heart0" } });
    fireEvent.change(screen.getByLabelText("Score 最小"), { target: { value: "3" } });

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => {
          const url = input.toString();
          return (
            url.includes("/api/catalog/cards?") &&
            url.includes("basic_heart_color=heart01") &&
            url.includes("member_blade_min=2") &&
            url.includes("required_heart_color=heart0") &&
            url.includes("live_score_min=3")
          );
        }),
      ).toBe(true),
    );
  });

  it("sends work and unit filters from the catalog browser", async () => {
    const fetchMock = createFetchMock({
      catalogCards: { items: [CATALOG_SUMMARY], total: 1, limit: 100, offset: 0 },
      catalogDetail: {
        ...CATALOG_DETAIL,
        printings: [],
        source_observations: [],
        text_revisions: [],
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "浏览卡牌库" }));
    await waitFor(() => expect(screen.getByText("全卡浏览与人工审核")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("作品"), { target: { value: "love_live" } });
    fireEvent.change(screen.getByLabelText("组合"), { target: { value: "muse" } });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/catalog/cards?"),
        expect.anything(),
      ),
    );
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = input.toString();
        return (
          url.includes("/api/catalog/cards?") &&
          url.includes("work_key=love_live") &&
          url.includes("unit_key=muse")
        );
      }),
    ).toBe(true);
  });

  it.each([true, false])("handles the public four-card prototype condition: %s", (matched) => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    const ids = ["player_1-M002", "player_1-M003", "prototype-4", "prototype-5"];
    for (const [index, id] of ids.entries()) {
      const base = state.cards[index === 0 ? "player_1-M002" : "player_1-M003"];
      state.cards[id] = { ...base, instance_id: id, card: { ...base.card,
        name_ja: index < 2 ? base.card.name_ja : `公開Member ${index + 1}`,
        card_type: index === 0 ? "live" : "member" } };
    }
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options,
      public_reveal_policy: "public_four_lily_white_live", condition_met: matched,
      inspected_card_instance_ids: ids,
      candidate_card_instance_ids: matched ? ["player_1-M002"] : [],
      minimum: matched ? 1 : 0, maximum: matched ? 1 : 0,
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never}
      loading={false} onAction={onAction} title="公开四张" submitLabel="确认公开处理" />);
    const submit = screen.getByRole("button", { name: "确认公开处理" });
    if (matched) {
      expect(submit).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    } else {
      expect(screen.getByText("条件不成立，公开牌留在牌库原位置")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /候補カード/ })).toBeDisabled();
    }
    fireEvent.click(submit);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: matched ? ["player_1-M002"] : [], ordered_card_instance_ids: undefined,
    });
  });

  it.each([0, 1, 2])("privately keeps %s cards from the ten-minus-hand inspection", (keep) => {
    const onAction = vi.fn();
    const ids = ["player_1-M002", "player_1-M003"] as const;
    const effectId = "PL!SP-PR-028:1";
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, effect_definitions: {
      [effectId]: { ...INSPECTION_MATCH_PAYLOAD.state.effect_definitions["PL!-bp6-002:1"],
        effect_id: effectId, label_ja: "【登場】自分のデッキの上から、10から自分の手札の枚数を引いた数に等しい枚数のカードを見る。その中から2枚まで手札に加える。残りを控え室に置く。" },
    } };
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options, effect_id: effectId,
      inspected_card_instance_ids: ids, candidate_card_instance_ids: ids,
      minimum: 0, maximum: 2, requires_order: false, reveal_selected_to_opponent: false,
      selected_destination: "hand", unselected_destination: "waiting_room",
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never}
      loading={false} onAction={onAction} title="查看结果" submitLabel="确认取得" />);
    expect(screen.queryByText(/选中的卡会公开给对手/)).not.toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "确认取得" });
    expect(confirm).toBeEnabled();
    for (const id of ids.slice(0, keep)) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(INSPECTION_CARDS[id].card.name_ja) }));
    }
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: ids.slice(0, keep), ordered_card_instance_ids: undefined,
    });
  });

  it.each([10, 11])("finishes an empty private inspection with %s cards in hand", () => {
    const onAction = vi.fn();
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options, effect_id: "PL!SP-PR-028:1",
      inspected_card_instance_ids: [], candidate_card_instance_ids: [],
      minimum: 0, maximum: 0, requires_order: false, reveal_selected_to_opponent: false,
    } };
    render(<InspectionChoiceAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} title="查看结果" submitLabel="确认取得" />);
    fireEvent.click(screen.getByRole("button", { name: "确认取得" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: [], ordered_card_instance_ids: undefined,
    });
  });

  it("shows the first public recovery choice and submits only for the second chooser", () => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: {
      ...INSPECTION_MATCH_PAYLOAD.state.cards,
      "player_1-M002": { ...INSPECTION_CARDS["player_1-M002"], card: { ...INSPECTION_CARDS["player_1-M002"].card, card_type: "live" } },
      "player_1-M003": { ...INSPECTION_CARDS["player_1-M003"], owner_id: "player_2", card: { ...INSPECTION_CARDS["player_1-M003"].card, card_type: "live" } },
    } };
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], player_id: "player_2", options: {
      effect_id: "PL!N-bp4-007:1", multi_player_choice_type: "multi_player_waiting_live_recovery",
      candidate_card_instance_ids: ["player_1-M003"], minimum: 1, maximum: 1, selected_destination: "hand",
      selections: { player_1: { selected_card_instance_ids: ["player_1-M002"] } },
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never}
      loading={false} onAction={onAction} title="控室 Live" submitLabel="确认回收" />);
    expect(screen.getByText(new RegExp(`${state.players.player_1.name}: ${INSPECTION_CARDS["player_1-M002"].card.name_ja}`))).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "确认回收" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(INSPECTION_CARDS["player_1-M003"].card.name_ja) }));
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_2", {
      selected_card_instance_ids: ["player_1-M003"], ordered_card_instance_ids: undefined,
    });
  });

  it("renders structured effect inspection choices and submits the selected kept card", async () => {
    const onAction = vi.fn();
    render(
      <InspectionChoiceAction
        action={INSPECTION_MATCH_PAYLOAD.legal_actions[0] as never}
        state={INSPECTION_MATCH_PAYLOAD.state as never}
        loading={false}
        onAction={onAction}
        title="技能检查结果"
        submitLabel="确认技能处理"
      />,
    );

    expect(screen.getByText("技能检查结果")).toBeInTheDocument();
    expect(screen.getByText("確認メンバー · PL!-bp6-002:1")).toBeInTheDocument();
    expect(screen.getByText("【登場】自分のデッキの上からカードを2枚見る。")).toBeInTheDocument();
    expect(screen.getByText("候補カード")).toBeInTheDocument();
    expect(screen.getByText("条件外カード")).toBeInTheDocument();
    expect(screen.getByText("不符合条件")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "确认技能处理" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: ["player_1-M002"],
      ordered_card_instance_ids: undefined,
    });
  });

  it.each(["PL!N-sd2-009:1", "PL!N-sd2-012:1", "PL!N-sd2-014:1", "PL!N-bp7-018:1", "PL!-bp3-010:1", "PL!-bp5-014:1", "PL!-bp6-004:1", "PL!-pb1-016:1", "PL!-sd1-015:1", "PL!HS-bp2-010:1", "PL!HS-bp1-011:1", "PL!HS-bp6-022:1", "PL!HS-bp1-009:1", "PL!HS-pb1-018:1", "PL!N-bp3-012:1", "PL!SP-pb1-015:1", "PL!SP-pb1-016:1", "PL!SP-pb1-017:1", "PL!S-bp3-004:1", "PL!S-bp3-009:1", "PL!SP-bp1-005:1", "PL!SP-bp2-007:1", "PL!SP-pb2-017:1", "PL!S-pb1-013:1", "PL!S-pb1-014:1", "PL!S-pb1-015:1"])("allows keeping zero inspected cards for %s without selecting an ineligible card", (effectId) => {
    const onAction = vi.fn();
    const label = "【登場】『虹ヶ咲』のカードを1枚公開して手札に加えてもよい。";
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, effect_definitions: {
      [effectId]: { ...INSPECTION_MATCH_PAYLOAD.state.effect_definitions["PL!-bp6-002:1"], effect_id: effectId, label_ja: label },
    } };
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options, effect_id: effectId,
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never} loading={false}
      onAction={onAction} title="检查结果" submitLabel="确认检索" />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("不符合条件")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "确认检索" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: [], ordered_card_instance_ids: undefined,
    });
  });

  it.each([0, 1, 2])("allows a paid Wait inspection to return %s cards in chosen order", (keep) => {
    const onAction = vi.fn();
    const ids = ["player_1-M002", "player_1-M003"] as const;
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options,
      effect_id: "PL!-bp3-014:1", inspected_card_instance_ids: ids, candidate_card_instance_ids: ids,
      minimum: 0, maximum: 2, requires_order: true,
      selected_destination: "main_deck_top_ordered", unselected_destination: "waiting_room",
      reveal_selected_to_opponent: false,
    } };
    render(<InspectionChoiceAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} title="检查结果" submitLabel="确认排序" />);
    const confirm = screen.getByRole("button", { name: "确认排序" });
    expect(confirm).toBeEnabled();
    for (const id of ids.slice(0, keep)) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(INSPECTION_CARDS[id].card.name_ja) }));
    }
    if (keep === 2) fireEvent.click(screen.getAllByRole("button", { name: "上移已选卡" })[1]);
    fireEvent.click(confirm);
    const selected = keep === 2 ? [...ids].reverse() : ids.slice(0, keep);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: selected, ordered_card_instance_ids: selected,
    });
  });

  it("requires all four inspected cards and submits their edited deck-top order", () => {
    const onAction = vi.fn();
    const ids = ["peek-0", "peek-1", "peek-2", "peek-3"];
    const label = "【起動】【ターン1回】【E】：自分のデッキの上からカードを4枚見る。その後、それらを好きな順番でデッキの上に置く。";
    const cards = Object.fromEntries(ids.map((id, index) => [id, {
      ...INSPECTION_CARDS["player_1-M002"], instance_id: id,
      card: { ...INSPECTION_CARDS["player_1-M002"].card, name_ja: `確認${index + 1}` },
    }]));
    const state = { ...INSPECTION_MATCH_PAYLOAD.state,
      cards: { ...INSPECTION_CARDS, ...cards },
      effect_definitions: { "PL!N-bp7-006:1": {
        ...INSPECTION_MATCH_PAYLOAD.state.effect_definitions["PL!-bp6-002:1"],
        effect_id: "PL!N-bp7-006:1", label_ja: label,
      } },
    };
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      effect_id: "PL!N-bp7-006:1", source_card_instance_id: "player_1-M001",
      inspected_card_instance_ids: ids, candidate_card_instance_ids: ids,
      minimum: 4, maximum: 4, requires_order: true,
      selected_destination: "main_deck_top_ordered", reveal_selected_to_opponent: false,
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never}
      loading={false} onAction={onAction} title="检查结果" submitLabel="确认排序" />);
    expect(screen.getByText(label)).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "确认排序" });
    for (let i = 0; i < 3; i += 1) fireEvent.click(screen.getByRole("button", { name: new RegExp(`確認${i + 1}`) }));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /確認4/ }));
    expect(confirm).toBeEnabled();
    fireEvent.click(screen.getAllByRole("button", { name: "上移已选卡" })[3]);
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: ["peek-0", "peek-1", "peek-3", "peek-2"],
      ordered_card_instance_ids: ["peek-0", "peek-1", "peek-3", "peek-2"],
    });
  });

  it("requires a waiting-room member and area for simultaneous two-player deployment", () => {
    const onAction = vi.fn();
    const action = {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0],
      options: {
        multi_player_choice_type: "multi_player_deploy_waiting_member",
        deployment_policy: "simultaneous_member_area_entry",
        orientation: "wait",
        candidate_card_instance_ids: ["player_1-M002"],
        available_slots: ["left", "right"],
        minimum: 1,
        maximum: 1,
      },
    };
    const props = { state: INSPECTION_MATCH_PAYLOAD.state as never,
      loading: false, onAction, title: "双方登场", submitLabel: "确认登场" };
    const view = render(<InspectionChoiceAction {...props} action={action as never} />);
    expect(screen.getByRole("button", { name: "确认登场" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    expect(screen.getByRole("button", { name: "确认登场" })).toBeDisabled();
    const slots = screen.getByRole("group", { name: "登场区域" });
    fireEvent.click(slots.querySelectorAll("button")[1]);
    fireEvent.click(screen.getByRole("button", { name: "确认登场" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_id: "player_1-M002", slot: "right",
    });
    view.rerender(<InspectionChoiceAction {...props}
      action={{ ...action, player_id: "player_2" } as never} />);
    expect(screen.getByRole("button", { name: "确认登场" })).toBeDisabled();
    expect(screen.queryByRole("group", { name: "登场区域" })).not.toBeInTheDocument();
  });

  it.each([undefined, "__hidden__"])("keeps public deployment candidates usable with a redacted source %s", (source) => {
    const onAction = vi.fn();
    const cards = Object.fromEntries(Object.entries(INSPECTION_MATCH_PAYLOAD.state.cards)
      .filter(([id]) => id !== "player_1-M001"));
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards };
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      source_card_instance_id: source,
      multi_player_choice_type: "multi_player_deploy_waiting_member",
      candidate_card_instance_ids: ["player_1-M002"], available_slots: ["right"], minimum: 1, maximum: 1,
    } };
    render(<InspectionChoiceAction action={action as never} state={state as never}
      loading={false} onAction={onAction} title="双方登场" submitLabel="确认登场" />);
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("group", { name: "登场区域" }).querySelector("button")!);
    fireEvent.click(screen.getByRole("button", { name: "确认登场" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_id: "player_1-M002", slot: "right",
    });
  });

  it("confirms an empty multi-player deployment without inventing a target", () => {
    const onAction = vi.fn();
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      multi_player_choice_type: "multi_player_deploy_waiting_member",
      candidate_card_instance_ids: [], available_slots: [], minimum: 0, maximum: 0,
    } };
    render(<InspectionChoiceAction action={action as never}
      state={INSPECTION_MATCH_PAYLOAD.state as never} loading={false}
      onAction={onAction} title="双方登场" submitLabel="无目标确认" />);
    fireEvent.click(screen.getByRole("button", { name: "无目标确认" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {});
  });

  it("offers a manual adjustment for returning a waiting-room card to hand", () => {
    const onSubmit = vi.fn();
    const state = {
      ...MATCH_PAYLOAD.state,
      active_player_id: "player_1",
      cards: INSPECTION_CARDS,
      players: {
        ...MATCH_PAYLOAD.state.players,
        player_1: {
          ...MATCH_PAYLOAD.state.players.player_1,
          waiting_room: ["player_1-M002"],
          main_deck: ["player_1-M003"],
        },
      },
    };

    render(
      <ManualDrawer
        state={state as never}
        source={null}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("调整类型"), {
      target: { value: "return_from_waiting_room" },
    });

    const targetSelect = screen.getByLabelText("目标卡牌");
    expect(targetSelect).toHaveTextContent("候補カード");
    expect(targetSelect).not.toHaveTextContent("条件外カード");
    expect(screen.getByRole("button", { name: "提交结构化调整" })).toBeDisabled();

    fireEvent.change(targetSelect, { target: { value: "player_1-M002" } });
    fireEvent.click(screen.getByRole("button", { name: "提交结构化调整" }));

    expect(onSubmit).toHaveBeenCalledWith(
      "player_1",
      expect.objectContaining({
        adjustments: [
          expect.objectContaining({
            adjustment_type: "return_from_waiting_room",
            target_player_id: "player_1",
            target_card_instance_id: "player_1-M002",
          }),
        ],
      }),
    );
  });

  it("limits manual discard choices to cards currently in hand", () => {
    const onSubmit = vi.fn();
    const state = {
      ...MATCH_PAYLOAD.state,
      active_player_id: "player_1",
      cards: INSPECTION_CARDS,
      players: {
        ...MATCH_PAYLOAD.state.players,
        player_1: {
          ...MATCH_PAYLOAD.state.players.player_1,
          hand: ["player_1-M002"],
          main_deck: ["player_1-M003"],
          waiting_room: ["player_1-M001"],
        },
      },
    };

    render(
      <ManualDrawer
        state={state as never}
        source={null}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("调整类型"), {
      target: { value: "discard_card" },
    });

    const targetSelect = screen.getByLabelText("目标卡牌");
    expect(targetSelect).toHaveTextContent("候補カード");
    expect(targetSelect).not.toHaveTextContent("条件外カード");
    expect(targetSelect).not.toHaveTextContent("確認メンバー");
    expect(screen.getByRole("button", { name: "提交结构化调整" })).toBeDisabled();

    fireEvent.change(targetSelect, { target: { value: "player_1-M002" } });
    fireEvent.click(screen.getByRole("button", { name: "提交结构化调整" }));

    expect(onSubmit).toHaveBeenCalledWith(
      "player_1",
      expect.objectContaining({
        adjustments: [
          expect.objectContaining({
            adjustment_type: "discard_card",
            target_player_id: "player_1",
            target_card_instance_id: "player_1-M002",
          }),
        ],
      }),
    );
  });

  it("can target the opponent's public stage for formation manual adjustments", async () => {
    const onSubmit = vi.fn();
    const opponentLeft = {
      ...INSPECTION_CARDS["player_1-M002"],
      instance_id: "player_2-M101",
      owner_id: "player_2",
      card: {
        ...INSPECTION_CARDS["player_1-M002"].card,
        name_ja: "相手左メンバー",
      },
    };
    const opponentCenter = {
      ...INSPECTION_CARDS["player_1-M003"],
      instance_id: "player_2-M102",
      owner_id: "player_2",
      card: {
        ...INSPECTION_CARDS["player_1-M003"].card,
        name_ja: "相手中央メンバー",
      },
    };
    const state = {
      ...MATCH_PAYLOAD.state,
      active_player_id: "player_1",
      cards: {
        ...INSPECTION_CARDS,
        "player_2-M101": opponentLeft,
        "player_2-M102": opponentCenter,
      },
      players: {
        ...MATCH_PAYLOAD.state.players,
        player_2: {
          ...MATCH_PAYLOAD.state.players.player_2,
          member_area: {
            left: "player_2-M101",
            center: "player_2-M102",
            right: null,
          },
        },
      },
    };

    render(
      <ManualDrawer
        state={state as never}
        source={null}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("调整类型"), {
      target: { value: "formation_change" },
    });
    fireEvent.change(screen.getByLabelText("调整对象玩家"), {
      target: { value: "player_2" },
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "提交结构化调整" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "提交结构化调整" }));

    expect(onSubmit).toHaveBeenCalledWith(
      "player_1",
      expect.objectContaining({
        adjustments: [
          expect.objectContaining({
            adjustment_type: "formation_change",
            target_player_id: "player_2",
            slot_assignments: {
              left: "player_2-M101",
              center: "player_2-M102",
              right: null,
            },
          }),
        ],
      }),
    );
  });

  it("resolves optional discard-to-Wait-Energy effects without manual adjustment", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      pending_effects: [
        {
          invocation_id: "energy-effect-001",
          effect_id: "PL!SP-bp1-021:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "member_played",
          trigger_data: {},
          resolution_stage: "initial" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "energy-effect-001",
            effect_id: "PL!SP-bp1-021:1",
            source_card_instance_id: "player_1-M001",
            label_ja:
              "【登場】手札を1枚控え室に置いてもよい：自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。",
            trigger: "member_played",
            timing: "on_play",
            execution_mode: "prompt_then_resolve",
            is_optional: true,
            simulation_support: "test_validated_executable",
            candidate_card_instance_ids: ["player_1-M002"],
            card_selection_minimum: 1,
            card_selection_maximum: 1,
            choice_zone: "hand",
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    expect(screen.queryByText("结构化人工处理")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "energy-effect-001",
      accepted: true,
      selected_card_instance_ids: ["player_1-M002"],
      energy_instance_ids: [],
    });
    expect(onManual).not.toHaveBeenCalled();
  });

  it.each(["inspection_cost_candidates_unavailable", "inspection_source_not_active", "inspection_source_object_unavailable"])("can cancel an unpayable inspection without choosing a nonexistent cost: %s", (reason) => {
    const onAction = vi.fn();
    const label = "【登場】手札を1枚控え室に置く：自分のデッキの上からカードを5枚見る。";
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "effect-001", effect_id: "PL!-pb2-032:1", source_card_instance_id: "player_1-M001",
      label_ja: label, trigger: "member_played", timing: "on_play", execution_mode: "prompt_then_resolve",
      is_optional: false, simulation_support: "test_validated_executable", candidate_card_instance_ids: [],
      cost_payment_unavailable_reason: reason, resolution_stage: "initial",
    }] } };
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("无法支付费用");
    expect(screen.queryByRole("button", { name: "不使用" })).not.toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "结束此能力" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "effect-001", accepted: true, selected_card_instance_ids: [], energy_instance_ids: [],
    });
  });

  const private3FamilyEffectIds = [
    "PL!-sd1-016:1", "PL!HS-PR-001:1", "PL!HS-PR-002:1", "PL!HS-PR-005:1", "PL!HS-cl1-007:1", "PL!HS-pb1-011:1",
    "PL!N-PR-004:1", "PL!N-PR-006:1", "PL!N-PR-013:1", "PL!N-bp1-007:1", "PL!N-bp1-010:1",
    "PL!N-sd1-002:1", "PL!N-sd1-003:1", "PL!S-PR-013:1", "PL!S-PR-019:1",
  ];

  const inspectionSiblingEffectIds = ["PL!-sd1-015:1", "PL!HS-bp2-010:1", "PL!HS-bp1-011:1", "PL!HS-bp6-022:1", "PL!N-pb1-028:1", "PL!N-pb1-035:1"];
  const workUnitInspectionEffectIds = ["PL!HS-bp1-009:1", "PL!HS-pb1-018:1", "PL!N-bp3-012:1", "PL!SP-pb1-015:1", "PL!SP-pb1-016:1", "PL!SP-pb1-017:1"];
  const memberLiellaInspectionEffectIds = ["PL!S-bp3-004:1", "PL!S-bp3-009:1", "PL!SP-bp1-005:1", "PL!SP-bp2-007:1", "PL!SP-pb2-017:1"];
  const mixedHeartInspectionEffectIds = ["PL!S-pb1-013:1", "PL!S-pb1-014:1", "PL!S-pb1-015:1"];

  it("shows the exact multi-keep card text with manual control instead of automatic execution", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const source = { invocation_id: "multi-keep-review", effect_id: "PL!S-bp2-005:1", source_card_instance_id: "player_1-M001", player_id: "player_1" };
    const label = "【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを7枚見る。その中から【heart02】か【heart04】か【heart05】を持つメンバーカードを3枚まで公開して手札に加えてもよい。残りを控え室に置く。";
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, pending_effects: [source] };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      ...source, label_ja: label, trigger: "member_played", timing: "on_play", execution_mode: "manual_resolution",
      simulation_support: "manual_resolution", is_optional: true, candidate_card_instance_ids: [],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false} onAction={onAction} onManual={onManual} />);
    expect(document.body.textContent).toContain("カードを7枚見る");
    expect(document.body.textContent).toContain("メンバーカードを3枚まで");
    expect(screen.queryByRole("button", { name: "结算技能" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "结构化人工处理" }));
    expect(onManual).toHaveBeenCalledWith(source);
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "不使用" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", { invocation_id: "multi-keep-review", accepted: false });
  });

  it.each(["PL!-bp3-010:1", "PL!-bp5-014:1", "PL!-bp6-004:1", "PL!-pb1-016:1", "PL!-sd1-011:1", "PL!-sd1-012:1", ...private3FamilyEffectIds, ...inspectionSiblingEffectIds, ...workUnitInspectionEffectIds, ...memberLiellaInspectionEffectIds, ...mixedHeartInspectionEffectIds])("can explicitly end the optional unpayable hand cost for %s", (effectId) => {
    const onAction = vi.fn();
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "no-hand-cost", effect_id: effectId, source_card_instance_id: "player_1-M001",
      label_ja: "【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを見る。",
      trigger: "member_played", timing: "on_play", execution_mode: "prompt_then_resolve",
      is_optional: true, simulation_support: "test_validated_executable", candidate_card_instance_ids: [],
      cost_payment_unavailable_reason: "inspection_cost_candidates_unavailable", resolution_stage: "initial",
    }] } };
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("无法支付费用");
    const confirm = screen.getByRole("button", { name: "结束此能力" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "no-hand-cost", accepted: true, selected_card_instance_ids: [], energy_instance_ids: [],
    });
  });

  it.each(["PL!SP-bp7-018:1", "PL!-sd1-011:1", "PL!-sd1-012:1", ...private3FamilyEffectIds, "PL!N-pb1-028:1", "PL!N-pb1-035:1"])("requires exactly one private kept card after paying the cost for %s", (effectId) => {
    const onAction = vi.fn();
    const action = { ...INSPECTION_MATCH_PAYLOAD.legal_actions[0], options: {
      ...INSPECTION_MATCH_PAYLOAD.legal_actions[0].options, effect_id: effectId, minimum: 1, maximum: 1, reveal_selected_to_opponent: false,
    } };
    render(<InspectionChoiceAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} title="检查结果" submitLabel="加入手牌" />);
    const confirm = screen.getByRole("button", { name: "加入手牌" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect_choice", "player_1", {
      selected_card_instance_ids: ["player_1-M002"], ordered_card_instance_ids: undefined,
    });
  });

  it("shows a continuation hint for multi-step effects after cost handling", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      pending_effects: [
        {
          invocation_id: "after-cost-effect-001",
          effect_id: "PL!SP-bp1-021:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "member_played",
          trigger_data: {},
          resolution_stage: "after_cost" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "after-cost-effect-001",
            effect_id: "PL!SP-bp1-021:1",
            source_card_instance_id: "player_1-M001",
            label_ja: "【登場】カードを1枚引き、手札を1枚控え室に置く。",
            trigger: "member_played",
            timing: "on_play",
            execution_mode: "prompt_then_resolve",
            is_optional: false,
            simulation_support: "test_validated_executable",
            resolution_stage: "after_cost",
            candidate_card_instance_ids: ["player_1-M002"],
            card_selection_minimum: 1,
            card_selection_maximum: 1,
            choice_zone: "hand",
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    expect(
      screen.getByText("已完成发动/成本处理，继续选择后续效果。"),
    ).toBeInTheDocument();
  });

  it("requires both post-draw discards for Mia without paying the Wait cost again", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const label = "【起動】【ターン1回】このメンバーをウェイトにする：カードを2枚引き、手札を2枚控え室に置く。";
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      cards: {
        ...INSPECTION_MATCH_PAYLOAD.state.cards,
        "drawn-second": {
          ...INSPECTION_CARDS["player_1-M002"], instance_id: "drawn-second",
          card: { ...INSPECTION_CARDS["player_1-M002"].card, name_ja: "新しく引いたカード" },
        },
      },
      pending_effects: [{
        invocation_id: "mia-draw-two", effect_id: "PL!N-bp7-023:1",
        source_card_instance_id: "player_1-M001", player_id: "player_1",
        trigger_event: "player_activation", trigger_data: {}, resolution_stage: "after_cost",
      }],
    };
    const action = {
      action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
        invocation_id: "mia-draw-two", effect_id: "PL!N-bp7-023:1",
        source_card_instance_id: "player_1-M001", label_ja: label,
        trigger: "player_activation", timing: "activated_main", execution_mode: "prompt_then_resolve",
        simulation_support: "test_validated_executable", is_optional: false, resolution_stage: "after_cost",
        choice_type: "post_action_card_from_zone", choice_zone: "hand",
        card_selection_minimum: 2, card_selection_maximum: 2,
        candidate_card_instance_ids: ["player_1-M002", "drawn-second"],
      }] },
    };
    render(<EffectResolutionAction action={action as never} state={state as never}
      loading={false} onAction={onAction} onManual={onManual} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "结算技能" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /新しく引いたカード/ }));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "mia-draw-two", accepted: true,
      selected_card_instance_ids: ["player_1-M002", "drawn-second"], energy_instance_ids: [],
    });
    expect(onManual).not.toHaveBeenCalled();
  });

  it.each([1, 2])("submits conditional discard with %s hidden-source invocations", (count) => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "setsuna-extra", effect_id: "PL!N-sd2-007:1", source_card_instance_id: "hidden-source",
      label_ja: "【ライブ成功時】カードを1枚引く。このターン、相手もライブを成功している場合、さらにカードを1枚引き、手札を1枚控え室に置く。",
      trigger: "live_succeeded", timing: "live_success", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false, resolution_stage: "after_cost",
      choice_type: "post_action_card_from_zone", choice_zone: "hand", card_selection_minimum: 1,
      card_selection_maximum: 1, candidate_card_instance_ids: ["player_1-M002"],
    }] } };
    if (count === 2) action.options.invocations.push({ ...action.options.invocations[0], invocation_id: "setsuna-second", source_card_instance_id: "other-hidden-source" });
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={onManual} />);
    const confirm = screen.getByRole("button", { name: "结算技能" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "setsuna-extra", accepted: true, selected_card_instance_ids: ["player_1-M002"], energy_instance_ids: [],
    });
    expect(onManual).not.toHaveBeenCalled();
  });

  it("shows card details for duplicate waiting-room effect choices", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const duplicateA = {
      ...INSPECTION_CARDS["player_1-M002"],
      instance_id: "waiting-a",
      card: {
        ...INSPECTION_CARDS["player_1-M002"].card,
        card_id: "WAIT-A",
        card_code: "WAIT-A",
        name_ja: "同名カード",
        cost: 1,
      },
    };
    const duplicateB = {
      ...INSPECTION_CARDS["player_1-M002"],
      instance_id: "waiting-b",
      card: {
        ...INSPECTION_CARDS["player_1-M002"].card,
        card_id: "WAIT-B",
        card_code: "WAIT-B",
        name_ja: "同名カード",
        cost: 3,
      },
    };
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      cards: {
        ...INSPECTION_MATCH_PAYLOAD.state.cards,
        "waiting-a": duplicateA,
        "waiting-b": duplicateB,
      },
      players: {
        ...INSPECTION_MATCH_PAYLOAD.state.players,
        player_1: {
          ...INSPECTION_MATCH_PAYLOAD.state.players.player_1,
          waiting_room: ["waiting-a", "waiting-b"],
        },
      },
      pending_effects: [
        {
          invocation_id: "waiting-effect-001",
          effect_id: "PL!TEST-WAITING:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "member_played",
          trigger_data: {},
          resolution_stage: "initial" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "waiting-effect-001",
            effect_id: "PL!TEST-WAITING:1",
            source_card_instance_id: "player_1-M001",
            label_ja: "控室からカードを1枚選ぶ。",
            trigger: "member_played",
            timing: "on_play",
            execution_mode: "prompt_then_resolve",
            is_optional: false,
            simulation_support: "test_validated_executable",
            candidate_card_instance_ids: ["waiting-a", "waiting-b"],
            choice_type: "card_from_zone",
            card_selection_minimum: 1,
            card_selection_maximum: 1,
            choice_zone: "waiting_room",
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    expect(screen.getAllByRole("button", { name: /同名カード/ })).toHaveLength(2);
    expect(screen.getByText(/WAIT-A/)).toBeInTheDocument();
    expect(screen.getByText(/费用 1/)).toBeInTheDocument();
    expect(screen.getByText(/WAIT-B/)).toBeInTheDocument();
    expect(screen.getByText(/费用 3/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /同名カード/ })[1]);
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "waiting-effect-001",
      accepted: true,
      selected_card_instance_ids: ["waiting-b"],
      energy_instance_ids: [],
    });
    expect(onManual).not.toHaveBeenCalled();
  });

  it("submits grouped Stage Member choices and excludes prior group selections", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      pending_effects: [
        {
          invocation_id: "grouped-effect-001",
          effect_id: "PL!SP-bp4-023:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "live_started",
          trigger_data: {},
          resolution_stage: "initial" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "grouped-effect-001",
            effect_id: "PL!SP-bp4-023:1",
            source_card_instance_id: "player_1-M001",
            label_ja:
              "【ライブ開始時】ライブ終了時まで、自分のステージにいる、「澁谷かのん」「ウィーン・マルガレーテ」「鬼塚冬毬」のうちのメンバー1人と、これにより選んだメンバー以外の『Liella!』のメンバー1人は、【ブレード】を得る。",
            trigger: "live_started",
            timing: "live_start",
            execution_mode: "prompt_then_resolve",
            is_optional: false,
            simulation_support: "test_validated_executable",
            candidate_card_instance_ids: [],
            choice_type: "member_group_from_stage",
            card_selection_minimum: 0,
            card_selection_maximum: 0,
            choice_groups: [
              {
                group_id: "named_member",
                label_ja: "指定名のメンバー",
                candidate_card_instance_ids: ["player_1-M001"],
                exclude_group_ids: [],
                minimum: 1,
                maximum: 1,
              },
              {
                group_id: "other_liella",
                label_ja: "選んだメンバー以外の『Liella!』のメンバー",
                candidate_card_instance_ids: ["player_1-M001", "player_1-M002"],
                exclude_group_ids: ["named_member"],
                minimum: 1,
                maximum: 1,
              },
            ],
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: /確認メンバー/ })[0]);
    expect(screen.getAllByRole("button", { name: /確認メンバー/ })[1]).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "grouped-effect-001",
      accepted: true,
      selected_card_instance_ids: [],
      energy_instance_ids: [],
      selected_card_instance_ids_by_group: {
        named_member: ["player_1-M001"],
        other_liella: ["player_1-M002"],
      },
    });
    expect(onManual).not.toHaveBeenCalled();
  });

  it("requires and submits a branch for choose-one effects", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      pending_effects: [
        {
          invocation_id: "branch-effect-001",
          effect_id: "PL!TEST-BRANCH:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "member_played",
          trigger_data: {},
          resolution_stage: "initial" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "branch-effect-001",
            effect_id: "PL!TEST-BRANCH:1",
            source_card_instance_id: "player_1-M001",
            label_ja:
              "【登場】以下から1つを選ぶ。 ・カードを1枚引き、手札を1枚控え室に置く。 ・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。",
            trigger: "member_played",
            timing: "on_play",
            execution_mode: "prompt_then_resolve",
            is_optional: false,
            simulation_support: "test_validated_executable",
            candidate_card_instance_ids: [],
            choice_type: "choose_effect_branch",
            card_selection_minimum: 0,
            card_selection_maximum: 0,
            choice_zone: "hand",
            branch_ids: ["draw_discard", "wait_opponent_cost2"],
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "抽 1 张后弃 1 张手牌" }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "branch-effect-001",
      accepted: true,
      selected_card_instance_ids: [],
      energy_instance_ids: [],
      selected_branch: "draw_discard",
    });
  });

  it("chooses a discard cost without allowing a branch override, then resets the follow-up selection", () => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, pending_choice: null };
    const invocation = {
      invocation_id: "cost-result-001", effect_id: "PL!-bp5-003:2",
      source_card_instance_id: "player_1-M001", label_ja: "【起動】手札を1枚控え室に置く：費用により処理。",
      trigger: "player_activation", timing: "activated_main", execution_mode: "prompt_then_resolve",
      is_optional: false, simulation_support: "test_validated_executable",
      resolution_stage: "initial", choice_type: "card_from_zone", choice_zone: "hand",
      candidate_card_instance_ids: ["player_1-M002"], card_selection_minimum: 1, card_selection_maximum: 1,
      branch_from_cost: true, branch_ids: ["discarded_muse", "discarded_other"],
    };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [invocation] } };
    const { rerender } = render(<EffectResolutionAction action={action as never} state={state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /弃置 μ's/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "cost-result-001", accepted: true, selected_card_instance_ids: ["player_1-M002"], energy_instance_ids: [],
    });
    const followUp = { ...action, options: { invocations: [{ ...invocation,
      resolution_stage: "after_cost", choice_type: "choose_effect_branch", choice_zone: "waiting_room",
      candidate_card_instance_ids: ["player_1-M003"], selected_branch: "discarded_other",
    }] } };
    rerender(<EffectResolutionAction action={followUp as never} state={state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByText(/费用判定/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /弃置其他作品/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /条件外カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenLastCalledWith("resolve_effect", "player_1", {
      invocation_id: "cost-result-001", accepted: true, selected_card_instance_ids: ["player_1-M003"],
      energy_instance_ids: [], selected_branch: "discarded_other",
    });
  });

  it.each([{ slots: ["left", "right"], occupied: false }, { slots: [] as string[], occupied: false },
    { slots: ["center"], occupied: true }])("uses legal deployment areas without a manual adjustment: %j", ({ slots, occupied }) => {
    const onAction = vi.fn();
    const action = {
      action_type: "resolve_effect", player_id: "player_1", label_zh: "技能", label_ja: "能力",
      options: { invocations: [{
        invocation_id: "deploy-001", effect_id: "PL!S-sd1-006:1", source_card_instance_id: "player_1-M001",
        label_ja: "メンバーのいないエリアに登場させる。", trigger: "member_played", timing: "on_play",
        execution_mode: "prompt_then_resolve", simulation_support: "test_validated_executable",
        resolution_stage: "after_cost", is_optional: false,
        choice_type: "deploy_member_from_waiting_room", choice_zone: "waiting_room",
        card_selection_minimum: 1, card_selection_maximum: 1,
        candidate_card_instance_ids: ["player_1-M002"], deployment_choice: true,
        position_change_slots_by_candidate: { "player_1-M002": slots },
        deployment_members_by_slot: occupied ? { center: "player_1-M003" } : {},
      }] },
    };
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    expect(screen.getByText("登场区域")).toBeInTheDocument();
    if (!slots.length) {
      expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
      expect(onAction).not.toHaveBeenCalled();
      return;
    }
    fireEvent.click(screen.getByRole("button", { name: occupied ? /中.*条件外カード/ : "右" }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "deploy-001", accepted: true, selected_card_instance_ids: ["player_1-M002"],
      energy_instance_ids: [], to_slot: occupied ? "center" : "right",
    });
  });

  it.each([false, true, "none"])("submits independent named groups including absent names: %s", (partial) => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    state.cards["player_1-M002"] = { ...state.cards["player_1-M002"], card: { ...state.cards["player_1-M002"].card, name_ja: "澁谷かのん" } };
    state.cards["player_1-M003"] = { ...state.cards["player_1-M003"], card: { ...state.cards["player_1-M003"].card, name_ja: "唐 可可" } };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "named-groups", effect_id: "PL!SP-bp1-024:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】かのんと可可を1人ずつ選ぶ。", trigger: "live_started", timing: "live_start",
      execution_mode: "prompt_then_resolve", simulation_support: "test_validated_executable", is_optional: false,
      choice_type: "member_group_from_stage", selection_policy: "public_named_groups_as_much_as_possible",
      candidate_card_instance_ids: [], card_selection_minimum: 0, card_selection_maximum: 0,
      choice_groups: [
        { group_id: "kanon", label_ja: "かのん", candidate_card_instance_ids: partial ? [] : ["player_1-M002"], minimum: partial ? 0 : 1, maximum: partial ? 0 : 1 },
        { group_id: "keke", label_ja: "可可", candidate_card_instance_ids: partial === "none" ? [] : ["player_1-M003"], minimum: partial === "none" ? 0 : 1, maximum: partial === "none" ? 0 : 1 },
      ],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    if (!partial) {
      expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: /澁谷かのん/ }));
    }
    if (partial !== "none") {
      expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: /唐 可可/ }));
    }
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", expect.objectContaining({
      invocation_id: "named-groups", selected_card_instance_ids_by_group: {
        ...(!partial ? { kanon: ["player_1-M002"] } : {}), ...(partial !== "none" ? { keke: ["player_1-M003"] } : {}),
      },
    }));
  });

  it.each([false, true])("selects a Stage Member Wait cost and optional Heart color: %s", (heart) => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    state.cards["player_1-M002"] = { ...state.cards["player_1-M002"], card: { ...state.cards["player_1-M002"].card, name_ja: "費用メンバー" } };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "wait-cost", effect_id: heart ? "PL!N-bp7-012:1" : "PL!N-sd2-006:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】『虹ヶ咲』のメンバー1人をウェイトにしてもよい：自身に加算。",
      execution_mode: "prompt_then_resolve", is_optional: true, simulation_support: "test_validated_executable",
      choice_type: "member_from_stage", choice_zone: "stage", requires_color_choice: heart,
      candidate_card_instance_ids: ["player_1-M002"], card_selection_minimum: 1, card_selection_maximum: 1,
      color_slots: heart ? ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"] : [],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /費用メンバー/ }));
    if (heart) {
      expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "黄色" }));
    }
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "wait-cost", accepted: true, selected_card_instance_ids: ["player_1-M002"], energy_instance_ids: [],
      ...(heart ? { selected_color_slot: "heart03" } : {}),
    });
  });

  it("requires both discard cards and an explicit Heart color in the same cost confirmation", () => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    for (const [id, name] of [["player_1-M002", "費用A"], ["player_1-M003", "費用B"]]) {
      state.cards[id] = { ...state.cards[id], card: { ...state.cards[id].card, name_ja: name } };
    }
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "discard-color", effect_id: "PL!N-sd2-005:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】手札を2枚控え室に置いてもよい：好きなハートの色を1つ指定する。",
      execution_mode: "prompt_then_resolve", is_optional: true, simulation_support: "test_validated_executable",
      choice_type: "card_from_zone", choice_zone: "hand", requires_color_choice: true,
      candidate_card_instance_ids: ["player_1-M002", "player_1-M003"], card_selection_minimum: 2, card_selection_maximum: 2,
      color_slots: ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /費用A/ }));
    fireEvent.click(screen.getByRole("button", { name: /費用B/ }));
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "紫色" }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "discard-color", accepted: true, selected_card_instance_ids: ["player_1-M002", "player_1-M003"],
      energy_instance_ids: [], selected_color_slot: "heart06",
    });
  });

  it("requires one explicit named Member choice instead of auto-selecting the first copy", () => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    for (const id of ["player_1-M002", "player_1-M003"] as const) {
      state.cards[id] = { ...state.cards[id], card: { ...state.cards[id].card, name_ja: "嵐 千砂都" } };
    }
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "named-live", effect_id: "PL!SP-bp7-025:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】ライブ終了時まで、自分のステージにいる「嵐 千砂都」1人は【ブレード】を得る。",
      trigger: "live_started", timing: "live_start", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false,
      choice_type: "member_from_stage", choice_zone: "stage", card_selection_minimum: 1, card_selection_maximum: 1,
      selection_policy: "public_single_as_much_as_possible", candidate_card_instance_ids: ["player_1-M002", "player_1-M003"],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("button", { name: "结算技能" })).toBeDisabled();
    expect(onAction).not.toHaveBeenCalled();
    const candidates = screen.getAllByRole("button", { name: /嵐 千砂都/ });
    expect(candidates).toHaveLength(2);
    fireEvent.click(candidates[0]);
    fireEvent.click(candidates[1]);
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "named-live", accepted: true, selected_card_instance_ids: ["player_1-M003"], energy_instance_ids: [],
    });
  });

  it.each([
    { empty: false, returned: false }, { empty: true, returned: false },
    { empty: false, returned: true },
  ])("handles other-Nijigasaki selection %j", ({ empty, returned }) => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    const id = returned ? "player_1-M001" : "player_1-M002";
    state.cards[id] = { ...state.cards[id], card: { ...state.cards[id].card, name_ja: "桜坂しずく", cost: 15 } };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "other-niji", effect_id: "PL!N-PR-036:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】ほかの虹ヶ咲メンバー1人にHeart。cost15以上ならさらにHeart。",
      trigger: "live_started", timing: "live_start", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false,
      choice_type: "member_from_stage", choice_zone: "stage", card_selection_minimum: empty ? 0 : 1,
      card_selection_maximum: empty ? 0 : 1, selection_policy: "public_other_nijigasaki_cost_heart",
      candidate_card_instance_ids: empty ? [] : [id],
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    const resolve = screen.getByRole("button", { name: "结算技能" });
    if (empty) {
      expect(resolve).toBeEnabled();
    } else {
      expect(resolve).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: /桜坂しずく/ }));
    }
    fireEvent.click(resolve);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "other-niji", accepted: true, selected_card_instance_ids: empty ? [] : [id], energy_instance_ids: [],
    });
  });

  it.each(["low", "high", "empty"])("allows a low Blade Aqours choice before checking the score condition: %s", (mode) => {
    const onAction = vi.fn();
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    const ids = mode === "empty" ? [] : ["player_1-M002", "player_1-M003"];
    ids.forEach((id, i) => { state.cards[id] = { ...state.cards[id],
      card: { ...state.cards[id].card, name_ja: `Aqours Blade ${i + 5}`, blade: i + 5 } }; });
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "aqours-six", effect_id: "PL!S-bp3-025:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】Aqours1人を選ぶ。そのBladeが6以上ならこのLiveのscore+1。",
      trigger: "live_started", timing: "live_start", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false, choice_type: "member_from_stage",
      choice_zone: "stage", card_selection_minimum: ids.length ? 1 : 0, card_selection_maximum: ids.length ? 1 : 0,
      selection_policy: "public_aqours_blade_six_source_score", candidate_card_instance_ids: ids,
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    const resolve = screen.getByRole("button", { name: "结算技能" });
    if (ids.length) {
      expect(resolve).toBeDisabled();
      const low = screen.getByRole("button", { name: /Aqours Blade 5/ });
      expect(low).toBeEnabled();
      fireEvent.click(mode === "low" ? low : screen.getByRole("button", { name: /Aqours Blade 6/ }));
    }
    fireEvent.click(resolve);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "aqours-six", accepted: true,
      selected_card_instance_ids: ids.length ? [ids[mode === "low" ? 0 : 1]] : [], energy_instance_ids: [],
    });
  });

  it.each([0, 1, 2])("requires a current Blade-four target or explicitly resolves no targets: %s", (count) => {
    const onAction = vi.fn();
    const ids = ["player_1-M002", "player_1-M003"].slice(0, count);
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    ids.forEach((id, i) => { state.cards[id] = { ...state.cards[id],
      card: { ...state.cards[id].card, name_ja: `Blade4-${i}`, blade: 4 } }; });
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "blade-four", effect_id: "PL!N-sd2-026:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ開始時】ブレード4以上の虹ヶ咲メンバー1人にheart02二つ。",
      trigger: "live_started", timing: "live_start", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false,
      choice_type: "member_from_stage", choice_zone: "stage", card_selection_minimum: count ? 1 : 0,
      card_selection_maximum: count ? 1 : 0, selection_policy: "public_nijigasaki_blade_four_heart",
      candidate_card_instance_ids: ids,
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    const resolve = screen.getByRole("button", { name: "结算技能" });
    if (count) {
      expect(resolve).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: new RegExp(`Blade4-${count - 1}`) }));
    } else { expect(resolve).toBeEnabled(); }
    fireEvent.click(resolve);
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "blade-four", accepted: true,
      selected_card_instance_ids: count ? [ids[count - 1]] : [], energy_instance_ids: [],
    });
  });

  it.each([false, true])("orders up to three public Yell cards, including choosing zero: %s", (chooseZero) => {
    const onAction = vi.fn();
    const ids = ["player_1-M001", "player_1-M002", "player_1-M003", "extra-yell"];
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, cards: { ...INSPECTION_MATCH_PAYLOAD.state.cards } } as unknown as MatchState;
    ids.forEach((id, index) => {
      state.cards[id] = { ...state.cards["player_1-M001"], instance_id: id,
        card: { ...state.cards["player_1-M001"].card, name_ja: `Yell ${index + 1}` } };
    });
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      invocation_id: "aqours-bottom", effect_id: "PL!S-cl1-002:1", source_card_instance_id: "player_1-M001",
      label_ja: "【ライブ成功時】Aqoursのエール3枚までを好きな順でデッキの下に置く。",
      trigger: "live_succeeded", timing: "live_success", execution_mode: "prompt_then_resolve",
      simulation_support: "test_validated_executable", is_optional: false, choice_type: "card_from_zone",
      choice_zone: "resolution_area", card_selection_minimum: 0, card_selection_maximum: 3,
      card_selection_requires_order: true, selection_policy: "public_yell_aqours_bottom_three",
      candidate_card_instance_ids: ids,
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never} loading={false}
      onAction={onAction} onManual={vi.fn()} />);
    if (!chooseZero) {
      ids.slice(0, 3).forEach((_, i) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`Yell ${i + 1}`) })));
      fireEvent.click(screen.getByRole("button", { name: /Yell 4/ }));
      expect(screen.getAllByRole("button", { name: "上移已选卡" })).toHaveLength(3);
      expect(screen.getAllByRole("button", { name: "上移已选卡" })[0]).toBeDisabled();
      fireEvent.click(screen.getAllByRole("button", { name: "下移已选卡" })[0]);
    }
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "aqours-bottom", accepted: true,
      selected_card_instance_ids: chooseZero ? [] : [ids[1], ids[0], ids[2]], energy_instance_ids: [],
    });
  });

  it.each(["overlap_source_binding_incomplete", "overlap_attached_ability_requires_review",
    "overlap_public_ability_requires_timing_review"])("offers manual processing for an unresolved overlap source: %s", (reason) => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const source = { invocation_id: "review-deploy", effect_id: "AUDIT", source_card_instance_id: "player_1-M001", player_id: "player_1" };
    const state = { ...INSPECTION_MATCH_PAYLOAD.state, pending_effects: [source] };
    const action = { action_type: "resolve_effect", player_id: "player_1", options: { invocations: [{
      ...source, label_ja: "監査用の効果登場", trigger: "member_played", timing: "on_play",
      execution_mode: "prompt_then_resolve", simulation_support: "test_validated_executable",
      is_optional: false, candidate_card_instance_ids: [], deployment_choice: true,
      deployment_requires_manual_resolution: true,
      deployment_unsupported_slots_by_candidate: { "player_1-M002": { right: reason } },
    }] } };
    render(<EffectResolutionAction action={action as never} state={state as never}
      loading={false} onAction={onAction} onManual={onManual} />);
    expect(screen.getByRole("status")).toHaveTextContent("部分登场区域涉及未确认能力");
    expect(screen.queryByRole("button", { name: "结算技能" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "结构化人工处理" }));
    expect(onManual).toHaveBeenCalledWith(source);
    expect(onAction).not.toHaveBeenCalled();
  });

  it("translates the overlap review notice and preserves its manual entry", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const source = { invocation_id: "review-deploy", effect_id: "AUDIT", source_card_instance_id: "player_1-M001", player_id: "player_1" };
    const matchCreate = { ...INSPECTION_MATCH_PAYLOAD,
      state: { ...INSPECTION_MATCH_PAYLOAD.state, pending_choice: null, pending_effects: [source] },
      legal_actions: [{ action_type: "resolve_effect", player_id: "player_1", label_zh: "处理技能", label_ja: "能力",
        options: { invocations: [{ ...source, label_ja: "監査用の効果登場", trigger: "member_played", timing: "on_play",
          execution_mode: "prompt_then_resolve", simulation_support: "test_validated_executable", is_optional: false,
          candidate_card_instance_ids: [], deployment_choice: true, deployment_requires_manual_resolution: true,
          deployment_unsupported_slots: { right: "overlap_source_binding_incomplete" },
        }] } }],
    };
    vi.stubGlobal("fetch", createFetchMock({ matchCreate }));
    render(<App />);
    const create = await screen.findByRole("button", { name: "创建对局" });
    await waitFor(() => expect(create).not.toBeDisabled());
    fireEvent.click(create);
    await screen.findByText("部分登场区域涉及未确认能力，未自动处理；请使用手动调整。");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByText("未確認の能力が関係する登場エリアは自動処理できません。手動調整で確認してください。"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "構造化手動処理" })).toBeEnabled();
  });

  it.each([{ hasTarget: true, chooseOne: false }, { hasTarget: false, chooseOne: false },
    { hasTarget: true, chooseOne: true }])("resolves private hand deployment: %j", ({ hasTarget, chooseOne }) => {
    const onAction = vi.fn();
    const action = {
      action_type: "resolve_effect", player_id: "player_1", label_zh: "技能", label_ja: "能力",
      options: { invocations: [{
        invocation_id: "private-deploy", effect_id: "AUDIT", source_card_instance_id: "player_1-M001",
        label_ja: "手札からメンバーを選び登場させる。", trigger: "member_played", timing: "on_play",
        execution_mode: "prompt_then_resolve", simulation_support: "test_validated_executable",
        resolution_stage: "initial", is_optional: false,
        choice_type: "card_from_zone", choice_zone: "hand",
        card_selection_minimum: 0, card_selection_maximum: 1,
        selection_policy: "private_filtered_may_choose_none", deployment_choice: true,
        candidate_card_instance_ids: hasTarget ? ["player_1-M002"] : [],
        position_change_slots_by_candidate: { "player_1-M002": ["right"] },
        energy_instance_ids: ["player_1-E001"], energy_required: 1,
      }] },
    };
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByRole("button", { name: "不选目标并结算" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "能量 E001" }));
    if (hasTarget) {
      fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
      fireEvent.click(screen.getByRole("button", { name: "右" }));
      if (!chooseOne) fireEvent.click(screen.getByRole("button", { name: "不选目标" }));
    }
    if (!chooseOne) expect(screen.queryByText("登场区域")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: chooseOne ? "结算技能" : "不选目标并结算" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "private-deploy", accepted: true,
      selected_card_instance_ids: chooseOne ? ["player_1-M002"] : [],
      energy_instance_ids: ["player_1-E001"],
      ...(chooseOne ? { to_slot: "right" } : {}),
    });
  });

  it("lets the controller choose the next automatic effect using resolve_effect", () => {
    const onAction = vi.fn();
    const invocations = ["first", "second"].map((id) => ({
      invocation_id: id, effect_id: `AUDIT-${id}`, source_card_instance_id: "player_1-M001",
      label_ja: id === "first" ? "カードを1枚引く。" : "手札が4枚になるまでカードを引く。",
      trigger: "member_played", timing: "on_play", execution_mode: "auto_resolve",
      simulation_support: "test_validated_executable", resolution_stage: "initial", is_optional: false,
      candidate_card_instance_ids: [], card_selection_minimum: 0, card_selection_maximum: 0,
    }));
    const action = { action_type: "resolve_effect", player_id: "player_1",
      options: { effect_order_choice: true, invocations, waiting_player_ids: ["player_2"] } };
    render(<EffectResolutionAction action={action as never} state={INSPECTION_MATCH_PAYLOAD.state as never}
      loading={false} onAction={onAction} onManual={vi.fn()} />);
    expect(screen.getByText("选择先结算的技能 (2)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("先结算的技能"), { target: { value: "second" } });
    expect(screen.getByText("手札が4枚になるまでカードを引く。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));
    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "second", accepted: true, selected_card_instance_ids: [], energy_instance_ids: [],
    });
  });

  it("submits branch follow-up card choices with the selected branch", () => {
    const onAction = vi.fn();
    const onManual = vi.fn();
    const state = {
      ...INSPECTION_MATCH_PAYLOAD.state,
      pending_choice: null,
      pending_effects: [
        {
          invocation_id: "branch-effect-001",
          effect_id: "PL!TEST-BRANCH:1",
          source_card_instance_id: "player_1-M001",
          player_id: "player_1",
          trigger_event: "member_played",
          trigger_data: { selected_branch: "draw_discard" },
          resolution_stage: "after_cost" as const,
        },
      ],
    };
    const action = {
      action_type: "resolve_effect",
      player_id: "player_1",
      label_zh: "处理待结算技能",
      label_ja: "待機中の能力を解決",
      options: {
        invocations: [
          {
            invocation_id: "branch-effect-001",
            effect_id: "PL!TEST-BRANCH:1",
            source_card_instance_id: "player_1-M001",
            label_ja:
              "【登場】以下から1つを選ぶ。 ・カードを1枚引き、手札を1枚控え室に置く。 ・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。",
            trigger: "member_played",
            timing: "on_play",
            execution_mode: "prompt_then_resolve",
            is_optional: false,
            simulation_support: "test_validated_executable",
            candidate_card_instance_ids: ["player_1-M002"],
            choice_type: "choose_effect_branch",
            card_selection_minimum: 1,
            card_selection_maximum: 1,
            choice_zone: "hand",
            branch_ids: ["draw_discard", "wait_opponent_cost2"],
            selected_branch: "draw_discard",
          },
        ],
        waiting_player_ids: [],
      },
    };

    render(
      <EffectResolutionAction
        action={action as never}
        state={state as never}
        loading={false}
        onAction={onAction}
        onManual={onManual}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /候補カード/ }));
    fireEvent.click(screen.getByRole("button", { name: "结算技能" }));

    expect(onAction).toHaveBeenCalledWith("resolve_effect", "player_1", {
      invocation_id: "branch-effect-001",
      accepted: true,
      selected_card_instance_ids: ["player_1-M002"],
      energy_instance_ids: [],
      selected_branch: "draw_discard",
    });
  });
});

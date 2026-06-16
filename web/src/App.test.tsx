import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, {
  EffectResolutionAction,
  InspectionChoiceAction,
  ManualDrawer,
  MemberPlayAction,
  StageAttachments,
  availableValue,
  canResolveEffect,
  formatEffectText,
  formatHeartSummary,
  resolveMemberPlaySelection,
} from "./App";
import { resetRuntimeConfigForTests } from "./api";
import type { DeckList } from "./types";

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
    if (path === "/api/rooms" && method === "POST") {
      return jsonResponse(overrides.roomCreate ?? roomPayload("waiting_for_guest"));
    }
    if (path.startsWith("/api/rooms/") && path.includes("/leave") && method === "POST") {
      return jsonResponse(overrides.roomLeave ?? roomPayload("expired"));
    }
    if (path.startsWith("/api/rooms/") && method === "GET") {
      return jsonResponse(overrides.roomPoll ?? roomPayload("active"));
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

describe("App", () => {
  beforeEach(() => {
    cleanup();
    resetRuntimeConfigForTests();
    localStorage.clear();
    localStorage.setItem("loveca-ui-locale", "zh");
    vi.stubGlobal("fetch", createFetchMock({}));
  });

  it("defaults to Japanese and opens the usage guide when no language is stored", async () => {
    localStorage.removeItem("loveca-ui-locale");

    render(<App />);

    expect(screen.getByText("LoveCA ルール検証ツール")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "まず下のボタンを見ます" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "カードを閲覧" })).toBeInTheDocument();
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

  it("leaves the hosted room before returning from an online match", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "release",
        browserPreview: false,
        apiBaseUrl: "https://api.test",
        cardDatabaseFingerprint: "test",
      },
      roomCreate: roomPayload("active"),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线房间 Preview")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "房间创建" }));

    await waitFor(() => expect(screen.getByText("LoveCA 规则验证器")).toBeInTheDocument());
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

  it("sends a keepalive hosted-room leave request on page unload", async () => {
    seedSavedDecks([{ path: "test.json", deck: SAMPLE_DECK }]);
    const fetchMock = createFetchMock({
      runtimeConfig: {
        mode: "release",
        browserPreview: false,
        apiBaseUrl: "https://api.test",
        cardDatabaseFingerprint: "test",
      },
      roomCreate: roomPayload("active"),
    });
    vi.stubGlobal("fetch", fetchMock);
    const addEventListenerSpy = vi.spyOn(window, "addEventListener");

    render(<App />);
    await waitFor(() => expect(screen.getByText("在线房间 Preview")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "房间创建" }));
    await waitFor(() => expect(screen.getByText("LoveCA 规则验证器")).toBeInTheDocument());
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

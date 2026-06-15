import { getPreviewCatalogCard, listPreviewCatalogCards } from "./browser-preview-api";
import type {
  CardDefinition,
  CardInstance,
  CatalogCardDetail,
  CatalogCardSummary,
  GameEvent,
  MatchPayload,
  PlayerState,
} from "./types";

export async function createPreviewDemoMatch(): Promise<MatchPayload> {
  const [members, lives, energies] = await Promise.all([
    listPreviewCatalogCards({ cardType: "member", limit: 24, offset: 0 }),
    listPreviewCatalogCards({ cardType: "live", limit: 12, offset: 0 }),
    listPreviewCatalogCards({ cardType: "energy", limit: 8, offset: 0 }),
  ]);
  if (members.items.length < 6 || lives.items.length < 2 || energies.items.length < 1) {
    throw new Error("Preview demo requires bundled Member, Live, and Energy card data.");
  }

  const selected = [
    ...members.items.slice(0, 12),
    ...lives.items.slice(0, 4),
    ...energies.items.slice(0, 2),
  ];
  const details = new Map<string, CatalogCardDetail>();
  await Promise.all(
    selected.map(async (summary) => {
      details.set(summary.card_code, await getPreviewCatalogCard(summary.card_code));
    }),
  );

  const cards: Record<string, CardInstance> = {};
  const make = (
    ownerId: "player_1" | "player_2",
    summary: CatalogCardSummary,
    suffix: string,
    orientation: "active" | "wait" = "active",
  ) => {
    const detail = details.get(summary.card_code);
    if (!detail) throw new Error(`Preview demo detail missing: ${summary.card_code}`);
    const instanceId = `${ownerId}-${suffix}`;
    cards[instanceId] = {
      instance_id: instanceId,
      owner_id: ownerId,
      card: cardDefinitionFromDetail(detail),
      orientation,
      face_up: true,
    };
    return instanceId;
  };

  const p1Members = members.items.slice(0, 6);
  const p2Members = members.items.slice(6, 12);
  const p1Live = lives.items[0];
  const p2Live = lives.items[1] ?? lives.items[0];
  const p1Yell = [p1Members[3], p1Members[4]];
  const p2Yell = [p2Members[3], p2Members[4]];

  const p1 = createDemoPlayer("player_1", "Player 1", {
    left: make("player_1", p1Members[0], "stage-left"),
    center: make("player_1", p1Members[1], "stage-center"),
    right: make("player_1", p1Members[2], "stage-right", "wait"),
    live: make("player_1", p1Live, "live-1"),
    yells: [
      make("player_1", p1Yell[0], "yell-1"),
      make("player_1", p1Yell[1], "yell-2"),
    ],
    hand: [
      make("player_1", p1Members[5], "hand-1"),
      make("player_1", lives.items[2] ?? p1Live, "hand-2"),
    ],
    energy: [
      make("player_1", energies.items[0], "energy-1"),
      make("player_1", energies.items[0], "energy-2"),
      make("player_1", energies.items[0], "energy-3", "wait"),
    ],
    successLive: [make("player_1", lives.items[3] ?? p1Live, "success-live-1")],
    liveScore: p1Live.score ?? 2,
    bladeCount: 2,
    winner: true,
  });

  const p2 = createDemoPlayer("player_2", "Player 2", {
    left: make("player_2", p2Members[0], "stage-left"),
    center: make("player_2", p2Members[1], "stage-center"),
    right: make("player_2", p2Members[2], "stage-right"),
    live: make("player_2", p2Live, "live-1"),
    yells: [
      make("player_2", p2Yell[0], "yell-1"),
      make("player_2", p2Yell[1], "yell-2"),
    ],
    hand: [
      make("player_2", p2Members[5], "hand-1"),
      make("player_2", lives.items[2] ?? p2Live, "hand-2"),
    ],
    energy: [
      make("player_2", energies.items[1] ?? energies.items[0], "energy-1"),
      make("player_2", energies.items[1] ?? energies.items[0], "energy-2"),
      make("player_2", energies.items[1] ?? energies.items[0], "energy-3"),
    ],
    successLive: [],
    liveScore: p2Live.score ?? 1,
    bladeCount: 2,
    winner: false,
  });

  const events: GameEvent[] = [
    {
      event_type: "preview_demo_loaded",
      player_id: null,
      source: "system",
      data: { note: "Static browser preview demo. No rule engine is running." },
    },
    {
      event_type: "live_judgment_completed",
      player_id: null,
      source: "system",
      data: { winner_player_ids: ["player_1"], basis: "higher_total_score" },
    },
  ];

  return {
    state: {
      match_id: "preview-demo",
      rule_version: "1.06",
      seed: 20260615,
      revision: 8,
      phase: "live_judgment",
      first_player_id: "player_1",
      second_player_id: "player_2",
      turn_number: 1,
      next_first_player_id: "player_1",
      success_live_moved_player_ids: ["player_1"],
      success_live_moved_instance_ids: { player_1: [], player_2: [] },
      live_success_effects_queued: true,
      active_player_id: null,
      players: { player_1: p1, player_2: p2 },
      cards,
      effect_registry_version: "preview-demo",
      effect_definitions: {},
      pending_effects: [],
      effect_usage: [],
      pending_choice: null,
      live_winner_ids: ["player_1"],
      live_judgment_summary: {
        basis: "higher_total_score",
        winner_ids: ["player_1"],
        players: {
          player_1: {
            player_id: "player_1",
            successful_live_instance_ids: p1.live_area,
            requirements_satisfied: true,
            base_score: p1.live_result.base_score,
            score_bonus: p1.live_result.score_bonus,
            total_score: p1.live_result.total_score,
          },
          player_2: {
            player_id: "player_2",
            successful_live_instance_ids: p2.live_area,
            requirements_satisfied: true,
            base_score: p2.live_result.base_score,
            score_bonus: p2.live_result.score_bonus,
            total_score: p2.live_result.total_score,
          },
        },
      },
      game_result: null,
      completed_reason: null,
    },
    events,
    legal_actions: [],
  };
}

function cardDefinitionFromDetail(detail: CatalogCardDetail): CardDefinition {
  const primaryPrinting = detail.printings[0] ?? null;
  const textRevision = detail.text_revisions[0] ?? null;
  return {
    card_code: detail.card.card_code,
    card_id: "",
    image_url: primaryPrinting?.image_url ?? null,
    name_ja: detail.card.name_ja,
    card_type: detail.card.card_type,
    cost: detail.card.cost,
    blade: detail.card.blade,
    score: detail.card.score,
    basic_hearts: detail.card.heart_values.basic ?? {},
    required_hearts: detail.card.heart_values.required ?? {},
    blade_heart_color_slot:
      detail.card.member_blade_heart_color_slot ?? detail.card.live_blade_heart_color_slot,
    special_blade_hearts: detail.card.special_blade_hearts.map((heart) => ({
      effect_type: heart.effect_type as CardDefinition["special_blade_hearts"][number]["effect_type"],
      value: heart.value,
      source_alt: heart.source_alt,
    })),
    raw_effect_text_ja: textRevision?.raw_effect_text_ja ?? null,
    text_revision_id: textRevision?.revision_id ?? null,
    raw_text_hash: textRevision?.raw_text_hash ?? null,
    work_keys: detail.card.works.map((work) => work.work_key),
    ability_bucket: textRevision?.raw_effect_text_ja ? "other" : "none",
    effect_ids: detail.card.effects.map((effect) => effect.effect_id),
    effect_registry_status: detail.card.effect_registry_status,
    effect_registry_errors: detail.card.effect_registry_errors,
  };
}

function createDemoPlayer(
  playerId: "player_1" | "player_2",
  name: string,
  input: {
    left: string;
    center: string;
    right: string;
    live: string;
    yells: string[];
    hand: string[];
    energy: string[];
    successLive: string[];
    liveScore: number;
    bladeCount: number;
    winner: boolean;
  },
): PlayerState {
  const availableHearts: Record<string, number> = input.winner
    ? { heart01: 2, heart02: 1, heart03: 1 }
    : { heart01: 1, heart03: 1 };
  return {
    player_id: playerId,
    name,
    main_deck: Array.from({ length: 34 }, (_, index) => `${playerId}-deck-${index + 1}`),
    energy_deck: Array.from({ length: 8 }, (_, index) => `${playerId}-energy-deck-${index + 1}`),
    hand: input.hand,
    member_area: {
      left: input.left,
      center: input.center,
      right: input.right,
    },
    member_area_attachments: { left: [], center: [], right: [] },
    member_areas_entered_this_turn: ["left", "center"],
    energy_area: input.energy,
    live_area: [input.live],
    waiting_room: input.yells,
    resolution_area: [],
    success_live_area: input.successLive,
    manual_modifiers: [],
    refresh_count: 0,
    live_result: {
      blade_count: input.bladeCount,
      revealed_instance_ids: input.yells,
      member_hearts: { heart01: 1, heart02: 1 },
      manual_hearts: {},
      yell_hearts: input.winner ? { heart01: 1, heart03: 1 } : { heart03: 1 },
      available_hearts: availableHearts,
      all_color_hearts: 0,
      special_blade_heart_results: [],
      draw_count: 0,
      live_allocations: [
        {
          live_instance_id: input.live,
          required_hearts: input.winner ? { heart01: 2 } : { heart03: 1 },
          consumed_hearts: input.winner ? { heart01: 2 } : { heart03: 1 },
          all_color_hearts_used: 0,
          missing_hearts: {},
          remaining_hearts: input.winner ? { heart02: 1, heart03: 1 } : { heart01: 1 },
          remaining_all_color_hearts: 0,
          satisfied: true,
        },
      ],
      score_bonus: input.winner ? 1 : 0,
      base_score: input.liveScore,
      requirements_satisfied: true,
      total_score: input.liveScore + (input.winner ? 1 : 0),
    },
  };
}

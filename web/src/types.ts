export type CardType = "member" | "live" | "energy";

export interface SpecialBladeHeart {
  effect_type: "all_color" | "draw" | "score" | "unknown";
  value: number | null;
  source_alt: string;
}

export interface CardDefinition {
  card_code: string;
  card_id: string;
  name_ja: string;
  card_type: CardType;
  cost: number | null;
  blade: number | null;
  score: number | null;
  basic_hearts: Record<string, number>;
  required_hearts: Record<string, number>;
  blade_heart_color_slot: string | null;
  special_blade_hearts: SpecialBladeHeart[];
  raw_effect_text_ja: string | null;
  text_revision_id: number | null;
  raw_text_hash: string | null;
  work_keys: string[];
  effect_ids: string[];
  effect_registry_status: "supported" | "unregistered" | "hash_mismatch";
  effect_registry_errors: string[];
}

export interface EffectDefinition {
  effect_id: string;
  card_code: string;
  text_revision_id: number;
  raw_text_hash: string;
  effect_index: number;
  label_ja: string;
  effect_type: string;
  timing: string;
  trigger: string;
  frequency_limit: string;
  is_optional: boolean;
  simulation_support: string;
  review_status: string;
}

export interface EffectInvocation {
  invocation_id: string;
  effect_id: string;
  source_card_instance_id: string;
  player_id: string;
  trigger_event: string;
  trigger_data: Record<string, unknown>;
  resolution_stage: "initial" | "after_cost";
}

export interface CardInstance {
  instance_id: string;
  owner_id: string;
  card: CardDefinition;
  orientation: "active" | "wait";
  face_up: boolean;
}

export interface PlayerState {
  player_id: string;
  name: string;
  main_deck: string[];
  energy_deck: string[];
  hand: string[];
  member_area: Record<"left" | "center" | "right", string | null>;
  member_areas_entered_this_turn: string[];
  energy_area: string[];
  live_area: string[];
  waiting_room: string[];
  resolution_area: string[];
  success_live_area: string[];
  manual_modifiers: Array<{
    modifier_id: string;
    modifier_type: "score" | "blade" | "heart" | "flag";
    duration: "live" | "turn" | "game";
    created_turn: number;
    amount: number | null;
    color_slot: string | null;
    flag: string | null;
    value: unknown;
    target_card_instance_id: string | null;
  }>;
  refresh_count: number;
  live_result: {
    blade_count: number;
    revealed_instance_ids: string[];
    member_hearts: Record<string, number>;
    manual_hearts: Record<string, number>;
    yell_hearts: Record<string, number>;
    available_hearts: Record<string, number>;
    all_color_hearts: number;
    special_blade_heart_results: Array<{
      card_instance_id: string;
      effect_type: string;
      value: number;
      source_alt: string;
    }>;
    draw_count: number;
    live_allocations: Array<{
      live_instance_id: string;
      required_hearts: Record<string, number>;
      consumed_hearts: Record<string, number>;
      all_color_hearts_used: number;
      missing_hearts: Record<string, number>;
      remaining_hearts: Record<string, number>;
      remaining_all_color_hearts: number;
      satisfied: boolean;
    }>;
    score_bonus: number;
    base_score: number;
    requirements_satisfied: boolean | null;
    total_score: number;
  };
}

export interface PendingChoice {
  choice_type:
    | "mulligan"
    | "live_requirements"
    | "success_live"
    | "manual_card_selection";
  player_id: string;
  message_ja: string;
  message_zh: string;
  options: Record<string, unknown>;
}

export interface MatchState {
  match_id: string;
  rule_version: string;
  seed: number;
  revision: number;
  phase: string;
  first_player_id: string | null;
  second_player_id: string | null;
  turn_number: number;
  next_first_player_id: string | null;
  success_live_moved_player_ids: string[];
  active_player_id: string | null;
  players: Record<string, PlayerState>;
  cards: Record<string, CardInstance>;
  effect_registry_version: string | null;
  effect_definitions: Record<string, EffectDefinition>;
  pending_effects: EffectInvocation[];
  effect_usage: Array<{
    effect_id: string;
    source_card_instance_id: string;
    turn_number: number;
    usage_count: number;
  }>;
  pending_choice: PendingChoice | null;
  live_winner_ids: string[];
  live_judgment_summary: {
    basis: string;
    winner_ids: string[];
    players: Record<
      string,
      {
        player_id: string;
        successful_live_instance_ids: string[];
        requirements_satisfied: boolean | null;
        base_score: number;
        score_bonus: number;
        total_score: number;
      }
    >;
  } | null;
  game_result: {
    outcome: "win" | "draw";
    winner_player_ids: string[];
    reason: "success_live_threshold";
    final_turn: number;
  } | null;
  completed_reason: string | null;
}

export interface GameEvent {
  event_type: string;
  player_id: string | null;
  data: Record<string, unknown>;
  source: "player" | "system" | "manual";
}

export interface LegalAction {
  action_type: string;
  player_id: string | null;
  label_zh: string;
  label_ja: string;
  options: Record<string, unknown>;
}

export interface MatchPayload {
  state: MatchState;
  events: GameEvent[];
  legal_actions: LegalAction[];
}

export interface MatchSummary {
  match_id: string;
  rule_version: string;
  seed: number;
  status: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

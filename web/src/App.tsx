import {
  Activity,
  ArrowDownToLine,
  ChevronDown,
  ChevronUp,
  CirclePlay,
  Database,
  Download,
  History,
  RefreshCw,
  Settings2,
  Swords,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createMatch, getMatch, listMatches, submitAction } from "./api";
import type {
  CardInstance,
  GameEvent,
  LegalAction,
  MatchPayload,
  MatchState,
  MatchSummary,
  PlayerState,
} from "./types";

const phaseLabels: Record<string, [string, string]> = {
  setup_choose_first: ["选择先攻", "先攻選択"],
  setup_mulligan_first: ["先攻调度", "先攻引き直し"],
  setup_mulligan_second: ["后攻调度", "後攻引き直し"],
  first_active: ["先攻活动阶段", "先攻アクティブフェイズ"],
  first_energy: ["先攻能量阶段", "先攻エネルギーフェイズ"],
  first_draw: ["先攻抽牌阶段", "先攻ドローフェイズ"],
  first_main: ["先攻主要阶段", "先攻メインフェイズ"],
  second_active: ["后攻活动阶段", "後攻アクティブフェイズ"],
  second_energy: ["后攻能量阶段", "後攻エネルギーフェイズ"],
  second_draw: ["后攻抽牌阶段", "後攻ドローフェイズ"],
  second_main: ["后攻主要阶段", "後攻メインフェイズ"],
  live_set_first: ["先攻 Live 设置", "先攻ライブカードセット"],
  live_set_second: ["后攻 Live 设置", "後攻ライブカードセット"],
  performance_first: ["先攻 Live 公开", "先攻パフォーマンスフェイズ"],
  yell_first: ["先攻应援", "先攻エール"],
  performance_second: ["后攻 Live 公开", "後攻パフォーマンスフェイズ"],
  yell_second: ["后攻应援", "後攻エール"],
  live_judgment: ["Live 胜负判定", "ライブ勝敗判定"],
  complete: ["首轮判定完成", "ライブ判定完了"],
};

const heartLabels: Record<string, string> = {
  heart0: "任意",
  heart01: "粉",
  heart02: "红",
  heart03: "黄",
  heart06: "紫",
};

const judgmentBasisLabels: Record<string, string> = {
  no_successful_live: "双方均无满足所需 Heart 的 Live，不产生胜者",
  only_one_player_has_successful_live: "仅一方有成功 Live，该玩家胜利",
  equal_total_score: "双方 Live 总分相同，双方均胜利",
  higher_total_score: "比较双方 Live 总分，较高者胜利",
};

export default function App() {
  const [match, setMatch] = useState<MatchPayload | null>(null);
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<CardInstance | null>(null);
  const [manualOpen, setManualOpen] = useState(false);

  useEffect(() => {
    listMatches().then(setMatches).catch(() => setMatches([]));
  }, []);

  async function run<T>(operation: () => Promise<T>, apply: (value: T) => void) {
    setLoading(true);
    setError(null);
    try {
      apply(await operation());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  async function handleAction(
    actionType: string,
    playerId?: string | null,
    payload: Record<string, unknown> = {},
  ) {
    if (!match) return;
    await run(
      () =>
        submitAction(match.state.match_id, {
          action_type: actionType,
          expected_revision: match.state.revision,
          player_id: playerId,
          payload,
        }),
      (next) =>
        setMatch({
          ...next,
          events: [...match.events, ...next.events],
        }),
    );
  }

  if (!match) {
    return (
      <StartScreen
        matches={matches}
        loading={loading}
        error={error}
        onCreate={(input) => run(() => createMatch(input), setMatch)}
        onResume={(id) => run(() => getMatch(id), setMatch)}
      />
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <Swords size={22} />
          <div>
            <strong>LoveCA 规则验证器</strong>
            <span>総合ルール ver. {match.state.rule_version}</span>
          </div>
        </div>
        <div className="phase-status">
          <span className="phase-cn">{phaseLabels[match.state.phase]?.[0]}</span>
          <span>{phaseLabels[match.state.phase]?.[1] ?? match.state.phase}</span>
        </div>
        <div className="top-actions">
          <span className="revision">rev {match.state.revision}</span>
          <a
            className="icon-button"
            href={`/api/matches/${match.state.match_id}/replay`}
            title="导出 Replay JSON"
          >
            <Download size={18} />
          </a>
          <button
            className="icon-button"
            title="返回对局列表"
            onClick={() => setMatch(null)}
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className="workspace">
        <section className="board-column">
          <PlayerBoard
            player={match.state.players.player_2}
            state={match.state}
            role={match.state.second_player_id === "player_2" ? "后攻" : "先攻"}
            compact
            onCard={setDetails}
          />
          <LiveCenter state={match.state} onCard={setDetails} />
          <PlayerBoard
            player={match.state.players.player_1}
            state={match.state}
            role={match.state.first_player_id === "player_1" ? "先攻" : "后攻"}
            onCard={setDetails}
          />
        </section>
        <EventLog events={match.events} state={match.state} />
      </main>

      {match.legal_actions.length > 0 && (
        <ActionDock
          state={match.state}
          actions={match.legal_actions}
          loading={loading}
          onAction={handleAction}
          onManual={() => setManualOpen(true)}
        />
      )}

      {details && <CardDialog instance={details} onClose={() => setDetails(null)} />}
      {manualOpen && (
        <ManualDrawer
          state={match.state}
          onClose={() => setManualOpen(false)}
          onSubmit={(playerId, payload) => {
            setManualOpen(false);
            void handleAction("manual_adjustment", playerId, payload);
          }}
        />
      )}
    </div>
  );
}

function StartScreen({
  matches,
  loading,
  error,
  onCreate,
  onResume,
}: {
  matches: MatchSummary[];
  loading: boolean;
  error: string | null;
  onCreate: (input: { player1Name: string; player2Name: string; seed?: number }) => void;
  onResume: (id: string) => void;
}) {
  const [player1Name, setPlayer1Name] = useState("Player 1");
  const [player2Name, setPlayer2Name] = useState("Player 2");
  const [seed, setSeed] = useState("106");
  return (
    <div className="start-page">
      <header className="start-header">
        <div className="brand-lockup">
          <Swords size={24} />
          <div>
            <strong>LoveCA 规则验证器</strong>
            <span>本地可重放规则调试环境</span>
          </div>
        </div>
        <span className="local-badge">127.0.0.1 · Local</span>
      </header>
      <main className="start-grid">
        <section className="setup-panel">
          <div className="section-heading">
            <CirclePlay size={20} />
            <div>
              <h1>创建规则验证对局</h1>
              <p>使用已导入的 60+12 张示例牌组，运行到第一次 Live 判定。</p>
            </div>
          </div>
          <div className="form-grid">
            <label>
              Player 1
              <input value={player1Name} onChange={(e) => setPlayer1Name(e.target.value)} />
            </label>
            <label>
              Player 2
              <input value={player2Name} onChange={(e) => setPlayer2Name(e.target.value)} />
            </label>
            <label>
              Random seed
              <input value={seed} onChange={(e) => setSeed(e.target.value)} inputMode="numeric" />
            </label>
            <div className="deck-source">
              <Database size={18} />
              <span>examples/decks/sample-deck.json</span>
            </div>
          </div>
          {error && <div className="error-banner">{error}</div>}
          <button
            className="primary-button"
            disabled={loading}
            onClick={() =>
              onCreate({
                player1Name,
                player2Name,
                seed: seed ? Number(seed) : undefined,
              })
            }
          >
            {loading ? <RefreshCw className="spin" size={18} /> : <CirclePlay size={18} />}
            创建对局
          </button>
        </section>

        <section className="history-panel">
          <div className="section-heading compact-heading">
            <History size={20} />
            <div>
              <h2>最近对局</h2>
              <p>从独立 runtime SQLite 恢复。</p>
            </div>
          </div>
          <div className="match-list">
            {matches.length === 0 && <div className="empty-state">暂无已保存对局</div>}
            {matches.map((item) => (
              <button
                className="match-row"
                key={item.match_id}
                onClick={() => onResume(item.match_id)}
              >
                <span>
                  <strong>{item.status === "complete" ? "已完成" : "进行中"}</strong>
                  <small>{item.match_id.slice(0, 8)} · seed {item.seed}</small>
                </span>
                <span>rev {item.revision}</span>
              </button>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

function PlayerBoard({
  player,
  state,
  role,
  compact = false,
  onCard,
}: {
  player: PlayerState;
  state: MatchState;
  role: string;
  compact?: boolean;
  onCard: (card: CardInstance) => void;
}) {
  return (
    <section className={`player-board ${compact ? "compact" : ""}`}>
      <div className="player-heading">
        <div>
          <span className="role-label">{role}</span>
          <strong>{player.name}</strong>
        </div>
        <div className="player-metrics">
          <Metric label="Deck" value={player.main_deck.length} />
          <Metric label="Energy" value={player.energy_area.length} />
          <Metric label="Success" value={player.success_live_area.length} />
          <Metric label="Score" value={player.live_result.total_score} />
        </div>
      </div>
      <div className="zone-row">
        <Zone label="成功ライブ" ids={player.success_live_area} state={state} onCard={onCard} small />
        <div className="member-stage">
          {(["left", "center", "right"] as const).map((slot) => (
            <div className="member-slot" key={slot}>
              <span>{slot === "left" ? "左" : slot === "center" ? "中" : "右"}</span>
              {player.member_area[slot] ? (
                <CardTile instance={state.cards[player.member_area[slot]!]} onClick={onCard} />
              ) : (
                <div className="slot-empty">Member</div>
              )}
            </div>
          ))}
        </div>
        <Zone label="Energy" ids={player.energy_area} state={state} onCard={onCard} small />
      </div>
      <Zone label={`手牌 ${player.hand.length}`} ids={player.hand} state={state} onCard={onCard} hand />
    </section>
  );
}

function LiveCenter({ state, onCard }: { state: MatchState; onCard: (card: CardInstance) => void }) {
  return (
    <section className="live-center">
      <Zone
        label={`${state.players.player_2.name} Live`}
        ids={state.players.player_2.live_area}
        state={state}
        onCard={onCard}
        small
      />
      <LiveAnalysisPanel state={state} onCard={onCard} />
      <Zone
        label={`${state.players.player_1.name} Live`}
        ids={state.players.player_1.live_area}
        state={state}
        onCard={onCard}
        small
      />
    </section>
  );
}

function LiveAnalysisPanel({
  state,
  onCard,
}: {
  state: MatchState;
  onCard: (card: CardInstance) => void;
}) {
  const visible =
    state.phase.startsWith("performance") ||
    state.phase.startsWith("yell") ||
    state.phase === "live_judgment" ||
    state.phase === "complete";
  const summary = state.live_judgment_summary;
  const winners = summary?.winner_ids.map((id) => state.players[id].name) ?? [];
  if (!visible) {
    return (
      <div className="phase-track">
        <Activity size={18} />
        <strong>{phaseLabels[state.phase]?.[0]}</strong>
        <span>{phaseLabels[state.phase]?.[1]}</span>
        {state.pending_choice && <em>{state.pending_choice.message_zh}</em>}
      </div>
    );
  }
  return (
    <section className="live-analysis">
      <header className="live-analysis-heading">
        <div>
          <Activity size={16} />
          <strong>Live 判定明细</strong>
          <span>
            {phaseLabels[state.phase]?.[0]} · {phaseLabels[state.phase]?.[1]}
          </span>
          <small>総合ルール 8.3.10–8.3.16 / 8.4.2–8.4.7</small>
        </div>
        <div className={`judgment-basis ${summary ? "resolved" : ""}`}>
          <small>判定基准</small>
          <strong>
            {summary
              ? judgmentBasisLabels[summary.basis] ?? summary.basis
              : "等待双方完成应援与 Heart 判定"}
          </strong>
          {summary && (
            <span>{winners.length > 0 ? `胜者：${winners.join("、")}` : "无胜者"}</span>
          )}
        </div>
      </header>
      <div className="live-breakdown-grid">
        {["player_2", "player_1"].map((playerId) => (
          <PlayerLiveBreakdown
            key={playerId}
            player={state.players[playerId]}
            state={state}
            onCard={onCard}
          />
        ))}
      </div>
    </section>
  );
}

function PlayerLiveBreakdown({
  player,
  state,
  onCard,
}: {
  player: PlayerState;
  state: MatchState;
  onCard: (card: CardInstance) => void;
}) {
  const result = player.live_result;
  const requirementStatus =
    result.requirements_satisfied === false &&
    result.live_allocations.length === 0 &&
    result.revealed_instance_ids.length === 0
      ? "无 Live 可判定"
      : result.requirements_satisfied === null
      ? "尚未判定"
      : result.requirements_satisfied
        ? "所需 Heart 满足"
        : "所需 Heart 未满足";
  return (
    <article className="live-breakdown">
      <header>
        <div>
          <strong>{player.name}</strong>
          <span
            className={
              result.requirements_satisfied === true
                ? "status-success"
                : result.requirements_satisfied === false
                  ? "status-failed"
                  : ""
            }
          >
            {requirementStatus}
          </span>
        </div>
        <div className="live-metrics">
          <Metric label="Blade" value={result.blade_count} />
          <Metric label="应援翻开" value={result.revealed_instance_ids.length} />
          <Metric label="基础分" value={result.base_score} />
          <Metric label="特殊加分" value={result.score_bonus} />
          <Metric label="总分" value={result.total_score} />
        </div>
      </header>

      <div className="heart-ledger">
        <HeartLine label="成员 Heart" hearts={result.member_hearts} />
        <HeartLine label="应援 Heart" hearts={result.yell_hearts} />
        {Object.keys(result.manual_hearts).length > 0 && (
          <HeartLine label="人工调整" hearts={result.manual_hearts} />
        )}
        <HeartLine
          label="Live 所有 Heart"
          hearts={result.available_hearts}
          allColor={result.all_color_hearts}
        />
      </div>

      <div className="yell-reveals">
        <span>应援公开卡</span>
        <div>
          {result.revealed_instance_ids.length === 0 && <em>无</em>}
          {result.revealed_instance_ids.map((id) => (
            <button key={id} onClick={() => onCard(state.cards[id])}>
              {state.cards[id].card.name_ja}
            </button>
          ))}
        </div>
      </div>

      {result.special_blade_heart_results.length > 0 && (
        <div className="special-results">
          <span>特殊 Blade Heart</span>
          <div>
            {result.special_blade_heart_results.map((item, index) => (
              <code key={`${item.card_instance_id}-${index}`}>
                {item.source_alt} → {item.effect_type} {item.value}
              </code>
            ))}
          </div>
        </div>
      )}

      <div className="allocation-list">
        {result.live_allocations.length === 0 && (
          <div className="allocation-empty">尚无逐张 Live Heart 分配结果</div>
        )}
        {result.live_allocations.map((allocation) => (
          <div
            className={`allocation-row ${allocation.satisfied ? "satisfied" : "failed"}`}
            key={allocation.live_instance_id}
          >
            <button onClick={() => onCard(state.cards[allocation.live_instance_id])}>
              {state.cards[allocation.live_instance_id].card.name_ja}
            </button>
            <HeartLine label="需求" hearts={allocation.required_hearts} />
            <HeartLine
              label="消费"
              hearts={allocation.consumed_hearts}
              allColor={allocation.all_color_hearts_used}
            />
            <HeartLine label="缺口" hearts={allocation.missing_hearts} />
            <strong>{allocation.satisfied ? "满足" : "失败"}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}

function HeartLine({
  label,
  hearts,
  allColor = 0,
}: {
  label: string;
  hearts: Record<string, number>;
  allColor?: number;
}) {
  const entries = Object.entries(hearts).filter(([, amount]) => amount !== 0);
  return (
    <div className="heart-line">
      <span>{label}</span>
      <div>
        {entries.length === 0 && allColor === 0 && <em>0</em>}
        {entries.map(([color, amount]) => (
          <span className={`heart-token ${color}`} key={color}>
            <i />
            {heartLabels[color] ?? color} {amount}
          </span>
        ))}
        {allColor > 0 && (
          <span className="heart-token all-color">
            <i />
            ALL {allColor}
          </span>
        )}
      </div>
    </div>
  );
}

function Zone({
  label,
  ids,
  state,
  onCard,
  hand = false,
  small = false,
}: {
  label: string;
  ids: string[];
  state: MatchState;
  onCard: (card: CardInstance) => void;
  hand?: boolean;
  small?: boolean;
}) {
  return (
    <div className={`zone ${hand ? "hand-zone" : ""} ${small ? "small-zone" : ""}`}>
      <span className="zone-label">{label}</span>
      <div className="card-strip">
        {ids.length === 0 && <span className="zone-empty">空</span>}
        {ids.map((id) => (
          <CardTile key={id} instance={state.cards[id]} onClick={onCard} />
        ))}
      </div>
    </div>
  );
}

function CardTile({
  instance,
  onClick,
  selected = false,
}: {
  instance: CardInstance;
  onClick: (card: CardInstance) => void;
  selected?: boolean;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <button
      className={`card-tile ${instance.orientation === "wait" ? "wait" : ""} ${selected ? "selected" : ""}`}
      onClick={() => onClick(instance)}
      title={instance.card.name_ja}
    >
      {!imageFailed ? (
        <img
          src={`/api/card-images/${encodeURIComponent(instance.card.card_id)}`}
          alt={instance.card.name_ja}
          onError={() => setImageFailed(true)}
        />
      ) : (
        <div className={`card-fallback ${instance.card.card_type}`}>
          <span>{instance.card.card_type.toUpperCase()}</span>
          <strong>{instance.card.name_ja}</strong>
          <small>{instance.card.card_code}</small>
        </div>
      )}
      <div className="card-caption">
        <span>{instance.card.name_ja}</span>
        {instance.orientation === "wait" && <em>WAIT</em>}
      </div>
    </button>
  );
}

function EventLog({ events, state }: { events: GameEvent[]; state: MatchState }) {
  return (
    <aside className="event-panel">
      <div className="event-heading">
        <History size={18} />
        <strong>Action / Event Log</strong>
        <span>{events.length}</span>
      </div>
      <div className="event-list">
        {events.length === 0 && <div className="empty-state">等待第一项 Action</div>}
        {[...events].reverse().map((event, index) => (
          <div className={`event-row ${event.source}`} key={`${event.event_type}-${index}`}>
            <span>{event.source}</span>
            <strong>{event.event_type}</strong>
            <small>
              {event.player_id ? state.players[event.player_id]?.name : "System"}
            </small>
            <code>{JSON.stringify(event.data)}</code>
          </div>
        ))}
      </div>
    </aside>
  );
}

function ActionDock({
  state,
  actions,
  loading,
  onAction,
  onManual,
}: {
  state: MatchState;
  actions: LegalAction[];
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
  onManual: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [slot, setSlot] = useState("center");
  const [memberId, setMemberId] = useState("");
  const [liveOrder, setLiveOrder] = useState<string[]>([]);

  useEffect(() => {
    setSelected([]);
    setMemberId("");
    setLiveOrder([]);
  }, [state.revision]);

  return (
    <footer className="action-dock">
      <div className="action-context">
        <strong>Legal Actions</strong>
        <span>{state.active_player_id ? state.players[state.active_player_id].name : "System"}</span>
      </div>
      <div className="action-controls">
        {actions.map((action) => {
          if (action.action_type === "manual_adjustment") {
            return (
              <button className="secondary-button" key={action.action_type} onClick={onManual}>
                <Settings2 size={17} />
                {action.label_zh}
              </button>
            );
          }
          if (action.action_type === "choose_first_player") {
            return (action.options.player_ids as string[]).map((playerId) => (
              <button
                className="primary-button"
                key={playerId}
                disabled={loading}
                onClick={() => onAction(action.action_type, null, { first_player_id: playerId })}
              >
                <CirclePlay size={17} />
                {state.players[playerId].name} 先攻
              </button>
            ));
          }
          if (action.action_type === "submit_mulligan") {
            const hand = action.options.hand_instance_ids as string[];
            return (
              <SelectionAction
                key={action.action_type}
                title="选择需要调度的手牌"
                ids={hand}
                selected={selected}
                state={state}
                onToggle={(id) => toggleSelected(selected, id, setSelected)}
                onSubmit={() =>
                  onAction(action.action_type, action.player_id, {
                    card_instance_ids: selected,
                  })
                }
              />
            );
          }
          if (action.action_type === "set_live_cards") {
            const hand = action.options.hand_instance_ids as string[];
            return (
              <SelectionAction
                key={action.action_type}
                title="选择最多 3 张卡设置到 Live 区"
                ids={hand}
                selected={selected}
                state={state}
                maximum={3}
                onToggle={(id) => toggleSelected(selected, id, setSelected, 3)}
                onSubmit={() =>
                  onAction(action.action_type, action.player_id, {
                    card_instance_ids: selected,
                  })
                }
              />
            );
          }
          if (action.action_type === "play_member") {
            const cardIds = action.options.card_instance_ids as string[];
            const slots = action.options.slots as string[];
            const energy = action.options.active_energy_instance_ids as string[];
            const chosen = memberId || cardIds[0] || "";
            const cost = chosen ? state.cards[chosen].card.cost ?? 0 : 0;
            return (
              <div className="inline-action" key={action.action_type}>
                <select value={chosen} onChange={(e) => setMemberId(e.target.value)}>
                  {cardIds.map((id) => (
                    <option key={id} value={id}>
                      {state.cards[id].card.name_ja} · cost {state.cards[id].card.cost}
                    </option>
                  ))}
                </select>
                <select value={slot} onChange={(e) => setSlot(e.target.value)}>
                  {slots.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <button
                  className="primary-button"
                  onClick={() =>
                    onAction(action.action_type, action.player_id, {
                      card_instance_id: chosen,
                      slot,
                      energy_instance_ids: energy.slice(0, cost),
                    })
                  }
                >
                  登场
                </button>
              </div>
            );
          }
          if (action.action_type === "resolve_live_requirements") {
            if (action.options.card_instance_ids) {
              return (action.options.card_instance_ids as string[]).map((id) => (
                <button
                  className="primary-button"
                  key={id}
                  onClick={() =>
                    onAction(action.action_type, action.player_id, {
                      success_live_instance_id: id,
                    })
                  }
                >
                  选择 {state.cards[id].card.name_ja}
                </button>
              ));
            }
            const order =
              liveOrder.length > 0
                ? liveOrder
                : (action.options.live_instance_ids as string[]);
            return (
              <div className="order-action" key={action.action_type}>
                {order.map((id, index) => (
                  <span key={id}>
                    {state.cards[id].card.name_ja}
                    <button
                      className="mini-icon"
                      disabled={index === 0}
                      onClick={() => setLiveOrder(moveItem(order, index, index - 1))}
                    >
                      <ChevronUp size={14} />
                    </button>
                    <button
                      className="mini-icon"
                      disabled={index === order.length - 1}
                      onClick={() => setLiveOrder(moveItem(order, index, index + 1))}
                    >
                      <ChevronDown size={14} />
                    </button>
                  </span>
                ))}
                <button
                  className="primary-button"
                  onClick={() =>
                    onAction(action.action_type, action.player_id, {
                      live_instance_ids: order,
                    })
                  }
                >
                  确认判定顺序
                </button>
              </div>
            );
          }
          return (
            <button
              className="primary-button"
              key={action.action_type}
              disabled={loading}
              onClick={() => onAction(action.action_type, action.player_id)}
            >
              <ArrowDownToLine size={17} />
              {action.label_zh}
            </button>
          );
        })}
      </div>
    </footer>
  );
}

function SelectionAction({
  title,
  ids,
  selected,
  state,
  maximum,
  onToggle,
  onSubmit,
}: {
  title: string;
  ids: string[];
  selected: string[];
  state: MatchState;
  maximum?: number;
  onToggle: (id: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="selection-action">
      <span>{title}</span>
      <div className="selection-cards">
        {ids.map((id) => (
          <button
            className={selected.includes(id) ? "selected" : ""}
            key={id}
            onClick={() => onToggle(id)}
          >
            {state.cards[id].card.name_ja}
          </button>
        ))}
      </div>
      <button className="primary-button" onClick={onSubmit}>
        确认 {selected.length}
        {maximum ? ` / ${maximum}` : ""}
      </button>
    </div>
  );
}

function ManualDrawer({
  state,
  onClose,
  onSubmit,
}: {
  state: MatchState;
  onClose: () => void;
  onSubmit: (playerId: string, payload: Record<string, unknown>) => void;
}) {
  const [playerId, setPlayerId] = useState(state.active_player_id ?? "player_1");
  const [type, setType] = useState("modify_score");
  const [amount, setAmount] = useState("1");
  const [cardId, setCardId] = useState("");
  const [toZone, setToZone] = useState("waiting_room");
  const [color, setColor] = useState("heart01");
  const cards = Object.values(state.cards).filter((card) => card.owner_id === playerId);
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="manual-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>ManualAdjustmentAction</strong>
            <span>结构化人工规则调整</span>
          </div>
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <label>
          Target player
          <select value={playerId} onChange={(e) => setPlayerId(e.target.value)}>
            {Object.values(state.players).map((player) => (
              <option key={player.player_id} value={player.player_id}>
                {player.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Adjustment type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {[
              "move_card",
              "draw_card",
              "discard_card",
              "ready_energy",
              "pay_energy",
              "modify_score",
              "modify_heart",
              "modify_blade",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        {["move_card", "discard_card", "ready_energy", "pay_energy"].includes(type) && (
          <label>
            Target card
            <select value={cardId} onChange={(e) => setCardId(e.target.value)}>
              <option value="">请选择</option>
              {cards.map((card) => (
                <option key={card.instance_id} value={card.instance_id}>
                  {card.card.name_ja} · {card.instance_id}
                </option>
              ))}
            </select>
          </label>
        )}
        {type === "move_card" && (
          <label>
            Target zone
            <select value={toZone} onChange={(e) => setToZone(e.target.value)}>
              {[
                "hand",
                "main_deck",
                "energy_area",
                "live_area",
                "waiting_room",
                "resolution_area",
                "success_live_area",
                "member_left",
                "member_center",
                "member_right",
              ].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
        )}
        {type === "modify_heart" && (
          <label>
            Heart color
            <select value={color} onChange={(e) => setColor(e.target.value)}>
              {["heart0", "heart01", "heart02", "heart03", "heart04", "heart05", "heart06"].map(
                (item) => (
                  <option key={item}>{item}</option>
                ),
              )}
            </select>
          </label>
        )}
        {["draw_card", "modify_score", "modify_heart", "modify_blade"].includes(type) && (
          <label>
            Amount
            <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" />
          </label>
        )}
        <button
          className="primary-button"
          onClick={() =>
            onSubmit(playerId, {
              reason: "UI manual rule verification",
              requires_confirmation: true,
              confirmed_by: "local_debugger",
              adjustments: [
                {
                  adjustment_type: type,
                  target_player_id: playerId,
                  target_card_instance_id: cardId || undefined,
                  to_zone: type === "move_card" ? toZone : undefined,
                  color_slot: type === "modify_heart" ? color : undefined,
                  amount: Number(amount),
                },
              ],
            })
          }
        >
          提交结构化调整
        </button>
      </aside>
    </div>
  );
}

function CardDialog({ instance, onClose }: { instance: CardInstance; onClose: () => void }) {
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <article className="card-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button close-dialog" onClick={onClose}>
          <X size={18} />
        </button>
        <div className="dialog-image">
          <img
            src={`/api/card-images/${encodeURIComponent(instance.card.card_id)}`}
            alt={instance.card.name_ja}
          />
        </div>
        <div className="dialog-content">
          <span>{instance.card.card_type.toUpperCase()} · {instance.card.card_code}</span>
          <h2>{instance.card.name_ja}</h2>
          <div className="attribute-grid">
            <Metric label="Cost" value={instance.card.cost ?? "-"} />
            <Metric label="Blade" value={instance.card.blade ?? "-"} />
            <Metric label="Score" value={instance.card.score ?? "-"} />
            <Metric label="State" value={instance.orientation} />
          </div>
          <h3>官方日文效果</h3>
          <p className="effect-text">{instance.card.raw_effect_text_ja ?? "効果テキストなし"}</p>
          <h3>Heart</h3>
          <code>{JSON.stringify(instance.card.basic_hearts)}</code>
          <code>{JSON.stringify(instance.card.required_hearts)}</code>
        </div>
      </article>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function toggleSelected(
  selected: string[],
  id: string,
  setter: (value: string[]) => void,
  maximum?: number,
) {
  if (selected.includes(id)) {
    setter(selected.filter((item) => item !== id));
  } else if (!maximum || selected.length < maximum) {
    setter([...selected, id]);
  }
}

function moveItem(items: string[], from: number, to: number): string[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

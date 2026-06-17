import {
  Activity,
  ArrowDownToLine,
  BookOpen,
  ClipboardList,
  ChevronDown,
  ChevronUp,
  CirclePlay,
  Database,
  Download,
  HelpCircle,
  History,
  Play,
  RefreshCw,
  Settings2,
  Swords,
  X,
} from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  createMatch,
  createRoom,
  cardImageUrl,
  getRuntimeConfigSnapshot,
  getMatch,
  getRoom,
  getSavedDeck,
  joinRoom,
  listMatches,
  listSavedDecks,
  loadRuntimeConfig,
  matchReplayUrl,
  roomReplayUrl,
  submitAction,
  submitRoomAction,
} from "./api";
import { CatalogBrowser } from "./catalog-browser";
import { DeckBuilder } from "./deck-builder";
import type {
  CardInstance,
  DeckList,
  GameEvent,
  LegalAction,
  MatchListResponse,
  MatchPayload,
  MatchState,
  MatchSummary,
  SavedDeckSummary,
  PlayerState,
  EffectInvocation,
  RoomPayload,
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
  turn_complete: ["本回合判定完成", "ターン完了"],
  complete: ["对局结束", "対戦終了"],
};

const MATCH_HISTORY_PAGE_SIZE = 10;
const emptyMatchHistory: MatchListResponse = {
  items: [],
  page: 1,
  per_page: MATCH_HISTORY_PAGE_SIZE,
  total: 0,
  max_total: 100,
};

function matchHistoryAvailable(config: { browserPreview: boolean; apiBaseUrl: string }): boolean {
  return !config.browserPreview || config.apiBaseUrl.length > 0;
}

type UiLocale = "zh" | "ja";
type StartDeckSource = {
  id: string;
  kind: "draft" | "saved";
  label: string;
  mainCount: number;
  energyCount: number;
};

const UiLanguageContext = createContext<{
  locale: UiLocale;
  setLocale: (locale: UiLocale) => void;
}>({ locale: "zh", setLocale: () => undefined });

type OnlineSession = {
  roomCode: string;
  playerId: "player_1" | "player_2";
  playerToken: string;
};

const heartLabels: Record<UiLocale, Record<string, string>> = {
  zh: {
    heart0: "任意色",
    heart01: "粉色",
    heart02: "红色",
    heart03: "黄色",
    heart04: "绿色",
    heart05: "蓝色",
    heart06: "紫色",
  },
  ja: {
    heart0: "任意色",
    heart01: "ピンク",
    heart02: "赤",
    heart03: "黄",
    heart04: "緑",
    heart05: "青",
    heart06: "紫",
  },
};

const judgmentBasisLabels: Record<string, [string, string]> = {
  no_successful_live: ["双方均无满足所需爱心的演出，不产生胜者", "双方とも必要ハートを満たすライブがなく、勝者なし"],
  only_one_player_has_successful_live: ["仅一方有成功演出，该玩家胜利", "一方のみ成功ライブがあり、そのプレイヤーの勝利"],
  equal_total_score: ["双方演出总分相同，双方均胜利", "双方のライブ合計スコアが同じため、双方勝利"],
  higher_total_score: ["比较双方演出总分，较高者胜利", "双方のライブ合計スコアを比較し、高い側の勝利"],
};

export default function App() {
  const [runtimeConfig, setRuntimeConfig] = useState(getRuntimeConfigSnapshot);
  const browserPreview = runtimeConfig.browserPreview;
  const hostedOnline = runtimeConfig.apiBaseUrl.length > 0;
  const [locale, setLocale] = useState<UiLocale>(() => {
    const stored = localStorage.getItem("loveca-ui-locale");
    if (stored === "ja" || stored === "zh") return stored;
    return "ja";
  });
  const [screen, setScreen] = useState<"home" | "match" | "catalog" | "decks">("home");
  const [match, setMatch] = useState<MatchPayload | null>(null);
  const [matchHistory, setMatchHistory] = useState<MatchListResponse>(emptyMatchHistory);
  const [matchHistoryLoaded, setMatchHistoryLoaded] = useState(false);
  const [matchHistoryLoading, setMatchHistoryLoading] = useState(false);
  const [savedDecks, setSavedDecks] = useState<SavedDeckSummary[]>([]);
  const [draftDeck, setDraftDeck] = useState<DeckList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<CardInstance | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualSource, setManualSource] = useState<EffectInvocation | null>(null);
  const [showPreviewNotice, setShowPreviewNotice] = useState(browserPreview);
  const [showUsageGuide, setShowUsageGuide] = useState(true);
  const [usageGuideLocale, setUsageGuideLocale] = useState<UiLocale>("ja");
  const [onlineSession, setOnlineSession] = useState<OnlineSession | null>(null);
  const [onlineRoom, setOnlineRoom] = useState<RoomPayload | null>(null);
  const [onlineStatus, setOnlineStatus] = useState<string | null>(null);

  const loadMatchHistoryPage = useCallback((page = 1) => {
    if (!matchHistoryAvailable(runtimeConfig)) {
      setMatchHistory(emptyMatchHistory);
      setMatchHistoryLoaded(true);
      return Promise.resolve();
    }
    setMatchHistoryLoading(true);
    return listMatches({ page, perPage: MATCH_HISTORY_PAGE_SIZE })
      .then((history) => {
        setMatchHistory(history);
        setMatchHistoryLoaded(true);
      })
      .catch(() => {
        setMatchHistory(emptyMatchHistory);
        setMatchHistoryLoaded(true);
      })
      .finally(() => setMatchHistoryLoading(false));
  }, [runtimeConfig]);

  useEffect(() => {
    let disposed = false;
    loadRuntimeConfig()
      .then((config) => {
        if (disposed) return;
        setRuntimeConfig(config);
        setShowPreviewNotice(config.browserPreview);
        if (!matchHistoryAvailable(config)) {
          setMatchHistory(emptyMatchHistory);
          setMatchHistoryLoaded(true);
        }
        listSavedDecks().then(setSavedDecks).catch(() => setSavedDecks([]));
      })
      .catch(() => {
        if (disposed) return;
        const config = getRuntimeConfigSnapshot();
        if (!matchHistoryAvailable(config)) {
          setMatchHistory(emptyMatchHistory);
          setMatchHistoryLoaded(true);
        }
        listSavedDecks().then(setSavedDecks).catch(() => setSavedDecks([]));
      });
    return () => {
      disposed = true;
    };
  }, []);
  useEffect(() => {
    localStorage.setItem("loveca-ui-locale", locale);
    document.documentElement.lang = locale === "ja" ? "ja" : "zh-CN";
  }, [locale]);
  useEffect(() => {
    if (!onlineSession) return;
    let disposed = false;
    const poll = async () => {
      try {
        const room = await getRoom(onlineSession.roomCode, onlineSession.playerToken);
        if (disposed) return;
        setOnlineRoom(room);
        setOnlineStatus(null);
        if (room.match) {
          setMatch((current) => ({
            ...room.match!,
            events: current?.state.match_id === room.match!.state.match_id
              ? mergeEvents(current.events, room.match!.events)
              : room.match!.events,
          }));
          setScreen("match");
        }
      } catch (reason) {
        if (!disposed) {
          setOnlineStatus(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };
    void poll();
    const id = window.setInterval(() => void poll(), 2000);
    return () => {
      disposed = true;
      window.clearInterval(id);
    };
  }, [onlineSession]);

  const previewNotice = browserPreview && showPreviewNotice ? (
    <PreviewNotice
      locale={locale}
      hostedOnline={hostedOnline}
      onClose={() => {
        setShowPreviewNotice(false);
      }}
    />
  ) : null;
  const usageGuide = showUsageGuide && !showPreviewNotice ? (
    <UsageGuideDialog locale={usageGuideLocale} onClose={() => setShowUsageGuide(false)} />
  ) : null;
  const renderShell = (content: ReactNode) => (
    <UiLanguageContext.Provider value={{ locale, setLocale }}>
      {content}
      {previewNotice}
      {usageGuide}
    </UiLanguageContext.Provider>
  );

  const deckSources = useMemo<StartDeckSource[]>(() => {
    const sources: StartDeckSource[] = [];
    if (draftDeck) {
      sources.push({
        id: "draft",
        kind: "draft",
        label:
          draftDeck.name ??
          (locale === "zh" ? "当前编辑中牌组" : "編集中のデッキ"),
        mainCount: draftDeck.main_deck.reduce((sum, entry) => sum + entry.quantity, 0),
        energyCount: draftDeck.energy_deck.reduce((sum, entry) => sum + entry.quantity, 0),
      });
    }
    for (const item of savedDecks) {
      sources.push({
        id: `saved:${item.path}`,
        kind: "saved",
        label: item.name ?? item.path,
        mainCount: item.main_card_count,
        energyCount: item.energy_card_count,
      });
    }
    return sources;
  }, [draftDeck, locale, savedDecks]);

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
        onlineSession
          ? submitRoomAction(onlineSession.roomCode, onlineSession.playerToken, {
            action_type: actionType,
            expected_revision: match.state.revision,
            player_id: playerId,
            payload,
          })
          : submitAction(match.state.match_id, {
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

  async function resolveDeckSource(sourceId: string): Promise<DeckList> {
    if (sourceId === "draft") {
      if (!draftDeck) {
        throw new Error(locale === "zh" ? "当前没有临时牌组。" : "一時デッキがありません。");
      }
      return draftDeck;
    }
    if (sourceId.startsWith("saved:")) {
      return getSavedDeck(sourceId.slice("saved:".length));
    }
    throw new Error(locale === "zh" ? "未知牌组来源。" : "不明なデッキソースです。");
  }

  if (!match) {
    if (screen === "catalog") {
      return renderShell(
          <CatalogBrowser
            locale={locale}
            setLocale={setLocale}
            onBack={() => setScreen("home")}
          />,
      );
    }
    if (screen === "decks") {
      return renderShell(
          <DeckBuilder
            locale={locale}
            setLocale={setLocale}
            onBack={() => {
              listSavedDecks().then(setSavedDecks).catch(() => setSavedDecks([]));
              setScreen("home");
            }}
            onUseForMatch={(deck) => {
              setDraftDeck(deck);
              setMatch(null);
              setScreen("home");
            }}
          />,
      );
    }
    return renderShell(
        <StartScreen
          matches={matchHistory.items}
          history={matchHistory}
          historyLoaded={matchHistoryLoaded}
          historyLoading={matchHistoryLoading}
          deckSources={deckSources}
          loading={loading}
          error={error}
          browserPreview={browserPreview}
          hostedOnline={hostedOnline}
          matchCreationDisabled={browserPreview}
          matchCreationDisabledMessage={locale === "zh"
            ? "浏览器预览版暂不包含本地规则引擎。请使用本地版启动对战，或连接远程服务创建在线测试房间。"
            : "ブラウザプレビュー版にはローカルルールエンジンが含まれていません。ローカル版で対戦を開始するか、リモートサービスに接続してオンライン検証ルームを作成してください。"}
          onBrowse={() => setScreen("catalog")}
          onDeckBuilder={() => setScreen("decks")}
          onHelp={() => {
            setUsageGuideLocale(locale);
            setShowUsageGuide(true);
          }}
          onlineAvailable={hostedOnline}
          onlineRoom={onlineRoom}
          onlineStatus={onlineStatus}
          onCreateOnlineRoom={async (input) => {
            await run(
              async () =>
                createRoom({
                  playerName: input.playerName,
                  deck: await resolveDeckSource(input.deckSourceId),
                  seed: input.seed,
                }),
              (room) => {
                if (!room.player_token || room.player_id !== "player_1") {
                  throw new Error("online room response did not include a host token");
                }
                setOnlineSession({
                  roomCode: room.room_code,
                  playerId: room.player_id,
                  playerToken: room.player_token,
                });
                setOnlineRoom(room);
                if (room.match) {
                  setMatch(room.match);
                  setScreen("match");
                }
              },
            );
          }}
          onJoinOnlineRoom={async (input) => {
            await run(
              async () =>
                joinRoom({
                  roomCode: input.roomCode,
                  playerName: input.playerName,
                  deck: await resolveDeckSource(input.deckSourceId),
                }),
              (room) => {
                if (!room.player_token || room.player_id !== "player_2") {
                  throw new Error("online room response did not include a guest token");
                }
                setOnlineSession({
                  roomCode: room.room_code,
                  playerId: room.player_id,
                  playerToken: room.player_token,
                });
                setOnlineRoom(room);
                if (room.match) {
                  setMatch(room.match);
                  setScreen("match");
                }
              },
            );
          }}
          onCreate={async (input) => {
            await run(
              async () =>
                createMatch({
                  player1Name: input.player1Name,
                  player1Deck: await resolveDeckSource(input.player1SourceId),
                  player2Name: input.player2Name,
                  player2Deck: await resolveDeckSource(input.player2SourceId),
                  seed: input.seed,
                }),
              (next) => {
                setMatch(next);
                setScreen("match");
              },
            );
          }}
          onResume={(id) =>
            run(() => getMatch(id), (next) => {
              setMatch(next);
              setScreen("match");
            })
          }
          onHistoryRefresh={() => void loadMatchHistoryPage(1)}
          onHistoryPage={(page) => void loadMatchHistoryPage(page)}
        />,
      );
  }

  if (screen === "catalog") {
    return renderShell(
        <CatalogBrowser
          locale={locale}
          setLocale={setLocale}
          onBack={() => setScreen("match")}
        />,
    );
  }
  if (screen === "decks") {
    return renderShell(
          <DeckBuilder
            locale={locale}
            setLocale={setLocale}
            onBack={() => setScreen("match")}
            onUseForMatch={(deck) => {
              setDraftDeck(deck);
              setMatch(null);
              setScreen("home");
            }}
          />,
      );
  }

  const bottomPlayerId = onlineSession?.playerId ?? "player_1";
  const topPlayerId = bottomPlayerId === "player_1" ? "player_2" : "player_1";
  const visibleActions = onlineSession
    ? match.legal_actions.filter((action) => canSubmitOnlineAction(action, onlineSession.playerId))
    : match.legal_actions;

  return renderShell(
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <Swords size={22} />
          <div>
            <strong>{locale === "zh" ? "LoveCA 规则验证器" : "LoveCA ルール検証ツール"}</strong>
            <span>総合ルール ver. {match.state.rule_version}</span>
          </div>
        </div>
        <div className="phase-status">
          {onlineSession && (
            <span className="turn-number">
              {locale === "zh" ? "房间" : "ルーム"} {onlineSession.roomCode}
            </span>
          )}
          <span className="turn-number">
            {locale === "zh" ? `第 ${match.state.turn_number} 回合` : `ターン ${match.state.turn_number}`}
          </span>
          <span className="phase-cn">
            {phaseLabels[match.state.phase]?.[locale === "zh" ? 0 : 1] ?? match.state.phase}
          </span>
          {locale === "zh" && <span>{phaseLabels[match.state.phase]?.[1] ?? match.state.phase}</span>}
        </div>
        <div className="top-actions">
          <LanguageToggle />
          <span className="revision">
            {locale === "zh" ? "操作步数" : "操作数"} {match.state.revision}
          </span>
          <button
            className="icon-button"
            title={locale === "zh" ? "使用说明" : "使い方"}
            onClick={() => {
              setUsageGuideLocale(locale);
              setShowUsageGuide(true);
            }}
          >
            <HelpCircle size={18} />
          </button>
          <button
            className="icon-button"
            title={locale === "zh" ? "浏览卡牌库" : "カード閲覧"}
            onClick={() => setScreen("catalog")}
          >
            <BookOpen size={18} />
          </button>
          <button
            className="icon-button"
            title={locale === "zh" ? "牌组编辑器" : "デッキ編集"}
            onClick={() => setScreen("decks")}
          >
            <ClipboardList size={18} />
          </button>
          {onlineSession ? (
            <a
              className="icon-button"
              href={roomReplayUrl(onlineSession.roomCode, onlineSession.playerToken)}
              title={locale === "zh" ? "导出在线回放 JSON" : "オンラインリプレイ JSON を出力"}
            >
              <Download size={18} />
            </a>
          ) : browserPreview ? (
            <button
              className="icon-button"
              disabled
              title={locale === "zh" ? "预览版不支持回放导出" : "プレビュー版ではリプレイ出力は未対応"}
            >
              <Download size={18} />
            </button>
          ) : (
            <a
              className="icon-button"
              href={matchReplayUrl(match.state.match_id)}
              title={locale === "zh" ? "导出回放 JSON" : "リプレイ JSON を出力"}
            >
              <Download size={18} />
            </a>
          )}
          <button
            className="icon-button"
            title={locale === "zh" ? "返回对局列表" : "対戦一覧へ戻る"}
            onClick={() => {
              setMatch(null);
              setOnlineSession(null);
              setOnlineRoom(null);
              setOnlineStatus(null);
            }}
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className="workspace">
        <section className="board-column">
          <PlayerBoard
            player={match.state.players[topPlayerId]}
            state={match.state}
            role={playerRoleLabel(match.state, topPlayerId, locale)}
            compact
            hideHand
            onCard={setDetails}
          />
          <LiveCenter state={match.state} onCard={setDetails} />
          <PlayerBoard
            player={match.state.players[bottomPlayerId]}
            state={match.state}
            role={playerRoleLabel(match.state, bottomPlayerId, locale)}
            onCard={setDetails}
          />
        </section>
        <EventLog events={match.events} state={match.state} />
      </main>

      {visibleActions.length > 0 && (
        <ActionDock
          state={match.state}
          actions={visibleActions}
          loading={loading}
          onAction={handleAction}
          onManual={(source) => {
            setManualSource(source ?? null);
            setManualOpen(true);
          }}
        />
      )}
      {onlineSession && match.legal_actions.length > 0 && visibleActions.length === 0 && (
        <footer className="action-dock">
          <div className="action-context">
            <strong>{locale === "zh" ? "下一步操作" : "次にできる操作"}</strong>
            <span>{locale === "zh" ? "等待对手操作" : "相手の操作待ち"}</span>
          </div>
        </footer>
      )}

      {details && (
        <CardDialog
          instance={details}
          state={match.state}
          onClose={() => setDetails(null)}
        />
      )}
      {manualOpen && (
        <ManualDrawer
          state={match.state}
          source={manualSource}
          onClose={() => {
            setManualOpen(false);
            setManualSource(null);
          }}
          onSubmit={(playerId, payload) => {
            setManualOpen(false);
            setManualSource(null);
            void handleAction("manual_adjustment", playerId, payload);
          }}
        />
      )}
    </div>,
  );
}

function useUiLanguage() {
  const context = useContext(UiLanguageContext);
  return {
    ...context,
    tr: (zh: string, ja: string) => (context.locale === "zh" ? zh : ja),
  };
}

function canSubmitOnlineAction(action: LegalAction, localPlayerId: string): boolean {
  return action.player_id === null || action.player_id === localPlayerId;
}

function playerRoleLabel(state: MatchState, playerId: string, locale: UiLocale): string {
  if (state.first_player_id === playerId) return "先攻";
  if (state.second_player_id === playerId) return locale === "zh" ? "后攻" : "後攻";
  return locale === "zh" ? "未定" : "未定";
}

function mergeEvents(existing: GameEvent[], incoming: GameEvent[]): GameEvent[] {
  if (incoming.length <= existing.length) return existing;
  return [...existing, ...incoming.slice(existing.length)];
}

function PreviewNotice({
  locale,
  hostedOnline,
  onClose,
}: {
  locale: UiLocale;
  hostedOnline: boolean;
  onClose: () => void;
}) {
  return (
    <div className="preview-notice-backdrop" role="dialog" aria-modal="true">
      <section className="preview-notice">
        <div className="preview-notice-header">
          <strong>{locale === "zh" ? "浏览器预览版" : "ブラウザプレビュー版"}</strong>
          <button
            className="mini-icon"
            onClick={onClose}
            aria-label={locale === "zh" ? "关闭" : "閉じる"}
          >
            <X size={16} />
          </button>
        </div>
        <div className="preview-notice-grid">
          <section>
            <h3>{locale === "zh" ? "当前可以做" : "現在できること"}</h3>
            <ul>
              <li>{locale === "zh" ? "浏览已打包的卡库数据" : "同梱済みカードデータの閲覧"}</li>
              <li>{locale === "zh" ? "查看卡牌详情和官方图片链接" : "カード詳細と公式画像 URL の確認"}</li>
              <li>{locale === "zh" ? "在浏览器本地保存牌组" : "ブラウザローカルでデッキ保存"}</li>
              <li>{locale === "zh" ? "查看 5 个合法初始测试牌组" : "5個の合法な初期テストデッキの確認"}</li>
              <li>{locale === "zh" ? "导入 / 导出 decklist.v0 JSON" : "decklist.v0 JSON の読み込み / 書き出し"}</li>
              <li>{locale === "zh" ? "进行 MVP 牌组合法性和属性分析" : "MVP デッキ合法性 / 属性分析"}</li>
            </ul>
          </section>
          <section>
            <h3>{locale === "zh" ? "当前还不能做" : "まだできないこと"}</h3>
            <ul>
              <li>
                {hostedOnline
                  ? locale === "zh"
                    ? "浏览器内纯本地对战引擎"
                    : "ブラウザ内だけで動くローカル対戦エンジン"
                  : locale === "zh"
                    ? "浏览器内完整对战验证"
                    : "ブラウザ内の完全な対戦検証"}
              </li>
              <li>
                {hostedOnline
                  ? locale === "zh"
                    ? "实时通信、房间列表、账号和长期保存"
                    : "リアルタイム通信、ルーム一覧、アカウント、長期保存"
                  : locale === "zh"
                    ? "在线双人对战"
                    : "オンライン二人対戦"}
              </li>
              <li>{locale === "zh" ? "完整技能自动化" : "全スキル自動化"}</li>
              <li>{locale === "zh" ? "云端账号、同步或防作弊" : "クラウドアカウント、同期、不正対策"}</li>
            </ul>
          </section>
        </div>
        <p>
          {locale === "zh"
            ? "数据保存在当前浏览器中。这个预览版本用于稳定公开体验，开发中的规则引擎仍会继续快速迭代。"
            : "データはこのブラウザ内に保存されます。このプレビュー版は公開体験を安定させるためのもので、開発中のルールエンジンは継続して更新されます。"}
        </p>
        <button className="primary-button" onClick={onClose}>
          {locale === "zh" ? "开始使用" : "始める"}
        </button>
      </section>
    </div>
  );
}

function UsageGuideDialog({
  locale,
  onClose,
}: {
  locale: UiLocale;
  onClose: () => void;
}) {
  const isZh = locale === "zh";
  const [pageIndex, setPageIndex] = useState(0);
  const pages = [
    {
      icon: <CirclePlay size={28} />,
      label: isZh ? "01 / 开始" : "01 / 開始",
      title: isZh ? "先看底部能点什么" : "まず下のボタンを見ます",
      caption: isZh
        ? "对局里不用猜下一步。现在能做的事，都会变成屏幕底部的按钮。"
        : "次に何をするか迷う必要はありません。今できることは画面下部のボタンになります。",
      visual: (
        <div className="usage-flow-strip">
          <div className="usage-flow-card">
            <ClipboardList size={22} />
            <strong>{isZh ? "选牌组" : "デッキ選択"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card accent">
            <Play size={22} />
            <strong>{isZh ? "下一步按钮" : "次のボタン"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card">
            <History size={22} />
            <strong>{isZh ? "看记录" : "履歴確認"}</strong>
          </div>
        </div>
      ),
      items: [
        isZh ? "不知道该做什么时，先看屏幕底部。" : "何をするか迷ったら、まず画面下部を見ます。",
        isZh ? "想确认卡牌效果，就点那张卡。" : "カード効果を確認したいときは、そのカードを押します。",
        isZh ? "刚才发生了什么，可以看右侧记录。" : "直前に何が起きたかは、右側の履歴で確認できます。",
      ],
    },
    {
      icon: <BookOpen size={28} />,
      label: isZh ? "02 / 首页" : "02 / ホーム",
      title: isZh ? "首页先选你要做的事" : "ホームで目的を選びます",
      caption: isZh
        ? "这里不是只有开对局。你可以先整理牌组、查卡牌，也可以从以前的记录继续。"
        : "対戦を始めるだけではありません。デッキを整える、カードを調べる、前の記録から再開することもできます。",
      visual: (
        <div className="usage-adjust-grid">
          <div>
            <CirclePlay size={20} />
            <span>{isZh ? "开新对局" : "新規対戦"}</span>
          </div>
          <div>
            <ClipboardList size={20} />
            <span>{isZh ? "编辑牌组" : "デッキ編集"}</span>
          </div>
          <div>
            <BookOpen size={20} />
            <span>{isZh ? "查卡牌" : "カード確認"}</span>
          </div>
          <div>
            <History size={20} />
            <span>{isZh ? "继续旧局" : "履歴から再開"}</span>
          </div>
        </div>
      ),
      items: [
        isZh ? "想测试规则，先选双方牌组再创建对局。" : "ルールを試すときは、両方のデッキを選んで対戦を作ります。",
        isZh ? "牌组不确定时，先进牌组编辑器保存一副可用牌组。" : "デッキが決まっていないときは、デッキ編集で保存します。",
        isZh ? "只想看卡图、效果或收录信息，就进卡牌库。" : "カード画像、能力、収録情報だけ見たいときはカード一覧を使います。",
      ],
    },
    {
      icon: <History size={28} />,
      label: isZh ? "03 / 履历" : "03 / 履歴",
      title: isZh ? "履历是回到旧测试的入口" : "履歴から前の検証に戻れます",
      caption: isZh
        ? "刷新页面后，最近对局会从服务器或本地数据库读回来。它适合接着打、复盘问题，或者确认当时停在第几步。"
        : "ページを更新しても、最近の対戦はサーバーまたはローカルDBから読み直されます。続きを打つ、問題を見直す、何手目で止まったか確認するための場所です。",
      visual: (
        <div className="usage-flow-strip">
          <div className="usage-flow-card">
            <RefreshCw size={22} />
            <strong>{isZh ? "刷新" : "更新"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card accent">
            <History size={22} />
            <strong>{isZh ? "最近 100 局" : "最近100件"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card">
            <Play size={22} />
            <strong>{isZh ? "继续" : "再開"}</strong>
          </div>
        </div>
      ),
      items: [
        isZh ? "每页显示 10 局，太旧的记录用翻页找。" : "1ページに10件ずつ表示します。古い記録はページを送って探します。",
        isZh ? "“操作步数”就是这局已经提交过多少步操作。" : "「操作数」は、その対戦で送信済みの操作回数です。",
        isZh ? "这不是排行榜，只是规则测试和复盘用的入口。" : "ランキングではなく、検証と見直しのための入口です。",
      ],
    },
    {
      icon: <Settings2 size={28} />,
      label: isZh ? "04 / 卡住" : "04 / 停止時",
      title: isZh ? "卡住时不是出错" : "止まってもエラーではありません",
      caption: isZh
        ? "有些技能还没完全自动处理。系统会停下来，让你像线下打牌一样把结果补进去。"
        : "まだ自動処理できない能力があります。その場合は、実際の対戦と同じように結果を手で入れます。",
      visual: (
        <div className="usage-manual-visual">
          <div className="usage-effect-card">
            <span>{isZh ? "待处理技能" : "待機中の能力"}</span>
            <strong>{isZh ? "需要你处理" : "手で処理します"}</strong>
            <small>{isZh ? "自动处理还没覆盖" : "自動処理は未対応"}</small>
          </div>
          <div className="usage-manual-button">
            <Settings2 size={22} />
            <strong>{isZh ? "人工处理" : "手動処理"}</strong>
          </div>
        </div>
      ),
      items: [
        isZh ? "先看它正在等哪张卡、哪个技能。" : "まず、どのカードの能力で止まっているか確認します。",
        isZh ? "点“人工处理技能”，把实际处理结果填进去。" : "「手動処理」を押して、実際の処理結果を入力します。",
        isZh ? "除非只是调试，否则不要一上来就跳过技能。" : "デバッグ目的でない限り、いきなりスキップしないでください。",
      ],
    },
    {
      icon: <ArrowDownToLine size={28} />,
      label: isZh ? "05 / 怎么补" : "05 / 補正方法",
      title: isZh ? "按牌局结果补一下" : "対戦結果に合わせて入れます",
      caption: isZh
        ? "比如这个技能应该抽 1 张、把一张卡从控室拿回手牌，或者给角色加爱心，就在这里选对应动作。"
        : "例えば、1枚引く、控え室から手札に戻す、ハートを増やす、といった結果をここで選びます。",
      visual: (
        <div className="usage-adjust-grid">
          <div>
            <ArrowDownToLine size={20} />
            <span>{isZh ? "移动卡" : "カード移動"}</span>
          </div>
          <div>
            <RefreshCw size={20} />
            <span>{isZh ? "能量横竖" : "エネルギー向き"}</span>
          </div>
          <div>
            <Activity size={20} />
            <span>{isZh ? "分数/爱心" : "スコア/ハート"}</span>
          </div>
          <div>
            <Database size={20} />
            <span>{isZh ? "看牌/抽牌" : "確認/ドロー"}</span>
          </div>
        </div>
      ),
      items: [
        isZh ? "卡去了哪里，就用“移动卡”。" : "カードの移動先を直すときは「カード移動」です。",
        isZh ? "能量要横放或竖起来，就用能量状态调整。" : "エネルギーの向きを変えるときは、エネルギー状態の調整を使います。",
        isZh ? "分数、爱心、应援棒变了，就用数值修正。" : "スコア、ハート、ブレードが変わるなら数値修正を使います。",
      ],
    },
    {
      icon: <History size={28} />,
      label: isZh ? "06 / 提交后" : "06 / 送信後",
      title: isZh ? "提交后继续打" : "送信したら続きます",
      caption: isZh
        ? "提交后系统会把这次人工处理记到右侧记录里，然后对局继续。漏了一步也可以再补。"
        : "送信すると、その手動処理は右側の履歴に残り、対戦が続きます。足りない分は後から補えます。",
      visual: (
        <div className="usage-flow-strip">
          <div className="usage-flow-card accent">
            <Settings2 size={22} />
            <strong>{isZh ? "人工处理" : "手動処理"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card">
            <History size={22} />
            <strong>{isZh ? "操作记录" : "履歴"}</strong>
          </div>
          <span className="usage-flow-arrow">→</span>
          <div className="usage-flow-card">
            <Play size={22} />
            <strong>{isZh ? "继续" : "続行"}</strong>
          </div>
        </div>
      ),
      items: [
        isZh ? "先看场面是不是和实际处理结果一致。" : "まず盤面が実際の処理結果と合っているか見ます。",
        isZh ? "如果少动了一张卡，再开人工处理补一次。" : "カードを動かし忘れたら、もう一度手動処理で補います。",
        isZh ? "真的不知道怎么处理，或只是想继续测试流程时，才跳过。" : "処理が分からない、または流れだけ確認したいときだけスキップします。",
      ],
    },
  ];
  const page = pages[pageIndex];
  const isLastPage = pageIndex === pages.length - 1;
  return (
    <div className="usage-guide-backdrop" role="dialog" aria-modal="true" aria-labelledby="usage-guide-title">
      <section className="usage-guide">
        <div className="usage-guide-header">
          <div>
            <span>{page.label}</span>
            <strong id="usage-guide-title">
              {page.title}
            </strong>
          </div>
          <button
            className="mini-icon"
            onClick={onClose}
            aria-label={isZh ? "关闭使用说明" : "使い方を閉じる"}
          >
            <X size={16} />
          </button>
        </div>
        <div className="usage-guide-page">
          <div className="usage-guide-hero">
            <div className="usage-guide-icon">{page.icon}</div>
            {page.visual}
          </div>
          <div className="usage-guide-copy">
            <p>{page.caption}</p>
            <ul>
              {page.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
        <div className="usage-guide-footer">
          <button
            className="secondary-button"
            disabled={pageIndex === 0}
            onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
          >
            {isZh ? "上一页" : "前へ"}
          </button>
          <div className="usage-guide-dots" aria-label={isZh ? "说明页码" : "ページ"}>
            {pages.map((item, index) => (
              <button
                key={item.label}
                className={index === pageIndex ? "active" : ""}
                aria-label={`${index + 1}`}
                onClick={() => setPageIndex(index)}
              />
            ))}
          </div>
          <button
            className="primary-button"
            onClick={() => {
              if (isLastPage) {
                onClose();
              } else {
                setPageIndex((current) => Math.min(pages.length - 1, current + 1));
              }
            }}
          >
            {isLastPage
              ? isZh ? "知道了，开始使用" : "確認して始める"
              : isZh ? "下一页" : "次へ"}
          </button>
        </div>
      </section>
    </div>
  );
}

function LanguageToggle() {
  const { locale, setLocale } = useUiLanguage();
  return (
    <div className="language-toggle" aria-label="UI language">
      <button className={locale === "zh" ? "selected" : ""} onClick={() => setLocale("zh")}>
        中文
      </button>
      <button className={locale === "ja" ? "selected" : ""} onClick={() => setLocale("ja")}>
        日本語
      </button>
    </div>
  );
}

function StartScreen({
  matches,
  history,
  historyLoaded,
  historyLoading,
  deckSources,
  loading,
  error,
  browserPreview,
  hostedOnline,
  matchCreationDisabled,
  matchCreationDisabledMessage,
  onBrowse,
  onDeckBuilder,
  onHelp,
  onlineAvailable,
  onlineRoom,
  onlineStatus,
  onCreateOnlineRoom,
  onJoinOnlineRoom,
  onCreate,
  onResume,
  onHistoryRefresh,
  onHistoryPage,
}: {
  matches: MatchSummary[];
  history: MatchListResponse;
  historyLoaded: boolean;
  historyLoading: boolean;
  deckSources: StartDeckSource[];
  loading: boolean;
  error: string | null;
  browserPreview: boolean;
  hostedOnline: boolean;
  matchCreationDisabled: boolean;
  matchCreationDisabledMessage: string;
  onBrowse: () => void;
  onDeckBuilder: () => void;
  onHelp: () => void;
  onlineAvailable: boolean;
  onlineRoom: RoomPayload | null;
  onlineStatus: string | null;
  onCreateOnlineRoom: (input: {
    playerName: string;
    deckSourceId: string;
    seed?: number;
  }) => void | Promise<void>;
  onJoinOnlineRoom: (input: {
    roomCode: string;
    playerName: string;
    deckSourceId: string;
  }) => void | Promise<void>;
  onCreate: (input: {
    player1Name: string;
    player1SourceId: string;
    player2Name: string;
    player2SourceId: string;
    seed?: number;
  }) => void | Promise<void>;
  onResume: (id: string) => void;
  onHistoryRefresh: () => void;
  onHistoryPage: (page: number) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const [player1Name, setPlayer1Name] = useState(locale === "zh" ? "玩家 1" : "プレイヤー 1");
  const [player2Name, setPlayer2Name] = useState(locale === "zh" ? "玩家 2" : "プレイヤー 2");
  const [onlinePlayerName, setOnlinePlayerName] = useState(locale === "zh" ? "在线玩家" : "オンライン参加者");
  const [seed, setSeed] = useState("");
  const [roomCode, setRoomCode] = useState("");
  const [player1SourceId, setPlayer1SourceId] = useState("");
  const [player2SourceId, setPlayer2SourceId] = useState("");
  const [onlineSourceId, setOnlineSourceId] = useState("");

  useEffect(() => {
    if (deckSources.length === 0) {
      setPlayer1SourceId("");
      setPlayer2SourceId("");
      return;
    }
    setPlayer1SourceId((current) =>
      deckSources.some((item) => item.id === current) ? current : deckSources[0].id,
    );
    setPlayer2SourceId((current) =>
      deckSources.some((item) => item.id === current) ? current : deckSources[0].id,
    );
    setOnlineSourceId((current) =>
      deckSources.some((item) => item.id === current) ? current : deckSources[0].id,
    );
  }, [deckSources]);

  const player1Source = deckSources.find((item) => item.id === player1SourceId) ?? null;
  const player2Source = deckSources.find((item) => item.id === player2SourceId) ?? null;
  const cappedTotal = Math.min(history.total, history.max_total);
  const totalPages = Math.max(1, Math.ceil(cappedTotal / history.per_page));

  return (
    <div className="start-page">
      <header className="start-header">
        <div className="brand-lockup">
          <Swords size={24} />
          <div>
            <strong>{tr("LoveCA 规则验证器", "LoveCA ルール検証ツール")}</strong>
            <span>{tr("本地可重放规则调试环境", "ローカル・リプレイ対応ルール検証環境")}</span>
          </div>
        </div>
        <div className="start-actions">
          <LanguageToggle />
          <button
            className="icon-button"
            title={tr("使用说明", "使い方")}
            onClick={onHelp}
          >
            <HelpCircle size={18} />
          </button>
          <span className="local-badge">
            {browserPreview ? tr("GitHub Pages · 预览", "GitHub Pages · プレビュー") : tr("127.0.0.1 · 本地", "127.0.0.1 · ローカル")}
          </span>
        </div>
      </header>
      <main className="start-grid">
        <section className="setup-panel">
          <div className="section-heading">
            <CirclePlay size={20} />
            <div>
              <h1>{tr("创建规则验证对局", "ルール検証対戦を作成")}</h1>
              <p>
                {browserPreview
                  ? hostedOnline
                    ? tr(
                      "预览版可编辑牌组，也可以连接远程服务创建在线测试房间。",
                      "プレビュー版ではデッキ編集に加え、リモートサービスへ接続してオンライン検証ルームを作成できます。",
                    )
                    : tr(
                      "预览版可编辑和分析牌组；对战需要本地规则引擎。",
                      "プレビュー版ではデッキ編集と分析が利用できます。対戦にはローカルルールエンジンが必要です。",
                    )
                  : tr(
                    "选择双方牌组来源，运行完整对局并保留回放。",
                    "両プレイヤーのデッキを選択して対戦を開始し、リプレイを保存します。",
                  )}
              </p>
            </div>
          </div>
          <div className="form-grid">
            <label>
              {tr("玩家 1", "プレイヤー 1")}
              <input value={player1Name} onChange={(e) => setPlayer1Name(e.target.value)} />
            </label>
            <label>
              {tr("玩家 2", "プレイヤー 2")}
              <input value={player2Name} onChange={(e) => setPlayer2Name(e.target.value)} />
            </label>
            <label>
              {tr("玩家 1 牌组", "プレイヤー 1 デッキ")}
              <select
                value={player1SourceId}
                onChange={(event) => setPlayer1SourceId(event.target.value)}
              >
                {deckSources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {tr("玩家 2 牌组", "プレイヤー 2 デッキ")}
              <select
                value={player2SourceId}
                onChange={(event) => setPlayer2SourceId(event.target.value)}
              >
                {deckSources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {tr("随机种子（留空则每局随机）", "ランダムシード（空欄なら対戦ごとに生成）")}
              <input
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                inputMode="numeric"
                placeholder={tr("自动生成", "自動生成")}
              />
            </label>
            <div className="deck-source-grid">
              <div className="deck-source">
                <Database size={18} />
                <span>
                  {player1Source
                    ? `${player1Source.label} · ${player1Source.mainCount}+${player1Source.energyCount}`
                    : tr("暂无牌组来源", "デッキソースなし")}
                </span>
              </div>
              <div className="deck-source">
                <Database size={18} />
                <span>
                  {player2Source
                    ? `${player2Source.label} · ${player2Source.mainCount}+${player2Source.energyCount}`
                    : tr("暂无牌组来源", "デッキソースなし")}
                </span>
              </div>
            </div>
          </div>
          {error && <div className="error-banner">{error}</div>}
          {matchCreationDisabled && (
            <div className="info-banner">{matchCreationDisabledMessage}</div>
          )}
          <button
            className="primary-button"
            disabled={matchCreationDisabled || loading || !player1SourceId || !player2SourceId}
            onClick={() =>
              onCreate({
                player1Name,
                player1SourceId,
                player2Name,
                player2SourceId,
                seed: seed ? Number(seed) : undefined,
              })
            }
          >
            {loading ? <RefreshCw className="spin" size={18} /> : <CirclePlay size={18} />}
            {matchCreationDisabled ? tr("本地版可用", "ローカル版のみ") : tr("创建对局", "対戦を作成")}
          </button>
          {onlineAvailable && (
            <section className="online-room-panel">
              <div className="section-heading compact-heading">
                <Swords size={18} />
                <div>
                  <h2>{tr("在线测试房间", "オンライン検証ルーム")}</h2>
                  <p>
                    {tr(
                      "通过远程服务同步房间；暂时没有账号、房间列表或防作弊。",
                      "リモートサービスでルームを同期します。アカウント、ルーム一覧、不正対策はまだありません。",
                    )}
                  </p>
                </div>
              </div>
              <div className="online-room-fields">
                <label>
                  {tr("在线玩家名", "オンライン表示名")}
                  <input
                    value={onlinePlayerName}
                    onChange={(event) => setOnlinePlayerName(event.target.value)}
                  />
                </label>
                <label>
                  {tr("在线用牌组", "オンライン用デッキ")}
                  <select
                    value={onlineSourceId}
                    onChange={(event) => setOnlineSourceId(event.target.value)}
                  >
                    {deckSources.map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {onlineRoom && (
                <div className="online-room-status">
                  <strong>{onlineRoom.room_code}</strong>
                  <span>
                    {onlineRoom.status === "waiting_for_guest"
                      ? tr("等待对手加入", "相手の参加待ち")
                      : onlineRoom.status === "active"
                        ? tr("对局已创建", "対戦作成済み")
                        : tr("房间已过期", "ルーム期限切れ")}
                  </span>
                </div>
              )}
              {onlineStatus && <div className="info-banner">{onlineStatus}</div>}
              <div className="online-room-actions">
                <button
                  className="secondary-button online-button"
                  disabled={loading || !onlineSourceId || !onlinePlayerName.trim()}
                  onClick={() =>
                    onCreateOnlineRoom({
                      playerName: onlinePlayerName.trim(),
                      deckSourceId: onlineSourceId,
                      seed: seed ? Number(seed) : undefined,
                    })
                  }
                >
                  {tr("房间创建", "ルーム作成")}
                </button>
                <label>
                  {tr("房间码", "ルームコード")}
                  <input
                    value={roomCode}
                    onChange={(event) => setRoomCode(event.target.value.toUpperCase())}
                    placeholder="ABC123"
                    maxLength={6}
                    autoCapitalize="characters"
                    spellCheck={false}
                  />
                </label>
                <button
                  className="secondary-button online-button"
                  disabled={
                    loading
                    || !onlineSourceId
                    || !onlinePlayerName.trim()
                    || roomCode.trim().length === 0
                  }
                  onClick={() =>
                    onJoinOnlineRoom({
                      roomCode: roomCode.trim(),
                      playerName: onlinePlayerName.trim(),
                      deckSourceId: onlineSourceId,
                    })
                  }
                >
                  {tr("房间参加", "ルーム参加")}
                </button>
              </div>
            </section>
          )}
          <button className="secondary-button" disabled={loading} onClick={onBrowse}>
            <BookOpen size={18} />
            {tr("浏览卡牌库", "カードを閲覧")}
          </button>
          <button className="secondary-button" disabled={loading} onClick={onDeckBuilder}>
            <ClipboardList size={18} />
            {tr("牌组编辑器", "デッキ編集")}
          </button>
        </section>

        <section className="history-panel">
          <div className="section-heading compact-heading">
            <History size={20} />
            <div>
              <h2>{tr("最近对局", "最近の対戦")}</h2>
              <p>
                {browserPreview
                  ? tr("预览版暂不保存对局。", "プレビュー版では対戦履歴は保存されません。")
                  : tr(
                    "保存最近 100 局的入口。可以回到中断的测试，也可以确认之前打到第几步。",
                    "最近100件まで表示します。中断した検証の再開や、どこまで進んだかの確認に使います。",
                )}
              </p>
            </div>
            {!browserPreview && (
              <button
                className="secondary-button"
                disabled={historyLoading}
                onClick={onHistoryRefresh}
              >
                {historyLoading ? <RefreshCw className="spin" size={16} /> : <RefreshCw size={16} />}
                {historyLoaded ? tr("刷新", "更新") : tr("读取", "読み込み")}
              </button>
            )}
          </div>
          <div className="match-list">
            {matches.length === 0 && (
              <div className="empty-state">
                {historyLoaded
                  ? tr("暂无已保存对局", "保存済みの対戦はありません")
                  : tr("点击读取最近对局", "最近の対戦を読み込んでください")}
              </div>
            )}
            {matches.map((item) => (
              <button
                className="match-row"
                key={item.match_id}
                onClick={() => onResume(item.match_id)}
              >
                <span>
                  <strong>
                    {item.status === "complete"
                      ? tr("已完成", "完了")
                      : tr("进行中", "進行中")}
                  </strong>
                  <small>{item.match_id.slice(0, 8)} · {tr("种子", "シード")} {item.seed}</small>
                </span>
                <span>{tr("操作步数", "操作数")} {item.revision}</span>
              </button>
            ))}
          </div>
          {!browserPreview && cappedTotal > 0 && (
            <div className="history-pagination">
              <button
                className="secondary-button"
                disabled={history.page <= 1}
                onClick={() => onHistoryPage(history.page - 1)}
              >
                {tr("上一页", "前へ")}
              </button>
              <span>
                {tr("第", "")}
                {history.page}
                {tr("页", "ページ")} / {totalPages}
                <small>{tr("共", "合計")} {cappedTotal}</small>
              </span>
              <button
                className="secondary-button"
                disabled={history.page >= totalPages}
                onClick={() => onHistoryPage(history.page + 1)}
              >
                {tr("下一页", "次へ")}
              </button>
            </div>
          )}
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
  hideHand = false,
  onCard,
}: {
  player: PlayerState;
  state: MatchState;
  role: string;
  compact?: boolean;
  hideHand?: boolean;
  onCard: (card: CardInstance) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const activeEnergy = player.energy_area.filter(
    (instanceId) => state.cards[instanceId].orientation === "active",
  ).length;
  return (
    <section className={`player-board ${compact ? "compact" : ""}`}>
      <div className="player-heading">
        <div>
          <span className="role-label">{role}</span>
          <strong>{player.name}</strong>
        </div>
        <div className="player-metrics">
          <Metric label={tr("牌库", "デッキ")} value={player.main_deck.length} />
          <Metric label={tr("能量", "エネルギー")} value={player.energy_area.length} />
          <Metric label={tr("可用能量", "使用可能エネルギー")} value={activeEnergy} />
          <Metric label={tr("成功演出", "成功ライブ")} value={`${player.success_live_area.length} / 3`} />
          <Metric label={tr("分数", "スコア")} value={player.live_result.total_score} />
        </div>
      </div>
      <div className="zone-row">
        <Zone label={tr("成功演出", "成功ライブ")} ids={player.success_live_area} state={state} onCard={onCard} small />
        <div className="member-stage">
          {(["left", "center", "right"] as const).map((slot) => (
            <div className="member-slot" key={slot}>
              <span>{memberSlotLabel(slot, locale)}</span>
              {player.member_area[slot] ? (
                <CardTile instance={state.cards[player.member_area[slot]!]} onClick={onCard} />
              ) : (
                <div className="slot-empty">{tr("角色", "メンバー")}</div>
              )}
              <StageAttachments
                ids={player.member_area_attachments?.[slot] ?? []}
                state={state}
                onCard={onCard}
              />
            </div>
          ))}
        </div>
        <Zone label={tr("能量", "エネルギー")} ids={player.energy_area} state={state} onCard={onCard} small />
      </div>
      <Zone
        label={`${tr("手牌", "手札")} ${player.hand.length}`}
        ids={player.hand}
        state={state}
        onCard={onCard}
        hand
        hidden={hideHand}
      />
    </section>
  );
}

function LiveCenter({ state, onCard }: { state: MatchState; onCard: (card: CardInstance) => void }) {
  const { tr } = useUiLanguage();
  return (
    <section className="live-center">
      <Zone
        label={`${state.players.player_2.name} ${tr("演出区", "ライブエリア")}`}
        ids={state.players.player_2.live_area}
        state={state}
        onCard={onCard}
        small
      />
      <LiveAnalysisPanel state={state} onCard={onCard} />
      <Zone
        label={`${state.players.player_1.name} ${tr("演出区", "ライブエリア")}`}
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
  const { locale, tr } = useUiLanguage();
  const visible =
    state.phase.startsWith("performance") ||
    state.phase.startsWith("yell") ||
    state.phase === "live_judgment" ||
    state.phase === "turn_complete" ||
    state.phase === "complete";
  const summary = state.live_judgment_summary;
  const winners = summary?.winner_ids.map((id) => state.players[id].name) ?? [];
  if (!visible) {
    return (
      <div className="phase-track">
        <Activity size={18} />
        <strong>{phaseLabels[state.phase]?.[locale === "zh" ? 0 : 1]}</strong>
        {locale === "zh" && <span>{phaseLabels[state.phase]?.[1]}</span>}
        {state.pending_choice && (
          <em>
            {locale === "zh"
              ? state.pending_choice.message_zh
              : state.pending_choice.message_ja}
          </em>
        )}
      </div>
    );
  }
  return (
    <section className="live-analysis">
      <header className="live-analysis-heading">
        <div>
          <Activity size={16} />
          <strong>{tr("Live 判定明细", "ライブ判定詳細")}</strong>
          <span>
            {phaseLabels[state.phase]?.[locale === "zh" ? 0 : 1]}
          </span>
          <small>総合ルール 8.3.10–8.3.16 / 8.4.2–8.4.7</small>
        </div>
        <div className={`judgment-basis ${summary ? "resolved" : ""}`}>
          <small>{tr("判定基准", "判定基準")}</small>
          <strong>
            {summary
              ? judgmentBasisLabels[summary.basis]?.[locale === "zh" ? 0 : 1]
                ?? summary.basis
              : tr("等待双方完成应援与爱心判定", "双方のエールとハート判定を待っています")}
          </strong>
          {summary && (
            <span>
              {winners.length > 0
                ? `${tr("胜者", "勝者")}：${winners.join("、")}`
                : tr("无胜者", "勝者なし")}
            </span>
          )}
          {state.phase === "turn_complete" && state.next_first_player_id && (
            <span>
              {tr("下一回合先攻", "次ターンの先攻")}：
              {state.players[state.next_first_player_id].name}
            </span>
          )}
          {state.game_result && (
            <span className="game-result">
              {state.game_result.outcome === "draw"
                ? tr("最终结果：平局", "最終結果：引き分け")
                : `${tr("最终胜者", "最終勝者")}：${state.game_result.winner_player_ids
                    .map((id) => state.players[id].name)
                    .join("、")}`}
            </span>
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
  const { tr } = useUiLanguage();
  const result = player.live_result;
  const requirementStatus =
    result.requirements_satisfied === false &&
    result.live_allocations.length === 0 &&
    result.revealed_instance_ids.length === 0
      ? tr("无 Live 可判定", "判定対象のライブなし")
      : result.requirements_satisfied === null
      ? tr("尚未判定", "未判定")
      : result.requirements_satisfied
        ? tr("所需爱心满足", "必要ハートを達成")
        : tr("所需爱心未满足", "必要ハート未達成");
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
          <Metric label={tr("应援棒", "ブレード")} value={result.blade_count} />
          <Metric label={tr("应援翻开", "エール公開")} value={result.revealed_instance_ids.length} />
          <Metric label={tr("基础分", "基本スコア")} value={result.base_score} />
          <Metric label={tr("特殊加分", "追加スコア")} value={result.score_bonus} />
          <Metric label={tr("总分", "合計スコア")} value={result.total_score} />
        </div>
      </header>

      <div className="heart-ledger">
        <HeartLine label={tr("成员爱心", "メンバーハート")} hearts={result.member_hearts} />
        <HeartLine label={tr("应援爱心", "エールハート")} hearts={result.yell_hearts} />
        {Object.keys(result.manual_hearts).length > 0 && (
          <HeartLine label={tr("人工调整", "手動調整")} hearts={result.manual_hearts} />
        )}
        <HeartLine
          label={tr("演出可用爱心", "ライブで使用可能なハート")}
          hearts={result.available_hearts}
          allColor={result.all_color_hearts}
        />
      </div>

      <div className="yell-reveals">
        <span>{tr("应援公开卡", "エールで公開したカード")}</span>
        <div>
          {result.revealed_instance_ids.length === 0 && <em>{tr("无", "なし")}</em>}
          {result.revealed_instance_ids.map((id) => (
            <button key={id} onClick={() => onCard(state.cards[id])}>
              {state.cards[id].card.name_ja}
            </button>
          ))}
        </div>
      </div>

      {result.special_blade_heart_results.length > 0 && (
        <div className="special-results">
          <span>{tr("特殊应援棒爱心", "特殊ブレードハート")}</span>
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
          <div className="allocation-empty">
            {tr("尚无逐张演出爱心分配结果", "ライブごとのハート割り当て結果はまだありません")}
          </div>
        )}
        {result.live_allocations.map((allocation) => (
          <div
            className={`allocation-row ${allocation.satisfied ? "satisfied" : "failed"}`}
            key={allocation.live_instance_id}
          >
            <button onClick={() => onCard(state.cards[allocation.live_instance_id])}>
              {state.cards[allocation.live_instance_id].card.name_ja}
            </button>
            <HeartLine label={tr("需求", "必要")} hearts={allocation.required_hearts} />
            <HeartLine
              label={tr("消费", "使用")}
              hearts={allocation.consumed_hearts}
              allColor={allocation.all_color_hearts_used}
            />
            <HeartLine label={tr("缺口", "不足")} hearts={allocation.missing_hearts} />
            <strong>
              {allocation.satisfied ? tr("满足", "達成") : tr("失败", "失敗")}
            </strong>
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
  const { locale } = useUiLanguage();
  const entries = Object.entries(hearts).filter(([, amount]) => amount !== 0);
  return (
    <div className="heart-line">
      <span>{label}</span>
      <div>
        {entries.length === 0 && allColor === 0 && <em>0</em>}
        {entries.map(([color, amount]) => (
          <span className={`heart-token ${color}`} key={color}>
            <i />
            {heartLabels[locale][color] ?? color} {amount}
          </span>
        ))}
        {allColor > 0 && (
          <span className="heart-token all-color">
            <i />
            {heartLabels[locale].heart0} {allColor}
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
  hidden = false,
  small = false,
}: {
  label: string;
  ids: string[];
  state: MatchState;
  onCard: (card: CardInstance) => void;
  hand?: boolean;
  hidden?: boolean;
  small?: boolean;
}) {
  const { tr } = useUiLanguage();
  return (
    <div className={`zone ${hand ? "hand-zone" : ""} ${small ? "small-zone" : ""}`}>
      <span className="zone-label">{label}</span>
      <div className="card-strip">
        {ids.length === 0 && <span className="zone-empty">{tr("空", "空き")}</span>}
        {hidden
          ? ids.map((id, index) => (
            <div
              className="hidden-hand-card"
              aria-label={tr("隐藏的对手手牌", "非公開の相手手札")}
              key={id}
            >
              <span>{index + 1}</span>
            </div>
          ))
          : ids.map((id) => (
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
  const { locale } = useUiLanguage();
  return (
    <button
      className={`card-tile ${instance.orientation === "wait" ? "wait" : ""} ${selected ? "selected" : ""}`}
      onClick={() => onClick(instance)}
      title={instance.card.name_ja}
    >
      <LocalCardArt card={instance.card} />
      <div className="card-caption">
        <span>{instance.card.name_ja}</span>
        {instance.orientation === "wait" && <em>{orientationLabel("wait", locale)}</em>}
      </div>
    </button>
  );
}

export function StageAttachments({
  ids,
  state,
  onCard,
}: {
  ids: string[];
  state: MatchState;
  onCard: (card: CardInstance) => void;
}) {
  const { locale, tr } = useUiLanguage();
  if (ids.length === 0) {
    return <span className="stage-attachments-empty">{tr("下方 0", "下 0")}</span>;
  }
  const memberCount = ids.filter(
    (id) => state.cards[id].card.card_type === "member",
  ).length;
  const energyCount = ids.length - memberCount;
  return (
    <details className="stage-attachments">
      <summary>
        {tr("下方", "下")} {ids.length}
        <small>
          {tr("角色", "メンバー")} {memberCount} · {tr("能量", "エネルギー")} {energyCount}
        </small>
      </summary>
      <div className="stage-attachment-list">
        {ids.map((id) => (
          <button key={id} onClick={() => onCard(state.cards[id])}>
            <strong>{state.cards[id].card.name_ja}</strong>
            <span>{cardTypeLabel(state.cards[id].card.card_type, locale)}</span>
          </button>
        ))}
      </div>
    </details>
  );
}

function EventLog({ events, state }: { events: GameEvent[]; state: MatchState }) {
  const { tr } = useUiLanguage();
  return (
    <aside className="event-panel">
      <div className="event-heading">
        <History size={18} />
        <strong>{tr("操作记录", "操作・イベント履歴")}</strong>
        <span>{events.length}</span>
      </div>
      <div className="event-list">
        {events.length === 0 && (
          <div className="empty-state">{tr("等待第一步操作", "最初の操作待ち")}</div>
        )}
        {[...events].reverse().map((event, index) => (
          <div className={`event-row ${event.source}`} key={`${event.event_type}-${index}`}>
            <span>{event.source}</span>
            <strong>{event.event_type}</strong>
            <small>
              {event.player_id ? state.players[event.player_id]?.name : tr("系统", "システム")}
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
  onManual: (source?: EffectInvocation) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const [selected, setSelected] = useState<string[]>([]);
  const [liveOrder, setLiveOrder] = useState<string[]>([]);

  useEffect(() => {
    setSelected([]);
    setLiveOrder([]);
  }, [state.revision]);

  return (
    <footer className="action-dock">
      <div className="action-context">
        <strong>{tr("下一步操作", "次にできる操作")}</strong>
        <span>{state.active_player_id ? state.players[state.active_player_id].name : "System"}</span>
      </div>
      <div className="action-controls">
        {actions.map((action) => {
          if (action.action_type === "manual_adjustment") {
            const sources = (action.options.source_invocations ?? []) as Array<{
              invocation_id: string;
              effect_id: string;
              source_card_instance_id: string;
            }>;
            return (
              <button
                className="secondary-button"
                key={`${action.action_type}-${sources[0]?.invocation_id ?? "general"}`}
                onClick={() => {
                  const source = sources[0];
                  onManual(
                    source
                      ? state.pending_effects.find(
                          (item) => item.invocation_id === source.invocation_id,
                        )
                      : undefined,
                  );
                }}
              >
                <Settings2 size={17} />
                {locale === "zh" ? action.label_zh : action.label_ja}
              </button>
            );
          }
          if (action.action_type === "activate_effect") {
            return (
              <EffectActivationAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
              />
            );
          }
          if (action.action_type === "resolve_effect") {
            return (
              <EffectResolutionAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
                onManual={onManual}
              />
            );
          }
          if (action.action_type === "resolve_effect_choice") {
            return (
              <InspectionChoiceAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
                title={tr("技能检查结果", "能力による確認結果")}
                submitLabel={tr("确认技能处理", "能力の処理を確定")}
              />
            );
          }
          if (action.action_type === "skip_effect") {
            return (
              <SkipEffectAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
              />
            );
          }
          if (action.action_type === "resolve_manual_inspection") {
            return (
              <InspectionChoiceAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
                title={tr("检查牌堆顶卡牌", "デッキ上のカードを確認")}
                submitLabel={tr("确认筛选结果", "選択結果を確定")}
              />
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
                {state.players[playerId].name} {tr("先攻", "を先攻にする")}
              </button>
            ));
          }
          if (action.action_type === "submit_mulligan") {
            const hand = action.options.hand_instance_ids as string[];
            return (
              <SelectionAction
                key={action.action_type}
                title={tr("选择需要调度的手牌", "引き直す手札を選択")}
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
                title={tr("选择最多 3 张卡设置到 Live 区", "ライブエリアに置くカードを3枚まで選択")}
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
            return (
              <MemberPlayAction
                key={`${action.action_type}-${state.revision}`}
                action={action}
                state={state}
                loading={loading}
                onAction={onAction}
              />
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
                  {tr("确认判定顺序", "判定順を確定")}
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
              {locale === "zh" ? action.label_zh : action.label_ja}
            </button>
          );
        })}
      </div>
    </footer>
  );
}

function InspectionCard({
  instance,
  selected,
  disabled = false,
  badge,
  onSelect,
}: {
  instance: CardInstance;
  selected: boolean;
  disabled?: boolean;
  badge?: string;
  onSelect: () => void;
}) {
  const { locale } = useUiLanguage();
  const card = instance.card;
  return (
    <button
      className={`inspection-card ${selected ? "selected" : ""} ${disabled ? "disabled" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      disabled={disabled}
    >
      <div className="inspection-card-image">
        <LocalCardArt card={card} />
        <span className="inspection-select-state">
          {badge
            ? badge
            : selected
              ? locale === "zh" ? "已选择" : "選択済み"
              : locale === "zh" ? "点击选择" : "クリックして選択"}
        </span>
      </div>
      <div className="inspection-card-details">
        <div>
          <strong>{card.name_ja}</strong>
          <span>{cardTypeLabel(card.card_type, locale)} · {card.card_code}</span>
        </div>
        <dl>
          {card.cost !== null && <><dt>{locale === "zh" ? "费用" : "コスト"}</dt><dd>{card.cost}</dd></>}
          {card.blade !== null && <><dt>{locale === "zh" ? "应援棒" : "ブレード"}</dt><dd>{card.blade}</dd></>}
          {card.score !== null && <><dt>{locale === "zh" ? "分数" : "スコア"}</dt><dd>{card.score}</dd></>}
        </dl>
        {Object.keys(card.basic_hearts).length > 0 && (
          <span>{locale === "zh" ? "爱心" : "ハート"}: {formatHeartSummary(card.basic_hearts, locale)}</span>
        )}
        {Object.keys(card.required_hearts).length > 0 && (
          <span>{locale === "zh" ? "所需" : "必要"}: {formatHeartSummary(card.required_hearts, locale)}</span>
        )}
        <p>{formatEffectText(card.raw_effect_text_ja, locale)}</p>
      </div>
    </button>
  );
}

export function formatHeartSummary(
  hearts: Record<string, number>,
  locale: UiLocale = "zh",
): string {
  return Object.entries(hearts)
    .filter(([, amount]) => amount > 0)
    .map(([color, amount]) => `${heartLabels[locale][color] ?? color} ${amount}`)
    .join(" / ");
}

export function formatEffectText(
  rawText: string | null,
  locale: UiLocale = "zh",
): string {
  if (!rawText) return "効果テキストなし";
  return rawText.replace(
    /heart0[1-6]|heart0/gi,
    (token) => heartLabels[locale][token.toLowerCase()] ?? token,
  );
}

function effectTriggerLabel(trigger: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    member_played: ["登場", "登場"],
    player_activation: ["起動", "起動"],
    live_started: ["ライブ開始時", "ライブ開始時"],
    live_succeeded: ["ライブ成功時", "ライブ成功時"],
    baton_touch_performed: ["バトンタッチ時", "バトンタッチ時"],
  };
  const label = labels[trigger];
  if (!label) return trigger;
  return locale === "zh" ? label[0] : label[1];
}

function effectExecutionModeLabel(mode: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    auto_resolve: ["自动结算", "自動解決"],
    prompt_then_resolve: ["提示后处理", "選択して解決"],
    manual_resolution: ["人工处理", "手動処理"],
  };
  const label = labels[mode];
  if (!label) return mode;
  return locale === "zh" ? label[0] : label[1];
}

function effectSupportStatusLabel(status: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    supported: ["已接入", "対応済み"],
    unregistered: ["未注册", "未登録"],
    hash_mismatch: ["文本不匹配", "テキスト不一致"],
  };
  const label = labels[status];
  if (!label) return status;
  return locale === "zh" ? label[0] : label[1];
}

function orientationLabel(orientation: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    active: ["竖置", "アクティブ"],
    wait: ["横置", "ウェイト"],
  };
  const label = labels[orientation.toLowerCase()];
  return label ? label[locale === "zh" ? 0 : 1] : orientation;
}

function cardTypeLabel(type: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    member: ["角色", "メンバー"],
    energy: ["能量", "エネルギー"],
    live: ["Live", "ライブ"],
  };
  const label = labels[type.toLowerCase()];
  return label ? label[locale === "zh" ? 0 : 1] : type;
}

function zoneLabel(zone: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    hand: ["手牌", "手札"],
    main_deck: ["主牌堆", "メインデッキ"],
    energy_deck: ["能量牌堆", "エネルギーデッキ"],
    energy_area: ["能量区", "エネルギーエリア"],
    live_area: ["Live 区", "ライブエリア"],
    waiting_room: ["控室", "控え室"],
    resolution_area: ["处理区", "処理エリア"],
    success_live_area: ["成功 Live 区", "成功ライブエリア"],
    member_left: ["左侧角色位", "左のメンバー枠"],
    member_center: ["中间角色位", "中央のメンバー枠"],
    member_right: ["右侧角色位", "右のメンバー枠"],
  };
  const label = labels[zone];
  return label ? label[locale === "zh" ? 0 : 1] : zone;
}

function effectBranchLabel(branchId: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    draw_discard: ["抽 1 张后弃 1 张手牌", "1枚引いて手札を1枚控え室へ"],
    wait_opponent_cost2: [
      "将对手全部费用 2 以下角色横置",
      "相手のコスト2以下メンバーすべてをウェイト",
    ],
    ready_member: ["选择 Member 变为 Active", "メンバーを選んでアクティブ"],
    ready_energy: ["选择 Energy 变为 Active", "エネルギーを選んでアクティブ"],
  };
  const label = labels[branchId];
  if (!label) return branchId;
  return locale === "zh" ? label[0] : label[1];
}

function effectTimingSummaryLabel(key: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    on_play: ["登場", "登場"],
    activated: ["起動", "起動"],
    live_start: ["ライブ開始時", "ライブ開始時"],
    live_success: ["ライブ成功時", "ライブ成功時"],
    baton_touch: ["バトンタッチ時", "バトンタッチ時"],
  };
  const label = labels[key];
  if (!label) return key;
  return locale === "zh" ? label[0] : label[1];
}

function EffectActivationAction({
  action,
  state,
  loading,
  onAction,
}: {
  action: LegalAction;
  state: MatchState;
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const activations = action.options.activations as Array<{
    effect_id: string;
    source_card_instance_id: string;
    label_ja: string;
    trigger: string;
    timing: string;
    execution_mode: string;
    frequency_limit: string;
    simulation_support: string;
  }>;
  return (
    <div className="effect-action">
      <span className="effect-action-title">{tr("可发动技能", "使用可能な能力")}</span>
      <div className="effect-option-list">
        {activations.map((activation) => (
          <button
            className="effect-option"
            disabled={loading}
            key={`${activation.effect_id}-${activation.source_card_instance_id}`}
            onClick={() =>
              onAction(action.action_type, action.player_id, {
                effect_id: activation.effect_id,
                source_card_instance_id: activation.source_card_instance_id,
              })
            }
          >
            <Play size={16} />
            <span>
              <strong>
                {state.cards[activation.source_card_instance_id].card.name_ja}
              </strong>
              <small>
                {effectTriggerLabel(activation.trigger, locale)} ·{" "}
                {effectExecutionModeLabel(activation.execution_mode, locale)}
              </small>
              <small>{formatEffectText(activation.label_ja, locale)}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SkipEffectAction({
  action,
  state,
  loading,
  onAction,
}: {
  action: LegalAction;
  state: MatchState;
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
}) {
  const { tr } = useUiLanguage();
  const invocations = (action.options.invocations ?? []) as Array<{
    invocation_id: string;
    effect_id: string;
    source_card_instance_id: string;
    label_ja: string;
  }>;
  const pendingChoice = action.options.pending_choice as
    | { options?: Record<string, unknown> }
    | null
    | undefined;
  const defaultInvocationId =
    (pendingChoice?.options?.invocation_id as string | undefined) ??
    invocations[0]?.invocation_id ??
    "";
  const [invocationId, setInvocationId] = useState(defaultInvocationId);
  const current =
    invocations.find((item) => item.invocation_id === invocationId) ?? invocations[0];
  if (!current) return null;
  return (
    <div className="skip-effect-action">
      <span>
        {tr(
          "调试用：当前技能无法处理时可跳过，并在日志中记录错误。",
          "デバッグ用：処理できない能力をスキップし、ログにエラーを記録します。",
        )}
      </span>
      {invocations.length > 1 && (
        <select value={current.invocation_id} onChange={(event) => setInvocationId(event.target.value)}>
          {invocations.map((invocation) => (
            <option key={invocation.invocation_id} value={invocation.invocation_id}>
              {state.cards[invocation.source_card_instance_id]?.card.name_ja ?? invocation.effect_id}
            </option>
          ))}
        </select>
      )}
      <button
        className="skip-effect-button"
        disabled={loading}
        onClick={() =>
          onAction(action.action_type, action.player_id, {
            invocation_id: current.invocation_id,
            reason: "UI debug skip",
            error_message: "effect handling is not available or failed",
          })
        }
      >
        {tr("跳过并记录错误", "スキップしてエラー記録")}
      </button>
    </div>
  );
}

export function EffectResolutionAction({
  action,
  state,
  loading,
  onAction,
  onManual,
}: {
  action: LegalAction;
  state: MatchState;
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
  onManual: (source?: EffectInvocation) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const invocations = action.options.invocations as Array<{
    invocation_id: string;
    effect_id: string;
    source_card_instance_id: string;
    label_ja: string;
    trigger: string;
    timing: string;
    execution_mode: string;
    is_optional: boolean;
    simulation_support: string;
    candidate_card_instance_ids: string[];
    choice_type?: string;
    card_selection_minimum?: number;
    card_selection_maximum?: number;
    choice_zone?: string;
    choice_orientation?: string;
    color_slots?: string[];
    energy_instance_ids?: string[];
    energy_required?: number;
    branch_ids?: string[];
    selected_branch?: string;
    choice_groups?: Array<{
      group_id: string;
      label_ja?: string | null;
      candidate_card_instance_ids: string[];
      exclude_group_ids?: string[];
      minimum?: number;
      maximum?: number;
    }>;
  }>;
  const waitingPlayerIds = (action.options.waiting_player_ids ?? []) as string[];
  const [invocationId, setInvocationId] = useState(invocations[0]?.invocation_id ?? "");
  const current =
    invocations.find((item) => item.invocation_id === invocationId) ?? invocations[0];
  const [selectedCards, setSelectedCards] = useState<string[]>([]);
  const [selectedEnergy, setSelectedEnergy] = useState<string[]>([]);
  const [selectedColor, setSelectedColor] = useState("");
  const [selectedCount, setSelectedCount] = useState<number | null>(null);
  const [selectedBranch, setSelectedBranch] = useState("");
  const [selectedGroups, setSelectedGroups] = useState<Record<string, string[]>>({});

  useEffect(() => {
    setSelectedCards([]);
    setSelectedEnergy([]);
    setSelectedColor("");
    setSelectedCount(null);
    setSelectedBranch("");
    setSelectedGroups({});
  }, [current?.invocation_id]);

  if (!current) return null;
  const source = state.pending_effects.find(
    (item) => item.invocation_id === current.invocation_id,
  );
  const manual = current.simulation_support === "manual_resolution";
  const requiredEnergy = current.energy_required ?? 0;
  const choiceType = current.choice_type ?? "";
  const usesCardChoice = ["card_from_zone", "energy_from_area", "member_from_stage"].includes(choiceType)
    || Boolean(current.choice_zone && current.candidate_card_instance_ids.length > 0);
  const minimumCards = usesCardChoice
    ? current.card_selection_minimum ?? (current.candidate_card_instance_ids.length > 0 ? 1 : 0)
    : 0;
  const maximumCards = usesCardChoice
    ? current.card_selection_maximum ?? Math.max(minimumCards, current.candidate_card_instance_ids.length)
    : 0;
  const isEnergyChoice = current.choice_zone === "energy_area";
  const colorSlots = current.color_slots ?? [];
  const requiresColor = choiceType === "choose_color";
  const requiresCount = choiceType === "choose_count";
  const branchIds = current.branch_ids ?? [];
  const isBranchChoice = choiceType === "choose_effect_branch";
  const isGroupedStageChoice = choiceType === "member_group_from_stage";
  const choiceGroups = current.choice_groups ?? [];
  const resolvedBranch = current.selected_branch || selectedBranch;
  const requiresBranch = isBranchChoice && !current.selected_branch;
  const minimumCount = current.card_selection_minimum ?? 0;
  const maximumCount = current.card_selection_maximum ?? 0;
  const resolvedSelectedCount = selectedCount ?? minimumCount;
  const selectedGroupIdSet = new Set(
    Object.values(selectedGroups).flatMap((items) => items),
  );
  const groupSelectionsValid = !isGroupedStageChoice || choiceGroups.every((group) => {
    const selected = selectedGroups[group.group_id] ?? [];
    const minimum = group.minimum ?? 0;
    const maximum = group.maximum ?? Math.max(minimum, group.candidate_card_instance_ids.length);
    const candidates = new Set(group.candidate_card_instance_ids);
    return (
      selected.length >= minimum &&
      selected.length <= maximum &&
      selected.length === new Set(selected).size &&
      selected.every((instanceId) => candidates.has(instanceId))
    );
  });
  return (
    <div className="effect-resolution">
      <div className="effect-resolution-header">
        <span>
          {tr("待结算技能", "解決待ち能力")} {invocations.length > 1 ? `(${invocations.length})` : ""}
        </span>
        {invocations.length > 1 && (
          <select value={current.invocation_id} onChange={(event) => setInvocationId(event.target.value)}>
            {invocations.map((item) => (
              <option key={item.invocation_id} value={item.invocation_id}>
                {state.cards[item.source_card_instance_id].card.name_ja}
              </option>
            ))}
          </select>
        )}
      </div>
      {waitingPlayerIds.length > 0 && (
        <small>
          {tr("另一方技能需等待当前玩家处理完毕。", "相手側の能力は現在の解決完了まで待機します。")}
        </small>
      )}
      <strong>{state.cards[current.source_card_instance_id].card.name_ja}</strong>
      <small>
        {effectTriggerLabel(current.trigger, locale)} ·{" "}
        {effectExecutionModeLabel(current.execution_mode, locale)} ·{" "}
        {current.is_optional ? tr("可选", "任意") : tr("强制", "強制")}
      </small>
      <p>{formatEffectText(current.label_ja, locale)}</p>
      {isBranchChoice && (
        <div className="effect-candidates effect-branch-choices">
          {branchIds.map((branchId) => (
            <button
              className={resolvedBranch === branchId ? "selected" : ""}
              key={branchId}
              type="button"
              disabled={Boolean(current.selected_branch)}
              onClick={() => setSelectedBranch(branchId)}
            >
              {effectBranchLabel(branchId, locale)}
            </button>
          ))}
          {current.selected_branch && (
            <span>
              {tr("已选择", "選択済み")}:
              {" "}
              {effectBranchLabel(current.selected_branch, locale)}
            </span>
          )}
        </div>
      )}
      {usesCardChoice && current.candidate_card_instance_ids.length > 0 && (
        <div className="effect-candidates">
          {current.candidate_card_instance_ids.map((instanceId) => (
            <button
              className={selectedCards.includes(instanceId) ? "selected" : ""}
              key={instanceId}
              onClick={() =>
                setSelectedCards((currentSelected) => {
                  if (currentSelected.includes(instanceId)) {
                    return currentSelected.filter((item) => item !== instanceId);
                  }
                  if (maximumCards <= 1) {
                    return [instanceId];
                  }
                  if (currentSelected.length < maximumCards) {
                    return [...currentSelected, instanceId];
                  }
                  return currentSelected;
                })
              }
            >
              {isEnergyChoice
                ? `${state.cards[instanceId].card.name_ja} · ${orientationLabel(state.cards[instanceId].orientation, locale)}`
                : state.cards[instanceId].card.name_ja}
            </button>
          ))}
          <span>
            {selectedCards.length} / {maximumCards}
            {minimumCards > 0 ? ` · ${tr("至少", "最低")} ${minimumCards}` : ""}
          </span>
        </div>
      )}
      {isGroupedStageChoice && choiceGroups.length > 0 && (
        <div className="effect-grouped-choice">
          {choiceGroups.map((group) => {
            const selected = selectedGroups[group.group_id] ?? [];
            const maximum = group.maximum ?? 1;
            const excludedIds = new Set(
              (group.exclude_group_ids ?? []).flatMap(
                (groupId) => selectedGroups[groupId] ?? [],
              ),
            );
            return (
              <div className="effect-choice-group" key={group.group_id}>
                <strong>{group.label_ja ?? group.group_id}</strong>
                <div className="effect-candidates">
                  {group.candidate_card_instance_ids.map((instanceId) => {
                    const isSelected = selected.includes(instanceId);
                    const disabled =
                      excludedIds.has(instanceId) ||
                      (!isSelected && selectedGroupIdSet.has(instanceId));
                    const card = state.cards[instanceId];
                    return (
                      <button
                        className={isSelected ? "selected" : ""}
                        disabled={disabled}
                        key={instanceId}
                        type="button"
                        onClick={() =>
                          setSelectedGroups((currentGroups) => {
                            const currentSelected = currentGroups[group.group_id] ?? [];
                            const nextSelected = currentSelected.includes(instanceId)
                              ? currentSelected.filter((item) => item !== instanceId)
                              : maximum <= 1
                                ? [instanceId]
                                : currentSelected.length < maximum
                                  ? [...currentSelected, instanceId]
                                  : currentSelected;
                            return {
                              ...currentGroups,
                              [group.group_id]: nextSelected,
                            };
                          })
                        }
                      >
                        {card?.card.name_ja ?? instanceId}
                      </button>
                    );
                  })}
                  <span>
                    {selected.length} / {maximum}
                    {(group.minimum ?? 0) > 0 ? ` · ${tr("至少", "最低")} ${group.minimum}` : ""}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {requiresColor && (
        <div className="effect-candidates effect-color-choices">
          {colorSlots.map((colorSlot) => (
            <button
              className={selectedColor === colorSlot ? "selected" : ""}
              key={colorSlot}
              type="button"
              onClick={() => setSelectedColor(colorSlot)}
            >
              <span className={`heart-dot ${colorSlot}`} />
              {heartLabels[locale][colorSlot] ?? colorSlot}
            </button>
          ))}
        </div>
      )}
      {requiresCount && (
        <label className="effect-count-choice">
          {tr("选择数量", "数を選択")}
          <input
            type="number"
            min={minimumCount}
            max={maximumCount}
            value={selectedCount ?? minimumCount}
            onChange={(event) => setSelectedCount(Number(event.target.value))}
          />
          <span>{minimumCount}–{maximumCount}</span>
        </label>
      )}
      {requiredEnergy > 0 && (
        <div className="effect-candidates">
          {(current.energy_instance_ids ?? []).map((instanceId) => (
            <button
              className={selectedEnergy.includes(instanceId) ? "selected" : ""}
              key={instanceId}
              onClick={() =>
                setSelectedEnergy(
                  selectedEnergy.includes(instanceId)
                    ? selectedEnergy.filter((item) => item !== instanceId)
                    : selectedEnergy.length < requiredEnergy
                      ? [...selectedEnergy, instanceId]
                      : selectedEnergy,
                )
              }
            >
              {tr("能量", "エネルギー")} {instanceId.split("-").at(-1)}
            </button>
          ))}
          <span>{selectedEnergy.length} / {requiredEnergy}</span>
        </div>
      )}
      <div className="effect-resolution-buttons">
        {manual ? (
          <button className="primary-button" disabled={!source} onClick={() => onManual(source)}>
            <Settings2 size={16} />
            {tr("结构化人工处理", "構造化手動処理")}
          </button>
        ) : (
          <button
            className="primary-button"
            disabled={
              loading ||
              !canResolveEffect(
                minimumCards,
                maximumCards,
                selectedCards.length,
                requiredEnergy,
                selectedEnergy.length,
                requiresColor,
                Boolean(selectedColor),
                requiresCount,
                resolvedSelectedCount >= minimumCount
                  && resolvedSelectedCount <= maximumCount,
                requiresBranch,
                Boolean(resolvedBranch),
              ) ||
              !groupSelectionsValid
            }
            onClick={() => {
              const payload: Record<string, unknown> = {
                invocation_id: current.invocation_id,
                accepted: true,
                selected_card_instance_ids: selectedCards,
                energy_instance_ids: selectedEnergy,
              };
              if (isGroupedStageChoice) {
                payload.selected_card_instance_ids_by_group = selectedGroups;
              }
              if (requiresColor) {
                payload.selected_color_slot = selectedColor;
              }
              if (requiresCount) {
                payload.selected_count = resolvedSelectedCount;
              }
              if (isBranchChoice) {
                payload.selected_branch = resolvedBranch;
              }
              onAction(action.action_type, action.player_id, payload);
            }}
          >
            {tr("结算技能", "能力を解決")}
          </button>
        )}
        {current.is_optional && (
          <button
            className="secondary-button"
            disabled={loading}
            onClick={() =>
              onAction(action.action_type, action.player_id, {
                invocation_id: current.invocation_id,
                accepted: false,
              })
            }
          >
            {tr("不使用", "使用しない")}
          </button>
        )}
      </div>
    </div>
  );
}

export function InspectionChoiceAction({
  action,
  state,
  loading,
  onAction,
  title,
  submitLabel,
}: {
  action: LegalAction;
  state: MatchState;
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
  title: string;
  submitLabel: string;
}) {
  const { locale, tr } = useUiLanguage();
  const inspected = ((action.options.inspected_card_instance_ids ?? []) as string[]).filter(
    (item): item is string => typeof item === "string",
  );
  const candidateIds = ((action.options.candidate_card_instance_ids ?? inspected) as string[]).filter(
    (item): item is string => typeof item === "string",
  );
  const candidates = new Set(candidateIds);
  const minimum = Number(action.options.minimum ?? 0);
  const maximum = Number(action.options.maximum ?? 0);
  const requiresOrder = Boolean(action.options.requires_order);
  const selectedDestination = String(action.options.selected_destination ?? "");
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    setSelected([]);
  }, [state.revision, action.action_type]);

  const isValidSelection =
    selected.length >= minimum &&
    selected.length <= maximum &&
    selected.every((item) => candidates.has(item));

  return (
    <div className="effect-resolution">
      <strong>{title}</strong>
      <span>
        {tr("选择", "選択")} {minimum}–{maximum} {tr("张", "枚")}
        {action.options.reveal_selected_to_opponent
          ? tr("，选中的卡会公开给对手", "。選んだカードは相手に公開されます")
          : ""}
      </span>
      {selectedDestination === "main_deck_top_ordered" && (
        <small>
          {tr(
            "已选卡牌的排列顺序会按从左到右放回牌堆顶。",
            "選択済みカードは左から右の順でデッキ上に戻ります。",
          )}
        </small>
      )}
      <div className="inspection-card-grid">
        {inspected.map((instanceId) => {
          const candidate = candidates.has(instanceId);
          return (
            <InspectionCard
              key={instanceId}
              instance={state.cards[instanceId]}
              selected={selected.includes(instanceId)}
              disabled={!candidate}
              badge={
                candidate ? undefined : locale === "zh" ? "不符合条件" : "条件外"
              }
              onSelect={() =>
                candidate
                  ? toggleSelected(selected, instanceId, setSelected, maximum)
                  : undefined
              }
            />
          );
        })}
      </div>
      {requiresOrder && selected.length > 0 && (
        <div className="order-action">
          {selected.map((id, index) => (
            <span key={id}>
              {state.cards[id].card.name_ja}
              <button
                className="mini-icon"
                disabled={index === 0}
                aria-label={tr("上移已选卡", "選択カードを上へ")}
                onClick={() => setSelected(moveItem(selected, index, index - 1))}
              >
                <ChevronUp size={14} />
              </button>
              <button
                className="mini-icon"
                disabled={index === selected.length - 1}
                aria-label={tr("下移已选卡", "選択カードを下へ")}
                onClick={() => setSelected(moveItem(selected, index, index + 1))}
              >
                <ChevronDown size={14} />
              </button>
            </span>
          ))}
        </div>
      )}
      <button
        className="primary-button"
        disabled={loading || !isValidSelection}
        onClick={() =>
          onAction(action.action_type, action.player_id, {
            selected_card_instance_ids: selected,
            ordered_card_instance_ids: requiresOrder ? selected : undefined,
          })
        }
      >
        {submitLabel}
      </button>
    </div>
  );
}

function MemberPlayAction({
  action,
  state,
  loading,
  onAction,
}: {
  action: LegalAction;
  state: MatchState;
  loading: boolean;
  onAction: (
    actionType: string,
    playerId?: string | null,
    payload?: Record<string, unknown>,
  ) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const placements = action.options.placements as MemberPlacement[];
  const energy = action.options.active_energy_instance_ids as string[];
  const [selectedMemberId, setSelectedMemberId] = useState("");
  const [selectedSlot, setSelectedSlot] = useState("");
  const [selectedPlayMode, setSelectedPlayMode] = useState<MemberPlayMode | "">("");
  const selection = resolveMemberPlaySelection(
    placements,
    selectedMemberId,
    selectedSlot,
    selectedPlayMode,
  );
  const player = state.players[action.player_id ?? ""];
  const placement = selection.placement;
  const newCost = placement
    ? state.cards[placement.card_instance_id].card.cost ?? 0
    : 0;
  const reduction = placement?.use_baton_touch
    ? Math.min(newCost, placement.replaced_member_cost)
    : 0;

  return (
    <div className="member-play-action">
      <div className="member-play-step member-card-step">
        <span className="member-play-label">{tr("1 · 选择角色", "1 · メンバーを選択")}</span>
        <div className="member-choice-strip">
          {selection.memberIds.map((instanceId) => (
            <div
              className="member-choice-card"
              data-instance-id={instanceId}
              key={instanceId}
            >
              <CardTile
                instance={state.cards[instanceId]}
                selected={instanceId === selection.selectedMemberId}
                onClick={() => {
                  setSelectedMemberId(instanceId);
                  setSelectedSlot("");
                  setSelectedPlayMode("");
                }}
              />
              <span>{tr("费用", "コスト")} {state.cards[instanceId].card.cost ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="member-play-step member-target-step">
        <span className="member-play-label">{tr("2 · 选择区域", "2 · エリアを選択")}</span>
        <div className="member-slot-options">
          {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => {
            const currentId = player.member_area[slot];
            const legal = selection.availableSlots.includes(slot);
            const enteredThisTurn = player.member_areas_entered_this_turn.includes(slot);
            return (
              <button
                className={`member-slot-choice ${
                  slot === selection.selectedSlot ? "selected" : ""
                }`}
                data-slot={slot}
                disabled={!legal}
                key={slot}
                onClick={() => {
                  setSelectedSlot(slot);
                  setSelectedPlayMode("");
                }}
              >
                <strong>{memberSlotLabel(slot, locale)}</strong>
                <span>
                  {currentId
                    ? state.cards[currentId].card.name_ja
                    : enteredThisTurn
                      ? tr("本回合不可指定", "このターンは指定不可")
                      : tr("空", "空き")}
                </span>
                {currentId && (
                  <small>{tr("费用", "コスト")} {state.cards[currentId].card.cost ?? 0}</small>
                )}
              </button>
            );
          })}
        </div>

        {placement?.replaced_card_instance_id && (
          <div className="member-play-modes" aria-label="登场方式">
            {selection.availableModes.map((mode) => (
              <button
                className={mode === selection.selectedMode ? "selected" : ""}
                data-mode={mode}
                key={mode}
                onClick={() => setSelectedPlayMode(mode)}
              >
                {mode === "baton" ? "バトンタッチ" : tr("通常登场", "通常登場")}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="member-payment-summary">
        <span className="member-play-label">{tr("费用", "コスト")}</span>
        <dl>
          <div>
            <dt>{tr("新角色", "新しいメンバー")}</dt>
            <dd>{newCost}</dd>
          </div>
          <div>
            <dt>{tr("原角色", "元のメンバー")}</dt>
            <dd>{placement?.replaced_member_cost ?? 0}</dd>
          </div>
          <div>
            <dt>{tr("换位减免", "バトンタッチ軽減")}</dt>
            <dd>-{reduction}</dd>
          </div>
          <div>
            <dt>{tr("能量总数", "エネルギー合計")}</dt>
            <dd>{player.energy_area.length}</dd>
          </div>
          <div>
            <dt>{tr("可用能量", "使用可能エネルギー")}</dt>
            <dd>{energy.length}</dd>
          </div>
          <div className="payment-total">
            <dt>{tr("实付能量", "支払うエネルギー")}</dt>
            <dd>{placement?.payment_cost ?? 0}</dd>
          </div>
        </dl>
        <button
          className="primary-button"
          disabled={loading || !placement}
          onClick={() => {
            if (!placement) return;
            onAction(action.action_type, action.player_id, {
              card_instance_id: placement.card_instance_id,
              slot: placement.slot,
              use_baton_touch: placement.use_baton_touch,
              energy_instance_ids: energy.slice(0, placement.payment_cost),
            });
          }}
        >
          {placement?.use_baton_touch ? "バトンタッチ" : tr("登场", "登場")}
        </button>
      </div>
    </div>
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
  const { tr } = useUiLanguage();
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
        {tr("确认", "確定")} {selected.length}
        {maximum ? ` / ${maximum}` : ""}
      </button>
    </div>
  );
}

export function ManualDrawer({
  state,
  source,
  onClose,
  onSubmit,
}: {
  state: MatchState;
  source: EffectInvocation | null;
  onClose: () => void;
  onSubmit: (playerId: string, payload: Record<string, unknown>) => void;
}) {
  const { locale, tr } = useUiLanguage();
  const [playerId, setPlayerId] = useState(
    source?.player_id ?? state.active_player_id ?? "player_1",
  );
  const [type, setType] = useState("modify_score");
  const [amount, setAmount] = useState("1");
  const [cardId, setCardId] = useState("");
  const [cardIds, setCardIds] = useState<string[]>([]);
  const [toZone, setToZone] = useState("waiting_room");
  const [color, setColor] = useState("heart01");
  const [duration, setDuration] = useState<"live" | "turn" | "game">("live");
  const [flag, setFlag] = useState("");
  const [minimum, setMinimum] = useState("0");
  const [maximum, setMaximum] = useState("1");
  const [revealSelected, setRevealSelected] = useState(true);
  const [targetSlot, setTargetSlot] = useState<"left" | "center" | "right">("center");
  const [fromSlot, setFromSlot] = useState<"left" | "center" | "right">("center");
  const [toSlot, setToSlot] = useState<"left" | "center" | "right">("left");
  const [energyOrientation, setEnergyOrientation] = useState<"active" | "wait">("active");
  const player = state.players[playerId];
  const attachedIds = Object.values(player.member_area_attachments ?? {}).flat();
  const genericCards = Object.values(state.cards).filter(
    (card) => card.owner_id === playerId && !attachedIds.includes(card.instance_id),
  );
  const attachableCards = [
    ...player.hand
      .filter((id) => state.cards[id].card.card_type === "member")
      .map((id) => state.cards[id]),
    ...player.energy_area
      .filter((id) => state.cards[id].card.card_type === "energy")
      .map((id) => state.cards[id]),
  ];
  const attachedCards = attachedIds.map((id) => state.cards[id]);
  const stageCards = MEMBER_SLOT_DISPLAY_ORDER
    .map((slot) => player.member_area[slot])
    .filter((id): id is string => id !== null)
    .map((id) => state.cards[id]);
  const handCards = player.hand.map((id) => state.cards[id]);
  const selectableCards =
    type === "attach_card_under_member"
      ? attachableCards
      : type === "move_attached_card"
        ? attachedCards
        : type === "move_member"
          ? stageCards
          : type === "discard_card"
            ? handCards
          : type === "return_from_waiting_room"
            ? player.waiting_room.map((id) => state.cards[id])
          : ["ready_energy", "pay_energy"].includes(type)
            ? player.energy_area.map((id) => state.cards[id])
          : genericCards;
  const selectedCard = cardId ? state.cards[cardId] : null;
  const stageMemberIds = Object.values(player.member_area).filter(
    (id): id is string => id !== null,
  );
  const selectedMemberSlot = cardId
    ? MEMBER_SLOT_DISPLAY_ORDER.find((slot) => player.member_area[slot] === cardId)
    : undefined;
  const [formation, setFormation] = useState<Record<"left" | "center" | "right", string>>({
    left: player.member_area.left ?? "",
    center: player.member_area.center ?? "",
    right: player.member_area.right ?? "",
  });
  useEffect(() => {
    setCardId("");
    setCardIds([]);
    const occupied = MEMBER_SLOT_SELECTION_PRIORITY.filter(
      (slot) => player.member_area[slot],
    );
    const firstOccupied = occupied[0] ?? "center";
    setTargetSlot(firstOccupied);
    setFromSlot(firstOccupied);
    setToSlot(
      MEMBER_SLOT_SELECTION_PRIORITY.find((slot) => slot !== firstOccupied)
        ?? "left",
    );
    setFormation({
      left: player.member_area.left ?? "",
      center: player.member_area.center ?? "",
      right: player.member_area.right ?? "",
    });
  }, [playerId, state.revision]);
  useEffect(() => {
    if (type !== "move_attached_card") {
      return;
    }
    setToZone(
      selectedCard?.card.card_type === "energy" ? "energy_area" : "hand",
    );
  }, [type, selectedCard?.instance_id, selectedCard?.card.card_type]);
  const formationIds = Object.values(formation).filter(Boolean);
  const stageAdjustmentValid =
    type === "attach_card_under_member"
      ? Boolean(cardId && player.member_area[targetSlot])
      : type === "move_attached_card"
        ? Boolean(cardId)
        : type === "move_member"
          ? Boolean(cardId && selectedMemberSlot && selectedMemberSlot !== toSlot)
          : type === "position_change"
            ? Boolean(player.member_area[fromSlot] && fromSlot !== toSlot)
          : type === "formation_change"
            ? formationIds.length === stageMemberIds.length
              && new Set(formationIds).size === stageMemberIds.length
              && stageMemberIds.every((id) => formationIds.includes(id))
            : type === "discard_card"
              ? Boolean(cardId)
            : type === "return_from_waiting_room"
              ? Boolean(cardId)
            : ["ready_energy", "pay_energy"].includes(type)
              ? cardIds.length > 0
            : true;
  const persistent = ["modify_score", "modify_heart", "modify_blade", "set_flag"].includes(type);
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="manual-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>{tr("人工处理技能", "能力を手動処理")}</strong>
            <span>{tr("结构化人工规则调整", "構造化手動ルール調整")}</span>
            {source && (
              <span>
                {state.cards[source.source_card_instance_id].card.name_ja} · {source.effect_id}
              </span>
            )}
          </div>
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <label>
          {tr("目标玩家", "対象プレイヤー")}
          <select value={playerId} onChange={(e) => setPlayerId(e.target.value)}>
            {Object.values(state.players).map((player) => (
              <option key={player.player_id} value={player.player_id}>
                {player.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("调整类型", "調整タイプ")}
          <select
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setCardId("");
              setCardIds([]);
            }}
          >
            {[
              "move_card",
              "move_member",
              "attach_card_under_member",
              "move_attached_card",
              "formation_change",
              "draw_card",
              "inspect_top_cards",
              "discard_card",
              "return_from_waiting_room",
              "ready_energy",
              "pay_energy",
              "modify_score",
              "modify_heart",
              "modify_blade",
              "set_flag",
              "clear_flag",
            ].map((item) => (
              <option key={item} value={item}>
                {adjustmentTypeLabel(item, locale)}
              </option>
            ))}
          </select>
        </label>
        {[
          "move_card",
          "move_member",
          "attach_card_under_member",
          "move_attached_card",
          "discard_card",
          "return_from_waiting_room",
        ].includes(type) && (
          <label>
            {tr("目标卡牌", "対象カード")}
            <select value={cardId} onChange={(e) => setCardId(e.target.value)}>
              <option value="">{tr("请选择", "選択してください")}</option>
              {selectableCards.map((card) => (
                <option key={card.instance_id} value={card.instance_id}>
                  {card.card.name_ja}
                  {type === "move_member"
                    ? ` · ${memberSlotLabel(
                        MEMBER_SLOT_DISPLAY_ORDER.find(
                          (slot) => player.member_area[slot] === card.instance_id,
                        ) ?? "",
                        locale,
                      )}`
                    : ` · ${card.instance_id}`}
                </option>
              ))}
            </select>
          </label>
        )}
        {["ready_energy", "pay_energy"].includes(type) && (
          <div className="effect-candidates">
            {selectableCards.map((card) => (
              <button
                className={cardIds.includes(card.instance_id) ? "selected" : ""}
                key={card.instance_id}
                type="button"
                onClick={() =>
                  setCardIds((current) =>
                    current.includes(card.instance_id)
                      ? current.filter((item) => item !== card.instance_id)
                      : [...current, card.instance_id],
                  )
                }
                >
                {card.card.name_ja} · {orientationLabel(card.orientation, locale)}
              </button>
            ))}
            <span>{tr("已选", "選択")} {cardIds.length}</span>
          </div>
        )}
        {type === "move_member" && (
          <label>
            {tr("目标位置", "移動先")}
            <select
              value={toSlot}
              onChange={(e) =>
                setToSlot(e.target.value as "left" | "center" | "right")
              }
            >
              {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => (
                <option disabled={slot === selectedMemberSlot} key={slot} value={slot}>
                  {memberSlotLabel(slot, locale)} ·{" "}
                  {player.member_area[slot]
                    ? state.cards[player.member_area[slot]!].card.name_ja
                    : tr("空", "空き")}
                </option>
              ))}
            </select>
          </label>
        )}
        {type === "move_card" && (
          <label>
            {tr("移动到哪里", "移動先")}
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
                <option key={item} value={item}>{zoneLabel(item, locale)}</option>
              ))}
            </select>
          </label>
        )}
        {type === "attach_card_under_member" && (
          <label>
            {tr("放到哪个角色下方", "どのメンバーの下に置くか")}
            <select
              value={targetSlot}
              onChange={(e) =>
                setTargetSlot(e.target.value as "left" | "center" | "right")
              }
            >
              {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => (
                <option
                  disabled={!player.member_area[slot]}
                  key={slot}
                  value={slot}
                >
                  {memberSlotLabel(slot, locale)} ·{" "}
                  {player.member_area[slot]
                    ? state.cards[player.member_area[slot]!].card.name_ja
                    : tr("空", "空き")}
                </option>
              ))}
            </select>
          </label>
        )}
        {type === "move_attached_card" && (
          <>
            <label>
              {tr("移动到哪里", "移動先")}
              <select value={toZone} onChange={(e) => setToZone(e.target.value)}>
                {(selectedCard?.card.card_type === "energy"
                  ? ["energy_area", "energy_deck"]
                  : ["hand", "waiting_room", "member_left", "member_center", "member_right"]
                ).map((item) => (
                  <option
                    disabled={
                      item.startsWith("member_")
                      && player.member_area[
                        item.replace("member_", "") as "left" | "center" | "right"
                      ] !== null
                    }
                    key={item}
                    value={item}
                  >
                    {zoneLabel(item, locale)}
                  </option>
                ))}
              </select>
            </label>
            {selectedCard?.card.card_type === "energy" && toZone === "energy_area" && (
              <label>
                {tr("能量放置方式", "エネルギーの向き")}
                <select
                  value={energyOrientation}
                  onChange={(e) =>
                    setEnergyOrientation(e.target.value as "active" | "wait")
                  }
                >
                  <option value="active">{orientationLabel("active", locale)}</option>
                  <option value="wait">{orientationLabel("wait", locale)}</option>
                </select>
              </label>
            )}
          </>
        )}
        {type === "position_change" && (
          <div className="manual-range">
            <label>
              {tr("从哪里", "移動元")}
              <select
                value={fromSlot}
                onChange={(e) =>
                  setFromSlot(e.target.value as "left" | "center" | "right")
                }
              >
                {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => (
                  <option disabled={!player.member_area[slot]} key={slot} value={slot}>
                    {memberSlotLabel(slot)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {tr("移到哪里", "移動先")}
              <select
                value={toSlot}
                onChange={(e) =>
                  setToSlot(e.target.value as "left" | "center" | "right")
                }
              >
                {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => (
                  <option disabled={slot === fromSlot} key={slot} value={slot}>
                    {memberSlotLabel(slot)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {type === "formation_change" && (
          <div className="formation-controls">
            {MEMBER_SLOT_DISPLAY_ORDER.map((slot) => (
              <label key={slot}>
                {memberSlotLabel(slot)}
                <select
                  value={formation[slot]}
                  onChange={(e) =>
                    setFormation((current) => ({
                      ...current,
                      [slot]: e.target.value,
                    }))
                  }
                >
                  <option value="">{tr("空", "空き")}</option>
                  {stageMemberIds.map((id) => (
                    <option key={id} value={id}>
                      {state.cards[id].card.name_ja}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}
        {type === "modify_heart" && (
          <label>
            {tr("爱心颜色", "ハートの色")}
            <select value={color} onChange={(e) => setColor(e.target.value)}>
              {["heart0", "heart01", "heart02", "heart03", "heart04", "heart05", "heart06"].map(
                (item) => (
                  <option key={item} value={item}>
                    {heartLabels[locale][item]}
                  </option>
                ),
              )}
            </select>
          </label>
        )}
        {type === "inspect_top_cards" && (
          <>
            <div className="manual-range">
              <label>
                最少保留
                <input
                  type="number"
                  min="0"
                  value={minimum}
                  onChange={(event) => setMinimum(event.target.value)}
                />
              </label>
              <label>
                最多保留
                <input
                  type="number"
                  min="0"
                  value={maximum}
                  onChange={(event) => setMaximum(event.target.value)}
                />
              </label>
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={revealSelected}
                onChange={(event) => setRevealSelected(event.target.checked)}
              />
              加入手牌前向对手公开
            </label>
          </>
        )}
        {persistent && (
          <label>
            {tr("持续时间", "続く期間")}
            <select
              value={duration}
              onChange={(e) => setDuration(e.target.value as "live" | "turn" | "game")}
            >
              <option value="live">{tr("本次表演", "今回のライブ")}</option>
              <option value="turn">{tr("本回合", "このターン")}</option>
              <option value="game">{tr("整场对局", "この対戦中")}</option>
            </select>
          </label>
        )}
        {["set_flag", "clear_flag"].includes(type) && (
          <label>
            {tr("标记名", "フラグ名")}
            <input value={flag} onChange={(e) => setFlag(e.target.value)} />
          </label>
        )}
        {["draw_card", "inspect_top_cards", "modify_score", "modify_heart", "modify_blade"].includes(type) && (
          <label>
            {tr("数量", "数")}
            <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" />
          </label>
        )}
        <button
          className="primary-button"
          disabled={!stageAdjustmentValid}
          onClick={() =>
            onSubmit(playerId, {
              reason: source
                ? `Manual resolution for ${source.effect_id}`
                : "UI manual rule verification",
              requires_confirmation: true,
              confirmed_by: "local_debugger",
              source_invocation_id: source?.invocation_id,
              source_effect_id: source?.effect_id,
              source_card_instance_id: source?.source_card_instance_id,
              adjustments: [
                {
                  adjustment_type: type,
                  target_player_id: playerId,
                  target_card_instance_id:
                    ["ready_energy", "pay_energy"].includes(type)
                      ? undefined
                      : cardId || undefined,
                  target_card_instance_ids:
                    ["ready_energy", "pay_energy"].includes(type)
                      ? cardIds
                      : undefined,
                  to_zone:
                    type === "move_card" || type === "move_attached_card"
                      ? toZone
                      : undefined,
                  target_slot:
                    type === "attach_card_under_member" ? targetSlot : undefined,
                  from_slot: type === "position_change" ? fromSlot : undefined,
                  to_slot:
                    type === "position_change" || type === "move_member"
                      ? toSlot
                      : undefined,
                  slot_assignments:
                    type === "formation_change"
                      ? {
                          left: formation.left || null,
                          center: formation.center || null,
                          right: formation.right || null,
                        }
                      : undefined,
                  orientation:
                    type === "move_attached_card"
                    && selectedCard?.card.card_type === "energy"
                    && toZone === "energy_area"
                      ? energyOrientation
                      : undefined,
                  color_slot: type === "modify_heart" ? color : undefined,
                  amount: ["draw_card", "modify_score", "modify_heart", "modify_blade"].includes(type)
                    || type === "inspect_top_cards"
                    ? Number(amount)
                    : undefined,
                  minimum: type === "inspect_top_cards" ? Number(minimum) : undefined,
                  maximum: type === "inspect_top_cards" ? Number(maximum) : undefined,
                  reveal_selected_to_opponent:
                    type === "inspect_top_cards" ? revealSelected : undefined,
                  source_invocation_id:
                    type === "inspect_top_cards" ? source?.invocation_id : undefined,
                  source_effect_id:
                    type === "inspect_top_cards" ? source?.effect_id : undefined,
                  source_card_instance_id:
                    type === "inspect_top_cards"
                      ? source?.source_card_instance_id
                      : undefined,
                  duration: persistent ? duration : undefined,
                  flag: ["set_flag", "clear_flag"].includes(type) ? flag : undefined,
                  value: type === "set_flag" ? true : undefined,
                },
              ],
            })
          }
        >
          {tr("提交结构化调整", "構造化調整を送信")}
        </button>
      </aside>
    </div>
  );
}

function CardDialog({
  instance,
  state,
  onClose,
}: {
  instance: CardInstance;
  state: MatchState;
  onClose: () => void;
}) {
  const { locale, tr } = useUiLanguage();
  const effects = instance.card.effect_ids
    .map((effectId) => state.effect_definitions[effectId])
    .filter(Boolean);
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <article className="card-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button close-dialog" onClick={onClose}>
          <X size={18} />
        </button>
        <div className="dialog-image">
          <LocalCardArt card={instance.card} className="dialog-card-art" />
        </div>
        <div className="dialog-content">
          <span>{cardTypeLabel(instance.card.card_type, locale)} · {instance.card.card_code}</span>
          <h2>{instance.card.name_ja}</h2>
          <div className="attribute-grid">
            <Metric label={tr("费用", "コスト")} value={instance.card.cost ?? "-"} />
            <Metric label={tr("应援棒", "ブレード")} value={instance.card.blade ?? "-"} />
            <Metric label={tr("分数", "スコア")} value={instance.card.score ?? "-"} />
            <Metric label={tr("状态", "状態")} value={orientationLabel(instance.orientation, locale)} />
          </div>
          <h3>{tr("官方日文效果", "公式日本語テキスト")}</h3>
          <p className="effect-text">
            {formatEffectText(instance.card.raw_effect_text_ja, locale)}
          </p>
          <h3>{tr("技能执行支持", "能力実行サポート")}</h3>
          <div className="effect-support-list">
            <span className={`support-status ${instance.card.effect_registry_status}`}>
              {effectSupportStatusLabel(instance.card.effect_registry_status, locale)}
            </span>
            {effects.map((effect) => (
              <div key={effect.effect_id}>
                <strong>{effect.effect_id}</strong>
                <span>
                  {effectTriggerLabel(effect.trigger, locale)} ·{" "}
                  {effectExecutionModeLabel(effect.execution_mode, locale)} ·{" "}
                  {effect.simulation_support} · {effect.review_status}
                </span>
                <small>{formatEffectText(effect.label_ja, locale)}</small>
              </div>
            ))}
            {instance.card.effect_registry_errors.map((error) => (
              <code key={error}>{error}</code>
            ))}
          </div>
          <h3>{tr("爱心", "ハート")}</h3>
          {Object.keys(instance.card.basic_hearts).length > 0 && (
            <HeartLine
              label={tr("基本爱心", "基本ハート")}
              hearts={instance.card.basic_hearts}
            />
          )}
          {Object.keys(instance.card.required_hearts).length > 0 && (
            <HeartLine
              label={tr("所需爱心", "必要ハート")}
              hearts={instance.card.required_hearts}
            />
          )}
          {Object.keys(instance.card.basic_hearts).length === 0
            && Object.keys(instance.card.required_hearts).length === 0
            && <span>{tr("无", "なし")}</span>}
        </div>
      </article>
    </div>
  );
}

function LocalCardArt({
  card,
  className = "",
}: {
  card: CardInstance["card"];
  className?: string;
}) {
  const [sourceMode, setSourceMode] = useState<"local" | "remote" | "fallback">(
    card.card_id ? "local" : card.image_url ? "remote" : "fallback",
  );

  useEffect(() => {
    setSourceMode(card.card_id ? "local" : card.image_url ? "remote" : "fallback");
  }, [card.card_id, card.image_url]);

  if (sourceMode !== "fallback") {
    const src =
      sourceMode === "local"
        ? cardImageUrl(card.card_id)
        : (card.image_url ?? "");
    return (
      <img
        className={className}
        src={src}
        alt={card.name_ja}
        onError={() => {
          if (sourceMode === "local" && card.image_url) {
            setSourceMode("remote");
            return;
          }
          setSourceMode("fallback");
        }}
      />
    );
  }
  return (
    <div className={`card-fallback ${card.card_type} ${className}`.trim()}>
      <span>{cardTypeLabel(card.card_type, "ja")}</span>
      <strong>{card.name_ja}</strong>
      <small>{card.card_code}</small>
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

export function availableValue(current: string, available: string[]): string {
  return available.includes(current) ? current : available[0] ?? "";
}

export function canResolveEffect(
  minimumCards: number,
  maximumCards: number,
  selectedCount: number,
  requiredEnergy: number,
  selectedEnergyCount: number,
  requiresColor = false,
  hasColor = true,
  requiresCount = false,
  hasCount = true,
  requiresBranch = false,
  hasBranch = true,
): boolean {
  return (
    selectedCount >= minimumCards &&
    selectedCount <= maximumCards &&
    selectedEnergyCount === requiredEnergy &&
    (!requiresColor || hasColor) &&
    (!requiresCount || hasCount) &&
    (!requiresBranch || hasBranch)
  );
}

interface MemberPlacement {
  card_instance_id: string;
  slot: string;
  payment_cost: number;
  use_baton_touch: boolean;
  replaced_card_instance_id: string | null;
  replaced_member_cost: number;
}

type MemberPlayMode = "normal" | "baton";

const MEMBER_SLOT_DISPLAY_ORDER = ["left", "center", "right"] as const;
const MEMBER_SLOT_SELECTION_PRIORITY = ["center", "left", "right"] as const;

function memberSlotLabel(slot: string, locale: UiLocale = "zh"): string {
  if (locale === "ja") {
    return slot === "left"
      ? "左"
      : slot === "center"
        ? "中央"
        : slot === "right"
          ? "右"
          : slot;
  }
  return slot === "left"
    ? "左"
    : slot === "center"
      ? "中"
      : slot === "right"
        ? "右"
        : slot;
}

function adjustmentTypeLabel(type: string, locale: UiLocale): string {
  const labels: Record<string, [string, string]> = {
    move_card: ["通用卡牌移动", "カードを移動"],
    move_member: ["移动场上角色", "ステージのメンバーを移動"],
    attach_card_under_member: ["附加到角色下方", "メンバーの下に置く"],
    move_attached_card: ["移动附属卡", "下にあるカードを移動"],
    formation_change: ["阵型变更", "フォーメーションチェンジ"],
    draw_card: ["抽牌", "カードを引く"],
    inspect_top_cards: ["检查牌库顶", "デッキ上を確認"],
    discard_card: ["手牌送入控室", "手札を控え室に置く"],
    return_from_waiting_room: ["控室加入手牌", "控え室から手札に加える"],
    ready_energy: ["能量竖置", "エネルギーをアクティブにする"],
    pay_energy: ["能量横置", "エネルギーをウェイトにする"],
    modify_score: ["调整分数", "スコアを調整"],
    modify_heart: ["调整爱心", "ハートを調整"],
    modify_blade: ["调整应援棒", "ブレードを調整"],
    set_flag: ["设置标记", "フラグを設定"],
    clear_flag: ["清除标记", "フラグを解除"],
  };
  return labels[type]?.[locale === "zh" ? 0 : 1] ?? type;
}

export function resolveMemberPlaySelection(
  placements: MemberPlacement[],
  currentMemberId: string,
  currentSlot: string,
  currentMode: MemberPlayMode | "",
) {
  const memberIds = [...new Set(placements.map((item) => item.card_instance_id))];
  const selectedMemberId = availableValue(currentMemberId, memberIds);
  const memberPlacements = placements.filter(
    (item) => item.card_instance_id === selectedMemberId,
  );
  const availableSlots = MEMBER_SLOT_SELECTION_PRIORITY.filter((slot) =>
    memberPlacements.some((item) => item.slot === slot),
  );
  const selectedSlot = availableValue(currentSlot, availableSlots);
  const slotPlacements = memberPlacements.filter(
    (item) => item.slot === selectedSlot,
  );
  const availableModes: MemberPlayMode[] = [
    ...(slotPlacements.some((item) => !item.use_baton_touch)
      ? (["normal"] as const)
      : []),
    ...(slotPlacements.some((item) => item.use_baton_touch)
      ? (["baton"] as const)
      : []),
  ];
  const selectedMode = availableModes.includes(currentMode as MemberPlayMode)
    ? (currentMode as MemberPlayMode)
    : availableModes.includes("baton")
      ? "baton"
      : availableModes[0] ?? "normal";
  const placement =
    slotPlacements.find(
      (item) => item.use_baton_touch === (selectedMode === "baton"),
    ) ?? null;
  return {
    memberIds,
    selectedMemberId,
    availableSlots,
    selectedSlot,
    availableModes,
    selectedMode,
    placement,
  };
}

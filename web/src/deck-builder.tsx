import {
  Activity,
  ArrowLeft,
  BookOpen,
  ClipboardList,
  Download,
  Expand,
  LoaderCircle,
  Minus,
  Plus,
  Save,
  Search,
  Trash2,
  Upload,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  analyzeDeck,
  createSavedDeck,
  deleteSavedDeck,
  getCatalogCard,
  getSavedDeck,
  listCatalogCards,
  listCatalogFacets,
  listSavedDecks,
  renameSavedDeck,
  updateSavedDeck,
} from "./api";
import { formatEffectText } from "./text-format";
import type {
  CatalogCardDetail,
  DeckAnalysisResponse,
  CatalogFacetsResponse,
  CatalogCardSummary,
  DeckEntry,
  DeckList,
  SavedDeckSummary,
} from "./types";

type UiLocale = "zh" | "ja";
type DeckSearchSortKey =
  | "default"
  | "card_code"
  | "name"
  | "type"
  | "cost"
  | "blade"
  | "required_heart"
  | "score"
  | "deck_quantity";
type SortDirection = "asc" | "desc";
const MAIN_DECK_LIMIT = 60;
const MAIN_DECK_MEMBER_TARGET = 48;
const MAIN_DECK_LIVE_TARGET = 12;
const ENERGY_DECK_LIMIT = 12;
const MAX_COPIES_PER_CARD = 4;
const CATALOG_PAGE_SIZE = 24;
const HEART_COLOR_OPTIONS = ["heart0", "heart01", "heart02", "heart03", "heart04", "heart05", "heart06"] as const;

const EMPTY_DECK: DeckList = {
  version: "decklist.v0",
  name: null,
  main_deck: [],
  energy_deck: [],
};

function tr(locale: UiLocale, zh: string, ja: string): string {
  return locale === "zh" ? zh : ja;
}

function heartColorLabel(locale: UiLocale, value: string): string {
  const labels: Record<string, { zh: string; ja: string }> = {
    heart0: { zh: "任意色", ja: "任意色" },
    heart01: { zh: "粉色", ja: "ピンク" },
    heart02: { zh: "红色", ja: "赤" },
    heart03: { zh: "黄色", ja: "黄" },
    heart04: { zh: "绿色", ja: "緑" },
    heart05: { zh: "蓝色", ja: "青" },
    heart06: { zh: "紫色", ja: "紫" },
  };
  const label = labels[value];
  if (!label) return value;
  return locale === "zh" ? label.zh : label.ja;
}

function effectTriggerLabel(locale: UiLocale, trigger: string): string {
  const labels: Record<string, { zh: string; ja: string }> = {
    member_played: { zh: "登場", ja: "登場" },
    player_activation: { zh: "起動", ja: "起動" },
    live_started: { zh: "ライブ開始時", ja: "ライブ開始時" },
    baton_touch_performed: { zh: "バトンタッチ時", ja: "バトンタッチ時" },
    on_play: { zh: "登場", ja: "登場" },
    activated: { zh: "起動", ja: "起動" },
    live_start: { zh: "ライブ開始時", ja: "ライブ開始時" },
    baton_touch: { zh: "バトンタッチ時", ja: "バトンタッチ時" },
  };
  const label = labels[trigger];
  if (!label) return trigger;
  return locale === "zh" ? label.zh : label.ja;
}

function effectExecutionModeLabel(locale: UiLocale, mode: string): string {
  const labels: Record<string, { zh: string; ja: string }> = {
    auto_resolve: { zh: "自动结算", ja: "自動解決" },
    prompt_then_resolve: { zh: "提示后处理", ja: "選択して解決" },
    manual_resolution: { zh: "人工处理", ja: "手動処理" },
  };
  const label = labels[mode];
  if (!label) return mode;
  return locale === "zh" ? label.zh : label.ja;
}

function effectSupportStatusLabel(locale: UiLocale, status: string): string {
  const labels: Record<string, { zh: string; ja: string }> = {
    supported: { zh: "已接入", ja: "対応済み" },
    unregistered: { zh: "未注册", ja: "未登録" },
    hash_mismatch: { zh: "文本不匹配", ja: "テキスト不一致" },
  };
  const label = labels[status];
  if (!label) return status;
  return locale === "zh" ? label.zh : label.ja;
}

export function DeckBuilder({
  locale,
  setLocale,
  onBack,
  onUseForMatch,
}: {
  locale: UiLocale;
  setLocale: (locale: UiLocale) => void;
  onBack: () => void;
  onUseForMatch: (deck: DeckList) => void;
}) {
  const [query, setQuery] = useState("");
  const [cardType, setCardType] = useState<"" | "member" | "live" | "energy">("");
  const [workKey, setWorkKey] = useState("");
  const [unitKey, setUnitKey] = useState("");
  const [basicHeartColor, setBasicHeartColor] = useState("");
  const [memberCostMin, setMemberCostMin] = useState("");
  const [memberCostMax, setMemberCostMax] = useState("");
  const [memberBladeMin, setMemberBladeMin] = useState("");
  const [memberBladeMax, setMemberBladeMax] = useState("");
  const [memberBladeHeartColor, setMemberBladeHeartColor] = useState("");
  const [requiredHeartColor, setRequiredHeartColor] = useState("");
  const [requiredHeartMin, setRequiredHeartMin] = useState("");
  const [requiredHeartMax, setRequiredHeartMax] = useState("");
  const [liveScoreMin, setLiveScoreMin] = useState("");
  const [liveScoreMax, setLiveScoreMax] = useState("");
  const [hasLiveBladeHeart, setHasLiveBladeHeart] = useState<"" | "true" | "false">("");
  const [liveBladeHeartColor, setLiveBladeHeartColor] = useState("");
  const [sortKey, setSortKey] = useState<DeckSearchSortKey>("default");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [facets, setFacets] = useState<CatalogFacetsResponse>({ works: [], units: [] });
  const [cards, setCards] = useState<CatalogCardSummary[]>([]);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogPage, setCatalogPage] = useState(0);
  const [summaryCache, setSummaryCache] = useState<Record<string, CatalogCardSummary>>({});
  const [detailCache, setDetailCache] = useState<Record<string, CatalogCardDetail>>({});
  const [selectedCardCode, setSelectedCardCode] = useState<string | null>(null);
  const [selectedCatalogKey, setSelectedCatalogKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogCardDetail | null>(null);
  const [savedDecks, setSavedDecks] = useState<SavedDeckSummary[]>([]);
  const [selectedDeckId, setSelectedDeckId] = useState<string | null>(null);
  const [deck, setDeck] = useState<DeckList>(EMPTY_DECK);
  const [deckName, setDeckName] = useState("");
  const [loadingCards, setLoadingCards] = useState(false);
  const [loadingDecks, setLoadingDecks] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<DeckAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const visibleCards = useMemo(
    () => {
      const filtered = aggregateDeckCatalogCards(cards.filter((card) =>
        matchesCatalogCardFilters(card, {
          cardType,
          basicHeartColor,
          memberCostMin: parseOptionalInt(memberCostMin),
          memberCostMax: parseOptionalInt(memberCostMax),
          memberBladeMin: parseOptionalInt(memberBladeMin),
          memberBladeMax: parseOptionalInt(memberBladeMax),
          memberBladeHeartColor,
          requiredHeartColor,
          requiredHeartMin: parseOptionalInt(requiredHeartMin),
          requiredHeartMax: parseOptionalInt(requiredHeartMax),
          liveScoreMin: parseOptionalInt(liveScoreMin),
          liveScoreMax: parseOptionalInt(liveScoreMax),
          hasLiveBladeHeart:
            hasLiveBladeHeart === "" ? undefined : hasLiveBladeHeart === "true",
          liveBladeHeartColor,
        }),
      ));
      return sortDeckCatalogCards(filtered, sortKey, sortDirection, deck);
    },
    [
      basicHeartColor,
      cardType,
      cards,
      deck,
      hasLiveBladeHeart,
      liveBladeHeartColor,
      liveScoreMax,
      liveScoreMin,
      memberBladeHeartColor,
      memberBladeMax,
      memberBladeMin,
      memberCostMax,
      memberCostMin,
      requiredHeartColor,
      requiredHeartMax,
      requiredHeartMin,
      sortDirection,
      sortKey,
    ],
  );
  const selectedSummary = useMemo(
    () =>
      visibleCards.find((card) => catalogRowKey(card) === selectedCatalogKey) ??
      visibleCards.find((card) => card.card_code === selectedCardCode) ??
      null,
    [selectedCardCode, selectedCatalogKey, visibleCards],
  );
  const mainCount = sumDeck(deck.main_deck);
  const energyCount = sumDeck(deck.energy_deck);
  const totalCount = mainCount + energyCount;
  const deckTypeCounts = useMemo(
    () => resolveDeckTypeCounts(deck.main_deck, summaryCache, detailCache),
    [deck.main_deck, detailCache, summaryCache],
  );
  const memberCount = deckTypeCounts.member;
  const liveCount = deckTypeCounts.live;
  const memberEntries = useMemo(
    () => filterDeckEntriesByType(deck.main_deck, summaryCache, detailCache, "member"),
    [deck.main_deck, detailCache, summaryCache],
  );
  const liveEntries = useMemo(
    () => filterDeckEntriesByType(deck.main_deck, summaryCache, detailCache, "live"),
    [deck.main_deck, detailCache, summaryCache],
  );
  const deckCardCodes = useMemo(
    () =>
      [...new Set([...deck.main_deck, ...deck.energy_deck].map((entry) => entry.card_code))],
    [deck],
  );
  const catalogPageCount = Math.max(1, Math.ceil(catalogTotal / CATALOG_PAGE_SIZE));

  useEffect(() => {
    let active = true;
    setLoadingDecks(true);
    listSavedDecks()
      .then((response) => {
        if (!active) return;
        setSavedDecks(response);
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingDecks(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoadingCards(true);
    listCatalogCards({
      q: query || undefined,
      cardType: cardType || undefined,
      workKey: workKey || undefined,
      unitKey: unitKey || undefined,
      basicHeartColor: basicHeartColor || undefined,
      memberCostMin: parseOptionalInt(memberCostMin),
      memberCostMax: parseOptionalInt(memberCostMax),
      memberBladeMin: parseOptionalInt(memberBladeMin),
      memberBladeMax: parseOptionalInt(memberBladeMax),
      memberBladeHeartColor: memberBladeHeartColor || undefined,
      requiredHeartColor: requiredHeartColor || undefined,
      requiredHeartMin: parseOptionalInt(requiredHeartMin),
      requiredHeartMax: parseOptionalInt(requiredHeartMax),
      liveScoreMin: parseOptionalInt(liveScoreMin),
      liveScoreMax: parseOptionalInt(liveScoreMax),
      hasLiveBladeHeart:
        hasLiveBladeHeart === "" ? undefined : hasLiveBladeHeart === "true",
      liveBladeHeartColor: liveBladeHeartColor || undefined,
      limit: CATALOG_PAGE_SIZE,
      offset: catalogPage * CATALOG_PAGE_SIZE,
    })
      .then((response) => {
        if (!active) return;
        setCards(response.items);
        setCatalogTotal(response.total);
        setSummaryCache((current) => {
          const next = { ...current };
          for (const item of response.items) {
            next[item.card_code] = item;
          }
          return next;
        });
        const first = aggregateDeckCatalogCards(response.items)[0] ?? null;
        setSelectedCardCode((current) =>
          current && response.items.some((item) => item.card_code === current)
            ? current
            : first?.card_code ?? null,
        );
        setSelectedCatalogKey((current) =>
          current && response.items.some((item) => catalogRowKey(item) === current)
            ? current
            : first ? catalogRowKey(first) : null,
        );
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingCards(false);
      });
    return () => {
      active = false;
    };
  }, [
    basicHeartColor,
    cardType,
    catalogPage,
    hasLiveBladeHeart,
    liveBladeHeartColor,
    liveScoreMax,
    liveScoreMin,
    memberBladeHeartColor,
    memberBladeMax,
    memberBladeMin,
    memberCostMax,
    memberCostMin,
    query,
    requiredHeartColor,
    requiredHeartMax,
    requiredHeartMin,
    unitKey,
    workKey,
  ]);

  useEffect(() => {
    setCatalogPage(0);
  }, [
    basicHeartColor,
    cardType,
    hasLiveBladeHeart,
    liveBladeHeartColor,
    liveScoreMax,
    liveScoreMin,
    memberBladeHeartColor,
    memberBladeMax,
    memberBladeMin,
    memberCostMax,
    memberCostMin,
    query,
    requiredHeartColor,
    requiredHeartMax,
    requiredHeartMin,
    unitKey,
    workKey,
  ]);

  useEffect(() => {
    setSelectedCatalogKey((current) => {
      if (current && visibleCards.some((card) => catalogRowKey(card) === current)) {
        return current;
      }
      return visibleCards[0] ? catalogRowKey(visibleCards[0]) : null;
    });
    setSelectedCardCode((current) => {
      if (current && visibleCards.some((card) => card.card_code === current)) {
        return current;
      }
      return visibleCards[0]?.card_code ?? null;
    });
  }, [visibleCards]);

  useEffect(() => {
    let active = true;
    listCatalogFacets()
      .then((response) => {
        if (!active) return;
        setFacets(response);
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedCardCode) {
      setDetail(null);
      return;
    }
    if (detailCache[selectedCardCode]) {
      setDetail(detailCache[selectedCardCode]);
      return;
    }
    let active = true;
    getCatalogCard(selectedCardCode)
      .then((response) => {
        if (!active) return;
        setDetailCache((current) => ({ ...current, [selectedCardCode]: response }));
        setDetail(response);
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, [detailCache, selectedCardCode]);

  useEffect(() => {
    const missingCodes = deckCardCodes.filter((cardCode) => !detailCache[cardCode]);
    if (missingCodes.length === 0) {
      return;
    }
    let active = true;
    Promise.all(
      missingCodes.map(async (cardCode) => {
        try {
          return [cardCode, await getCatalogCard(cardCode)] as const;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (!active) return;
      const entries = results.filter(
        (item): item is readonly [string, CatalogCardDetail] => item !== null,
      );
      if (entries.length === 0) return;
      setDetailCache((current) => {
        const next = { ...current };
        for (const [cardCode, response] of entries) {
          next[cardCode] = response;
        }
        return next;
      });
    });
    return () => {
      active = false;
    };
  }, [deckCardCodes, detailCache]);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setAnalyzing(true);
      analyzeDeck({
        ...deck,
        name: deckName || null,
      })
        .then((response) => {
          if (!active) return;
          setAnalysisError(null);
          setAnalysis(response);
        })
        .catch((reason) => {
          if (!active) return;
          setAnalysisError(reason instanceof Error ? reason.message : String(reason));
          setAnalysis(null);
        })
        .finally(() => {
          if (active) setAnalyzing(false);
        });
    }, 200);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [deck, deckName]);

  function addCard(summary: CatalogCardSummary) {
    const preferredPrintingId = summary.card_id;
    const entry = {
      card_code: summary.card_code,
      quantity: 1,
      preferred_printing_id: preferredPrintingId,
    };
    if (summary.card_type === "energy") {
      const blocked = additionError(
        "energy_deck",
        summary.card_type,
        energyCount,
        currentEntryQuantity(deck.energy_deck, summary.card_code),
        1,
        locale,
        memberCount,
        liveCount,
      );
      if (blocked) {
        setMessage(blocked);
        return;
      }
      setDeck((current) => ({
        ...current,
        energy_deck: mergeEntry(current.energy_deck, entry, "energy"),
      }));
      return;
    }
    const blocked = additionError(
      "main_deck",
      summary.card_type,
      mainCount,
      currentEntryQuantity(deck.main_deck, summary.card_code),
      1,
      locale,
      memberCount,
      liveCount,
    );
    if (blocked) {
      setMessage(blocked);
      return;
    }
    setDeck((current) => ({
      ...current,
      main_deck: mergeEntry(current.main_deck, entry, summary.card_type),
    }));
  }

  async function refreshDecks() {
    const response = await listSavedDecks();
    setSavedDecks(response);
  }

  async function saveCurrentDeck() {
    setSaving(true);
    setMessage(null);
    try {
      const payload = { ...deck, name: deckName || null };
      const response = selectedDeckId
        ? await updateSavedDeck(selectedDeckId, {
            deck: payload,
            name: deckName || null,
            overwrite: true,
          })
        : await createSavedDeck({
            deck: payload,
            name: deckName || null,
            overwrite: false,
          });
      setSelectedDeckId(response.path);
      await refreshDecks();
      setMessage(tr(locale, "牌组已保存。", "デッキを保存しました。"));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  async function loadDeck(deckId: string) {
    setSaving(true);
    setMessage(null);
    try {
      const loaded = await getSavedDeck(deckId);
      setDeck(loaded);
      setDeckName(loaded.name ?? "");
      setSelectedDeckId(deckId);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  async function renameCurrentDeck() {
    if (!selectedDeckId || !deckName.trim()) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await renameSavedDeck(selectedDeckId, { name: deckName.trim() });
      setSelectedDeckId(response.path);
      await refreshDecks();
      setMessage(tr(locale, "牌组已重命名。", "デッキ名を変更しました。"));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  async function deleteCurrentDeck() {
    if (!selectedDeckId) return;
    setSaving(true);
    setMessage(null);
    try {
      await deleteSavedDeck(selectedDeckId);
      setDeck(EMPTY_DECK);
      setDeckName("");
      setSelectedDeckId(null);
      await refreshDecks();
      setMessage(tr(locale, "牌组已删除。", "デッキを削除しました。"));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  function updateEntry(section: "main_deck" | "energy_deck", cardCode: string, updater: (entry: DeckEntry) => DeckEntry | null) {
    setDeck((current) => ({
      ...current,
      [section]: current[section]
        .map((entry) => (entry.card_code === cardCode ? updater(entry) : entry))
        .filter((entry): entry is DeckEntry => entry !== null),
    }));
  }

  function addQuantity(section: "main_deck" | "energy_deck", cardCode: string, delta: number) {
    if (delta > 0) {
      const snapshot = detailCache[cardCode]?.card ?? summaryCache[cardCode] ?? null;
      const blocked = additionError(
        section,
        snapshot?.card_type ?? (section === "energy_deck" ? "energy" : "member"),
        sumDeck(deck[section]),
        currentEntryQuantity(deck[section], cardCode),
        delta,
        locale,
        memberCount,
        liveCount,
      );
      if (blocked) {
        setMessage(blocked);
        return;
      }
    }
    updateEntry(section, cardCode, (entry) => {
      const cardType = cardTypeForDeckEntry(
        cardCode,
        summaryCache,
        detailCache,
        section === "energy_deck" ? "energy" : "member",
      );
      const maxQuantity = cardType === "energy" ? ENERGY_DECK_LIMIT : MAX_COPIES_PER_CARD;
      const next = Math.max(0, Math.min(maxQuantity, entry.quantity + delta));
      return next === 0 ? null : { ...entry, quantity: next };
    });
  }

  function updatePreferredPrinting(
    section: "main_deck" | "energy_deck",
    cardCode: string,
    preferredPrintingId: string,
  ) {
    updateEntry(section, cardCode, (entry) => ({
      ...entry,
      preferred_printing_id: preferredPrintingId || null,
    }));
  }

  function replaceDeck(next: DeckList) {
    setDeck(next);
    setDeckName(next.name ?? "");
    setSelectedDeckId(null);
  }

  function exportCurrentDeck() {
    const payload = {
      ...deck,
      name: deckName || deck.name,
    };
    const filename = `${slugifyDeckFilename(payload.name ?? "loveca-deck")}.decklist.v0.json`;
    const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function importDeckFile(file: File) {
    setSaving(true);
    setMessage(null);
    try {
      const parsed = JSON.parse(await file.text()) as DeckList;
      if (parsed.version !== "decklist.v0" || !Array.isArray(parsed.main_deck) || !Array.isArray(parsed.energy_deck)) {
        throw new Error(tr(locale, "不是有效的 decklist.v0 文件。", "有効な decklist.v0 ファイルではありません。"));
      }
      replaceDeck({
        version: "decklist.v0",
        name: parsed.name ?? file.name.replace(/\.json$/i, ""),
        main_deck: normalizeImportedEntries(parsed.main_deck),
        energy_deck: normalizeImportedEntries(parsed.energy_deck),
      });
      setMessage(tr(locale, "牌组 JSON 已导入。请检查后保存。", "デッキ JSON を読み込みました。確認して保存してください。"));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  const analyzedEnergyCount = analysis?.card_type_counts.energy_deck?.energy ?? energyCount;
  function selectCatalogCard(card: CatalogCardSummary) {
    setSelectedCardCode(card.card_code);
    setSelectedCatalogKey(catalogRowKey(card));
  }

  return (
    <div className="catalog-shell">
      <header className="topbar catalog-topbar">
        <div className="brand-lockup">
          <ClipboardList size={22} />
          <div>
            <strong>{tr(locale, "牌组编辑与保存", "デッキ編集と保存")}</strong>
            <span>{tr(locale, "本地 decklist.v0 持久化", "ローカル decklist.v0 永続化")}</span>
          </div>
        </div>
        <div className="phase-status">
          <span className="turn-number">
            {tr(locale, "当前牌组", "現在のデッキ")}
          </span>
          <span className="phase-cn">
            {tr(locale, `${totalCount} 张`, `${totalCount}枚`)}
          </span>
          <span>
            {tr(locale, `${savedDecks.length} 个已保存`, `${savedDecks.length}個保存済み`)}
          </span>
        </div>
        <div className="top-actions">
          <LanguageToggle locale={locale} setLocale={setLocale} />
          <button className="icon-button" onClick={onBack} title={tr(locale, "返回", "戻る")}>
            <ArrowLeft size={18} />
          </button>
        </div>
      </header>

      {message && <div className="error-banner">{message}</div>}

      <main className="deck-workspace">
        <section className="deck-sidebar">
          <div className="section-heading compact-heading">
            <BookOpen size={18} />
            <div>
              <h2>{tr(locale, "已保存牌组", "保存済みデッキ")}</h2>
              <p>{tr(locale, "本地文件库", "ローカルファイルライブラリ")}</p>
            </div>
          </div>
          <div className="deck-list">
            {loadingDecks && (
              <div className="catalog-loading">
                <LoaderCircle size={16} className="spin" />
                {tr(locale, "加载牌组中", "デッキを読み込み中")}
              </div>
            )}
            {savedDecks.map((item) => (
              <button
                key={item.path}
                className={`deck-row ${selectedDeckId === item.path ? "selected" : ""}`}
                onClick={() => void loadDeck(item.path)}
              >
                <strong>{item.name ?? item.path}</strong>
                <small>
                  {item.main_card_count}+{item.energy_card_count} · {item.version}
                </small>
              </button>
            ))}
            {savedDecks.length === 0 && !loadingDecks && (
              <div className="empty-state">
                {tr(locale, "尚未保存任何牌组。", "まだ保存されたデッキはありません。")}
              </div>
            )}
          </div>
          <div className="deck-actions">
            <button className="secondary-button" onClick={() => replaceDeck(EMPTY_DECK)}>
              <WandSparkles size={16} />
              {tr(locale, "新建空牌组", "空デッキを作成")}
            </button>
            <button
              className="secondary-button"
              disabled={!selectedDeckId}
              onClick={() => void deleteCurrentDeck()}
            >
              <Trash2 size={16} />
              {tr(locale, "删除当前", "現在のデッキを削除")}
            </button>
          </div>
        </section>

        <section className="deck-center">
          <div className="deck-overview" aria-label={tr(locale, "牌组状态总览", "デッキ状態")}>
            <div className="deck-overview-card">
              <small>{tr(locale, "主牌组", "メインデッキ")}</small>
              <strong>{mainCount} / {MAIN_DECK_LIMIT}</strong>
              <span>
                {tr(
                  locale,
                  `Member ${memberCount}/${MAIN_DECK_MEMBER_TARGET} · Live ${liveCount}/${MAIN_DECK_LIVE_TARGET}`,
                  `メンバー ${memberCount}/${MAIN_DECK_MEMBER_TARGET} · ライブ ${liveCount}/${MAIN_DECK_LIVE_TARGET}`,
                )}
              </span>
            </div>
            <div className="deck-overview-card">
              <small>{tr(locale, "能量组", "エネルギーデッキ")}</small>
              <strong>{energyCount} / {ENERGY_DECK_LIMIT}</strong>
              <span>{tr(locale, "能量卡不受同卡 4 张限制", "エネルギーは同名4枚制限なし")}</span>
            </div>
            <div className={`deck-overview-card ${analysis?.is_legal ? "legal" : "review"}`}>
              <small>{tr(locale, "合法性", "合法性")}</small>
              <strong>
                {analyzing
                  ? tr(locale, "分析中", "分析中")
                  : analysis
                    ? analysis.is_legal
                      ? tr(locale, "合法", "合法")
                      : tr(locale, "需修正", "要修正")
                    : tr(locale, "等待分析", "分析待ち")}
              </strong>
              <span>
                {analysis
                  ? tr(locale, `问题 ${analysis.issues.length}`, `問題 ${analysis.issues.length}`)
                  : tr(locale, `${totalCount} 张总计`, `${totalCount}枚合計`)}
              </span>
            </div>
          </div>
          <div className="deck-toolbar">
            <label className="deck-name-field">
              {tr(locale, "牌组名称", "デッキ名")}
              <input
                value={deckName}
                onChange={(event) => setDeckName(event.target.value)}
                placeholder={tr(locale, "未命名牌组", "無題デッキ")}
              />
            </label>
            <div className="deck-save-actions">
              <button className="secondary-button" onClick={() => importInputRef.current?.click()}>
                <Upload size={18} />
                {tr(locale, "导入 JSON", "JSONを読み込む")}
              </button>
              <input
                ref={importInputRef}
                type="file"
                accept="application/json,.json"
                className="visually-hidden"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) void importDeckFile(file);
                }}
              />
              <button className="secondary-button" onClick={exportCurrentDeck}>
                <Download size={18} />
                {tr(locale, "导出 JSON", "JSONを書き出す")}
              </button>
              <button
                className="secondary-button"
                disabled={totalCount === 0}
                onClick={() =>
                  onUseForMatch({
                    ...deck,
                    name: deckName || null,
                  })
                }
              >
                <Activity size={18} />
                {tr(locale, "用于创建对局", "対戦作成に使う")}
              </button>
              <button className="primary-button" disabled={saving} onClick={() => void saveCurrentDeck()}>
                <Save size={18} />
                {selectedDeckId ? tr(locale, "保存更新", "更新保存") : tr(locale, "保存", "保存")}
              </button>
              <button
                className="secondary-button"
                disabled={saving || !selectedDeckId || !deckName.trim()}
                onClick={() => void renameCurrentDeck()}
              >
                {tr(locale, "重命名", "名前変更")}
              </button>
            </div>
          </div>
          <div className="deck-sections">
            <DeckSection
              locale={locale}
              title={tr(locale, `Member ${memberCount} / ${MAIN_DECK_MEMBER_TARGET}`, `メンバー ${memberCount} / ${MAIN_DECK_MEMBER_TARGET}`)}
              entries={memberEntries}
              summaryCache={summaryCache}
              detailCache={detailCache}
              selectedCardCode={selectedCardCode}
              onDecrease={(cardCode) => addQuantity("main_deck", cardCode, -1)}
              onIncrease={(cardCode) => addQuantity("main_deck", cardCode, 1)}
              onPreferred={(cardCode, value) => updatePreferredPrinting("main_deck", cardCode, value)}
              onSelectCard={setSelectedCardCode}
              canIncrease={(cardCode) =>
                !additionError(
                  "main_deck",
                  cardTypeForDeckEntry(cardCode, summaryCache, detailCache, "member"),
                  mainCount,
                  currentEntryQuantity(deck.main_deck, cardCode),
                  1,
                  locale,
                  memberCount,
                  liveCount,
                )
              }
              onPreview={(cardCode) => {
                setSelectedCardCode(cardCode);
                setPreviewOpen(true);
              }}
            />
            <DeckSection
              locale={locale}
              title={tr(locale, `Live ${liveCount} / ${MAIN_DECK_LIVE_TARGET}`, `ライブ ${liveCount} / ${MAIN_DECK_LIVE_TARGET}`)}
              entries={liveEntries}
              summaryCache={summaryCache}
              detailCache={detailCache}
              selectedCardCode={selectedCardCode}
              onDecrease={(cardCode) => addQuantity("main_deck", cardCode, -1)}
              onIncrease={(cardCode) => addQuantity("main_deck", cardCode, 1)}
              onPreferred={(cardCode, value) => updatePreferredPrinting("main_deck", cardCode, value)}
              onSelectCard={setSelectedCardCode}
              canIncrease={(cardCode) =>
                !additionError(
                  "main_deck",
                  cardTypeForDeckEntry(cardCode, summaryCache, detailCache, "live"),
                  mainCount,
                  currentEntryQuantity(deck.main_deck, cardCode),
                  1,
                  locale,
                  memberCount,
                  liveCount,
                )
              }
              onPreview={(cardCode) => {
                setSelectedCardCode(cardCode);
                setPreviewOpen(true);
              }}
            />
            <DeckSection
              locale={locale}
              title={tr(locale, `Energy ${energyCount} / ${ENERGY_DECK_LIMIT}`, `エネルギー ${energyCount} / ${ENERGY_DECK_LIMIT}`)}
              entries={deck.energy_deck}
              summaryCache={summaryCache}
              detailCache={detailCache}
              selectedCardCode={selectedCardCode}
              onDecrease={(cardCode) => addQuantity("energy_deck", cardCode, -1)}
              onIncrease={(cardCode) => addQuantity("energy_deck", cardCode, 1)}
              onPreferred={(cardCode, value) => updatePreferredPrinting("energy_deck", cardCode, value)}
              onSelectCard={setSelectedCardCode}
              canIncrease={(cardCode) =>
                !additionError(
                  "energy_deck",
                  cardTypeForDeckEntry(cardCode, summaryCache, detailCache, "energy"),
                  energyCount,
                  currentEntryQuantity(deck.energy_deck, cardCode),
                  1,
                  locale,
                  memberCount,
                  liveCount,
                )
              }
              onPreview={(cardCode) => {
                setSelectedCardCode(cardCode);
                setPreviewOpen(true);
              }}
              compact
            />
          </div>
          <section className="deck-analysis-panel">
            <div className="deck-analysis-header">
              <div className="deck-analysis-title">
                <Activity size={18} />
                <div>
                  <h2>{tr(locale, "当前牌组分析", "現在のデッキ分析")}</h2>
                  <p>{tr(locale, "自动刷新构筑合法性和 Live 判定相关指标。", "構築合法性とライブ判定関連指標を自動更新します。")}</p>
                </div>
              </div>
              {analysis && (
                <span className={`deck-analysis-pill ${analysis.is_legal ? "legal" : "illegal"}`}>
                  {analysis.is_legal
                    ? tr(locale, "当前牌组合法", "現在のデッキは合法です")
                    : tr(locale, "当前牌组不合法", "現在のデッキは不正です")}
                </span>
              )}
            </div>
            {!analysis && !analyzing && !analysisError && (
              <div className="empty-state">
                {tr(locale, "等待分析结果。", "分析結果を待機中です。")}
              </div>
            )}
            {analyzing && (
              <div className="catalog-loading">
                <LoaderCircle size={16} className="spin" />
                {tr(locale, "分析牌组中", "デッキを分析中")}
              </div>
            )}
            {analysisError && (
              <div className="error-banner deck-analysis-error">{analysisError}</div>
            )}
            {analysis && (
              <div className="deck-analysis-grid">
                <div className="deck-analysis-metrics">
                  <div className="deck-analysis-metric">
                    <small>{tr(locale, "主牌组", "メイン")}</small>
                    <strong>{mainCount} / {MAIN_DECK_LIMIT}</strong>
                    <span>{tr(locale, "Member + Live", "メンバー + ライブ")}</span>
                  </div>
                  <div className="deck-analysis-metric">
                    <small>Member</small>
                    <strong>{memberCount} / {MAIN_DECK_MEMBER_TARGET}</strong>
                    <span>{tr(locale, "角色卡", "メンバー")}</span>
                  </div>
                  <div className="deck-analysis-metric">
                    <small>Live</small>
                    <strong>{liveCount} / {MAIN_DECK_LIVE_TARGET}</strong>
                    <span>{tr(locale, "Live 卡", "ライブ")}</span>
                  </div>
                  <div className="deck-analysis-metric">
                    <small>Energy</small>
                    <strong>{analyzedEnergyCount} / {ENERGY_DECK_LIMIT}</strong>
                    <span>{tr(locale, "能量组", "エネルギー")}</span>
                  </div>
                  <div className={`deck-analysis-metric issue-count ${analysis.issues.length ? "warn" : "ok"}`}>
                    <small>{tr(locale, "问题", "問題")}</small>
                    <strong>{analysis.issues.length}</strong>
                    <span>{analysis.issues.length ? tr(locale, "需要处理", "要対応") : tr(locale, "无", "なし")}</span>
                  </div>
                </div>
                <div className="deck-analysis-dashboard">
                  <div className="deck-analysis-summary">
                    <strong>{tr(locale, "Member cost curve", "メンバーコスト分布")}</strong>
                    <DistributionChips
                      locale={locale}
                      values={analysis.member_cost_curve}
                      itemLabel={tr(locale, "Cost", "コスト")}
                    />
                  </div>
                  <div className="deck-analysis-summary emphasis">
                    <strong>{tr(locale, "基本 Heart", "基本ハート")}</strong>
                    <span>{formatColorValueMap(locale, analysis.member_basic_heart_distribution)}</span>
                  </div>
                  <div className="deck-analysis-summary emphasis">
                    <strong>{tr(locale, "所需 Heart", "必要ハート")}</strong>
                    <span>{formatColorValueMap(locale, analysis.live_required_heart_distribution)}</span>
                  </div>
                  <div className="deck-analysis-summary">
                    <strong>{tr(locale, "Live score", "ライブスコア")}</strong>
                    <DistributionChips
                      locale={locale}
                      values={analysis.live_score_distribution}
                      itemLabel="Score"
                    />
                  </div>
                  <div className="deck-analysis-summary">
                    <strong>{tr(locale, "Special Blade Heart", "特殊ブレードハート")}</strong>
                    <span>{formatMetricMap(analysis.special_blade_heart_summary)}</span>
                  </div>
                  <div className="deck-analysis-summary">
                    <strong>{tr(locale, "技能时点", "能力タイミング")}</strong>
                    <span>{formatEffectTimingSummary(locale, analysis.effect_timing_summary)}</span>
                  </div>
                  <div className="deck-analysis-summary">
                    <strong>{tr(locale, "技能处理方式", "能力解決方式")}</strong>
                    <span>{formatEffectExecutionSummary(locale, analysis.effect_execution_summary)}</span>
                  </div>
                  <div className="deck-analysis-issues">
                    <strong>{tr(locale, "Issues", "問題一覧")}</strong>
                    {analysis.issues.length === 0 ? (
                      <div className="deck-analysis-empty">{tr(locale, "无", "なし")}</div>
                    ) : (
                      analysis.issues.map((issue, index) => (
                        <div key={`${issue.code}-${index}`} className="deck-analysis-issue">
                          <strong>{issue.code}</strong>
                          <span>{issue.message}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
        </section>

        <section className="deck-sidebar deck-catalog">
          <div className="deck-search">
            <label className="catalog-search">
              <Search size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={tr(locale, "搜索卡名、卡号、套装", "カード名・カード番号・セットを検索")}
              />
            </label>
            <div className="catalog-filter-row">
              {(["", "member", "live", "energy"] as const).map((value) => (
                <button
                  className={`filter-chip ${cardType === value ? "active" : ""}`}
                  key={value || "all"}
                  onClick={() => setCardType(value)}
                >
                  {value === ""
                    ? tr(locale, "全部", "すべて")
                    : value === "member"
                      ? tr(locale, "角色卡", "メンバー")
                      : value === "live"
                        ? tr(locale, "Live 卡", "ライブ")
                        : tr(locale, "能量卡", "エネルギー")}
                </button>
              ))}
            </div>
            <div className="catalog-filter-grid">
              <label className="catalog-select-filter">
                <span>{tr(locale, "作品", "作品")}</span>
                <select value={workKey} onChange={(event) => setWorkKey(event.target.value)}>
                  <option value="">{tr(locale, "全部作品", "すべての作品")}</option>
                  {facets.works.map((item) => (
                    <option key={item.work_key} value={item.work_key}>
                      {item.canonical_name_ja}
                    </option>
                  ))}
                </select>
              </label>
              <label className="catalog-select-filter">
                <span>{tr(locale, "组合", "ユニット")}</span>
                <select value={unitKey} onChange={(event) => setUnitKey(event.target.value)}>
                  <option value="">{tr(locale, "全部组合", "すべてのユニット")}</option>
                  {facets.units.map((item) => (
                    <option key={item.unit_key} value={item.unit_key}>
                      {item.canonical_name_ja}
                    </option>
                  ))}
                </select>
              </label>
              <label className="catalog-select-filter">
                <span>{tr(locale, "排序", "並び順")}</span>
                <select
                  value={sortKey}
                  onChange={(event) => setSortKey(event.target.value as DeckSearchSortKey)}
                >
                  <option value="default">{tr(locale, "默认", "デフォルト")}</option>
                  <option value="card_code">{tr(locale, "卡号", "カード番号")}</option>
                  <option value="name">{tr(locale, "卡名", "カード名")}</option>
                  <option value="type">{tr(locale, "卡牌种类", "カード種別")}</option>
                  <option value="cost">Member Cost</option>
                  <option value="blade">Blade</option>
                  <option value="required_heart">{tr(locale, "Live 所需 Heart", "ライブ必要ハート")}</option>
                  <option value="score">Live Score</option>
                  <option value="deck_quantity">{tr(locale, "当前投入枚数", "現在の投入枚数")}</option>
                </select>
              </label>
              <label className="catalog-select-filter">
                <span>{tr(locale, "方向", "方向")}</span>
                <select
                  value={sortDirection}
                  onChange={(event) => setSortDirection(event.target.value as SortDirection)}
                  disabled={sortKey === "default"}
                >
                  <option value="asc">{tr(locale, "升序", "昇順")}</option>
                  <option value="desc">{tr(locale, "降序", "降順")}</option>
                </select>
              </label>
            </div>
            {(cardType === "" || cardType === "member") && (
              <div className="catalog-filter-grid extended">
                <label className="catalog-select-filter">
                  <span>{tr(locale, "基本 Heart 颜色", "基本ハート色")}</span>
                  <select value={basicHeartColor} onChange={(event) => setBasicHeartColor(event.target.value)}>
                    <option value="">{tr(locale, "全部", "すべて")}</option>
                    {HEART_COLOR_OPTIONS.filter((value) => value !== "heart0").map((value) => (
                      <option key={value} value={value}>
                        {heartColorLabel(locale, value)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "角色费用最小", "コスト最小")}</span>
                  <input type="number" min="0" value={memberCostMin} onChange={(event) => setMemberCostMin(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "角色费用最大", "コスト最大")}</span>
                  <input type="number" min="0" value={memberCostMax} onChange={(event) => setMemberCostMax(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "应援棒最小", "ブレード最小")}</span>
                  <input type="number" min="0" value={memberBladeMin} onChange={(event) => setMemberBladeMin(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "应援棒最大", "ブレード最大")}</span>
                  <input type="number" min="0" value={memberBladeMax} onChange={(event) => setMemberBladeMax(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "应援 Heart 颜色", "ブレードハート色")}</span>
                  <select value={memberBladeHeartColor} onChange={(event) => setMemberBladeHeartColor(event.target.value)}>
                    <option value="">{tr(locale, "全部", "すべて")}</option>
                    {HEART_COLOR_OPTIONS.filter((value) => value !== "heart0").map((value) => (
                      <option key={value} value={value}>
                        {heartColorLabel(locale, value)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            {(cardType === "" || cardType === "live") && (
              <div className="catalog-filter-grid extended">
                <label className="catalog-select-filter">
                  <span>{tr(locale, "所需 Heart 颜色", "必要ハート色")}</span>
                  <select value={requiredHeartColor} onChange={(event) => setRequiredHeartColor(event.target.value)}>
                    <option value="">{tr(locale, "全部", "すべて")}</option>
                    {HEART_COLOR_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {heartColorLabel(locale, value)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "所需 Heart 数量最小", "必要ハート数最小")}</span>
                  <input type="number" min="0" value={requiredHeartMin} onChange={(event) => setRequiredHeartMin(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "所需 Heart 数量最大", "必要ハート数最大")}</span>
                  <input type="number" min="0" value={requiredHeartMax} onChange={(event) => setRequiredHeartMax(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "Score 最小", "スコア最小")}</span>
                  <input type="number" min="0" value={liveScoreMin} onChange={(event) => setLiveScoreMin(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "Score 最大", "スコア最大")}</span>
                  <input type="number" min="0" value={liveScoreMax} onChange={(event) => setLiveScoreMax(event.target.value)} />
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "有无应援 Heart", "ブレードハート有無")}</span>
                  <select value={hasLiveBladeHeart} onChange={(event) => setHasLiveBladeHeart(event.target.value as "" | "true" | "false")}>
                    <option value="">{tr(locale, "全部", "すべて")}</option>
                    <option value="true">{tr(locale, "有", "あり")}</option>
                    <option value="false">{tr(locale, "无", "なし")}</option>
                  </select>
                </label>
                <label className="catalog-select-filter">
                  <span>{tr(locale, "Live 应援 Heart 颜色", "ライブのブレードハート色")}</span>
                  <select value={liveBladeHeartColor} onChange={(event) => setLiveBladeHeartColor(event.target.value)}>
                    <option value="">{tr(locale, "全部", "すべて")}</option>
                    {HEART_COLOR_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {heartColorLabel(locale, value)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            <div className="catalog-meta">
              <span>
                {tr(
                  locale,
                  `当前页显示 ${visibleCards.length} / ${cards.length}，总计 ${catalogTotal} 张`,
                  `このページ ${visibleCards.length} / ${cards.length}件、合計 ${catalogTotal}件`,
                )}
              </span>
              <button
                className="mini-link"
                type="button"
                onClick={() => {
                  setBasicHeartColor("");
                  setMemberCostMin("");
                  setMemberCostMax("");
                  setMemberBladeMin("");
                  setMemberBladeMax("");
                  setMemberBladeHeartColor("");
                  setRequiredHeartColor("");
                  setRequiredHeartMin("");
                  setRequiredHeartMax("");
                  setLiveScoreMin("");
                  setLiveScoreMax("");
                  setHasLiveBladeHeart("");
                  setLiveBladeHeartColor("");
                }}
              >
                {tr(locale, "清空属性筛选", "属性フィルターをクリア")}
              </button>
            </div>
            <div className="catalog-pagebar">
              <span>
                {tr(
                  locale,
                  `第 ${catalogPage + 1} / ${catalogPageCount} 页 · 共 ${catalogTotal} 张`,
                  `${catalogPage + 1} / ${catalogPageCount} ページ · 全 ${catalogTotal} 件`,
                )}
              </span>
              <div className="deck-save-actions">
                <button
                  className="secondary-button"
                  disabled={catalogPage === 0 || loadingCards}
                  type="button"
                  onClick={() => setCatalogPage((current) => Math.max(0, current - 1))}
                >
                  {tr(locale, "上一页", "前へ")}
                </button>
                <button
                  className="secondary-button"
                  disabled={catalogPage + 1 >= catalogPageCount || loadingCards}
                  type="button"
                  onClick={() =>
                    setCatalogPage((current) => Math.min(catalogPageCount - 1, current + 1))
                  }
                >
                  {tr(locale, "下一页", "次へ")}
                </button>
              </div>
            </div>
          </div>
          <div className="catalog-list">
            {loadingCards && (
              <div className="catalog-loading">
                <LoaderCircle size={16} className="spin" />
                {tr(locale, "加载卡牌中", "カードを読み込み中")}
              </div>
            )}
            {!loadingCards && visibleCards.length === 0 && (
              <div className="empty-state">
                {tr(locale, "当前筛选条件下没有卡牌。", "現在の条件に一致するカードがありません。")}
              </div>
            )}
            {visibleCards.map((card) => (
              <div
                key={catalogRowKey(card)}
                className={`catalog-row ${selectedCatalogKey === catalogRowKey(card) ? "selected" : ""}`}
              >
                <button
                  className="catalog-row-main"
                  type="button"
                  onClick={() => selectCatalogCard(card)}
                >
                  <span className="catalog-row-top">
                    <strong>{card.name_ja}</strong>
                    <small>{card.card_code}</small>
                  </span>
                  <span className="catalog-row-bottom">
                    <span>{card.card_type.toUpperCase()}</span>
                    <span>{card.card_set_code ?? "-"}</span>
                    <span>{card.printing_count}×</span>
                  </span>
                  <span className="catalog-row-attributes">
                    {summarizeCatalogCard(locale, card).map((item) => (
                      <span key={`${card.card_id ?? card.card_code}-${item}`} className="catalog-attribute-chip">
                        {item}
                      </span>
                    ))}
                  </span>
                </button>
                <span className="deck-add-row">
                  <button
                    className="mini-link"
                    disabled={Boolean(
                      additionError(
                        card.card_type === "energy" ? "energy_deck" : "main_deck",
                        card.card_type,
                        card.card_type === "energy" ? energyCount : mainCount,
                        currentEntryQuantity(
                          card.card_type === "energy" ? deck.energy_deck : deck.main_deck,
                          card.card_code,
                        ),
                        1,
                        locale,
                        memberCount,
                        liveCount,
                      ),
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      addCard(card);
                    }}
                  >
                    <Plus size={14} />
                    {card.card_type === "energy"
                      ? tr(locale, "加入能量组", "エネルギーへ追加")
                      : tr(locale, "加入主牌组", "メインへ追加")}
                  </button>
                  <button
                    className="mini-link"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      selectCatalogCard(card);
                      setPreviewOpen(true);
                    }}
                  >
                    <Expand size={14} />
                    {tr(locale, "详情", "詳細")}
                  </button>
                </span>
              </div>
            ))}
          </div>
        </section>
      </main>
      {previewOpen && detail && (
        <CatalogPreviewDialog
          locale={locale}
          detail={detail}
          summary={selectedSummary}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </div>
  );
}

function DeckSection({
  locale,
  title,
  entries,
  summaryCache,
  detailCache,
  selectedCardCode,
  onIncrease,
  onDecrease,
  onPreferred,
  onSelectCard,
  canIncrease,
  onPreview,
  compact = false,
}: {
  locale: UiLocale;
  title: string;
  entries: DeckEntry[];
  summaryCache: Record<string, CatalogCardSummary>;
  detailCache: Record<string, CatalogCardDetail>;
  selectedCardCode: string | null;
  onIncrease: (cardCode: string) => void;
  onDecrease: (cardCode: string) => void;
  onPreferred: (cardCode: string, preferredPrintingId: string) => void;
  onSelectCard: (cardCode: string) => void;
  canIncrease: (cardCode: string) => boolean;
  onPreview: (cardCode: string) => void;
  compact?: boolean;
}) {
  return (
    <section className={`deck-section ${compact ? "compact" : ""}`}>
      <h3>{title}</h3>
      {entries.length === 0 && <div className="empty-state">{tr(locale, "空", "空")}</div>}
      <div className="deck-entry-list">
        {entries.map((entry) => {
          const detail = detailForCardCode(entry.card_code, detailCache);
          const summary = summaryCache[entry.card_code] ?? null;
          const printings = detail?.printings ?? [];
          const selectedPrinting =
            printings.find((item) => item.card_id === entry.preferred_printing_id) ??
            printings[0] ??
            null;
          return (
            <div
              key={entry.card_code}
              role="button"
              tabIndex={0}
              className={`deck-entry ${selectedCardCode === entry.card_code ? "selected" : ""}`}
              onClick={() => onSelectCard(entry.card_code)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectCard(entry.card_code);
                }
              }}
            >
              <div className="deck-entry-body">
                <div className="deck-entry-head">
                  <div className="deck-entry-title">
                    <strong>{detail?.card.name_ja ?? summary?.name_ja ?? entry.card_code}</strong>
                    <small>{entry.card_code}</small>
                  </div>
                  <span className="deck-entry-quantity">x{entry.quantity}</span>
                </div>
                <div className="deck-entry-meta">
                  {selectedPrinting && (
                    <span>
                      {selectedPrinting.card_id}
                      {selectedPrinting.rarity_ja ? ` · ${selectedPrinting.rarity_ja}` : ""}
                    </span>
                  )}
                </div>
                <div className="deck-entry-controls">
                  <button
                    className="mini-icon"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDecrease(entry.card_code);
                    }}
                  >
                    <Minus size={14} />
                  </button>
                  <button
                    className="mini-icon"
                    type="button"
                    disabled={!canIncrease(entry.card_code)}
                    onClick={(event) => {
                      event.stopPropagation();
                      onIncrease(entry.card_code);
                    }}
                  >
                    <Plus size={14} />
                  </button>
                  <button
                    className="mini-link"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onPreview(entry.card_code);
                    }}
                  >
                    <Expand size={14} />
                    {tr(locale, "详情", "詳細")}
                  </button>
                  <label className="deck-preferred-printing">
                    <span>{tr(locale, "印刷版本", "印刷版")}</span>
                    <select
                      value={entry.preferred_printing_id ?? ""}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => onPreferred(entry.card_code, event.target.value)}
                    >
                      <option value="">{tr(locale, "默认显示", "既定表示")}</option>
                      {printings.map((printing) => (
                        <option key={printing.card_id} value={printing.card_id}>
                          {printing.card_id}
                          {printing.rarity_ja ? ` · ${printing.rarity_ja}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DeckThumbnail({
  locale,
  localCardId,
  remoteImageUrl,
  alt,
  className,
}: {
  locale: UiLocale;
  localCardId: string | null;
  remoteImageUrl: string | null;
  alt: string;
  className?: string;
}) {
  const [sourceMode, setSourceMode] = useState<"local" | "remote" | "placeholder">(
    localCardId ? "local" : remoteImageUrl ? "remote" : "placeholder",
  );

  useEffect(() => {
    setSourceMode(localCardId ? "local" : remoteImageUrl ? "remote" : "placeholder");
  }, [localCardId, remoteImageUrl]);

  if (sourceMode === "placeholder") {
    return (
      <div className={`deck-card-thumbnail placeholder${className ? ` ${className}` : ""}`}>
        {tr(locale, "无图", "画像なし")}
      </div>
    );
  }

  const src =
    sourceMode === "local"
      ? `/api/card-images/${encodeURIComponent(localCardId ?? "")}`
      : (remoteImageUrl ?? "");
  return (
    <img
      className={`deck-card-thumbnail${className ? ` ${className}` : ""}`}
      src={src}
      alt={alt}
      onError={() => {
        if (sourceMode === "local" && remoteImageUrl) {
          setSourceMode("remote");
          return;
        }
        setSourceMode("placeholder");
      }}
    />
  );
}

function CatalogPreviewDialog({
  locale,
  detail,
  summary,
  onClose,
}: {
  locale: UiLocale;
  detail: CatalogCardDetail;
  summary: CatalogCardSummary | null;
  onClose: () => void;
}) {
  const defaultPrintingId = summary?.card_id ?? detail.printings[0]?.card_id ?? "";
  const [selectedPrintingId, setSelectedPrintingId] = useState(defaultPrintingId);
  useEffect(() => {
    setSelectedPrintingId(defaultPrintingId);
  }, [defaultPrintingId, detail.card.card_code]);
  const selectedPrinting =
    detail.printings.find((printing) => printing.card_id === selectedPrintingId)
    ?? detail.printings.find((printing) => printing.card_id === summary?.card_id)
    ?? detail.printings[0]
    ?? null;
  const text = formatEffectText(detail.text_revisions[0]?.raw_effect_text_ja ?? null, locale);
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <article className="card-dialog catalog-preview-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button close-dialog" onClick={onClose} type="button">
          ×
        </button>
        <div className="dialog-image">
          <DeckThumbnail
            locale={locale}
            localCardId={selectedPrinting?.card_id ?? summary?.card_id ?? null}
            remoteImageUrl={selectedPrinting?.image_url ?? summary?.image_url ?? null}
            alt={detail.card.name_ja}
            className="catalog-preview-image"
          />
        </div>
        <div className="dialog-content">
          <span>
            {formatCardType(locale, detail.card.card_type)} · {detail.card.card_code}
          </span>
          <h2>{detail.card.name_ja}</h2>
          <div className="attribute-grid">
            <DeckMetric label="Cost" value={detail.card.cost ?? "-"} />
            <DeckMetric label="Blade" value={detail.card.blade ?? "-"} />
            <DeckMetric label="Score" value={detail.card.score ?? "-"} />
            <DeckMetric label="Printing" value={selectedPrinting?.card_id ?? "-"} />
          </div>
          <h3>{tr(locale, "当前印刷版本", "現在の印刷版")}</h3>
          {detail.printings.length > 1 ? (
            <label className="deck-preview-printing">
              <span>{tr(locale, "选择卡面", "カード画像を選択")}</span>
              <select
                value={selectedPrinting?.card_id ?? ""}
                onChange={(event) => setSelectedPrintingId(event.target.value)}
              >
                {detail.printings.map((printing) => (
                  <option key={printing.card_id} value={printing.card_id}>
                    {printing.card_id}
                    {printing.rarity_ja ? ` · ${printing.rarity_ja}` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="effect-text">
              {selectedPrinting?.card_id ?? "-"}
              {selectedPrinting?.rarity_ja ? ` · ${selectedPrinting.rarity_ja}` : ""}
            </p>
          )}
          <h3>{tr(locale, "官方日文效果", "公式日本語テキスト")}</h3>
          <p className="effect-text">{text}</p>
          <h3>{tr(locale, "技能执行支持", "能力実行サポート")}</h3>
          <div className="effect-support-list">
            <span className={`support-status ${detail.card.effect_registry_status}`}>
              {effectSupportStatusLabel(locale, detail.card.effect_registry_status)}
            </span>
            {detail.card.effects.map((effect) => (
              <div key={effect.effect_id}>
                <strong>{effect.effect_id}</strong>
                <span>
                  {effectTriggerLabel(locale, effect.trigger)} ·{" "}
                  {effectExecutionModeLabel(locale, effect.execution_mode)} ·{" "}
                  {effect.simulation_support} · {effect.review_status}
                </span>
                <small>{formatEffectText(effect.label_ja, locale)}</small>
              </div>
            ))}
            {detail.card.effect_registry_errors.map((error) => (
              <code key={error}>{error}</code>
            ))}
          </div>
        </div>
      </article>
    </div>
  );
}

function DeckMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function DistributionChips({
  locale,
  values,
  itemLabel,
}: {
  locale: UiLocale;
  values: Record<string, number>;
  itemLabel: string;
}) {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) {
    return <span className="deck-distribution-empty">-</span>;
  }
  return (
    <span className="deck-distribution-chips">
      {entries.map(([key, value]) => (
        <span className="deck-distribution-chip" key={key}>
          <small>
            {itemLabel} {formatDistributionKey(locale, key)}
          </small>
          <strong>{value}</strong>
          <em>{tr(locale, "张", "枚")}</em>
        </span>
      ))}
    </span>
  );
}

function currentEntryQuantity(entries: DeckEntry[], cardCode: string): number {
  return entries.find((entry) => entry.card_code === cardCode)?.quantity ?? 0;
}

function parseOptionalInt(value: string): number | undefined {
  if (!value.trim()) {
    return undefined;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function matchesCatalogCardFilters(
  card: CatalogCardSummary,
  filters: {
    cardType: "" | "member" | "live" | "energy";
    basicHeartColor: string;
    memberCostMin?: number;
    memberCostMax?: number;
    memberBladeMin?: number;
    memberBladeMax?: number;
    memberBladeHeartColor: string;
    requiredHeartColor: string;
    requiredHeartMin?: number;
    requiredHeartMax?: number;
    liveScoreMin?: number;
    liveScoreMax?: number;
    hasLiveBladeHeart?: boolean;
    liveBladeHeartColor: string;
  },
): boolean {
  if (filters.cardType && card.card_type !== filters.cardType) {
    return false;
  }
  const memberFiltersActive =
    Boolean(filters.basicHeartColor) ||
    filters.memberCostMin !== undefined ||
    filters.memberCostMax !== undefined ||
    filters.memberBladeMin !== undefined ||
    filters.memberBladeMax !== undefined ||
    Boolean(filters.memberBladeHeartColor);
  const liveFiltersActive =
    Boolean(filters.requiredHeartColor) ||
    filters.requiredHeartMin !== undefined ||
    filters.requiredHeartMax !== undefined ||
    filters.liveScoreMin !== undefined ||
    filters.liveScoreMax !== undefined ||
    filters.hasLiveBladeHeart !== undefined ||
    Boolean(filters.liveBladeHeartColor);

  if (card.card_type === "member") {
    if (
      filters.basicHeartColor &&
      (card.basic_heart_by_color[filters.basicHeartColor] ?? 0) <= 0
    ) {
      return false;
    }
    if (
      filters.memberBladeHeartColor &&
      card.member_blade_heart_color_slot !== filters.memberBladeHeartColor
    ) {
      return false;
    }
    if (!matchesNumericRange(card.cost, filters.memberCostMin, filters.memberCostMax)) {
      return false;
    }
    if (
      !matchesNumericRange(card.blade, filters.memberBladeMin, filters.memberBladeMax)
    ) {
      return false;
    }
    if (!filters.cardType && liveFiltersActive && !memberFiltersActive) {
      return false;
    }
    return true;
  }

  if (card.card_type === "live") {
    if (
      filters.requiredHeartColor &&
      (card.required_heart_by_color[filters.requiredHeartColor] ?? 0) <= 0
    ) {
      return false;
    }
    const requiredHeartValue = filters.requiredHeartColor
      ? (card.required_heart_by_color[filters.requiredHeartColor] ?? 0)
      : card.required_heart_total;
    if (
      !matchesNumericRange(
        requiredHeartValue,
        filters.requiredHeartMin,
        filters.requiredHeartMax,
      )
    ) {
      return false;
    }
    if (!matchesNumericRange(card.score, filters.liveScoreMin, filters.liveScoreMax)) {
      return false;
    }
    if (
      filters.hasLiveBladeHeart !== undefined &&
      card.has_live_blade_heart !== filters.hasLiveBladeHeart
    ) {
      return false;
    }
    if (
      filters.liveBladeHeartColor &&
      card.live_blade_heart_color_slot !== filters.liveBladeHeartColor
    ) {
      return false;
    }
    if (!filters.cardType && memberFiltersActive && !liveFiltersActive) {
      return false;
    }
    return true;
  }

  return !filters.cardType && !memberFiltersActive && !liveFiltersActive
    ? true
    : filters.cardType === "energy";
}

function matchesNumericRange(
  value: number | null,
  min?: number,
  max?: number,
): boolean {
  if (min === undefined && max === undefined) {
    return true;
  }
  if (value === null) {
    return false;
  }
  if (min !== undefined && value < min) {
    return false;
  }
  if (max !== undefined && value > max) {
    return false;
  }
  return true;
}

function additionError(
  section: "main_deck" | "energy_deck",
  cardType: "member" | "live" | "energy",
  currentTotal: number,
  currentQuantity: number,
  delta: number,
  locale: UiLocale,
  memberCount: number,
  liveCount: number,
): string | null {
  if (cardType !== "energy" && currentQuantity + delta > MAX_COPIES_PER_CARD) {
    return tr(
      locale,
      `同一卡最多只能加入 ${MAX_COPIES_PER_CARD} 张。`,
      `同じカードは最大 ${MAX_COPIES_PER_CARD} 枚までです。`,
    );
  }
  const totalLimit = section === "main_deck" ? MAIN_DECK_LIMIT : ENERGY_DECK_LIMIT;
  if (currentTotal + delta > totalLimit) {
    return tr(
      locale,
      section === "main_deck"
        ? `主牌组最多只能放入 ${MAIN_DECK_LIMIT} 张。`
        : `能量组最多只能放入 ${ENERGY_DECK_LIMIT} 张。`,
      section === "main_deck"
        ? `メインデッキは最大 ${MAIN_DECK_LIMIT} 枚までです。`
        : `エネルギーデッキは最大 ${ENERGY_DECK_LIMIT} 枚までです。`,
    );
  }
  if (section === "main_deck" && cardType === "member" && memberCount + delta > MAIN_DECK_MEMBER_TARGET) {
    return tr(
      locale,
      `角色卡最多只能放入 ${MAIN_DECK_MEMBER_TARGET} 张。`,
      `メンバーは最大 ${MAIN_DECK_MEMBER_TARGET} 枚までです。`,
    );
  }
  if (section === "main_deck" && cardType === "live" && liveCount + delta > MAIN_DECK_LIVE_TARGET) {
    return tr(
      locale,
      `Live 卡最多只能放入 ${MAIN_DECK_LIVE_TARGET} 张。`,
      `ライブは最大 ${MAIN_DECK_LIVE_TARGET} 枚までです。`,
    );
  }
  return null;
}

function resolveDeckTypeCounts(
  entries: DeckEntry[],
  summaryCache: Record<string, CatalogCardSummary>,
  detailCache: Record<string, CatalogCardDetail>,
): Record<"member" | "live", number> {
  let member = 0;
  let live = 0;
  for (const entry of entries) {
    const cardType = cardTypeForDeckEntry(entry.card_code, summaryCache, detailCache, null);
    if (cardType === "member") member += entry.quantity;
    if (cardType === "live") live += entry.quantity;
  }
  return { member, live };
}

function cardTypeForDeckEntry(
  cardCode: string,
  summaryCache: Record<string, CatalogCardSummary>,
  detailCache: Record<string, CatalogCardDetail>,
  fallback: "member" | "live" | "energy" | null,
): "member" | "live" | "energy" {
  return detailForCardCode(cardCode, detailCache)?.card.card_type
    ?? summaryCache[cardCode]?.card_type
    ?? fallback
    ?? "member";
}

function detailForCardCode(
  cardCode: string,
  detailCache: Record<string, CatalogCardDetail>,
): CatalogCardDetail | null {
  const detail = detailCache[cardCode];
  return detail?.card.card_code === cardCode ? detail : null;
}

function catalogRowKey(card: CatalogCardSummary): string {
  if (card.card_type === "energy") {
    return `energy:${card.card_id ?? card.card_code}`;
  }
  return `${card.card_type}:${card.card_code}`;
}

function aggregateDeckCatalogCards(cards: CatalogCardSummary[]): CatalogCardSummary[] {
  const rows: CatalogCardSummary[] = [];
  const seenRuleCards = new Set<string>();
  for (const card of cards) {
    if (card.card_type === "energy") {
      rows.push(card);
      continue;
    }
    const key = `${card.card_type}:${card.card_code}`;
    if (seenRuleCards.has(key)) {
      continue;
    }
    seenRuleCards.add(key);
    rows.push(card);
  }
  return rows;
}

function sortDeckCatalogCards(
  cards: CatalogCardSummary[],
  sortKey: DeckSearchSortKey,
  sortDirection: SortDirection,
  deck: DeckList,
): CatalogCardSummary[] {
  if (sortKey === "default") {
    return cards;
  }
  const direction = sortDirection === "asc" ? 1 : -1;
  const indexed = cards.map((card, index) => ({ card, index }));
  indexed.sort((left, right) => {
    const value = compareDeckCatalogCards(left.card, right.card, sortKey, direction, deck);
    if (value !== 0) return value;
    return left.index - right.index;
  });
  return indexed.map((item) => item.card);
}

function compareDeckCatalogCards(
  left: CatalogCardSummary,
  right: CatalogCardSummary,
  sortKey: DeckSearchSortKey,
  direction: number,
  deck: DeckList,
): number {
  if (sortKey === "card_code") {
    return direction * compareText(left.card_code, right.card_code);
  }
  if (sortKey === "name") {
    return direction * compareText(left.name_ja, right.name_ja);
  }
  if (sortKey === "type") {
    const typeOrder: Record<string, number> = { member: 0, live: 1, energy: 2 };
    return direction * compareNumbers(typeOrder[left.card_type] ?? 99, typeOrder[right.card_type] ?? 99);
  }
  if (sortKey === "cost") {
    return compareOptionalNumbers(left.cost, right.cost, direction);
  }
  if (sortKey === "blade") {
    return compareOptionalNumbers(left.blade, right.blade, direction);
  }
  if (sortKey === "required_heart") {
    return compareOptionalNumbers(
      left.card_type === "live" ? left.required_heart_total : null,
      right.card_type === "live" ? right.required_heart_total : null,
      direction,
    );
  }
  if (sortKey === "score") {
    return compareOptionalNumbers(left.score, right.score, direction);
  }
  if (sortKey === "deck_quantity") {
    return direction * compareNumbers(deckQuantity(left, deck), deckQuantity(right, deck));
  }
  return 0;
}

function deckQuantity(card: CatalogCardSummary, deck: DeckList): number {
  return currentEntryQuantity(
    card.card_type === "energy" ? deck.energy_deck : deck.main_deck,
    card.card_code,
  );
}

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "ja");
}

function compareNumbers(left: number, right: number): number {
  return left === right ? 0 : left < right ? -1 : 1;
}

function compareOptionalNumbers(
  left: number | null,
  right: number | null,
  direction: number,
): number {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return direction * compareNumbers(left, right);
}

function filterDeckEntriesByType(
  entries: DeckEntry[],
  summaryCache: Record<string, CatalogCardSummary>,
  detailCache: Record<string, CatalogCardDetail>,
  cardType: "member" | "live",
): DeckEntry[] {
  return entries.filter(
    (entry) => cardTypeForDeckEntry(entry.card_code, summaryCache, detailCache, null) === cardType,
  );
}

function mergeEntry(
  entries: DeckEntry[],
  incoming: DeckEntry,
  cardType: "member" | "live" | "energy",
): DeckEntry[] {
  const existing = entries.find((entry) => entry.card_code === incoming.card_code);
  if (!existing) {
    return [...entries, incoming];
  }
  const maxQuantity = cardType === "energy" ? ENERGY_DECK_LIMIT : MAX_COPIES_PER_CARD;
  return entries.map((entry) =>
    entry.card_code === incoming.card_code
      ? {
          ...entry,
          quantity: Math.min(maxQuantity, entry.quantity + incoming.quantity),
          preferred_printing_id: incoming.preferred_printing_id ?? entry.preferred_printing_id,
        }
      : entry,
  );
}

function normalizeImportedEntries(entries: unknown): DeckEntry[] {
  if (!Array.isArray(entries)) {
    return [];
  }
  return entries.flatMap((entry): DeckEntry[] => {
    if (!entry || typeof entry !== "object") {
      return [];
    }
    const record = entry as Record<string, unknown>;
    if (typeof record.card_code !== "string") {
      return [];
    }
    const quantity = Number(record.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) {
      return [];
    }
    return [
      {
        card_code: record.card_code,
        quantity,
        preferred_printing_id:
          typeof record.preferred_printing_id === "string"
            ? record.preferred_printing_id
            : null,
      },
    ];
  });
}

function slugifyDeckFilename(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}._-]+/gu, "-")
    .replace(/^[-._]+|[-._]+$/g, "") || "loveca-deck";
}

function sumDeck(entries: DeckEntry[]): number {
  return entries.reduce((sum, entry) => sum + entry.quantity, 0);
}

function formatMetricMap(values: Record<string, number>): string {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) {
    return "-";
  }
  return entries.map(([key, value]) => `${key} ${value}`).join(" / ");
}

function formatDistributionKey(locale: UiLocale, key: string): string {
  if (key === "null") {
    return tr(locale, "不明", "不明");
  }
  return key;
}

function formatEffectTimingSummary(
  locale: UiLocale,
  values: Record<string, number>,
): string {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([key, value]) => `${effectTriggerLabel(locale, key)} ${value}`)
    .join(" / ");
}

function formatEffectExecutionSummary(
  locale: UiLocale,
  values: Record<string, number>,
): string {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([key, value]) => `${effectExecutionModeLabel(locale, key)} ${value}`)
    .join(" / ");
}

function formatColorValueMap(
  locale: UiLocale,
  values: Record<string, number>,
): string {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([key, value]) => `${heartColorLabel(locale, key)} ${value}`)
    .join(" / ");
}

function summarizeCatalogCard(
  locale: UiLocale,
  card: CatalogCardSummary,
): string[] {
  if (card.card_type === "member") {
    const summary = [
      card.cost !== null ? `Cost ${card.cost}` : null,
      card.blade !== null ? `${tr(locale, "应援棒", "ブレード")} ${card.blade}` : null,
      card.basic_heart_total > 0
        ? `${tr(locale, "基本 Heart", "基本ハート")} ${formatColorValueMap(locale, card.basic_heart_by_color)}`
        : null,
      card.member_blade_heart_color_slot
        ? `${tr(locale, "应援 Heart", "ブレードハート")} ${heartColorLabel(locale, card.member_blade_heart_color_slot)}`
        : null,
    ];
    return summary.filter((item): item is string => Boolean(item));
  }
  if (card.card_type === "live") {
    const summary = [
      card.score !== null ? `Score ${card.score}` : null,
      card.required_heart_total > 0
        ? `${tr(locale, "所需 Heart", "必要ハート")} ${formatColorValueMap(locale, card.required_heart_by_color)}`
        : null,
      card.live_blade_heart_color_slot
        ? `${tr(locale, "应援 Heart", "ブレードハート")} ${heartColorLabel(locale, card.live_blade_heart_color_slot)}`
        : null,
      card.has_live_blade_heart && !card.live_blade_heart_color_slot
        ? tr(locale, "有应援 Heart", "ブレードハートあり")
        : null,
    ];
    return summary.filter((item): item is string => Boolean(item));
  }
  return [tr(locale, "1 张 = 1 能量", "1枚 = 1エネルギー")];
}

function formatCardType(locale: UiLocale, cardType: string): string {
  if (cardType === "member") return tr(locale, "角色卡", "メンバー");
  if (cardType === "live") return tr(locale, "Live 卡", "ライブ");
  if (cardType === "energy") return tr(locale, "能量卡", "エネルギー");
  return cardType;
}

function LanguageToggle({
  locale,
  setLocale,
}: {
  locale: UiLocale;
  setLocale: (locale: UiLocale) => void;
}) {
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

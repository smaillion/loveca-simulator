import {
  Activity,
  ArrowLeft,
  BookOpen,
  ClipboardList,
  Expand,
  LoaderCircle,
  Minus,
  Plus,
  Save,
  Search,
  Trash2,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
  const [facets, setFacets] = useState<CatalogFacetsResponse>({ works: [], units: [] });
  const [cards, setCards] = useState<CatalogCardSummary[]>([]);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogPage, setCatalogPage] = useState(0);
  const [summaryCache, setSummaryCache] = useState<Record<string, CatalogCardSummary>>({});
  const [detailCache, setDetailCache] = useState<Record<string, CatalogCardDetail>>({});
  const [selectedCardCode, setSelectedCardCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogCardDetail | null>(null);
  const [savedDecks, setSavedDecks] = useState<SavedDeckSummary[]>([]);
  const [selectedDeckId, setSelectedDeckId] = useState<string | null>(null);
  const [deck, setDeck] = useState<DeckList>(EMPTY_DECK);
  const [deckName, setDeckName] = useState("");
  const [loadingCards, setLoadingCards] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingDecks, setLoadingDecks] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<DeckAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const visibleCards = useMemo(
    () =>
      cards.filter((card) =>
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
      ),
    [
      basicHeartColor,
      cardType,
      cards,
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
    ],
  );
  const selectedSummary = useMemo(
    () => visibleCards.find((card) => card.card_code === selectedCardCode) ?? null,
    [visibleCards, selectedCardCode],
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
        setSelectedCardCode((current) =>
          current && response.items.some((item) => item.card_code === current)
            ? current
            : response.items[0]?.card_code ?? null,
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
    setSelectedCardCode((current) =>
      current && visibleCards.some((card) => card.card_code === current)
        ? current
        : visibleCards[0]?.card_code ?? null,
    );
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
    setLoadingDetail(true);
    getCatalogCard(selectedCardCode)
      .then((response) => {
        if (!active) return;
        setDetailCache((current) => ({ ...current, [selectedCardCode]: response }));
        setDetail(response);
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingDetail(false);
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

  const analyzedEnergyCount = analysis?.card_type_counts.energy_deck?.energy ?? energyCount;
  const selectedPrintingForDetail =
    detail?.printings.find((printing) => printing.card_id === selectedSummary?.card_id)
    ?? detail?.printings[0]
    ?? null;
  const selectedCardImageId = selectedPrintingForDetail?.card_id ?? selectedSummary?.card_id ?? null;
  const selectedCardImageUrl = selectedPrintingForDetail?.image_url ?? selectedSummary?.image_url ?? null;

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
          <div className="deck-counts">
            <span>{tr(locale, `主牌组 ${mainCount}`, `メイン ${mainCount}`)}</span>
            <span>{tr(locale, `能量组 ${energyCount}`, `エネルギー ${energyCount}`)}</span>
            <span>{tr(locale, `${totalCount} 总数`, `${totalCount} 合計`)}</span>
          </div>
          <div className="deck-sections">
            <DeckSection
              locale={locale}
              title={tr(locale, "主牌组", "メインデッキ")}
              entries={deck.main_deck}
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
              title={tr(locale, "能量组", "エネルギーデッキ")}
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
            />
          </div>
          <section className="deck-analysis-panel">
            <div className="section-heading compact-heading">
              <Activity size={18} />
              <div>
                <h2>{tr(locale, "当前牌组分析", "現在のデッキ分析")}</h2>
                <p>{tr(locale, "使用本地 Deck Analyzer 自动刷新。", "ローカル Deck Analyzer で自動更新します。")}</p>
              </div>
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
                <div className={`deck-analysis-status ${analysis.is_legal ? "legal" : "illegal"}`}>
                  {analysis.is_legal
                    ? tr(locale, "当前牌组合法", "現在のデッキは合法です")
                    : tr(locale, "当前牌组不合法", "現在のデッキは不正です")}
                </div>
                <div className="deck-analysis-stats">
                  <span>{tr(locale, `主牌组 ${mainCount} / ${MAIN_DECK_LIMIT}`, `メイン ${mainCount} / ${MAIN_DECK_LIMIT}`)}</span>
                  <span>{tr(locale, `Member ${memberCount} / ${MAIN_DECK_MEMBER_TARGET}`, `メンバー ${memberCount} / ${MAIN_DECK_MEMBER_TARGET}`)}</span>
                  <span>{tr(locale, `Live ${liveCount} / ${MAIN_DECK_LIVE_TARGET}`, `ライブ ${liveCount} / ${MAIN_DECK_LIVE_TARGET}`)}</span>
                  <span>{tr(locale, `能量组 ${analyzedEnergyCount} / ${ENERGY_DECK_LIMIT}`, `エネルギー ${analyzedEnergyCount} / ${ENERGY_DECK_LIMIT}`)}</span>
                  <span>{tr(locale, `问题 ${analysis.issues.length}`, `問題 ${analysis.issues.length}`)}</span>
                </div>
                <div className="deck-analysis-summary">
                  <strong>{tr(locale, "Member cost curve", "メンバーコスト分布")}</strong>
                  <span>{formatMetricMap(analysis.member_cost_curve)}</span>
                </div>
                <div className="deck-analysis-summary">
                  <strong>{tr(locale, "基本 Heart", "基本ハート")}</strong>
                  <span>{formatMetricMap(analysis.member_basic_heart_distribution)}</span>
                </div>
                <div className="deck-analysis-summary">
                  <strong>{tr(locale, "所需 Heart", "必要ハート")}</strong>
                  <span>{formatMetricMap(analysis.live_required_heart_distribution)}</span>
                </div>
                <div className="deck-analysis-summary">
                  <strong>{tr(locale, "Live score", "ライブスコア")}</strong>
                  <span>{formatMetricMap(analysis.live_score_distribution)}</span>
                </div>
                <div className="deck-analysis-summary">
                  <strong>{tr(locale, "Special Blade Heart", "特殊ブレードハート")}</strong>
                  <span>{formatMetricMap(analysis.special_blade_heart_summary)}</span>
                </div>
                <div className="deck-analysis-issues">
                  <strong>{tr(locale, "Issues", "問題一覧")}</strong>
                  {analysis.issues.length === 0 ? (
                    <div className="empty-state">{tr(locale, "无", "なし")}</div>
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
                key={card.card_id ?? card.card_code}
                className={`catalog-row ${selectedCardCode === card.card_code ? "selected" : ""}`}
              >
                <button
                  className="catalog-row-main"
                  type="button"
                  onClick={() => setSelectedCardCode(card.card_code)}
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
                      setSelectedCardCode(card.card_code);
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
          <div className="catalog-detail-mini">
            {loadingDetail && (
              <div className="catalog-loading">
                <LoaderCircle size={16} className="spin" />
                {tr(locale, "加载卡详情中", "カード詳細を読み込み中")}
              </div>
            )}
            {detail && (
              <>
                <button
                  className="catalog-detail-preview"
                  type="button"
                  onClick={() => setPreviewOpen(true)}
                >
                  <DeckThumbnail
                    locale={locale}
                    localCardId={selectedCardImageId}
                    remoteImageUrl={selectedCardImageUrl}
                    alt={detail.card.name_ja}
                    className="catalog-detail-thumbnail"
                  />
                  <span>{tr(locale, "点击放大预览", "クリックで拡大表示")}</span>
                </button>
                <strong>{detail.card.name_ja}</strong>
                <span>{detail.card.card_code}</span>
                <p>{detail.text_revisions[0]?.raw_effect_text_ja ?? tr(locale, "无文本", "テキストなし")}</p>
                {detail.printings.length > 0 && (
                  <div className="catalog-printing-select">
                    <label>
                      {tr(locale, "印刷版本", "印刷版")}
                      <select
                        value={selectedSummary?.card_id ?? detail.printings[0].card_id}
                        onChange={(event) => {
                          const printingId = event.target.value;
                          if (!selectedSummary) return;
                          const section = selectedSummary.card_type === "energy" ? "energy_deck" : "main_deck";
                          const current = deck[section].find((entry) => entry.card_code === selectedSummary.card_code);
                          if (!current) return;
                          updatePreferredPrinting(section, selectedSummary.card_code, printingId);
                        }}
                      >
                        {detail.printings.map((printing) => (
                          <option key={printing.card_id} value={printing.card_id}>
                            {printing.card_id}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}
              </>
            )}
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
}) {
  return (
    <section className="deck-section">
      <h3>{title}</h3>
      {entries.length === 0 && <div className="empty-state">{tr(locale, "空", "空")}</div>}
      <div className="deck-entry-list">
        {entries.map((entry) => {
          const detail = detailCache[entry.card_code] ?? null;
          const summary = summaryCache[entry.card_code] ?? null;
          const printings = detail?.printings ?? [];
          const selectedPrinting =
            printings.find((item) => item.card_id === entry.preferred_printing_id) ??
            printings[0] ??
            null;
          const imageCardId = selectedPrinting?.card_id ?? summary?.card_id ?? null;
          const imageUrl = selectedPrinting?.image_url ?? summary?.image_url ?? null;
          const cardType = detail?.card.card_type ?? summary?.card_type ?? "member";
          return (
            <button
              key={entry.card_code}
              className={`deck-entry ${selectedCardCode === entry.card_code ? "selected" : ""}`}
              onClick={() => onSelectCard(entry.card_code)}
              type="button"
            >
              <DeckThumbnail
                locale={locale}
                localCardId={imageCardId}
                remoteImageUrl={imageUrl}
                alt={detail?.card.name_ja ?? summary?.name_ja ?? entry.card_code}
              />
              <div className="deck-entry-body">
                <div className="deck-entry-head">
                  <div className="deck-entry-title">
                    <strong>{detail?.card.name_ja ?? summary?.name_ja ?? entry.card_code}</strong>
                    <small>{entry.card_code}</small>
                  </div>
                  <span className="deck-entry-quantity">x{entry.quantity}</span>
                </div>
                <div className="deck-entry-meta">
                  <span>{formatCardType(locale, cardType)}</span>
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
            </button>
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
  const selectedPrinting =
    detail.printings.find((printing) => printing.card_id === summary?.card_id)
    ?? detail.printings[0]
    ?? null;
  const text = detail.text_revisions[0]?.raw_effect_text_ja ?? tr(locale, "无文本", "テキストなし");
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
          <p className="effect-text">
            {selectedPrinting?.card_id ?? "-"}
            {selectedPrinting?.rarity_ja ? ` · ${selectedPrinting.rarity_ja}` : ""}
          </p>
          <h3>{tr(locale, "官方日文效果", "公式日本語テキスト")}</h3>
          <p className="effect-text">{text}</p>
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
  return detailCache[cardCode]?.card.card_type
    ?? summaryCache[cardCode]?.card_type
    ?? fallback
    ?? "member";
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

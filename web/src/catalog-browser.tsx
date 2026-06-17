import {
  ArrowLeft,
  BadgeInfo,
  Filter,
  LoaderCircle,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getCatalogCard,
  listCatalogCards,
  listCatalogFacets,
  listCatalogReviewCandidates,
} from "./api";
import { formatEffectText } from "./text-format";
import type {
  CatalogCardDetail,
  CatalogFacetsResponse,
  CatalogCardSummary,
  CatalogReviewCandidate,
} from "./types";

type UiLocale = "zh" | "ja";

const HEART_LABELS: Record<UiLocale, Record<string, string>> = {
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

function tr(locale: UiLocale, zh: string, ja: string): string {
  return locale === "zh" ? zh : ja;
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function formatHeartMap(
  value: Record<string, number> | Record<string, Record<string, number>> | null,
  locale: UiLocale,
): string {
  if (!value || typeof value !== "object") {
    return tr(locale, "无", "なし");
  }
  const parts: string[] = [];
  for (const [key, amount] of Object.entries(value)) {
    if (amount && typeof amount === "object") {
      const nested = Object.entries(amount)
        .filter(([, count]) => typeof count === "number" && count > 0)
        .map(([nestedKey, count]) => `${HEART_LABELS[locale][nestedKey] ?? nestedKey} ${count}`);
      if (nested.length > 0) {
        parts.push(`${HEART_LABELS[locale][key] ?? key}: ${nested.join(" / ")}`);
      }
      continue;
    }
    if (typeof amount === "number" && amount > 0) {
      parts.push(`${HEART_LABELS[locale][key] ?? key} ${amount}`);
    }
  }
  return parts.length > 0 ? parts.join(" / ") : tr(locale, "无", "なし");
}

function CatalogDetailImage({
  localCardId,
  remoteImageUrl,
  alt,
  locale,
}: {
  localCardId: string | null;
  remoteImageUrl: string | null;
  alt: string;
  locale: UiLocale;
}) {
  const [sourceMode, setSourceMode] = useState<"local" | "remote" | "placeholder">(
    localCardId ? "local" : remoteImageUrl ? "remote" : "placeholder",
  );

  useEffect(() => {
    setSourceMode(localCardId ? "local" : remoteImageUrl ? "remote" : "placeholder");
  }, [localCardId, remoteImageUrl]);

  if (sourceMode === "placeholder") {
    return (
      <div className="catalog-card-image placeholder">
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
      className="catalog-card-image"
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

export function CatalogBrowser({
  locale,
  onBack,
  setLocale,
}: {
  locale: UiLocale;
  onBack: () => void;
  setLocale: (locale: UiLocale) => void;
}) {
  const [query, setQuery] = useState("");
  const [cardType, setCardType] = useState<"" | "member" | "live" | "energy">("");
  const [workKey, setWorkKey] = useState("");
  const [unitKey, setUnitKey] = useState("");
  const [facets, setFacets] = useState<CatalogFacetsResponse>({ works: [], units: [] });
  const [reviewOnly, setReviewOnly] = useState(false);
  const [cards, setCards] = useState<CatalogCardSummary[]>([]);
  const [reviewCandidates, setReviewCandidates] = useState<CatalogReviewCandidate[]>([]);
  const [totalCards, setTotalCards] = useState(0);
  const [selectedCatalogKey, setSelectedCatalogKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogCardDetail | null>(null);
  const [loadingCards, setLoadingCards] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingReview, setLoadingReview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [offset, setOffset] = useState(0);
  const pageSize = 100;

  const selectedSummary = useMemo(
    () => cards.find((card) => catalogRowKey(card) === selectedCatalogKey) ?? null,
    [cards, selectedCatalogKey],
  );
  const selectedCardCode = selectedSummary?.card_code ?? null;
  const pageStart = totalCards === 0 ? 0 : offset + 1;
  const pageEnd = totalCards === 0 ? 0 : Math.min(offset + pageSize, totalCards);

  function selectCatalogEntryByCardCode(cardCode: string): void {
    const match = cards.find((card) => card.card_code === cardCode);
    if (!match) {
      return;
    }
    setSelectedCatalogKey(catalogRowKey(match));
  }

  useEffect(() => {
    let active = true;
    setLoadingCards(true);
    setError(null);
    listCatalogCards({
      q: query || undefined,
      cardType: cardType || undefined,
      workKey: workKey || undefined,
      unitKey: unitKey || undefined,
      reviewOnly,
      limit: pageSize,
      offset,
    })
      .then((response) => {
        if (!active) return;
        setCards(response.items);
        setTotalCards(response.total);
        setSelectedCatalogKey((current) =>
          current && response.items.some((item) => catalogRowKey(item) === current)
            ? current
            : response.items[0] ? catalogRowKey(response.items[0]) : null,
        );
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingCards(false);
      });
    return () => {
      active = false;
    };
  }, [cardType, offset, query, reloadToken, reviewOnly, unitKey, workKey]);

  useEffect(() => {
    let active = true;
    listCatalogFacets()
      .then((response) => {
        if (!active) return;
        setFacets(response);
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoadingReview(true);
    listCatalogReviewCandidates({ limit: 100 }).then((response) => {
      if (!active) return;
      setReviewCandidates(response.items);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (active) setLoadingReview(false);
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
    let active = true;
    setLoadingDetail(true);
    getCatalogCard(selectedCardCode)
      .then((response) => {
        if (!active) return;
        setDetail(response);
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingDetail(false);
      });
    return () => {
      active = false;
    };
  }, [selectedCardCode]);

  return (
    <div className="catalog-shell">
      <header className="topbar catalog-topbar">
        <div className="brand-lockup">
          <BadgeInfo size={22} />
          <div>
            <strong>{tr(locale, "全卡浏览与人工审核", "全カード閲覧と手動レビュー")}</strong>
            <span>{tr(locale, "只读 catalog 视图", "読み取り専用のカタログ画面")}</span>
          </div>
        </div>
        <div className="phase-status">
          <span className="turn-number">
            {tr(locale, "卡库浏览", "カードブラウズ")}
          </span>
          <span className="phase-cn">
            {tr(locale, `${totalCards} 张卡`, `${totalCards}枚`)}
          </span>
          <span>
            {tr(
              locale,
              `${reviewCandidates.length} 条待审候选`,
              `${reviewCandidates.length}件のレビュー候補`,
            )}
          </span>
        </div>
        <div className="top-actions">
          <LanguageToggle locale={locale} setLocale={setLocale} />
          <button className="icon-button" onClick={onBack} title={tr(locale, "返回", "戻る")}>
            <ArrowLeft size={18} />
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className="catalog-workspace">
        <section className="catalog-sidebar">
          <div className="catalog-toolbar">
            <label className="catalog-search">
              <Search size={16} />
              <input
                value={query}
                onChange={(event) => {
                  setOffset(0);
                  setQuery(event.target.value);
                }}
                placeholder={tr(locale, "搜索卡名、卡号、套装", "カード名・カード番号・セットを検索")}
              />
            </label>
            <button
              className={`toggle-pill ${reviewOnly ? "active" : ""}`}
              onClick={() => {
                setOffset(0);
                setReviewOnly((value) => !value);
              }}
            >
              <ShieldAlert size={16} />
              {tr(locale, "仅待审", "レビューのみ")}
            </button>
          </div>
          <div className="catalog-filter-row">
            {(["", "member", "live", "energy"] as const).map((value) => (
              <button
                className={`filter-chip ${cardType === value ? "active" : ""}`}
                key={value || "all"}
                onClick={() => {
                  setOffset(0);
                  setCardType(value);
                }}
              >
                <Filter size={14} />
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
              <select
                value={workKey}
                onChange={(event) => {
                  setOffset(0);
                  setWorkKey(event.target.value);
                }}
              >
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
              <select
                value={unitKey}
                onChange={(event) => {
                  setOffset(0);
                  setUnitKey(event.target.value);
                }}
              >
                <option value="">{tr(locale, "全部组合", "すべてのユニット")}</option>
                {facets.units.map((item) => (
                  <option key={item.unit_key} value={item.unit_key}>
                    {item.canonical_name_ja}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="catalog-meta">
            <span>{loadingCards ? tr(locale, "加载中", "読み込み中") : tr(locale, "已加载", "読み込み済み")}</span>
            <button className="mini-link" onClick={() => setReloadToken((value) => value + 1)}>
              {tr(locale, "刷新", "更新")}
            </button>
          </div>
          <div className="catalog-pagebar">
            <button
              className="mini-link"
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - pageSize))}
            >
              {tr(locale, "上一页", "前へ")}
            </button>
            <span>
              {tr(
                locale,
                `${pageStart}-${pageEnd} / ${totalCards}`,
                `${pageStart}-${pageEnd} / ${totalCards}`,
              )}
            </span>
            <button
              className="mini-link"
              disabled={offset + pageSize >= totalCards}
              onClick={() => setOffset((value) => value + pageSize)}
            >
              {tr(locale, "下一页", "次へ")}
            </button>
          </div>
          <div className="catalog-list">
            {cards.map((card) => (
              <button
                key={catalogRowKey(card)}
                className={`catalog-row ${selectedCatalogKey === catalogRowKey(card) ? "selected" : ""}`}
                onClick={() => setSelectedCatalogKey(catalogRowKey(card))}
              >
                <span className="catalog-row-top">
                  <strong>{card.name_ja}</strong>
                  <small>{card.card_id ?? card.card_code}</small>
                </span>
                <span className="catalog-row-bottom">
                  <span>{card.card_type.toUpperCase()}</span>
                  <span>{card.card_set_code ?? "-"}</span>
                  <span>{card.rarity_ja ?? "-"}</span>
                  <span>{card.card_code}</span>
                </span>
              </button>
            ))}
            {loadingCards && (
              <div className="catalog-loading">
                <LoaderCircle size={18} className="spin" />
                {tr(locale, "正在加载卡牌", "カードを読み込み中")}
              </div>
            )}
          </div>
        </section>

        <section className="catalog-detail">
          {loadingDetail && <div className="catalog-loading">...</div>}
          {!detail && !loadingDetail && (
            <div className="empty-state">
              {tr(locale, "选择一张卡牌查看详情。", "カードを選択すると詳細が表示されます。")}
            </div>
          )}
          {detail && (
            <>
              <header className="catalog-detail-header">
                <div>
                  <div className="catalog-detail-title">
                    <strong>{detail.card.name_ja}</strong>
                    <span>{detail.card.card_code}</span>
                  </div>
                  <div className="catalog-detail-subtitle">
                    <span>{detail.card.card_type.toUpperCase()}</span>
                    <span>{detail.card.validation_status}</span>
                    <span>{selectedSummary?.card_set_code ?? "-"}</span>
                    <span>{selectedSummary?.rarity_ja ?? "-"}</span>
                    {selectedSummary?.card_id && <span>{selectedSummary.card_id}</span>}
                  </div>
                </div>
                <div className="catalog-stat-grid">
                  <Stat label="Cost" value={detail.card.cost ?? "-"} />
                  <Stat label="Blade" value={detail.card.blade ?? "-"} />
                  <Stat label="Score" value={detail.card.score ?? "-"} />
                </div>
              </header>

              <div className="catalog-card-block">
                <CatalogDetailImage
                  localCardId={selectedSummary?.card_id ?? detail.printings[0]?.card_id ?? null}
                  remoteImageUrl={selectedSummary?.image_url ?? detail.printings[0]?.image_url ?? null}
                  alt={detail.card.name_ja}
                  locale={locale}
                />
                <div className="catalog-card-summary">
                  <section>
                    <h3>{tr(locale, "Heart", "ハート")}</h3>
                    <p>{formatHeartMap(detail.card.heart_values, locale)}</p>
                    <p>
                      {detail.card.special_blade_hearts.length > 0
                        ? detail.card.special_blade_hearts
                            .map((item) =>
                              `${item.source_alt}${item.value == null ? "" : ` ${item.value}`}`,
                            )
                            .join(" / ")
                        : tr(locale, "无特殊 Blade Heart", "特殊ブレードハートなし")}
                    </p>
                  </section>
                  <section>
                    <h3>{tr(locale, "作品 / 组合", "作品 / ユニット")} </h3>
                    <p>
                      {detail.card.works.map((item) => item.canonical_name_ja).join(" / ") ||
                        tr(locale, "无", "なし")}
                    </p>
                    <p>
                      {detail.card.units.map((item) => item.canonical_name_ja).join(" / ") ||
                        tr(locale, "无", "なし")}
                    </p>
                  </section>
                </div>
              </div>

              <section className="catalog-panel">
                <h3>{tr(locale, "技能", "スキル")}</h3>
                <pre>{formatEffectText(detail.text_revisions[0]?.raw_effect_text_ja ?? null, locale)}</pre>
              </section>

              <section className="catalog-panel catalog-review-panel">
                <div className="catalog-review-header">
                  <h3>{tr(locale, "人工审核", "手動レビュー")}</h3>
                  {loadingReview && <LoaderCircle size={16} className="spin" />}
                </div>
                <div className="catalog-review-list">
                  {reviewCandidates
                    .filter((item) => item.card_code === detail.card.card_code)
                    .map((item) => (
                      <button
                        key={item.candidate_id}
                        className="catalog-review-item"
                        onClick={() => selectCatalogEntryByCardCode(item.card_code)}
                      >
                        <strong>{item.entity_type}</strong>
                        <span>{item.raw_value_ja}</span>
                        <small>{item.review_status}</small>
                      </button>
                    ))}
                  {reviewCandidates.filter((item) => item.card_code === detail.card.card_code).length === 0 && (
                    <div className="empty-state">
                      {tr(locale, "这张卡没有待审候选。", "このカードにレビュー候補はありません。")}
                    </div>
                  )}
                </div>
              </section>

              <section className="catalog-panel">
                <h3>{tr(locale, "来源观测", "ソース観測")}</h3>
                <div className="catalog-observation-list">
                  {detail.source_observations.map((observation) => (
                    <details key={observation.source_observation_id}>
                      <summary>
                        {observation.card_id} · {observation.parser_version}
                      </summary>
                      <pre>
                        {formatJson({
                          raw_fields: observation.raw_fields,
                          parse_notes: observation.parse_notes,
                        })}
                      </pre>
                    </details>
                  ))}
                </div>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function catalogRowKey(card: CatalogCardSummary): string {
  return card.card_id ?? card.card_code;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="catalog-stat">
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
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

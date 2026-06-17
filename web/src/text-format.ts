export type UiLocale = "zh" | "ja";

export const HEART_LABELS: Record<UiLocale, Record<string, string>> = {
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

export function heartColorLabel(locale: UiLocale, value: string): string {
  return HEART_LABELS[locale][value] ?? value;
}

export function formatHeartSummary(
  hearts: Record<string, number>,
  locale: UiLocale = "zh",
): string {
  return Object.entries(hearts)
    .filter(([, amount]) => amount > 0)
    .map(([color, amount]) => `${heartColorLabel(locale, color)} ${amount}`)
    .join(" / ");
}

export function formatEffectText(
  rawText: string | null,
  locale: UiLocale = "zh",
): string {
  if (!rawText) return locale === "zh" ? "无文本" : "テキストなし";
  return rawText.replace(
    /heart0[1-6]|heart0/gi,
    (token) => heartColorLabel(locale, token.toLowerCase()),
  );
}

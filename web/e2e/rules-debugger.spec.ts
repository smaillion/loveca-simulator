import { expect, test } from "@playwright/test";

test("creates a match and shows the rules board", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("创建规则验证对局")).toBeVisible();
  await page.getByRole("button", { name: "创建对局" }).click();
  await expect(page.getByText("Legal Actions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Player 1 先攻" })).toBeVisible();
  await page.screenshot({ path: "test-results/rules-board-desktop.png", fullPage: true });
});

test("creation screen fits a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("创建规则验证对局")).toBeVisible();
  await expect(page.getByRole("button", { name: "创建对局" })).toBeVisible();
  await page.screenshot({ path: "test-results/start-mobile.png", fullPage: true });
});

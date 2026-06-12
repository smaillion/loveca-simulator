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

test("activates and resolves a reviewed card effect", async ({ page, request }) => {
  const created = await request.post("/api/matches", {
    data: {
      player_1: {
        name: "Effect Player",
        deck_path: "examples/decks/sample-deck.json",
      },
      player_2: {
        name: "Opponent",
        deck_path: "examples/decks/sample-deck.json",
      },
      seed: 310,
    },
  });
  let payload = await created.json();
  const matchId = payload.state.match_id as string;

  async function action(
    actionType: string,
    playerId: string | null,
    actionPayload: Record<string, unknown> = {},
  ) {
    const response = await request.post(`/api/matches/${matchId}/actions`, {
      data: {
        action_type: actionType,
        expected_revision: payload.state.revision,
        player_id: playerId,
        payload: actionPayload,
      },
    });
    expect(response.ok()).toBeTruthy();
    payload = await response.json();
  }

  await action("choose_first_player", null, { first_player_id: "player_1" });
  await action("submit_mulligan", "player_1", { card_instance_ids: [] });
  await action("submit_mulligan", "player_2", { card_instance_ids: [] });
  await action("advance_phase", "player_1");
  await action("advance_phase", "player_1");
  await action("advance_phase", "player_1");

  const sourceId = Object.values(payload.state.cards).find(
    (card: any) =>
      card.owner_id === "player_1" && card.card.card_code === "PL!-bp3-001",
  )?.instance_id;
  expect(sourceId).toBeTruthy();
  await action("manual_adjustment", "player_1", {
    reason: "Playwright effect setup",
    requires_confirmation: true,
    confirmed_by: "playwright",
    adjustments: [
      {
        adjustment_type: "move_card",
        target_player_id: "player_1",
        target_card_instance_id: sourceId,
        to_zone: "member_center",
      },
    ],
  });

  await page.goto("/");
  await page.getByText(matchId.slice(0, 8), { exact: false }).click();
  await expect(page.getByText("可发动技能")).toBeVisible();
  await page.locator(".effect-option").filter({ hasText: "高坂穂乃果" }).click();
  await expect(page.getByText("待结算技能")).toBeVisible();
  await page.screenshot({ path: "test-results/effect-resolution-desktop.png", fullPage: true });
  await page.locator(".effect-candidates button").first().click();
  await page.getByRole("button", { name: "结算技能" }).click();
  await expect(page.getByText("待结算技能")).not.toBeVisible();
});

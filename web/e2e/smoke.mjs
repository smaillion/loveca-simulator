import { chromium } from "@playwright/test";

const browser = await chromium.launch({ headless: true });
try {
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 1024 } });
  desktop.setDefaultTimeout(5000);

  async function clickAction(locator) {
    const revisionText = await desktop.locator(".revision").textContent();
    const revision = Number.parseInt(revisionText?.match(/\d+/)?.[0] ?? "", 10);
    if (!Number.isInteger(revision)) {
      throw new Error(`unable to read revision from ${revisionText}`);
    }
    await locator.click();
    await desktop.waitForFunction(
      (expected) => document.querySelector(".revision")?.textContent?.includes(expected),
      `rev ${revision + 1}`,
    );
  }

  console.log("open desktop");
  await desktop.goto("http://127.0.0.1:8765/");
  console.log("create");
  await desktop.getByRole("button", { name: "创建对局" }).click();
  console.log("choose first");
  await clickAction(desktop.getByRole("button", { name: "Player 1 先攻" }));
  console.log("mulligan first");
  await clickAction(desktop.getByRole("button", { name: /^确认 0$/ }));
  console.log("mulligan second");
  await clickAction(desktop.getByRole("button", { name: /^确认 0$/ }));

  for (let index = 0; index < 3; index += 1) {
    console.log(`first auto ${index}`);
    await clickAction(
      desktop.getByRole("button", { name: "执行并进入下一阶段" }),
    );
  }
  console.log("first main end");
  await clickAction(desktop.getByRole("button", { name: "结束主要阶段" }));
  for (let index = 0; index < 3; index += 1) {
    console.log(`second auto ${index}`);
    await clickAction(
      desktop.getByRole("button", { name: "执行并进入下一阶段" }),
    );
  }
  console.log("second main end");
  await clickAction(desktop.getByRole("button", { name: "结束主要阶段" }));
  console.log("first live set");
  await clickAction(desktop.getByRole("button", { name: /^确认 0 \/ 3$/ }));
  console.log("second live set");
  await clickAction(desktop.getByRole("button", { name: /^确认 0 \/ 3$/ }));
  console.log("first Live reveal");
  await clickAction(desktop.getByRole("button", { name: "先攻 Live 公开" }));
  await desktop.getByText("先攻应援").first().waitFor();
  await desktop.getByText("Live 判定明细").waitFor();
  console.log("first Yell");
  await clickAction(desktop.getByRole("button", { name: "执行先攻应援" }));
  console.log("second Live reveal");
  await clickAction(desktop.getByRole("button", { name: "后攻 Live 公开" }));
  console.log("second Yell");
  await clickAction(desktop.getByRole("button", { name: "执行后攻应援" }));
  console.log("Live judgment");
  await clickAction(desktop.getByRole("button", { name: "执行 Live 胜负判定" }));
  console.log("wait turn complete");
  await desktop.getByText("本回合判定完成").first().waitFor();
  await desktop.screenshot({
    path: "test-results/turn-complete-desktop.png",
    fullPage: true,
  });
  await clickAction(desktop.getByRole("button", { name: "开始下一回合" }));
  await desktop.getByText("第 2 回合").waitFor();
  await desktop.getByText("先攻活动阶段").first().waitFor();
  const desktopOverflow = await desktop.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  if (desktopOverflow.body > desktopOverflow.viewport + 1) {
    throw new Error(`desktop horizontal overflow: ${JSON.stringify(desktopOverflow)}`);
  }

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  mobile.setDefaultTimeout(5000);
  await mobile.route("**/api/card-images/**", (route) => route.abort());
  console.log("open mobile");
  await mobile.goto("http://127.0.0.1:8765/");
  await mobile.getByText("创建规则验证对局").waitFor();
  await mobile.getByRole("button", { name: "创建对局" }).waitFor();
  await mobile.screenshot({
    path: "test-results/start-mobile.png",
    fullPage: true,
  });

  const overflow = await mobile.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  if (overflow.body > overflow.viewport + 1) {
    throw new Error(`mobile horizontal overflow: ${JSON.stringify(overflow)}`);
  }
  console.log("resume second turn on mobile with image fallback");
  await mobile.locator(".match-row").filter({ hasText: "进行中" }).first().click();
  await mobile.getByText("第 2 回合").waitFor();
  await mobile.locator(".card-fallback").first().waitFor();
  await mobile.screenshot({
    path: "test-results/second-turn-mobile.png",
    fullPage: true,
  });
  const completedMobileOverflow = await mobile.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  if (completedMobileOverflow.body > completedMobileOverflow.viewport + 1) {
    throw new Error(
      `completed mobile horizontal overflow: ${JSON.stringify(completedMobileOverflow)}`,
    );
  }

  console.log("create completed match through replay-safe API actions");
  const completedMatchId = await createCompletedMatch();
  await desktop.goto("http://127.0.0.1:8765/");
  await desktop
    .locator(".match-row")
    .filter({ hasText: completedMatchId.slice(0, 8) })
    .click();
  await desktop.getByText("对局结束").first().waitFor();
  await desktop.getByText("最终胜者：Player 1").waitFor();
  await desktop.screenshot({
    path: "test-results/match-complete-desktop.png",
    fullPage: true,
  });

  console.log("verify consecutive Member placement uses an available area");
  const memberMatchId = await createMemberPlacementMatch();
  await desktop.goto("http://127.0.0.1:8765/");
  await desktop
    .locator(".match-row")
    .filter({ hasText: memberMatchId.slice(0, 8) })
    .click();
  await clickAction(desktop.getByRole("button", { name: "登场" }));
  await clickAction(desktop.getByRole("button", { name: "登场" }));
  const memberState = (await api(`/api/matches/${memberMatchId}`)).state;
  if (
    !memberState.players.player_1.member_area.center ||
    !memberState.players.player_1.member_area.left ||
    memberState.players.player_1.member_area.right
  ) {
    throw new Error(
      `unexpected Member placement: ${JSON.stringify(memberState.players.player_1.member_area)}`,
    );
  }

  console.log("verify Baton Touch on a full Member Area");
  const batonFixture = await createBatonTouchMatch();
  await desktop.goto("http://127.0.0.1:8765/");
  await desktop
    .locator(".match-row")
    .filter({ hasText: batonFixture.matchId.slice(0, 8) })
    .click();
  await desktop.locator(".member-play-action").waitFor();
  const displayedSlotOrder = await desktop
    .locator(".member-slot-choice")
    .evaluateAll((items) => items.map((item) => item.getAttribute("data-slot")));
  if (JSON.stringify(displayedSlotOrder) !== JSON.stringify(["left", "center", "right"])) {
    throw new Error(`unexpected Member slot order: ${JSON.stringify(displayedSlotOrder)}`);
  }
  await desktop
    .locator(`.member-choice-card[data-instance-id="${batonFixture.newMemberId}"] .card-tile`)
    .click();
  await desktop.locator('.member-slot-choice[data-slot="center"]').click();
  await desktop.locator('.member-play-modes button[data-mode="baton"]').click();
  await desktop.screenshot({
    path: "test-results/member-play-desktop.png",
    fullPage: true,
  });
  const paymentSummary = desktop.locator(".member-payment-summary");
  await paymentSummary.getByText("Baton 减免").waitFor();
  await paymentSummary.getByText("可用 Active").waitFor();
  await paymentSummary.getByText("Energy 总数").waitFor();
  await paymentSummary.getByText("实付 Energy").waitFor();
  const paymentValues = await paymentSummary.locator("dd").allTextContents();
  if (
    !paymentValues.includes(String(batonFixture.paymentCost)) ||
    !paymentValues.includes(String(batonFixture.activeEnergyCount))
  ) {
    throw new Error(`unexpected Energy summary: ${JSON.stringify(paymentValues)}`);
  }

  await mobile.goto("http://127.0.0.1:8765/");
  await mobile
    .locator(".match-row")
    .filter({ hasText: batonFixture.matchId.slice(0, 8) })
    .click();
  await mobile.locator(".member-play-action").waitFor();
  await mobile.screenshot({
    path: "test-results/member-play-mobile.png",
    fullPage: true,
  });
  const memberMobileOverflow = await mobile.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  if (memberMobileOverflow.body > memberMobileOverflow.viewport + 1) {
    throw new Error(
      `Member play mobile horizontal overflow: ${JSON.stringify(memberMobileOverflow)}`,
    );
  }

  await clickAction(desktop.locator(".member-payment-summary .primary-button"));
  const batonState = (await api(`/api/matches/${batonFixture.matchId}`)).state;
  if (
    batonState.players.player_1.member_area.center !== batonFixture.newMemberId ||
    !batonState.players.player_1.waiting_room.includes(batonFixture.oldMemberId)
  ) {
    throw new Error(
      `unexpected Baton Touch result: ${JSON.stringify(
        batonState.players.player_1.member_area,
      )}`,
    );
  }
  console.log(
    "Playwright smoke passed: next turn, final result, Member placement, Baton Touch, and mobile layout.",
  );
} finally {
  await Promise.race([
    browser.close(),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
}

async function createCompletedMatch() {
  const created = await api("/api/matches", {
    method: "POST",
    body: JSON.stringify({
      player_1: {
        name: "Player 1",
        deck_path: "examples/decks/sample-deck.json",
      },
      player_2: {
        name: "Player 2",
        deck_path: "examples/decks/sample-deck.json",
      },
      seed: 30303,
    }),
  });
  let state = created.state;
  async function act(actionType, playerId = null, payload = {}) {
    const result = await api(`/api/matches/${state.match_id}/actions`, {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        expected_revision: state.revision,
        player_id: playerId,
        payload,
      }),
    });
    state = result.state;
  }

  await act("choose_first_player", null, { first_player_id: "player_1" });
  await act("submit_mulligan", "player_1", { card_instance_ids: [] });
  await act("submit_mulligan", "player_2", { card_instance_ids: [] });
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_1");
  }

  const liveIds = state.players.player_1.main_deck.filter(
    (id) => state.cards[id].card.card_type === "live",
  );
  const targetLiveId = liveIds.find(
    (id) => Object.keys(state.cards[id].card.required_hearts).length > 0,
  );
  if (!targetLiveId || liveIds.length < 3) {
    throw new Error("fixture deck does not contain enough Live cards");
  }
  const preloadIds = liveIds.filter((id) => id !== targetLiveId).slice(0, 2);
  const adjustments = [
    ...preloadIds.map((id) => ({
      adjustment_type: "move_card",
      target_player_id: "player_1",
      target_card_instance_id: id,
      to_zone: "success_live_area",
    })),
    {
      adjustment_type: "move_card",
      target_player_id: "player_1",
      target_card_instance_id: targetLiveId,
      to_zone: "hand",
    },
    ...Object.keys(state.cards[targetLiveId].card.required_hearts).map((color) => ({
      adjustment_type: "modify_heart",
      target_player_id: "player_1",
      color_slot: color,
      amount: 20,
      duration: "live",
    })),
  ];
  await act("manual_adjustment", "player_1", {
    reason: "Playwright final result setup",
    adjustments,
  });
  await act("end_main_phase", "player_1");
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_2");
  }
  await act("end_main_phase", "player_2");
  await act("set_live_cards", "player_1", {
    card_instance_ids: [targetLiveId],
  });
  await act("set_live_cards", "player_2", { card_instance_ids: [] });
  await act("advance_phase", "player_1");
  await act("advance_phase", "player_1");
  if (state.pending_choice?.choice_type === "live_requirements") {
    await act("resolve_live_requirements", "player_1", {
      live_instance_ids: state.pending_choice.options.live_instance_ids,
    });
  }
  await act("advance_phase", "player_2");
  await act("advance_phase", "player_2");
  await act("advance_phase");
  if (state.phase !== "complete") {
    throw new Error(`expected complete match, got ${state.phase}`);
  }
  return state.match_id;
}

async function createMemberPlacementMatch() {
  const created = await api("/api/matches", {
    method: "POST",
    body: JSON.stringify({
      player_1: {
        name: "Member Test",
        deck_path: "examples/decks/sample-deck.json",
      },
      player_2: {
        name: "Opponent",
        deck_path: "examples/decks/sample-deck.json",
      },
      seed: 40404,
    }),
  });
  let state = created.state;
  async function act(actionType, playerId = null, payload = {}) {
    const result = await api(`/api/matches/${state.match_id}/actions`, {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        expected_revision: state.revision,
        player_id: playerId,
        payload,
      }),
    });
    state = result.state;
  }
  await act("choose_first_player", null, { first_player_id: "player_1" });
  await act("submit_mulligan", "player_1", { card_instance_ids: [] });
  await act("submit_mulligan", "player_2", { card_instance_ids: [] });
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_1");
  }
  const members = state.players.player_1.main_deck
    .filter((id) => state.cards[id].card.card_type === "member")
    .sort((left, right) => {
      const leftCost = state.cards[left].card.cost ?? 0;
      const rightCost = state.cards[right].card.cost ?? 0;
      return leftCost - rightCost;
    });
  let selected;
  let second;
  for (let firstIndex = 0; firstIndex < members.length && !second; firstIndex += 1) {
    const first = members[firstIndex];
    const candidate = members
      .slice(firstIndex + 1)
      .find(
        (item) =>
          (state.cards[first].card.cost ?? 0) +
            (state.cards[item].card.cost ?? 0) <=
          state.players.player_1.energy_area.length,
      );
    if (candidate) {
      selected = first;
      second = candidate;
    }
  }
  if (!selected || !second) {
    throw new Error("fixture deck does not contain two affordable Members");
  }
  await act("manual_adjustment", "player_1", {
    reason: "Playwright Member placement setup",
    adjustments: [selected, second].map((id) => ({
      adjustment_type: "move_card",
      target_player_id: "player_1",
      target_card_instance_id: id,
      to_zone: "hand",
    })),
  });
  return state.match_id;
}

async function createBatonTouchMatch() {
  const created = await api("/api/matches", {
    method: "POST",
    body: JSON.stringify({
      player_1: {
        name: "Baton Test",
        deck_path: "examples/decks/sample-deck.json",
      },
      player_2: {
        name: "Opponent",
        deck_path: "examples/decks/sample-deck.json",
      },
      seed: 50505,
    }),
  });
  let state = created.state;
  async function act(actionType, playerId = null, payload = {}) {
    const result = await api(`/api/matches/${state.match_id}/actions`, {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        expected_revision: state.revision,
        player_id: playerId,
        payload,
      }),
    });
    state = result.state;
  }
  await act("choose_first_player", null, { first_player_id: "player_1" });
  await act("submit_mulligan", "player_1", { card_instance_ids: [] });
  await act("submit_mulligan", "player_2", { card_instance_ids: [] });
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_1");
  }

  const members = state.players.player_1.main_deck
    .filter((id) => state.cards[id].card.card_type === "member")
    .sort(
      (left, right) =>
        (state.cards[left].card.cost ?? 0) - (state.cards[right].card.cost ?? 0),
    );
  let oldMemberId;
  let newMemberId;
  for (const oldId of members) {
    const candidate = [...members]
      .reverse()
      .find(
        (newId) =>
          newId !== oldId &&
          (state.cards[newId].card.cost ?? 0) >
            (state.cards[oldId].card.cost ?? 0) &&
          (state.cards[newId].card.cost ?? 0) -
            (state.cards[oldId].card.cost ?? 0) <=
            4,
      );
    if (candidate) {
      oldMemberId = oldId;
      newMemberId = candidate;
      break;
    }
  }
  const sideMembers = members
    .filter((id) => id !== oldMemberId && id !== newMemberId)
    .slice(0, 2);
  if (!oldMemberId || !newMemberId || sideMembers.length !== 2) {
    throw new Error("fixture deck does not contain a Baton Touch setup");
  }
  await act("manual_adjustment", "player_1", {
    reason: "Playwright full Member Area Baton Touch setup",
    adjustments: [
      {
        adjustment_type: "move_card",
        target_player_id: "player_1",
        target_card_instance_id: sideMembers[0],
        to_zone: "member_left",
      },
      {
        adjustment_type: "move_card",
        target_player_id: "player_1",
        target_card_instance_id: oldMemberId,
        to_zone: "member_center",
      },
      {
        adjustment_type: "move_card",
        target_player_id: "player_1",
        target_card_instance_id: sideMembers[1],
        to_zone: "member_right",
      },
      {
        adjustment_type: "move_card",
        target_player_id: "player_1",
        target_card_instance_id: newMemberId,
        to_zone: "hand",
      },
    ],
  });
  await act("end_main_phase", "player_1");
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_2");
  }
  await act("end_main_phase", "player_2");
  await act("set_live_cards", "player_1", { card_instance_ids: [] });
  await act("set_live_cards", "player_2", { card_instance_ids: [] });
  await act("advance_phase", "player_1");
  await act("advance_phase", "player_1");
  await act("advance_phase", "player_2");
  await act("advance_phase", "player_2");
  await act("advance_phase");
  await act("start_next_turn");
  for (let index = 0; index < 3; index += 1) {
    await act("advance_phase", "player_1");
  }
  return {
    matchId: state.match_id,
    oldMemberId,
    newMemberId,
    paymentCost:
      (state.cards[newMemberId].card.cost ?? 0) -
      (state.cards[oldMemberId].card.cost ?? 0),
    activeEnergyCount: state.players.player_1.energy_area.filter(
      (id) => state.cards[id].orientation === "active",
    ).length,
  };
}

async function api(path, init) {
  const response = await fetch(`http://127.0.0.1:8765${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

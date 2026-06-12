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
  console.log("wait complete");
  await desktop.getByText("首轮判定完成").first().waitFor();
  await desktop.screenshot({
    path: "test-results/first-live-complete-desktop.png",
    fullPage: true,
  });
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
  console.log("resume completed match on mobile with image fallback");
  await mobile.locator(".match-row").filter({ hasText: "已完成" }).first().click();
  await mobile.getByText("首轮判定完成").first().waitFor();
  await mobile.locator(".card-fallback").first().waitFor();
  await mobile.screenshot({
    path: "test-results/first-live-complete-mobile.png",
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
  console.log("Playwright smoke passed: full first-Live flow and mobile layout.");
} finally {
  await Promise.race([
    browser.close(),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
}

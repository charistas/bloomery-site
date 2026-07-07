const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const site = require("../site.config.json");

const viewports = [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 }
];

function routeFor(pageName) {
  return pageName === "index.html" ? "/" : `/${pageName}`;
}

function localRequestLabel(requestUrl) {
  const url = new URL(requestUrl);
  if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
    return null;
  }

  return `${url.pathname}${url.search}`;
}

async function gotoWithConsoleChecks(page, pageName) {
  const errors = [];
  const failedResources = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    const label = localRequestLabel(response.url());
    if (label && response.status() >= 400) {
      failedResources.push(`${response.status()} ${label}`);
    }
  });
  page.on("requestfailed", (request) => {
    const label = localRequestLabel(request.url());
    if (label) {
      failedResources.push(`${label}: ${request.failure()?.errorText || "request failed"}`);
    }
  });

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(routeFor(pageName), { waitUntil: "networkidle" });
  expect(errors, `console/page errors on ${pageName}`).toEqual([]);
  expect(failedResources, `failed local resources on ${pageName}`).toEqual([]);
}

for (const pageName of site.pages) {
  for (const viewport of viewports) {
    test(`${pageName} renders at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoWithConsoleChecks(page, pageName);

      await expect(page.locator("body")).toBeVisible();
      const overflow = await page.evaluate(() => (
        document.documentElement.scrollWidth - document.documentElement.clientWidth
      ));
      expect(overflow, `${pageName} should not horizontally overflow at ${viewport.name}`).toBeLessThanOrEqual(1);

      const screenshotDir = path.join("test-results", "screenshots");
      fs.mkdirSync(screenshotDir, { recursive: true });
      const screenshotPath = path.join(screenshotDir, `${pageName.replace(".", "-")}-${viewport.name}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true, animations: "disabled" });
      expect(fs.statSync(screenshotPath).size).toBeGreaterThan(20000);
    });
  }

  test(`${pageName} has no automated WCAG A/AA violations`, async ({ page }) => {
    await gotoWithConsoleChecks(page, pageName);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();

    expect(results.violations).toEqual([]);
  });
}

test("email placeholders and Buttondown forms are wired", async ({ page }) => {
  await gotoWithConsoleChecks(page, "index.html");
  for (const email of site.requiredMailtoLinks) {
    await expect(page.locator(`a[href="mailto:${email}"]`).first()).toBeVisible();
  }

  for (const action of site.allowedFormActions) {
    await expect(page.locator(`form[action="${action}"]`)).toHaveCount(2);
  }
});

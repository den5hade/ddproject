import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { readOtpCode, uniqueIdentity } from "./helpers/auth";

/*
 * Happy path (plan §7/M7):
 * login → dashboard → upload PDF → status visible → detail opens.
 * Includes an axe a11y scan and 320px overflow checks (SG §58, M7).
 */

const SAMPLE_PDF = Buffer.from(
  readFileSync(new URL("./fixtures/sample.pdf", import.meta.url)),
);

// Mobile-first flows (SG §42): bottom nav + action sheet
test.use({ viewport: { width: 390, height: 844 } });

test("client happy path: login → upload → detail", async ({ page }) => {
  test.setTimeout(120_000);
  const identity = uniqueIdentity();

  // ---- Login ----------------------------------------------------------
  await page.goto("/login");
  await page.getByLabel(/email|телефон/i).fill(identity);
  await page.getByRole("button", { name: "Получить код" }).click();

  await expect(page.getByText(/мы отправили код на/i)).toBeVisible();

  // OTP arrives via dev Redis
  const code = readOtpCode(identity);
  for (const [index, digit] of [...code].entries()) {
    await page.getByLabel(`Цифра ${index + 1} из 6`).fill(digit);
  }

  // Verify auto-submits on complete code → dashboard greets us
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
    timeout: 15_000,
  });

  // Bottom nav (mobile viewport default) — navigate to documents
  await page.getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name: "Документы" })
    .click();
  await expect(page).toHaveURL("/documents");

  // Empty state before first upload
  await expect(page.getByText(/пока нет документов/i)).toBeVisible();

  // ---- Upload via the mobile sheet ------------------------------------
  await page.getByRole("button", { name: "Добавить" }).first().click();
  await expect(page.getByRole("dialog", { name: "Добавить" })).toBeVisible();
  const fileInput = page.locator('input[type="file"]').nth(1); // [0]=photo capture, [1]=general
  await fileInput.setInputFiles({
    name: "e2e-blood-test.pdf",
    mimeType: "application/pdf",
    buffer: SAMPLE_PDF,
  });
  await page.keyboard.press("Escape"); // close the sheet over the list

  // Queued → appears in list with a status chip; toast fires once (SG §49)
  // Backend derives title from the filename stem when not provided.
  await expect(page.getByText("Документ загружен")).toBeVisible();
  const card = page
    .locator("a[href^='/documents/']")
    .filter({ hasText: "e2e-blood-test" });
  await expect(card).toBeVisible();
  await expect(card.getByText(/обрабатывается|загружен|готов/i)).toBeVisible();

  // ---- Detail opens ----------------------------------------------------
  await card.click();
  await expect(page).toHaveURL(/\/documents\/[\da-f-]{36}$/);
  await expect(
    page.getByRole("heading", { name: /e2e-blood-test/ }),
  ).toBeVisible();
  await expect(page.getByText(/обработка может занять время/i)).toBeVisible(); // BK-6 honest hint

  // Tabs render both panels' entry points
  await expect(page.getByRole("tab", { name: "Оригинал" })).toBeVisible();
  await page.getByRole("tab", { name: "Извлечённая информация" }).click();
  await expect(page.getByText(/информация ещё извлекается/i)).toBeVisible({
    timeout: 10_000,
  });
});

test("pages pass axe a11y scan and have no 320px horizontal overflow", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const identity = uniqueIdentity();

  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/login");
  await page.getByLabel(/email|телефон/i).fill(identity);
  await page.getByRole("button", { name: "Получить код" }).click();
  const code = readOtpCode(identity);
  for (const [index, digit] of [...code].entries()) {
    await page.getByLabel(`Цифра ${index + 1} из 6`).fill(digit);
  }
  await expect(page).toHaveURL("/", { timeout: 15_000 });

  for (const path of ["/", "/documents", "/medical-record", "/profile"]) {
    await page.goto(path);
    // Session restore (silent refresh) can take a moment on cold start
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page).not.toHaveURL(/login/);

    // 320px sweep: no horizontal scroll (M7)
    const overflow = await page.evaluate(() => {
      const el = document.scrollingElement ?? document.documentElement;
      return el.scrollWidth - el.clientWidth;
    });
    expect(overflow, `${path} overflows at 320px by ${overflow}px`).toBeLessThanOrEqual(0);

    // Axe scan (M7): only critical/serious violations fail the build
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    const serious = results.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    );
    expect(
      serious.map((v) => `${v.id}: ${v.nodes.length} nodes`),
      `${path} a11y violations`,
    ).toEqual([]);
  }
});

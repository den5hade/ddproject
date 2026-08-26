import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { readOtpCode, uniqueIdentity } from "./helpers/auth";

/*
 * Authorization isolation (plan §7/M7):
 * Patient B cannot open Patient A's document by URL — the backend
 * answers 403/404 and the UI shows a calm, honest screen.
 */

async function loginAs(page: import("@playwright/test").Page): Promise<void> {
  const identity = uniqueIdentity();
  await page.goto("/login");
  await page.getByLabel(/email|телефон/i).fill(identity);
  await page.getByRole("button", { name: "Получить код" }).click();
  const code = readOtpCode(identity);
  for (const [index, digit] of [...code].entries()) {
    await page.getByLabel(`Цифра ${index + 1} из 6`).fill(digit);
  }
  await expect(page).toHaveURL("/", { timeout: 15_000 });
}

test.use({ viewport: { width: 390, height: 844 } });

test("foreign document URL renders an access-denied/not-found screen", async ({
  browser,
}) => {
  test.setTimeout(180_000);

  // --- Patient A: upload a document, capture its id -------------------
  const contextA = await browser.newContext();
  const pageA = await contextA.newPage();
  await loginAs(pageA);

  await pageA.goto("/documents");
  await pageA.getByRole("button", { name: "Добавить" }).first().click();
  await expect(pageA.getByRole("dialog", { name: "Добавить" })).toBeVisible();
  const fileInputA = pageA.locator('input[type="file"]').nth(1);
  await fileInputA.setInputFiles({
    name: "private-a.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(
      readFileSync(new URL("./fixtures/sample.pdf", import.meta.url)),
    ),
  });
  await pageA.keyboard.press("Escape");

  const cardA = pageA
    .locator("a[href^='/documents/']")
    .filter({ hasText: "private-a" });
  await expect(cardA).toBeVisible({ timeout: 15_000 });
  const docUrlA = new URL(
    await cardA.getAttribute("href") as string,
    pageA.url(),
  ).toString();

  // --- Patient B (fresh account): tries A's document URL --------------
  const contextB = await browser.newContext();
  const pageB = await contextB.newPage();
  await loginAs(pageB);

  await pageB.goto(docUrlA);
  // Backend denies (403) → UI shows the calm no-access screen, never data
  await expect(
    pageB.getByText(/нет доступа|документ не найден/i),
  ).toBeVisible({ timeout: 15_000 });
  await expect(pageB.getByText(/private-a\.pdf/)).toHaveCount(0);
  await expect(pageB.getByText(/test lab result/i)).toHaveCount(0);

  await contextA.close();
  await contextB.close();
});

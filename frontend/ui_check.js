const { chromium } = require("playwright");
const path = require("path");

const SHOT_DIR = "C:\\Users\\meind\\AppData\\Local\\Temp\\claude\\d--Work-Vadoo-Web-Vadoo-autonomous-agent-code\\739799fd-8b0d-47a5-bca6-952c3d366a5b\\scratchpad\\shots";

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 900, height: 1100 } });
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("http://localhost:3000");
  await page.evaluate(() => localStorage.setItem("vadoo_user_id", "832397588"));
  await page.reload();

  await page.waitForSelector("text=Submit a task");
  await page.getByText("Repeat this on a schedule").click();
  await page.waitForSelector("select");
  await page.screenshot({ path: path.join(SHOT_DIR, "1-schedule-fields.png"), fullPage: true });

  await page.getByPlaceholder(/create a webpage/).fill("test schedule ui");
  await page.getByRole("button", { name: /Create schedule/ }).click();

  await page.waitForSelector("text=Next run", { timeout: 10000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "2-schedule-created.png"), fullPage: true });

  await page
    .locator("li", { hasText: "test schedule ui" })
    .getByRole("button", { name: "Delete" })
    .click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SHOT_DIR, "3-after-delete.png"), fullPage: true });

  const stillThere = await page.locator("text=test schedule ui").count();

  console.log("CONSOLE_ERRORS:", JSON.stringify(errors));
  console.log("SCHEDULE_REMOVED_AFTER_DELETE:", stillThere === 0);

  await browser.close();
}

main().catch((e) => {
  console.error("FAILED:", e);
  process.exit(1);
});

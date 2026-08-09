const { chromium } = require("C:\\Users\\Administrator\\.workbuddy\\binaries\\node\\workspace\\node_modules\\playwright-core");
const fs = require("fs");
const path = require("path");

const BASE = "http://127.0.0.1:8659";
const SLASH = "/admin/v1";
const CHROME = "C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe";
const SHOTS = path.join(__dirname, "verify_shots");
fs.mkdirSync(SHOTS, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // Step 1: Node-side login to fetch a real tenant id for the invite test
  const lg = await fetch(BASE + "/dev/admin-login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "admin" }) });
  const lj = await lg.json();
  const TOKEN = lj.access_token || lj.token || (lj.data && lj.data.access_token) || "";
  let tenantId = "tenant_default";
  try {
    const tR = await fetch(BASE + SLASH + "/tenants-extended", { headers: { "Authorization": "Bearer " + TOKEN } });
    const tJ = await tR.json();
    const arr = Array.isArray(tJ) ? tJ : (tJ.data && (Array.isArray(tJ.data) ? tJ.data : (tJ.data.items || [])));
    if (arr[0]) tenantId = arr[0].id || arr[0].tenant_id;
  } catch (e) {}

  // Step 2: launch browser
  const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const consoleErrors = [];
  const pageErrors = [];
  const failedReq = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(e.message));
  page.on("requestfailed", (r) => failedReq.push(r.url() + " :: " + (r.failure() && r.failure().errorText)));
  page.on("response", (r) => { if (r.status() >= 400) failedReq.push("HTTP " + r.status() + " " + r.url()); });

  const results = {};
  function log(...a) { console.log(...a); }

  await page.goto(BASE + "/console.html", { waitUntil: "networkidle" });
  await sleep(400);
  // login
  await page.click("#loginBtn");
  await page.waitForSelector("#app.show", { timeout: 8000 });
  log("LOGIN: app shown OK");

  async function checkView(name, opts = {}) {
    // close any open drawer first
    const maskOpen = await page.$('#drawerMask.open');
    if (maskOpen) { await page.click('#drawerMask', { force: true }).catch(() => {}); await sleep(300); }
    await page.click(`.nav-item[data-page="${name}"]`);
    await page.waitForLoadState("networkidle");
    await sleep(700);
    const txt = await page.$eval("#content", (e) => e.innerText).catch(() => "");
    const hasErr = txt.includes("加载失败") || txt.includes("Error");
    await page.screenshot({ path: path.join(SHOTS, name + ".png") });
    results[name] = { len: txt.length, hasErr, sample: txt.slice(0, 40).replace(/\n/g, " ") };
    return txt;
  }

  async function getUsersCount() {
    const r = await fetch(BASE + SLASH + "/users", { headers: { "Authorization": "Bearer " + TOKEN } });
    const j = await r.json();
    return Array.isArray(j) ? j.length : (j.data ? j.data.length : 0);
  }

  // 1) Dashboard
  results.dashboard = { len: (await page.$eval("#content", e => e.innerText)).length };
  await page.screenshot({ path: path.join(SHOTS, "dashboard.png") });

  // 2) Users
  const uTxt = await checkView("users");
  const preUsers = await getUsersCount();
  // add user flow
  await page.click('button:has-text("添加用户")');
  await sleep(300);
  await page.fill("#iuUsername", "vh_pw_" + Date.now());
  await page.fill("#iuName", "验证员");
  // leave #iuTenant at prefilled default (tenant_default) to match real product flow
  await page.selectOption("#iuRole", "health_user");
  await page.click('button[onclick^="userAdd"]');
  await sleep(800);
  const drawerTxt1 = await page.$eval("#drawerBody", e => e.innerText).catch(() => "");
  const addOk = drawerTxt1.includes("已创建");
  if (addOk) {
    await page.click('button:has-text("知道了，去用户列表")');
    await sleep(300);
  }
  const postUsers = await getUsersCount();
  results.users.preCount = preUsers;
  results.users.postCount = postUsers;
  results.users.created = postUsers - preUsers;
  results.users.addResult = addOk ? "created" : "unknown";
  log("USERS add: pre=", preUsers, "post=", postUsers, "result=", addOk);

  // 3) Roles
  const rTxt = await checkView("roles");
  const roleCards = await page.$$eval(".plan-card", els => els.length).catch(() => 0);
  results.roles.cardCount = roleCards;
  log("ROLES cards:", roleCards);

  // 4) Content control (words)
  const wTxt = await checkView("words");
  const wordCount = await page.$eval("#wordsCount", e => e.innerText).catch(() => "0");
  results.words.count = wordCount;
  // add a word
  await page.click('button:has-text("添加敏感词")');
  await sleep(300);
  await page.fill("#wwWord", "verify_" + Date.now());
  await page.click('button[onclick^="wordAdd"]');
  let toast2 = "";
  try { await page.waitForSelector(".save-toast", { timeout: 4000 }); toast2 = await page.$eval(".save-toast", e => e.innerText); } catch (e) {}
  results.words.addToast = toast2;
  log("WORDS add toast:", toast2);

  // 5) Billing + detail drawer
  const bTxt = await checkView("billing");
  const detailBtn = await page.$('button[onclick^="openBillDetail"]');
  if (detailBtn) {
    await detailBtn.click();
    await sleep(900);
    const drawerTxt = await page.$eval("#drawerBody", e => e.innerText).catch(() => "");
    results.billing.detail = {
      opened: true,
      hasPlanFee: drawerTxt.includes("套餐费"),
      has299: drawerTxt.includes("299"),
      hasTop5: drawerTxt.includes("TOP5") || drawerTxt.includes("端点用量"),
      sample: drawerTxt.slice(0, 80).replace(/\n/g, " ")
    };
    await page.screenshot({ path: path.join(SHOTS, "billing_detail.png") });
    log("BILLING detail:", JSON.stringify(results.billing.detail));
  } else {
    results.billing.detail = { opened: false, note: "no 明细 button (list empty?)" };
    log("BILLING: no 明细 button");
  }

  // 6) Cost center
  const cTxt = await checkView("cost");
  results.cost.hasInfra = cTxt.includes("基建评估") || cTxt.includes("扩容");
  results.cost.hasForecast = cTxt.includes("容量预测");
  results.cost.hasDonut = cTxt.includes("成本构成");
  log("COST infra/forecast/donut:", results.cost.hasInfra, results.cost.hasForecast, results.cost.hasDonut);

  // 7) remaining views quick check
  for (const v of ["capabilities", "content", "tenants", "keys", "monitor", "audit"]) {
    await checkView(v);
  }

  // Summary
  log("\n===== VERIFY SUMMARY =====");
  log("consoleErrors:", consoleErrors.length, JSON.stringify(consoleErrors.slice(0, 8)));
  log("pageErrors:", pageErrors.length, JSON.stringify(pageErrors.slice(0, 8)));
  log("failedReq:", failedReq.length, JSON.stringify(failedReq.slice(0, 10)));
  log("viewResults:", JSON.stringify(results, null, 1));
  log("TENANT_USED:", tenantId);

  await browser.close();
})().catch(e => { console.error("SCRIPT ERROR:", e); process.exit(1); });

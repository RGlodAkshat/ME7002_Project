import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Audits actual server data. Accounts are supplied externally; this script never seeds users or orders.
const baseUrl = process.env.APP_URL || 'http://127.0.0.1:8082';
const outputDir = path.resolve('../.run/responsive-audit', process.argv[2] || 'latest');
const credentials = {
  admin: { email: process.env.QA_ADMIN_EMAIL, password: process.env.QA_ADMIN_PASSWORD },
  operator: { email: process.env.QA_OPERATOR_EMAIL, password: process.env.QA_OPERATOR_PASSWORD },
};
const viewports = [
  { name: 'laptop', width: 1440, height: 900 },
  { name: 'compact-laptop', width: 1280, height: 800 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'tablet', width: 834, height: 1112 },
  { name: 'phone', width: 390, height: 844 },
  { name: 'small-phone', width: 360, height: 800 },
];
const scenarios = [
  { name: 'login', role: 'public', route: 'login' },
  { name: 'shop', role: 'public', route: 'shop' },
  { name: 'shop-assistant', role: 'public', route: 'shop', click: 'Configuration assistant', optional: true },
  ...['Environment', 'Equipment', 'Products & parts', 'Processes', 'Model & rules'].map(section => ({ name: `configuration-${section.toLowerCase().replace(/[^a-z]+/g, '-')}`, role: 'admin', route: 'admin', click: section, optional: true })),
  ...['Operations', 'Orders', 'Reviews', 'Accounts'].map(section => ({ name: `admin-${section.toLowerCase()}`, role: 'admin', route: 'admin', click: section })),
  { name: 'order-route', role: 'admin', route: 'admin', click: 'Orders', order: true, optional: true },
  { name: 'operator-guidance', role: 'operator', route: 'operator' },
];
await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
const report = []; const skipped = new Set();
try {
  for (const viewport of viewports) {
    const contexts = new Map();
    for (const role of ['public', 'admin', 'operator']) {
      if (role !== 'public' && (!credentials[role].email || !credentials[role].password)) { skipped.add(`${role}: QA credentials not provided`); continue; }
      const context = await browser.newContext({ viewport, reducedMotion: 'reduce' }); const page = await context.newPage();
      if (role !== 'public') {
        await page.goto(`${baseUrl}/#/login`, { waitUntil: 'networkidle' });
        await page.getByLabel('Email', { exact: true }).fill(credentials[role].email);
        await page.getByLabel('Password', { exact: true }).fill(credentials[role].password);
        await page.getByRole('button', { name: 'Sign in', exact: true }).click();
        await page.waitForURL(`**/#/${role}`);
      }
      contexts.set(role, { context, page });
    }
    for (const scenario of scenarios) {
      const entry = contexts.get(scenario.role); if (!entry) continue; const { page } = entry;
      await page.goto(`${baseUrl}/#/${scenario.route}`, { waitUntil: 'networkidle' });
      await page.waitForFunction(() => !document.querySelector('.loading'));
      if (scenario.click) {
        const button = page.getByRole('button', { name: scenario.click, exact: true });
        if (!(await button.count()) && scenario.optional) { skipped.add(`${scenario.name}: current configuration has no relevant screen`); continue; }
        await button.click(); await page.waitForFunction(() => !document.querySelector('.loading'));
      }
      if (scenario.order) {
        const order = page.locator('.order-row').first(); if (!(await order.count())) { skipped.add(`${scenario.name}: no current orders`); continue; }
        await order.click(); await page.waitForSelector('.route-visual');
      }
      await page.evaluate(async () => { window.scrollTo(0, 0); await document.fonts.ready; });
      const audit = await page.evaluate(() => {
        const visible = element => { const style = getComputedStyle(element); const rect = element.getBoundingClientRect(); return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity) !== 0 && rect.width > 1 && rect.height > 1; };
        const label = element => (element.getAttribute('aria-label') || element.textContent || element.tagName).replace(/\s+/g, ' ').trim().slice(0, 90);
        const controls = [...document.querySelectorAll('button, input:not([type="checkbox"]):not([type="file"]), select, textarea, label.file-button, label.capture-button')].filter(visible).map(element => { const rect = element.getBoundingClientRect(); return { label: label(element), width: Math.round(rect.width), height: Math.round(rect.height) }; }).filter(({ width, height }) => width < 44 || height < 44);
        const clipped = [...document.querySelectorAll('main *')].filter(visible).map(element => ({ element, rect: element.getBoundingClientRect() })).filter(({ rect }) => rect.right > document.documentElement.clientWidth + 1 || rect.left < -1).slice(0, 20).map(({ element, rect }) => ({ element: `${element.tagName.toLowerCase()}.${element.className || ''}`, label: label(element), left: Math.round(rect.left), right: Math.round(rect.right) }));
        return { documentWidth: document.documentElement.scrollWidth, viewportWidth: document.documentElement.clientWidth, horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, shortControls: controls, clipped };
      });
      const screenshot = `${viewport.name}--${scenario.name}.png`;
      await page.screenshot({ path: path.join(outputDir, screenshot), fullPage: true });
      report.push({ viewport, scenario: scenario.name, screenshot, ...audit });
    }
    for (const { context } of contexts.values()) await context.close();
  }
} finally { await browser.close(); }
await writeFile(path.join(outputDir, 'report.json'), `${JSON.stringify({ skipped: [...skipped], screens: report }, null, 2)}\n`);
const failures = report.filter(item => item.horizontalOverflow || item.clipped.length || item.shortControls.length);
console.log(`Captured ${report.length} screenshots in ${outputDir}. ${failures.length} scenarios have responsive issues.`);
for (const reason of skipped) console.log(`Skipped: ${reason}`);
if (failures.length) process.exitCode = 1;

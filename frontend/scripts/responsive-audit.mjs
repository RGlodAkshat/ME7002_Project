import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const chromePath = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const baseUrl = process.env.APP_URL || 'http://127.0.0.1:8082';
const runName = process.argv[2] || 'latest';
const outputDir = path.resolve('../.run/responsive-audit', runName);

const viewports = [
  { name: 'laptop', width: 1440, height: 900 },
  { name: 'compact-laptop', width: 1280, height: 800 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'tablet', width: 834, height: 1112 },
  { name: 'phone', width: 390, height: 844 },
  { name: 'small-phone', width: 360, height: 800 },
];

const scenarios = [
  { name: 'customer-configure', hash: 'customer' },
  { name: 'customer-assistant', hash: 'customer', click: 'Ask AI' },
  { name: 'operator-guidance', hash: 'operator' },
  { name: 'supervisor-floor', hash: 'supervisor' },
  { name: 'supervisor-orders', hash: 'supervisor', click: 'Orders' },
  { name: 'supervisor-reviews', hash: 'supervisor', click: /Manual review/ },
  { name: 'supervisor-settings', hash: 'supervisor', click: 'Gateway settings' },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ executablePath: chromePath, headless: true });
const report = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
    const page = await context.newPage();

    for (const scenario of scenarios) {
      await page.goto(`${baseUrl}/#${scenario.hash}`, { waitUntil: 'networkidle' });
      await page.waitForSelector('.page-header');
      if (scenario.click) {
        await page.getByRole('button', { name: scenario.click, exact: typeof scenario.click === 'string' }).click();
        await page.waitForTimeout(150);
      }
      await page.waitForFunction(() => !document.querySelector('.loading'));
      await page.evaluate(async () => { window.scrollTo(0, 0); await document.fonts.ready; });

      const audit = await page.evaluate(() => {
        const visible = (element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
        };
        const label = (element) => (element.getAttribute('aria-label') || element.textContent || element.tagName)
          .replace(/\s+/g, ' ').trim().slice(0, 80);
        const controls = [...document.querySelectorAll('button, input:not([type="checkbox"]), select, textarea, label.upload')]
          .filter(visible)
          .map((element) => {
            const rect = element.getBoundingClientRect();
            return { label: label(element), width: Math.round(rect.width), height: Math.round(rect.height) };
          })
          .filter(({ width, height }) => width < 44 || height < 44);
        const clipped = [...document.querySelectorAll('main *')]
          .filter(visible)
          .map((element) => ({ element, rect: element.getBoundingClientRect() }))
          .filter(({ rect }) => rect.right > document.documentElement.clientWidth + 1 || rect.left < -1)
          .slice(0, 20)
          .map(({ element, rect }) => ({
            element: `${element.tagName.toLowerCase()}.${element.className || ''}`,
            label: label(element),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
          }));
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
          documentHeight: document.documentElement.scrollHeight,
          viewportHeight: document.documentElement.clientHeight,
          horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          shortControls: controls,
          clipped,
        };
      });

      const filename = `${viewport.name}--${scenario.name}.png`;
      await page.screenshot({ path: path.join(outputDir, filename), fullPage: true });
      report.push({ viewport, scenario: scenario.name, screenshot: filename, ...audit });
    }

    if (viewport.width <= 1024) {
      await page.goto(`${baseUrl}/#customer`, { waitUntil: 'networkidle' });
      await page.waitForSelector('.page-header');
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.waitForTimeout(300);
      const filename = `${viewport.name}--mobile-navigation.png`;
      await page.screenshot({ path: path.join(outputDir, filename), fullPage: true });
    }

    await context.close();
  }
} finally {
  await browser.close();
}

await writeFile(path.join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
const failures = report.filter(item => item.horizontalOverflow || item.clipped.length);
const undersizedCount = report.reduce((sum, item) => sum + item.shortControls.length, 0);
console.log(`Captured ${report.length + viewports.filter(viewport => viewport.width <= 1024).length} screenshots in ${outputDir}`);
console.log(`${failures.length} scenarios have viewport overflow; ${undersizedCount} undersized visible controls found.`);
if (failures.length || undersizedCount) process.exitCode = 1;

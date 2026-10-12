/** Exercises the normal product workflow against a fresh, isolated QA database.
 * Start the stack with DATABASE_URL pointing to an ignored .run QA database.
 * Accounts are created through the UI; no fixed credentials are shipped.
 */
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright-core';

const base = process.env.APP_URL || 'http://127.0.0.1:8082';
const root = path.resolve('..');
const output = path.join(root, '.run/platform-e2e');
const specPath = path.join(root, 'configs/examples/lab-fan.json');
const specification = JSON.parse(await readFile(specPath, 'utf8'));
const password = randomBytes(24).toString('base64url');
const suffix = Date.now().toString(36);
const adminEmail = `owner-${suffix}@example.test`;
const workerEmail = `operator-${suffix}@example.test`;
const viewports = [
  { name: 'laptop', width: 1440, height: 900 },
  { name: 'compact-laptop', width: 1280, height: 800 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'tablet', width: 834, height: 1112 },
  { name: 'phone', width: 390, height: 844 },
  { name: 'small-phone', width: 360, height: 800 },
];
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
const report = { completed: false, screenshots: [], browserErrors: [], checks: [] };

async function settle(page) {
  await page.waitForTimeout(250);
  await page.evaluate(async () => { await document.fonts.ready; });
}

async function capture(page, name, viewport) {
  await page.setViewportSize(viewport);
  const dialogOpen = await page.getByRole('dialog').count() > 0;
  if (!dialogOpen) await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
  const overflow = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
  assert.ok(overflow.width <= overflow.viewport, `${name} at ${viewport.width}px has horizontal overflow ${overflow.width}`);
  const filename = `${viewport.name}--${name}.png`;
  await page.screenshot({ path: path.join(output, filename), fullPage: !dialogOpen });
  report.screenshots.push({ filename, viewport, overflow });
}

async function signIn(page, email) {
  await page.goto(`${base}/#/login`, { waitUntil: 'networkidle' });
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

async function responseJson(context, endpoint) {
  const response = await context.request.get(`${base}/api${endpoint}`);
  assert.equal(response.status(), 200, `${endpoint}: ${await response.text()}`);
  return response.json();
}

async function poll(run, predicate, message, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await run();
    if (predicate(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  throw new Error(message);
}

try {
  const adminContext = await browser.newContext({ viewport: viewports[0], reducedMotion: 'reduce' });
  const admin = await adminContext.newPage();
  for (const context of [adminContext]) context.on('page', page => page.on('pageerror', error => report.browserErrors.push(error.message)));
  admin.on('pageerror', error => report.browserErrors.push(error.message));
  await admin.goto(`${base}/#/login`, { waitUntil: 'networkidle' });
  await admin.getByRole('heading', { name: 'Create the first administrator' }).waitFor();
  for (const viewport of viewports) await capture(admin, 'first-administrator', viewport);
  await admin.getByLabel('Name', { exact: true }).fill('Workspace owner');
  await admin.getByLabel('Email', { exact: true }).fill(adminEmail);
  await admin.getByLabel(/^Password/).fill(password);
  await admin.getByRole('button', { name: 'Create workspace account' }).click();
  await admin.getByRole('button', { name: 'Configuration', exact: true }).waitFor();
  report.checks.push('First administrator created through central login');

  await admin.getByLabel('Import configuration', { exact: true }).setInputFiles(specPath);
  await admin.getByRole('button', { name: 'Apply configuration', exact: true }).click();
  await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 1, 'Configuration import was not applied');
  report.checks.push('Ordinary configuration import validated and persisted');

  await admin.getByRole('button', { name: 'Accounts', exact: true }).click();
  await admin.getByRole('button', { name: 'Add account', exact: true }).click();
  const dialog = admin.getByRole('dialog');
  await dialog.getByLabel('Name', { exact: true }).fill('Assembly operator');
  await dialog.getByLabel('Email', { exact: true }).fill(workerEmail);
  await dialog.getByLabel(/^Password/).fill(password);
  await dialog.getByLabel(/^Skills/).fill('kitting, machining, assembly, quality');
  await dialog.getByRole('button', { name: 'Save account', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  report.checks.push('Administrator created a skilled operator account');

  const shopContext = await browser.newContext({ viewport: viewports[4], reducedMotion: 'reduce' });
  const shop = await shopContext.newPage();
  shop.on('pageerror', error => report.browserErrors.push(error.message));
  await shop.goto(`${base}/#/shop`, { waitUntil: 'networkidle' });
  const baseVariant = specification.entities.find(item => item.id === 'base-blue');
  const propellerVariant = specification.entities.find(item => item.id === 'propeller-yellow');
  assert.ok(baseVariant && propellerVariant, 'Prepared sample must include independent blue base and yellow propeller variants');
  await shop.getByRole('button', { name: baseVariant.name, exact: true }).click();
  await shop.getByRole('button', { name: propellerVariant.name, exact: true }).click();
  await shop.getByRole('button', { name: 'Review your order', exact: true }).waitFor();
  await poll(async () => shop.getByRole('button', { name: 'Review your order', exact: true }).isEnabled(), Boolean, 'Independent part selections were not validated');
  for (const viewport of viewports) await capture(shop, 'shop-parts', viewport);
  await shop.getByRole('button', { name: 'Configuration assistant', exact: true }).click();
  await shop.getByLabel('Describe your configuration').fill('yellow propeller and blue base');
  const assistantResponse = shop.waitForResponse(response => response.url().endsWith('/api/shop/converse') && response.request().method() === 'POST');
  await shop.getByRole('button', { name: 'Send', exact: true }).click();
  const proposal = await assistantResponse;
  assert.ok(proposal.ok(), await proposal.text());
  const proposed = await proposal.json();
  assert.equal(proposed.selections.base, baseVariant.id);
  assert.equal(proposed.selections.propeller, propellerVariant.id);
  await shop.locator('.chat-message--assistant').waitFor();
  for (const viewport of viewports) await capture(shop, 'shop-assistant', viewport);
  report.checks.push('Catalog-backed assistant proposes independent part variants without placing an order');
  await shop.getByRole('button', { name: 'Choose parts', exact: true }).click();
  await shop.getByRole('button', { name: 'Review your order', exact: true }).click();
  await shop.getByLabel('Your name', { exact: true }).fill('Configured customer');
  const orderResponse = shop.waitForResponse(response => response.url().endsWith('/api/shop/orders') && response.request().method() === 'POST');
  await shop.getByRole('button', { name: 'Confirm and place order', exact: true }).click();
  const response = await orderResponse;
  assert.ok(response.ok(), await response.text());
  const order = await response.json();
  await shop.getByRole('heading', { name: 'Made for you.' }).waitFor();
  await capture(shop, 'shop-confirmed', viewports[4]);
  assert.equal(order.selections.base, baseVariant.id);
  assert.equal(order.selections.propeller, propellerVariant.id);
  report.checks.push('Public shop validated and confirmed independent part variants');

  const workerContext = await browser.newContext({ viewport: viewports[4], reducedMotion: 'reduce' });
  const worker = await workerContext.newPage();
  worker.on('pageerror', error => report.browserErrors.push(error.message));
  await signIn(worker, workerEmail);
  await worker.locator('.current-instruction').waitFor();
  assert.equal(new URL(worker.url()).hash, '#/operator');
  const blocked = await workerContext.request.get(`${base}/api/configuration`);
  assert.equal(blocked.status(), 403);
  report.checks.push('Operator lands directly in guidance and cannot access administrator API');
  for (const viewport of viewports) await capture(worker, 'operator-guidance', viewport);

  await admin.getByRole('button', { name: 'Orders', exact: true }).click();
  await admin.locator('.order-row').first().click();
  await admin.locator('.route-visual').waitFor();
  for (const viewport of viewports) await capture(admin, 'order-route', viewport);

  for (let iteration = 0; iteration < 12; iteration++) {
    const currentOrder = await responseJson(adminContext, `/orders/${order.id}`);
    if (currentOrder.status === 'completed') break;
    const assigned = await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(task => task.order_id === order.id), 'No next operation was assigned');
    const task = assigned.find(item => item.order_id === order.id);
    await worker.reload({ waitUntil: 'networkidle' });
    if (task.status === 'awaiting_review') {
      await admin.getByRole('button', { name: 'Reviews', exact: true }).click();
      await admin.getByRole('button', { name: 'Approve work', exact: true }).first().waitFor();
      if (!report.screenshots.some(item => item.filename.endsWith('--specialist-review.png'))) {
        for (const viewport of viewports) await capture(admin, 'specialist-review', viewport);
      }
      await admin.getByRole('button', { name: 'Approve work', exact: true }).first().click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => !tasks.some(item => item.id === task.id), 'Approved task failed to release its operator');
      continue;
    }
    if (task.kind === 'machine' && task.command_id && !task.machine_completed) {
      await poll(() => responseJson(adminContext, `/orders/${order.id}`), value => { const stage = value.tasks.find(item => item.id === task.id); return stage.machine_completed || stage.status === 'completed'; }, 'Normal gateway callback did not finish the equipment cycle');
      continue;
    }
    await worker.locator('.current-instruction').waitFor();
    while (await worker.getByRole('button', { name: 'Next instruction', exact: true }).count()) {
      await worker.getByRole('button', { name: 'Next instruction', exact: true }).click();
    }
    if (task.scrap?.required && !task.scrap_report && (task.kind !== 'machine' || task.machine_completed)) {
      await worker.getByRole('button', { name: 'Save material loss', exact: true }).click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(item => item.id === task.id && item.scrap_report != null), 'Required material loss report was not persisted');
    }
    if (task.kind === 'machine' && !task.machine_completed) {
      await worker.getByRole('button', { name: 'Start equipment', exact: true }).click();
      await poll(() => responseJson(adminContext, `/orders/${order.id}`), value => { const stage = value.tasks.find(item => item.id === task.id); return stage.machine_completed || stage.status === 'completed'; }, 'Machine cycle did not finish through the external gateway', 40000);
      report.checks.push('Operator prepared equipment; gateway command and callback finished the machine cycle');
    } else if (task.verification) {
      await worker.getByRole('button', { name: 'Verify this operation', exact: true }).click();
      await worker.locator('input[type=file]').setInputFiles(path.join(root, 'backend/data/reference_images/blue.jpg'));
      await poll(async () => worker.getByRole('button', { name: 'Submit for verification', exact: true }).isEnabled(), Boolean, 'Evidence did not enable submission');
      if (!report.screenshots.some(item => item.filename.endsWith('--operator-verification.png'))) {
        for (const viewport of viewports) await capture(worker, 'operator-verification', viewport);
      }
      await worker.getByRole('button', { name: 'Submit for verification', exact: true }).click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(item => item.id === task.id && item.status === 'awaiting_review'), 'Configured human verification gate did not hold work');
    } else {
      await worker.getByRole('button', { name: 'Operation complete', exact: true }).click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => !tasks.some(item => item.id === task.id), 'Operation did not finish');
    }
  }
  const finished = await responseJson(adminContext, `/orders/${order.id}`);
  assert.equal(finished.status, 'completed', 'The whole configured manufacturing route must finish');
  assert.ok(finished.tasks.every(task => task.status === 'completed'));
  report.checks.push('Every stage completed with dependency, scrap and verification gates satisfied');
  const exported = await responseJson(adminContext, '/configuration/export');
  assert.deepEqual(exported, specification);
  report.checks.push('Export reconstructs the active server-managed specification');

  for (const tab of ['Configuration', 'Operations', 'Accounts']) {
    await admin.getByRole('button', { name: tab, exact: true }).click();
    for (const viewport of viewports) await capture(admin, `admin-${tab.toLowerCase()}`, viewport);
  }
  await admin.getByRole('button', { name: 'Configuration', exact: true }).click();
  for (const area of ['Equipment', 'Products & parts', 'Processes', 'Model & rules']) {
    await admin.getByRole('button', { name: area, exact: true }).click();
    for (const viewport of viewports) await capture(admin, `configuration-${area.toLowerCase().replaceAll(/[^a-z]+/g, '-')}`, viewport);
  }
  await admin.locator('summary').filter({ hasText: /^Manufacturing relationships \(/ }).click();
  await admin.getByRole('button', { name: 'Add relationship', exact: true }).click();
  for (const viewport of [viewports[0], viewports[5]]) await capture(admin, 'relationship-editor', viewport);
  await admin.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await admin.locator('summary').filter({ hasText: /^Manufacturing relationships \(/ }).click();
  await admin.getByRole('button', { name: 'Edit rule', exact: true }).first().click();
  for (const viewport of [viewports[0], viewports[5]]) await capture(admin, 'compatibility-editor', viewport);
  await admin.getByRole('button', { name: 'Close dialog', exact: true }).click();

  await admin.getByRole('button', { name: 'Equipment', exact: true }).click();
  const originalMachine = specification.entities.find(entity => entity.type === 'machine');
  await admin.locator('.entity-card').filter({ hasText: originalMachine.name }).first().click();
  for (const viewport of [viewports[0], viewports[5]]) await capture(admin, 'machine-editor', viewport);
  await admin.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Configured equipment label');
  await admin.getByRole('button', { name: 'Update definition', exact: true }).click();
  await admin.getByRole('button', { name: 'Save configuration', exact: true }).click();
  await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 2, 'Manual configuration edit was not saved');
  const edited = await responseJson(adminContext, '/configuration/export');
  assert.equal(edited.entities.find(entity => entity.id === originalMachine.id).name, 'Configured equipment label');
  await admin.getByLabel('Import configuration', { exact: true }).setInputFiles({ name: 'workspace-backup.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(edited)) });
  await admin.getByRole('button', { name: 'Apply configuration', exact: true }).click();
  await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 3, 'Exported configuration could not be reimported');
  assert.deepEqual(await responseJson(adminContext, '/configuration/export'), edited);
  assert.equal((await responseJson(adminContext, `/orders/${order.id}`)).configuration_revision, 1);
  report.checks.push('Manual admin edit is included in export; reimport keeps completed order history and its original revision');
  assert.deepEqual(report.browserErrors, [], 'Browser runtime errors must be fixed');
  report.completed = true;
  console.log(`Completed normal order workflow; ${report.screenshots.length} screenshots; no horizontal overflow or browser exceptions.`);
} finally {
  await writeFile(path.join(output, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();
}

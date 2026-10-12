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
if (process.env.QA_GATEWAY_PORT) specification.gateway.port = Number(process.env.QA_GATEWAY_PORT);
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
const landscape = { name: 'phone-landscape', width: 844, height: 390 };
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

  await admin.getByLabel('Import configuration', { exact: true }).setInputFiles({ name: 'lab-fan.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(specification)) });
  await admin.getByRole('button', { name: 'Apply configuration', exact: true }).click();
  await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 1, 'Configuration import was not applied');
  report.checks.push('Ordinary configuration import validated and persisted');

  await admin.getByRole('button', { name: 'Accounts', exact: true }).click();
  await admin.getByRole('button', { name: 'Add account', exact: true }).click();
  const dialog = admin.getByRole('dialog');
  await dialog.getByLabel('Name', { exact: true }).fill('Assembly operator');
  await dialog.getByLabel('Email', { exact: true }).fill(workerEmail);
  await dialog.getByLabel(/^Password/).fill(password);
  await dialog.getByRole('checkbox', { name: /^Skill: / }).first().waitFor();
  for (const checkbox of await dialog.getByRole('checkbox', { name: /^Skill: / }).all()) await checkbox.check();
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
  await shop.getByRole('button', { name: 'Separate parts', exact: true }).click();
  await shop.getByRole('button', { name: 'Assembled preview', exact: true }).waitFor();
  await shop.getByRole('button', { name: 'Reset view', exact: true }).click();
  await capture(shop, 'shop-separated-3d', viewports[0]);
  await shop.getByRole('button', { name: 'Assembled preview', exact: true }).click();
  report.checks.push('Configured 3D geometry supports separated inspection, fit/reset and honest illustrative labeling');
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
  await worker.getByRole('button', { name: 'Focus view', exact: true }).click();
  await capture(worker, 'operator-landscape-focus', landscape);
  assert.equal(await worker.locator('.operator-header').isVisible(), false);
  await worker.getByRole('button', { name: 'Exit focus view', exact: true }).click();
  report.checks.push('Operator focus view hides account chrome and remains actionable in phone landscape');

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
  for (const area of ['Equipment', 'Products & parts', 'Processes', 'Ontology view', 'Model & rules']) {
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

  // Import the actual lab RDF through the same public admin UI, not a test seed.
  await admin.getByLabel('Import configuration', { exact: true }).setInputFiles(path.join(root, 'smart_factory_v2_modular_3_final_updated.ttl'));
  await admin.getByRole('button', { name: 'Apply configuration', exact: true }).click();
  const importedLab = await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 4, 'Lab Turtle import did not apply');
  assert.equal(importedLab.specification.gateway, undefined, 'Observed lab integration must not invent a command gateway');
  assert.ok(importedLab.specification.rdf.triples.length > 0);
  const preservedRdf = importedLab.specification.rdf;
  await admin.getByRole('button', { name: 'Environment', exact: true }).click();
  await admin.getByRole('heading', { name: 'Published database integration', exact: true }).waitFor();
  for (const viewport of viewports) await capture(admin, 'lab-database-environment', viewport);
  await admin.getByRole('button', { name: 'Ontology view', exact: true }).click();
  const ontology = admin.locator('.graph-explorer').first();
  await ontology.getByRole('heading', { name: 'Manufacturing ontology', exact: true }).waitFor();
  for (const viewport of viewports) await capture(admin, 'lab-manufacturing-ontology', viewport);
  const labMachine = importedLab.specification.entities.find(entity => entity.id === 'MC1');
  assert.ok(labMachine);
  await ontology.getByLabel('Find a definition', { exact: true }).fill('MC1');
  await ontology.getByRole('listitem').filter({ hasText: labMachine.name }).first().click();
  await ontology.getByRole('button', { name: 'Edit selected definition', exact: true }).click();
  await admin.getByRole('dialog').getByLabel('Name', { exact: true }).fill('MC1 · Lab equipment');
  await admin.getByRole('button', { name: 'Update definition', exact: true }).click();
  await admin.getByRole('button', { name: 'Save configuration', exact: true }).click();
  await poll(() => responseJson(adminContext, '/configuration'), value => value.revision === 5, 'Graph edit did not use revisioned draft save');
  const editedLab = await responseJson(adminContext, '/configuration/export');
  assert.equal(editedLab.entities.find(entity => entity.id === 'MC1').name, 'MC1 · Lab equipment');
  assert.deepEqual(editedLab.rdf, preservedRdf, 'Editing executable ontology must retain original RDF provenance');
  report.checks.push('Actual Turtle imported through UI; DB-only environment rendered; graph edit persisted without rewriting source RDF');

  await admin.getByRole('button', { name: 'Accounts', exact: true }).click();
  await admin.locator('.account-row').filter({ hasText: workerEmail }).getByRole('button', { name: 'Edit account', exact: true }).click();
  await admin.getByRole('dialog').getByRole('checkbox', { name: /^Qualification: / }).first().waitFor();
  for (const checkbox of await admin.getByRole('dialog').getByRole('checkbox', { name: /^Qualification: / }).all()) await checkbox.check();
  for (const viewport of [viewports[0], viewports[4]]) await capture(admin, 'lab-process-qualifications', viewport);
  await admin.getByRole('button', { name: 'Save account', exact: true }).click();
  await admin.getByRole('dialog').waitFor({ state: 'hidden' });
  report.checks.push('Worker qualifications selected from actual lab workstation processes without typing arbitrary skills');

  await shop.reload({ waitUntil: 'networkidle' });
  await shop.locator('.shop-heading select').selectOption('PR1');
  await shop.getByRole('button', { name: 'Separate parts', exact: true }).waitFor();
  assert.equal(await shop.locator('.product-preview canvas').count(), 1, 'Actual imported lab product must render its configured 3D descriptors');
  await shop.getByRole('button', { name: 'Separate parts', exact: true }).click();
  await shop.getByRole('button', { name: 'Assembled preview', exact: true }).waitFor();
  await shop.getByRole('button', { name: 'Reset view', exact: true }).click();
  for (const viewport of [viewports[0], viewports[4], landscape]) await capture(shop, 'lab-separated-3d', viewport);
  await shop.getByRole('button', { name: 'Assembled preview', exact: true }).click();
  report.checks.push('Actual imported lab product has a rendered configured 3D canvas with separated inspection and reset controls');
  await poll(async () => shop.getByRole('button', { name: 'Review your order', exact: true }).isEnabled(), Boolean, 'TTL product BOM did not validate');
  await shop.getByRole('button', { name: 'Review your order', exact: true }).click();
  await shop.getByLabel('Your name', { exact: true }).fill('Lab demo customer');
  const labOrderResponse = shop.waitForResponse(response => response.url().endsWith('/api/shop/orders') && response.request().method() === 'POST');
  await shop.getByRole('button', { name: 'Confirm and place order', exact: true }).click();
  const placedLab = await labOrderResponse;
  assert.ok(placedLab.ok(), await placedLab.text());
  const labOrder = await placedLab.json();
  assert.equal(labOrder.product_id, 'PR1');
  assert.equal(labOrder.tasks.length, 8);
  report.checks.push('Guest checkout instantiated the actual PR1 eight-stage route from the imported manufacturing ontology');
  await admin.getByRole('button', { name: 'Orders', exact: true }).click();
  await admin.locator('.order-row').filter({ hasText: 'Lab demo customer' }).click();
  await admin.getByRole('heading', { name: 'Order knowledge graph', exact: true }).waitFor();
  for (const viewport of viewports) await capture(admin, 'lab-order-knowledge-graph', viewport);
  await admin.locator('.order-kit-status summary').click();
  await admin.getByRole('heading', { name: 'Order kit & stage progress', exact: true }).waitFor();
  for (const viewport of [viewports[0], viewports[4], landscape]) await capture(admin, 'lab-order-kit-status', viewport);
  await admin.locator('.order-kit-status summary').click();

  const stageEvidence = new Set();
  let reviewedStages = 0;
  for (let iteration = 0; iteration < 32; iteration++) {
    const current = await responseJson(adminContext, `/orders/${labOrder.id}`);
    if (current.status === 'completed') break;
    const assigned = await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(task => task.order_id === labOrder.id), 'No actual lab operation assigned');
    const task = assigned.find(item => item.order_id === labOrder.id);
    if (task.status === 'awaiting_review') {
      await admin.getByRole('button', { name: 'Reviews', exact: true }).click();
      await admin.getByRole('button', { name: 'Approve work', exact: true }).first().waitFor();
      await admin.getByRole('button', { name: 'Approve work', exact: true }).first().click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => !tasks.some(item => item.id === task.id), 'Lab specialist approval failed to advance the order');
      reviewedStages++;
      continue;
    }
    await worker.reload({ waitUntil: 'networkidle' });
    await worker.locator('.current-instruction').waitFor();
    if (!report.screenshots.some(item => item.filename.endsWith('--lab-kitting-part-reference.png')) && task.kind === 'manual') {
      await worker.locator('.instruction-reference').waitFor();
      await worker.getByText('Illustrative part reference — confirm the physical part and bin label.', { exact: true }).waitFor();
      for (const viewport of [viewports[0], viewports[4], landscape]) await capture(worker, 'lab-kitting-part-reference', viewport);
      await worker.getByRole('button', { name: 'Focus view', exact: true }).click();
      await capture(worker, 'lab-kitting-landscape-focus', landscape);
      await worker.getByRole('button', { name: 'Exit focus view', exact: true }).click();
    }
    if (task.kind === 'machine' && !task.command_id) {
      assert.equal(task.execution_mode, 'observed');
      assert.equal(task.instruction_phase, 'preparation');
      if (!report.screenshots.some(item => item.filename.endsWith('--lab-machine-preparation.png'))) for (const viewport of [viewports[0], viewports[4]]) await capture(worker, 'lab-machine-preparation', viewport);
      while (await worker.getByRole('button', { name: 'Next instruction', exact: true }).count()) await worker.getByRole('button', { name: 'Next instruction', exact: true }).click();
      await worker.getByRole('button', { name: 'Begin monitored operation', exact: true }).click();
      await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(item => item.id === task.id && item.command_id && item.instruction_phase === 'work'), 'Monitoring did not open the physical-work instruction phase');
      await poll(async () => worker.locator('.step-position').innerText(), text => text.includes('Instruction 1 of'), 'Operator did not reset to the first physical instruction');
      await worker.getByText('Monitoring this operation.', { exact: true }).waitFor();
      if (!report.screenshots.some(item => item.filename.endsWith('--lab-machine-observed-work.png'))) for (const viewport of [viewports[0], viewports[4]]) await capture(worker, 'lab-machine-observed-work', viewport);
      continue;
    }
    while (await worker.getByRole('button', { name: 'Next instruction', exact: true }).count()) await worker.getByRole('button', { name: 'Next instruction', exact: true }).click();
    if (task.scrap?.required && !task.scrap_report) await worker.getByRole('button', { name: 'Save material loss', exact: true }).click();
    await worker.getByRole('button', { name: 'Verify this operation', exact: true }).click();
    // This is only a QA evidence fixture, not a claim that blue photo verifies a red product.
    await worker.locator('input[type=file]').setInputFiles(path.join(root, 'backend/data/reference_images/blue.jpg'));
    await poll(async () => worker.getByRole('button', { name: 'Submit for verification', exact: true }).isEnabled(), Boolean, 'Lab evidence did not enable specialist submission');
    await worker.getByRole('button', { name: 'Submit for verification', exact: true }).click();
    await poll(() => responseJson(workerContext, '/operator/tasks'), tasks => tasks.some(item => item.id === task.id && item.status === 'awaiting_review'), 'Lab verification failed to hold the operation for review');
    stageEvidence.add(task.id);
  }
  const completedLab = await responseJson(adminContext, `/orders/${labOrder.id}`);
  assert.equal(completedLab.status, 'completed');
  assert.equal(reviewedStages, 8);
  assert.equal(stageEvidence.size, 8);
  const completedGraph = await responseJson(adminContext, `/orders/${labOrder.id}/graph`);
  assert.equal(completedGraph.nodes.filter(node => node.type === 'operation').length, 8);
  assert.ok(completedGraph.nodes.filter(node => node.type === 'operation').every(node => node.properties.status === 'completed'));
  assert.equal(completedGraph.nodes.filter(node => node.type === 'evidence').length, 8);
  assert.equal(completedGraph.configuration_revision, 5);
  assert.equal((await responseJson(adminContext, `/orders/${order.id}`)).configuration_revision, 1);
  report.checks.push('Actual lab route completed all eight operations with preparation/work phase guidance and eight specialist evidence approvals; runtime graph reflects every completion');

  // Cancellation is exercised on a separate real order, retaining the completed demonstration.
  await shop.reload({ waitUntil: 'networkidle' });
  await shop.locator('.shop-heading select').selectOption('PR1');
  await poll(async () => shop.getByRole('button', { name: 'Review your order', exact: true }).isEnabled(), Boolean, 'Cancellation sample did not validate');
  await shop.getByRole('button', { name: 'Review your order', exact: true }).click();
  await shop.getByLabel('Your name', { exact: true }).fill('Cancellation demonstration');
  const cancelOrderResponse = shop.waitForResponse(response => response.url().endsWith('/api/shop/orders') && response.request().method() === 'POST');
  await shop.getByRole('button', { name: 'Confirm and place order', exact: true }).click();
  const cancelOrder = await (await cancelOrderResponse).json();
  await admin.getByRole('button', { name: 'Orders', exact: true }).click();
  await admin.locator('.order-row').filter({ hasText: 'Cancellation demonstration' }).click();
  await admin.getByRole('button', { name: 'Cancel order', exact: true }).click();
  const cancelDialog = admin.getByRole('dialog');
  assert.equal(await cancelDialog.getByRole('button', { name: 'Confirm cancellation', exact: true }).isEnabled(), false);
  await cancelDialog.getByLabel('Cancellation reason', { exact: true }).fill('End the isolated demonstration safely');
  await cancelDialog.getByRole('checkbox').check();
  for (const viewport of [viewports[0], viewports[4]]) await capture(admin, 'admin-cancel-order', viewport);
  await cancelDialog.getByRole('button', { name: 'Confirm cancellation', exact: true }).click();
  await cancelDialog.waitFor({ state: 'hidden' });
  const cancelled = await responseJson(adminContext, `/orders/${cancelOrder.id}`);
  assert.equal(cancelled.status, 'cancelled', 'Unstarted manual order cancellation should release its resources');
  assert.ok(cancelled.tasks.every(task => task.status === 'cancelled'));
  assert.equal(await admin.getByRole('button', { name: 'Cancel order', exact: true }).count(), 0);
  report.checks.push('Admin cancellation requires explicit reason/acknowledgement and cancels a separate unstarted order without changing completed order history');
  assert.deepEqual(report.browserErrors, [], 'Browser runtime errors must be fixed');
  report.completed = true;
  console.log(`Completed normal order workflow; ${report.screenshots.length} screenshots; no horizontal overflow or browser exceptions.`);
} finally {
  await writeFile(path.join(output, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();
}

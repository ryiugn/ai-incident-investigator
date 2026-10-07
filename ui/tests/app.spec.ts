import { test, expect } from '@playwright/test';

for(const width of [390,1440]) {
  test(`all saved runs remain scrollable and selectable at ${width}px`,async ({page})=>{
    await page.setViewportSize({width,height:850});
    const runs=[{run_id:'pending-approval',workflow:'adaptive',state:'awaiting_approval'},
      ...Array.from({length:20},(_,i)=>({run_id:`saved-${String(20-i).padStart(2,'0')}`,workflow:'fixed',state:'finished'}))];
    await page.route('**/api/runs',route=>route.fulfill({json:runs}));
    await page.route('**/api/runs/saved-01',route=>route.fulfill({json:{...runs.at(-1),result:null}}));
    await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
    const history=page.getByRole('region',{name:'Recent runs'});
    await expect(history).toBeVisible();
    await expect(history.getByRole('button')).toHaveCount(21);
    await expect(history.getByRole('button').first()).toContainText('awaiting_approval');
    const oldest=history.getByRole('button').last();
    await oldest.scrollIntoViewIfNeeded();
    await expect(oldest).toBeInViewport();
    await oldest.click();
    await expect(page.locator('.run-top')).toContainText('saved-01');
    expect(await history.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
  });
}

test('investigation opens immutable evidence and missing case abstains', async ({ page }) => {
  await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
  await page.getByRole('button', { name: 'Start investigation' }).click();
  await expect(page.getByText('Shipping dependency timeouts were observed during order failures.').first()).toBeVisible();
  await page.getByRole('button', { name: 'Inspect evidence 1' }).first().click();
  await expect(page.getByRole('heading', { name: 'Evidence inspector' })).toBeVisible();
  await expect(page.getByText('Content hash', {exact:true})).toBeVisible();
  await page.getByLabel('Replay case').selectOption('demo-missing');
  await page.getByRole('button', { name: 'Start investigation' }).click();
  await expect(page.getByRole('heading', { name: 'Insufficient evidence' })).toBeVisible();
  await page.getByRole('button', { name: 'Benchmark' , exact:true}).click();
  await expect(page.getByRole('heading', { name: 'Fixed vs. adaptive' })).toBeVisible();
  await expect(page.getByText('Real-model findings pending', {exact:true})).toBeVisible();
});

for (const width of [390, 1440]) {
  test(`citation navigation exposes evidence and returns to source at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 850 });
    await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
    await page.getByRole('button', { name: 'Start investigation' }).click();
    const citation = page.getByRole('button', { name: 'Inspect evidence 1', exact: true }).first();
    await citation.click();
    const heading = page.getByRole('heading', { name: 'Evidence inspector' });
    await expect(heading).toBeFocused();
    await expect(heading).toBeInViewport();
    await expect(page.getByText('Content hash', { exact: true })).toBeInViewport();
    await page.getByRole('button', { name: 'Back to citation' }).click();
    await expect(citation).toBeFocused();
    await expect(citation).toBeInViewport();
    await citation.press('Enter');
    await expect(heading).toBeFocused();
    await expect(heading).toBeInViewport();
  });
}

test('workflow walkthrough explains the graph and shows the actual selected run', async ({page}) => {
  await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await expect(page.getByRole('heading',{name:'One bounded investigation loop.'})).toBeVisible();
  await page.getByRole('button',{name:/collect_evidence/}).click();
  await expect(page.getByText('The application validates arguments and scope, enforces limits, and calls one of five read-only tools. Duplicates use cached results.')).toBeVisible();
  await page.getByRole('button',{name:'Investigation',exact:true}).click();
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Recorded graph path'})).toBeVisible();
  await expect(page.locator('.execution-path li').first()).toHaveText('validate alert');
  await expect(page.locator('.execution-path li').last()).toHaveText('finalize');
  await page.getByLabel('Saved run').selectOption({index:1});
  await expect(page.locator('.execution-path li').last()).toHaveText('finalize');
});

test('expanded query approval survives page reload and shows the resumed path',async ({page})=>{
  await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
  await page.getByLabel('Replay case').selectOption('demo-approval');
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Review expanded evidence query'})).toBeVisible();
  await expect(page.getByText('Frozen snapshot horizon',{exact:true})).toBeVisible();
  await page.reload();
  await page.locator('.history button').first().click();
  await expect(page.getByRole('heading',{name:'Review expanded evidence query'})).toBeVisible();
  await page.getByRole('button',{name:'Approve exact query'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Inspect evidence 1'}).first().click();
  await expect(page.getByRole('heading',{name:'Evidence inspector'})).toBeFocused();
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await expect(page.locator('.execution-path')).toContainText('pause for approval');
  await expect(page.locator('.execution-path')).toContainText('resume approve');
});

test('decline skips the expanded query and leaves an explicit report limitation',async ({page})=>{
  await page.goto(process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090');
  await page.getByLabel('Replay case').selectOption('demo-approval');
  await page.getByRole('button',{name:'Start investigation'}).click();
  await page.getByRole('button',{name:'Decline and finalize'}).click();
  await expect(page.getByText('Expanded evidence query declined by the user; assessment uses only evidence already collected.',{exact:true})).toBeVisible();
  await expect(page.locator('.run-top')).toContainText('1 tool attempts');
});

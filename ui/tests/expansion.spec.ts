import {test,expect} from '@playwright/test';
const url=process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18104';
test('human review saves an incomplete atomic claim and restores it after reload',async({page})=>{
  await page.goto(url);
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Review report',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Human claim review'})).toBeVisible();
  await expect(page.getByText('Pending human review',{exact:true})).toBeVisible();
  await page.getByLabel('Reviewer name').fill('Automated test fixture — not a real review');
  await page.getByRole('button',{name:'Add atomic claim'}).first().click();
  await page.getByLabel('Atomic claim text').first().fill('Test draft retained across reload');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Draft saved');
  const runId=await page.locator('.review-panel').getAttribute('data-run-id');
  await page.reload();
  await page.locator('.history button').filter({hasText:runId!.slice(0,6)}).click();
  await page.getByRole('button',{name:'Review report',exact:true}).click();
  await expect(page.getByLabel('Atomic claim text').first()).toHaveValue('Test draft retained across reload');
  await page.getByRole('button',{name:'Finalize review',exact:true}).click();
  await expect(page.locator('.review-panel [role=alert]')).toBeVisible();
});
test('compare real fixed and adaptive runs from one frozen snapshot without a winner',async({page})=>{
  await page.goto(url);
  await page.getByLabel('Workflow',{exact:true}).selectOption('fixed');
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByLabel('Workflow',{exact:true}).selectOption('adaptive');
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Compare runs',exact:true}).click();
  await page.getByRole('button',{name:'Compare selected runs',exact:true}).click();
  await expect(page.getByText('Same frozen snapshot',{exact:true})).toBeVisible();
  await expect(page.getByText(/no benchmark correctness or winner inferred/)).toBeVisible();
  await expect(page.getByText('Pending human review').first()).toBeVisible();
});

test('isolated fixture reviewer can split claims, classify nonfactual units and finalize',async({page})=>{
  await page.goto(url);
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Review report',exact:true}).click();
  await page.getByLabel('Reviewer name').fill('AUTOMATED SOFTWARE TEST ONLY');
  const classifications=page.getByRole('combobox',{name:/Text classification/});
  for(let i=0;i<await classifications.count();i++) await classifications.nth(i).selectOption('nonfactual');
  await page.getByRole('button',{name:'Add atomic claim'}).first().click();
  await page.getByLabel('Atomic claim text').first().fill('Synthetic test judgment; not a human review');
  await page.getByLabel('Support judgment').first().selectOption('unjudgeable');
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Finalize review',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('Review finalized');
  await expect(page.getByText('Final human review',{exact:true})).toBeVisible();
});
test('hypotheses and UTC timeline expose supporting sources and event ordering',async({page})=>{
 await page.goto(url);
 await page.getByRole('button',{name:'Start investigation'}).click();
 await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
 await page.getByRole('button',{name:'Investigation context',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Hypotheses'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Incident timeline · UTC'})).toBeVisible();
 await expect(page.getByText(/Temporal proximity does not establish causation/)).toBeVisible();
 const events=page.locator('.timeline-list li time');
 await expect(events.first()).toBeVisible();
 const times=await events.evaluateAll(items=>items.map(e=>e.getAttribute('datetime')));
 expect(times).toEqual([...times].sort());
 await page.locator('.context-panel').getByRole('button',{name:/Open evidence/}).first().click();
 await expect(page.getByRole('heading',{name:'Evidence inspector'})).toBeFocused();
});
test('completed unreviewed reports show pending status without opening the editor',async({page})=>{
 await page.goto(url);
 await page.getByRole('button',{name:'Start investigation'}).click();
 await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
 await expect(page.getByText('Report review: pending',{exact:true})).toBeVisible();
});
test('trace fixture shows correlated spans and stress fixtures stay clearly labeled',async({page})=>{
 await page.goto(url);
 await page.getByLabel('Replay case').selectOption('demo-traces');
 await page.getByRole('button',{name:'Start investigation'}).click();
 await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
 await page.getByRole('button',{name:'Investigation context',exact:true}).click();
 await page.getByLabel('Event type').selectOption('trace_span');
 await expect(page.locator('.timeline-list li')).toHaveCount(4);
 await page.locator('.timeline-list li').last().getByRole('button').click();
 await expect(page.getByRole('heading',{name:'Evidence inspector'})).toBeFocused();
 await expect(page.locator('.inspector pre').first()).toContainText('parent_span_id');
 await page.getByLabel('Replay case').selectOption('stress-healthy-lookalike');
 await expect(page.locator('.case-meta')).toContainText('handcrafted stress fixture');
 await page.getByRole('button',{name:'Start investigation'}).click();
 await expect(page.getByRole('heading',{name:'Insufficient evidence'})).toBeVisible();
});
test('review citations wrap on narrow screens with many cited sources',async({page})=>{
 await page.setViewportSize({width:390,height:850});
 await page.route(/\/api\/runs\/[^/]+$/,async route=>{
  const response=await route.fetch();const job=await response.json();
  if(job.result?.report?.likely_cause){
   const original=Object.values(job.result.evidence)[0];
   const ids=Array.from({length:10},(_,i)=>`ui-test-source-${i}`);
   for(const id of ids)job.result.evidence[id]={...(original as object),evidence_id:id};
   job.result.report.likely_cause.evidence_ids=ids;
  }
  await route.fulfill({response,json:job});
 });
 await page.goto(url);
 await page.getByRole('button',{name:'Start investigation'}).click();
 await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
 await page.getByRole('button',{name:'Review report',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Human claim review'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const source=page.getByRole('button',{name:/Cited source/}).first();
 await source.click();
 await expect(page.locator('.review-evidence details[open]')).toBeInViewport();
 await page.getByRole('button',{name:'Back to reviewed text'}).click();
 await expect(source).toBeFocused();
});

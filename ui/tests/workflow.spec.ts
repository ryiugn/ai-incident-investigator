import {test, expect} from '@playwright/test';
const url=process.env.INVESTIGATOR_URL || 'http://127.0.0.1:18090';

test('recorded playback navigates real steps and opens run-bound evidence',async({page})=>{
  await page.goto(url);
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await expect(page.getByText('Recorded playback · completed boundaries',{exact:true})).toBeVisible();
  const steps=page.getByRole('combobox',{name:/^Recorded step/});
  await steps.selectOption('1');
  await expect(page.getByTestId('step-details')).toContainText('Choose a first step');
  await page.getByRole('button',{name:'Next recorded step'}).press('Enter');
  await expect(steps).toHaveValue('2');
  await steps.selectOption('3');
  await page.getByRole('button',{name:/Inspect collected evidence/}).first().click();
  await expect(page.getByRole('heading',{name:'Step evidence'})).toBeFocused();
  await expect(page.getByTestId('step-evidence')).toContainText('Coverage');
  await page.getByRole('button',{name:'Back to recorded step'}).click();
  await expect(page.getByRole('button',{name:/Inspect collected evidence/}).first()).toBeFocused();
  await page.setViewportSize({width:390,height:850});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('workflow shows a real approval wait and links to the exact approval controls',async({page})=>{
  await page.goto(url);
  await page.getByLabel('Replay case').selectOption('demo-approval');
  await page.getByRole('button',{name:'Start investigation'}).click();
  await expect(page.getByRole('heading',{name:'Review expanded evidence query'})).toBeVisible();
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await expect(page.getByTestId('workflow-status')).toContainText('Waiting for approval');
  await page.getByRole('button',{name:'Open approval controls'}).click();
  await page.getByRole('button',{name:'Decline and finalize'}).click();
  await expect(page.getByText('Expanded evidence query declined by the user; assessment uses only evidence already collected.',{exact:true})).toBeVisible();
});

test('switching workflow runs clears the previous evidence inspector',async({page})=>{
  await page.goto(url);
  const firstRun=page.waitForResponse(r=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Start investigation'}).click();
  const firstId=(await (await firstRun).json()).run_id;
  await expect(page.getByRole('heading',{name:'Observed failure condition'})).toBeVisible();
  await page.getByLabel('Replay case').selectOption('demo-missing');
  const secondRun=page.waitForResponse(r=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Start investigation'}).click();
  const secondId=(await (await secondRun).json()).run_id;
  await expect(page.getByRole('heading',{name:'Insufficient evidence',exact:true})).toBeVisible();
  await page.locator('.history button').filter({hasText:firstId.slice(0,6)}).click();
  await page.getByRole('button',{name:'Inspect evidence 1',exact:true}).first().click();
  await expect(page.locator('#evidence-inspector')).toContainText('Content hash');
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await page.getByLabel('Saved run').selectOption(secondId);
  await page.getByRole('button',{name:'Open report and citations'}).click();
  await expect(page.getByRole('heading',{name:'Insufficient evidence',exact:true})).toBeVisible();
  await expect(page.locator('#evidence-inspector')).not.toContainText('Content hash');
});

test('legacy interrupted runs show uncertainty without invented completed steps',async({page})=>{
  // Deliberately old API fixture: historical archives have no execution_steps.
  const job={run_id:'legacy-unknown',workflow:'adaptive',state:'interrupted',resumable:false,
    recovery_message:'A dispatched call has an unknown outcome. Reservations are retained.',
    result:{nodes:['validate_alert','triage'],report:null,evidence:{},events:[],
      usage:{tool_dispatches:0,model_requests:1,elapsed_ms:20000,estimated_cost_usd:0},termination_reason:'report'}};
  await page.route('**/api/runs',r=>r.fulfill({json:[job]}));
  await page.route('**/api/runs/legacy-unknown',r=>r.fulfill({json:job}));
  await page.goto(url);
  await page.getByRole('button',{name:'Graph walkthrough',exact:true}).click();
  await page.getByLabel('Saved run').selectOption('legacy-unknown');
  await expect(page.getByTestId('workflow-status')).toContainText('Interrupted');
  await expect(page.getByText(/A dispatched call has an unknown outcome/)).toBeVisible();
  await expect(page.getByText(/No completed step details were recorded/)).toBeVisible();
  await expect(page.getByText('Recorded stop reason: Not available yet',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Next recorded step'})).toHaveCount(0);
});

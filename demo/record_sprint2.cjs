// Real loopback browser recording; no screenshots or business outcomes are fabricated.
// Requires Playwright and a fresh demo/run_sprint2.py database on port 8774.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = path.resolve(process.argv[2]);
fs.mkdirSync(output, {recursive: true});
const base = 'http://127.0.0.1:8774';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const frames = [], steps = [], errors = [];
let browser, session, started;

(async () => {
  browser = await chromium.launch({headless: true,
    executablePath: process.env.BBMS_BROWSER_PATH || 'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}, deviceScaleFactor: 1});
  await context.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '*{cursor:none!important}';
      document.head.append(style);
    });
    document.addEventListener('pointerdown', event => {
      const dot = document.createElement('div');
      Object.assign(dot.style, {position:'fixed', left:(event.clientX-14)+'px', top:(event.clientY-14)+'px',
        width:'28px',height:'28px',borderRadius:'50%',background:'#8887',border:'2px solid #777a',
        pointerEvents:'none',zIndex:'2147483647',transition:'opacity 1s,transform 1s'});
      document.documentElement.append(dot);
      requestAnimationFrame(() => {dot.style.opacity='0';dot.style.transform='scale(1.5)';});
      setTimeout(() => dot.remove(), 1100);
    }, true);
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('dialog', dialog => dialog.accept());
  page.setDefaultTimeout(12000);
  await page.goto(base + '/', {waitUntil:'networkidle'});
  session = await context.newCDPSession(page);
  started = Date.now();
  session.on('Page.screencastFrame', async event => {
    const file = `frame-${String(frames.length).padStart(6,'0')}.jpg`;
    fs.writeFileSync(path.join(output,file), Buffer.from(event.data,'base64'));
    frames.push({file, time:(Date.now()-started)/1000});
    await session.send('Page.screencastFrameAck',{sessionId:event.sessionId}).catch(()=>{});
  });
  await session.send('Page.startScreencast',{format:'jpeg',quality:90,maxWidth:1600,maxHeight:1000,everyNthFrame:1});
  async function step(label, action, hold=2500) {
    await action(); await sleep(500);
    assert.equal(new URL(page.url()).origin, base);
    const file = `check-${String(steps.length).padStart(2,'0')}.png`;
    await page.screenshot({path:path.join(output,file)});
    steps.push({label, file, time:(Date.now()-started)/1000, url:page.url()});
    console.log(label); await sleep(hold);
  }
  const click = (label, target, hold) => step(label,()=>target.click(),hold);
  async function type(label, target, value) {
    await step(label,async()=>{await target.click();await target.pressSequentially(value,{delay:140});},1500);
  }
  async function login(name) {
    await step(`${name}: sign-in page`,()=>page.goto(base+'/accounts/login/'));
    await type(`${name}: account`,page.locator('#id_username'),name);
    await type(`${name}: password`,page.locator('#id_password'),process.env.BBMS_DEMO_PASSWORD || 'SyntheticDemo!49');
    await click(`${name}: signed in`,page.getByRole('button',{name:'Sign In',exact:false}));
  }
  async function logout() {
    await click('Account navigation menu',page.locator('#userMenuDropdown'),1500);
    await click('Sign out',page.getByRole('button',{name:'Logout',exact:false}),1500);
  }
  await step('Running BBMS home',async()=>{},4000);
  await login('abhinav');
  await click('Hospital portal',page.getByRole('link',{name:'Hospital Portal',exact:false}));
  await click('New hospital requisition',page.getByRole('link',{name:'New requisition'}));
  await click('Blood-group dropdown open',page.locator('#id_blood_group'),3500);
  await step('B+ selected',async()=>{await page.keyboard.press('b');await sleep(800);await page.keyboard.press('Enter');});
  assert.equal(await page.locator('#id_blood_group').inputValue(),'B+');
  await click('Component dropdown open',page.locator('#id_component_type'),3500);
  await step('Red Blood Cells selected',async()=>{await page.keyboard.press('r');await sleep(800);await page.keyboard.press('Enter');});
  await type('Quantity: two units',page.locator('#id_quantity'),'2');
  const required = new Date(); required.setDate(required.getDate()+2);
  await step('Required-by date',()=>page.locator('#id_required_by').fill(required.toISOString().slice(0,10)));
  await click('Emergency / STAT priority',page.locator('#id_is_stat'));
  await click('Hospital request submitted',page.getByRole('button',{name:'Submit requisition'}),4000);
  const requestPath = new URL(page.url()).pathname;
  assert.match(requestPath,/\/requisitions\/\d+\//);
  await logout(); await login('uttam');
  await click('Live STAT alert and staff queue',page.getByRole('link',{name:'Open review queue'}));
  await click('Review Abhinav Hospital request',page.locator('td a').first());
  await click('Staff approval recorded',page.getByRole('button',{name:'Record review'}),3500);
  await type('Cross-match actual Bag ID',page.locator('#id_cross_match_bag_id'),'BAG-ABHINAV-01');
  await click('Compatible cross-match recorded',page.getByRole('button',{name:'Record Cross-Match'}),3000);
  await click('FEFO allocation suggestions',page.getByRole('link',{name:'Allocate Units (FEFO)'}),4000);
  await click('Earliest-expiring bag selected',page.locator('.unit-checkbox').first());
  await click('Second compatible bag selected',page.locator('.unit-checkbox').nth(1));
  await click('Allocation committed',page.getByRole('button',{name:'Confirm Allocation'}));
  await click('Dispatch reserved units',page.getByRole('link',{name:'Dispatch Reserved Units'}),3500);
  await click('Dispatch committed and manifest generated',page.getByRole('button',{name:'Confirm Dispatch & Generate Manifest'}),5000);
  assert.match(page.url(),/\/manifests\//);
  await logout(); await login('abhinav');
  await step('Owning hospital tracks dispatch',()=>page.goto(base+requestPath),4000);
  await step('Receipt controls and dispatched Bag IDs',()=>page.getByRole('heading',{name:'Confirm receipt',exact:true}).scrollIntoViewIfNeeded(),3000);
  await click('First bag physically received',page.locator('input[name="bag_ids"]').first());
  await click('Second bag physically received',page.locator('input[name="bag_ids"]').nth(1));
  await click('Hospital receipt committed',page.getByRole('button',{name:'Confirm selected bags received'}));
  await step('Delivered bags and receiver identity',()=>page.getByRole('heading',{name:'Delivery tracking and receipt history'}).evaluate(e=>e.scrollIntoView({block:'center'})),5000);
  assert.equal(await page.locator('td').filter({hasText:/^Delivered$/}).count(),2);
  await logout(); await login('akshay');
  await step('Component separation: safe whole blood',()=>page.goto(base+'/inventory/blood-units/BAG-AKSHAY-WHOLE/separate/'),3000);
  await step('Traceable components and volumes',()=>page.locator('#id_volume_plasma').scrollIntoViewIfNeeded(),4000);
  await click('Execute component separation',page.getByRole('button',{name:'Execute Component Separation',exact:false}),3500);
  await step('Parent / child component traceability',()=>page.getByText('Child', {exact:false}).first().scrollIntoViewIfNeeded().catch(()=>{}),3500);
  await step('Inventory, donation and requisition reports',()=>page.goto(base+'/reports/'),3500);
  await click('Requisition fulfilment report',page.locator('#requisitions-tab'),3500);
  const downloadPromise=page.waitForEvent('download');
  await click('Download actual CSV report',page.locator('#requisitions-pane a[href*="csv"]'),2000);
  const download=await downloadPromise;
  await download.saveAs(path.join(output,'requisitions.csv'));
  await step('Central tamper-evident audit log',()=>page.goto(base+'/audit-log/'),5000);
  assert.match(await page.locator('body').innerText(),/Verified & Tamper-Free/);
  await step('Read-only audit records and team actors',()=>page.locator('table').scrollIntoViewIfNeeded(),5000);
  if(Date.now()-started<240000) await sleep(240000-(Date.now()-started));
  await session.send('Page.stopScreencast');
  fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify({duration:(Date.now()-started)/1000,frames,steps,errors},null,2));
  await browser.close(); console.log('RECORDING VERIFIED');
})().catch(async error=>{
  fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({error:String(error),frames,steps,errors},null,2));
  if(browser) await browser.close(); console.error(error); process.exitCode=1;
});

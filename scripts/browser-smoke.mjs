// Optional local UI verification using the bundled Playwright; no user data writes.
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const dependencyRoot=process.env.ARTIFACT_NODE_MODULES||join(process.env.USERPROFILE||'', '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const require=createRequire(join(dependencyRoot,'package.json'));
const {chromium}=require('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1365,height:900}});
 page.on('pageerror',e=>errors.push(e.message));
 const response=await page.goto('http://localhost:3000/',{waitUntil:'networkidle'});
 assert.equal(response.status(),200);
 assert.equal(await page.title(),'Edentica');
 await page.getByRole('heading',{name:'Мои программы',exact:true}).waitFor();
 assert.equal(await page.locator('.brand-mark').evaluate(el=>el.complete&&el.naturalWidth>0),true);
 await mkdir('output/postgres-qa',{recursive:true});
 await page.screenshot({path:'output/postgres-qa/home-desktop.png',fullPage:true});
 await page.locator('#header-login').click();
 await page.getByRole('heading',{name:'Войти в Edentica',exact:true}).waitFor();
 await page.locator('#close-auth').click();
 await page.locator('#skills-nav').click();
 await page.getByRole('heading',{name:'Навыки ИИ-методиста',exact:true}).waitFor();
 await page.locator('#home').click();
 await page.setViewportSize({width:390,height:844});
 await page.getByRole('heading',{name:'Мои программы',exact:true}).waitFor();
 await page.screenshot({path:'output/postgres-qa/home-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('Browser smoke: desktop, mobile, logo, login dialog and skills passed; no JavaScript errors.');
}finally{await browser.close()}

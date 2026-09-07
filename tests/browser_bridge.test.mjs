import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { extractPageScript, sanitizeData, runBrowserCli } from '../src/threads_cli/browser_bridge.mjs';

function post() {
  return { code: 'ROOT123', pk: '123', user: {username:'alice', full_name:'Alice', private_secret:'not-exported'},
    caption: {text:'CS2 完美C+ 找队友'}, taken_at:1788739200, like_count:0,
    text_post_app_info:{direct_reply_count:2,is_reply:false}, logging_info_token:'not-exported', __token:'not-exported' };
}
function data() {
  return {searchResults:{edges:[{node:{thread:{thread_items:[{post:post()}]}}}],
    page_info:{has_next_page:true,end_cursor:'cursor1'}}};
}
test('whitelist preserves post evidence and strips account/request data', () => {
  const out = sanitizeData(data(), 'search');
  const text = JSON.stringify(out);
  assert(!text.includes('not-exported'));
  const p = out.searchResults.edges[0].node.thread.thread_items[0].post;
  assert.equal(p.caption.text,'CS2 完美C+ 找队友');
  assert.equal(p.like_count,0);
  assert.equal(out.searchResults.page_info.end_cursor,'cursor1');
});
test('caption fragments survive missing caption', () => {
  const p = post(); p.caption=null; p.text_post_app_info.text_fragments={fragments:[{plaintext:'找队友'}]};
  assert.equal(sanitizeData({media:p},'post').media.caption.text,'找队友');
});
test('DOM extractor is executable and does not touch credentials', () => {
  const script = {textContent:JSON.stringify({result:{data:data()}})};
  const svg = {getAttribute:()=> 'Profile',closest:()=>({getAttribute:()=>'/@larryhaoai'})};
  const document = {body:{innerText:'CS2'},querySelectorAll:selector=>selector.startsWith('script')?[script]:[svg]};
  Object.defineProperty(document,'cookie',{get(){throw new Error('Credential read forbidden');}});
  const fn = vm.runInNewContext('('+extractPageScript+')',{document});
  const result = fn({kind:'search'});
  assert.equal(result.authenticated,true);
  assert.equal(result.viewer,'larryhaoai');
  assert.equal(result.data_roots.length,1);
  assert(!JSON.stringify(result).includes('not-exported'));
});
test('login wall is not a successful empty search', () => {
  const document={body:{innerText:'Log in or sign up for Threads'},querySelectorAll:()=>[]};
  const fn=vm.runInNewContext('('+extractPageScript+')',{document});
  const result=fn({kind:'search'});
  assert.equal(result.authenticated,false);
  assert.equal(result.login_visible,true);
});
test('write commands are rejected before browser access', async () => {
  await assert.rejects(runBrowserCli({},['post','hello']),/allowlisted/);
});
test('unrelated origins are not collected', async () => {
  await assert.rejects(runBrowserCli({url:async()=> 'https://example.com'},['search','cs2']),/Threads tab/);
});

test('browser content crosses the real CLI pipe and persists without session data', async () => {
  const directory=await mkdtemp(join(tmpdir(),'threads-bridge-test-'));
  let current='https://www.threads.com/';
  const calls=[];
  const cdp={send:async(method)=>{calls.push(method);return {};},readEvents:async()=>({cursor:1,events:[],hasMore:false,truncated:false})};
  const tab={url:async()=>current,goto:async(url)=>{current=url;},reload:async()=>{},
    capabilities:{get:async()=>cdp},playwright:{evaluate:async()=>({data_roots:[sanitizeData(data(),'search')],
      authenticated:true,viewer:'larryhaoai',ready:true,login_visible:false})}};
  try {
    const result=await runBrowserCli(tab,['search','cs2','--pages','1'],{
      executable:process.env.THREADS_TEST_EXECUTABLE ?? fileURLToPath(new URL('../.venv/bin/threads',import.meta.url)),dataDir:directory,viewer:'larryhaoai'});
    assert.equal(result.exit_code,0);
    assert.equal(result.posts[0].text,'CS2 完美C+ 找队友');
    assert.equal(result.auth_mode,'browser');
    assert.equal(result.completion,'page_limit_reached');
    assert.deepEqual(calls,['Network.enable']);
    const database=await readFile(join(directory,'evidence.sqlite3'));
    assert(!database.includes(Buffer.from('not-exported')));
  } finally { await rm(directory,{recursive:true,force:true}); }
});

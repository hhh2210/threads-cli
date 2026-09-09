import test from 'node:test';
import assert from 'node:assert/strict';
import {extractDM} from '../src/threads_cli/browser_dm.mjs';
test('DM whitelist keeps server message IDs and strips session and profile internals',()=>{
  const r=JSON.parse(extractDM({raw:{get_slide_thread:{id:'123456',__token:'secret',is_group:false,
    members:{nodes:[{id:'1',as_micg_interface:{username:'alice',__token:'secret'}}]},
    messages:{edges:[{node:{id:'mid.1',content:{text_body:'hello',__typename:'Text'},
      sender:{as_micg_interface:{username:'alice',__token:'secret'}},
      as_micg_interface:{message_id:'mid.1',timestamp_ms:'100000',offline_threading_id:'secret'}}}],
      page_info:{has_previous_page:true}}}}}));
  assert.equal(r.messages[0].message_id,'mid.1');assert.equal(r.messages[0].sender,'alice');
  assert.equal(r.messages[0].text,'hello');assert(!JSON.stringify(r).includes('secret'));
  assert.equal(r.has_more,true);
});

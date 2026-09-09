import test from 'node:test';
import assert from 'node:assert/strict';
import {extractNotifications} from '../src/threads_cli/browser_notifications.mjs';

test('reply notification keeps author/content/context and drops account internals',()=>{
  const result=JSON.parse(extractNotifications({raw:{notifications:{
    edges:[{node:{story_type:948,args:{tuuid:'notice-1',profile_name:'alice',timestamp:1788915116,
      __token:'must-not-leak',destination:'media?shortcode=ABC123&username=alice&id=internal',
      extra:{icon_name:'reply',title:'{alice|0000|1|user?id=internal|none}',content:'可以，一起',
        context:'邀请',media_dict:{code:'ABC123',user:{username:'alice'},logging_info_token:'must-not-leak'}}}}}],
    page_info:{has_next_page:true,end_cursor:'cursor1'}}}}));
  assert.equal(result.items[0].kind,'reply');
  assert.equal(result.items[0].title,'alice');
  assert.equal(result.items[0].url,'https://www.threads.com/@alice/post/ABC123');
  assert.equal(result.items[0].context,'邀请');
  assert(!JSON.stringify(result).includes('must-not-leak'));
  assert(!JSON.stringify(result).includes('internal'));
  assert.equal(result.has_more,true);
});
test('empty inbox and missing schema remain distinct',()=>{
  assert.equal(JSON.parse(extractNotifications({raw:{}})).ready,false);
  const empty=JSON.parse(extractNotifications({raw:{notifications:{edges:[],page_info:{has_next_page:false}}}}));
  assert.equal(empty.ready,true);assert.deepEqual(empty.items,[]);assert.equal(empty.has_more,false);
});
test('unknown types and malformed destination are not invented as replies',()=>{
  const r=JSON.parse(extractNotifications({raw:{notifications:{edges:[{node:{args:{tuuid:'1',
    destination:'media?username=evil/path&shortcode=abc',extra:{icon_name:'future-kind'}}}}],page_info:{}}}}));
  assert.equal(r.items[0].kind,'other');assert.equal(r.items[0].url,null);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {publishPost} from '../src/threads_cli/browser_post.mjs';

function fixture() {
  const state={open:false,text:'',prompt:false,sent:0};
  const editor={waitFor:async()=>{},innerText:async()=>state.text,fill:async text=>{state.text=text;}};
  const dialog={
    getByRole(role,opts){
      if(role==='textbox')return editor;
      if(role==='img')return {count:async()=>1};
      if(opts.name==='Cancel')return {click:async()=>{state.prompt=true;}};
      if(opts.name==="Don't save")return {count:async()=>state.prompt?1:0,
        click:async()=>{state.prompt=false;state.open=false;}};
      if(opts.name==='Post')return {click:async()=>{state.sent++;state.open=false;}};
      throw Error('unexpected control');
    },
    waitFor:async()=>{assert.equal(state.open,false);assert.equal(state.prompt,false);}
  };
  const tab={playwright:{evaluate:async()=>state.sent?['/@larryhaoai/post/NEW1234']:[],
    getByRole(role,opts){if(role==='dialog')return dialog;
      assert.equal(opts.name,'New thread');return {click:async()=>{state.open=true;}};}}};
  const read=async req=>req.kind==='status'?{viewer:'larryhaoai'}:
    {data_roots:[{media:{code:'NEW1234',user:{username:'larryhaoai'},caption:{text:state.text},
      text_post_app_info:{is_reply:false}}}]};
  const fail=(code,message)=>Object.assign(Error(message),{code});
  return {state,tab,read,fail};
}
test('composer check discards only its test draft and never clicks Post',async()=>{
  const f=fixture();const r=await publishPost(f.tab,{viewer:'larryhaoai',text:'test',check_composer:true},f.read,f.fail);
  assert.equal(r.status,'composer_verified');assert.equal(r.published,false);
  assert.equal(f.state.sent,0);assert.equal(f.state.text,'');assert.equal(f.state.open,false);
});
test('standalone publishing verifies exactly one new post',async()=>{
  const f=fixture();const r=await publishPost(f.tab,{viewer:'larryhaoai',text:'test'},f.read,f.fail);
  assert.equal(f.state.sent,1);assert.equal(r.url,'https://www.threads.com/@larryhaoai/post/NEW1234');
  assert.equal(r.in_reply_to,null);
});
test('existing draft is preserved without publication',async()=>{
  const f=fixture();f.state.text='user draft';
  await assert.rejects(publishPost(f.tab,{viewer:'larryhaoai',text:'test'},f.read,f.fail),e=>e.code==='not_submitted');
  assert.equal(f.state.text,'user draft');assert.equal(f.state.sent,0);
});

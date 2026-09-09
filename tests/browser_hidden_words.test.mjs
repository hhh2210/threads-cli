import test from 'node:test';
import assert from 'node:assert/strict';
import {assertSaved, manageHiddenWords, planWords, HIDDEN_WORDS_URL} from '../src/threads_cli/browser_hidden_words.mjs';

const fail = (code,message) => Object.assign(new Error(message), {code});
const base = () => ({name:'Filter', description:'Keep this description', scope:'PeopleYouDontFollow',
  duration:'2', words:['Club','原有词']});

function fixture(options = {}) {
  const state = {url:HIDDEN_WORDS_URL, saved:options.missing?null:base(), draft:null,
    dialog:options.existingDialog?'other':null, input:'', saves:0, batches:[], reloads:0, opens:0};
  const tab = {
    url:async()=>state.url,
    goto:async url=>{state.url=url; state.dialog=null;},
    reload:async()=>{state.dialog=null;state.draft=null;state.reloads++;},
    playwright:{
      expectNavigation:async action=>action(),
      evaluate:async (fn,{mode})=>{
        const viewer = options.wrongAccount?'bob':'alice';
        if(mode==='list') return JSON.stringify({ready:true,viewer,filters:state.saved?[{
          name:state.saved.name, word_count:state.saved.words.length,
          control_name:'Filter row', state:'Off'}]:[]});
        if(mode==='editor') {
          assert.equal(state.dialog,'editor');
          return JSON.stringify({ready:true,viewer,...state.draft});
        }
        assert.equal(state.dialog,'words');
        return JSON.stringify({ready:true,viewer,words:state.draft.words});
      },
      getByRole:(role,{name}={})=>{
        if(role==='dialog') return {count:async()=>state.dialog?1:0};
        if(role==='textbox') return {fill:async text=>{
          if(name==='Filter name')state.draft.name=text;
          else {assert.equal(name,'Add words separated by commas...');state.input=text;}
        }};
        assert.equal(role,'button');
        return {isEnabled:async()=>true,click:async()=>{
          if(name==='Filter row' || name==='Create New filter') {
            state.opens++;
            if(options.unhydrated && state.opens===1)return;
            state.draft=structuredClone(state.saved || {name:'',description:'',scope:'Anyone',duration:'0',words:[]});
            state.dialog='editor';
          } else if(name==='Create Add words') state.dialog='words';
          else if(name==='Add') {
            const batch=state.input.split(',');state.batches.push(batch);
            state.draft.words.push(...batch);state.input='';
          } else if(name==='Back') state.dialog='editor';
          else if(name==='Save') {
            state.saves++;state.saved=structuredClone(state.draft);state.dialog=null;
            if(options.dropOriginal)state.saved.words.shift();
            if(options.changeScope)state.saved.scope='Anyone';
            if(options.saveThrows)throw Error('Connection lost after save');
          } else throw Error(`Unexpected button ${name}`);
        }};
      },
    },
  };
  const req={operation:'add',viewer:'alice',filter_name:'Filter',words:['club','新词'],apply:true};
  return {state,tab,req};
}

test('planning deduplicates case and Unicode without splitting phrases',()=>{
  assert.deepEqual(planWords(['Club','Café'],['club','Cafe\u0301','multi word phrase','MULTI WORD PHRASE']),
    {added:['multi word phrase'],skipped:['club','Cafe\u0301','MULTI WORD PHRASE']});
});
test('existing words and every unrelated filter setting must survive',()=>{
  const before=base();
  assert.throws(()=>assertSaved(before,{...before,words:['new']},['new'],fail),{code:'verification_failed'});
  for(const key of ['name','description','scope','duration'])
    assert.throws(()=>assertSaved(before,{...before,[key]:'changed'},[],fail),{code:'verification_failed'});
});
test('bulk append crosses batch boundary and preserves disabled status and scope',async()=>{
  const f=fixture();f.req.words=['club',...Array.from({length:54},(_,i)=>`new ${i}`)];
  const r=await manageHiddenWords(f.tab,f.req,fail);
  assert.equal(r.status,'verified');assert.equal(f.state.saves,1);
  assert.deepEqual(f.state.batches.map(b=>b.length),[50,4]);
  assert.equal(r.words.length,56);assert.deepEqual(r.skipped,['club']);
  assert.equal(r.settings.duration,'2');assert.equal(r.settings.scope,'PeopleYouDontFollow');
  assert.equal(r.settings.description,'Keep this description');
  assert(f.state.reloads>=2);assert.equal(f.state.dialog,null);
});
test('live preview and all-existing retries never click Save',async()=>{
  for(const apply of [false,true]) {
    const f=fixture();f.req.apply=apply;f.req.words=apply?['club','原有词']:['new'];
    const r=await manageHiddenWords(f.tab,f.req,fail);
    assert.equal(r.status,apply?'unchanged':'preview');assert.equal(f.state.saves,0);
    assert.equal(f.state.dialog,null);
  }
});
test('missing filter fails closed unless explicitly creating',async()=>{
  const f=fixture({missing:true});
  await assert.rejects(manageHiddenWords(f.tab,f.req,fail),{code:'filter_not_found'});
  assert.equal(f.state.saves,0);
  f.req.create=true;
  const result=await manageHiddenWords(f.tab,f.req,fail);
  assert.equal(result.created,true);assert.equal(result.settings.duration,'0');
  assert.equal(result.settings.scope,'Anyone');assert.equal(f.state.saves,1);
});
test('wrong account or existing dialog cannot be overwritten',async()=>{
  for(const [option,code] of [['wrongAccount','account_mismatch'],['existingDialog','draft_present']]) {
    const f=fixture({[option]:true});
    await assert.rejects(manageHiddenWords(f.tab,f.req,fail),{code});
    assert.equal(f.state.saves,0);
    if(option==='existingDialog')assert.equal(f.state.dialog,'other');
  }
});
test('server loss of words/settings or uncertain save is never retried',async()=>{
  for(const option of ['dropOriginal','changeScope','saveThrows']) {
    const f=fixture({[option]:true});
    await assert.rejects(manageHiddenWords(f.tab,f.req,fail),{code:'save_unconfirmed'});
    assert.equal(f.state.saves,1);
  }
});
test('an ignored pre-hydration opener is retried only after observing no dialog',async()=>{
  const f=fixture({unhydrated:true});
  const r=await manageHiddenWords(f.tab,f.req,fail);
  assert.equal(r.status,'verified');assert.equal(f.state.saves,1);
  assert.equal(f.state.opens,3); // two initial attempts, one read-back opener
});
test('ambiguous filter names cannot select an arbitrary target',async()=>{
  const f=fixture();const evaluate=f.tab.playwright.evaluate;
  f.tab.playwright.evaluate=async(fn,arg)=>{
    const value=JSON.parse(await evaluate(fn,arg));
    if(arg.mode==='list')value.filters.push({...value.filters[0]});
    return JSON.stringify(value);
  };
  await assert.rejects(manageHiddenWords(f.tab,f.req,fail),{code:'ambiguous_filter'});
  assert.equal(f.state.saves,0);assert.equal(f.state.opens,0);
});

/** Standalone text posts, using the same explicit publish/verify contract as replies. */
function ownLinks({viewer}) {
  return [...new Set([...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href'))
    .filter(h=>h.startsWith(`/@${viewer}/post/`)))];
}
function findPost(page,code) {
  let found;
  function walk(x){if(!x||typeof x!=='object')return;
    if(x.code===code&&x.user?.username){found=x;return;}
    for(const v of Object.values(x))walk(v);}
  walk(page.data_roots);return found;
}
export async function publishPost(tab,req,readPage,fail) {
  let attempted=false, stage="session";
  try {
    const session=await readPage({url:'https://www.threads.com/',kind:'status'});
    if(session.viewer!==req.viewer)throw fail('account_mismatch','Post sender did not match.');
    stage="existing_links";
    const before=new Set(await tab.playwright.evaluate(ownLinks,{viewer:req.viewer}));
    stage="open_composer";
    await tab.playwright.getByRole('button',{name:'New thread',exact:true}).click();
    const dialog=tab.playwright.getByRole('dialog');
    stage="editor";
    const editor=dialog.getByRole('textbox',{name:'Empty text field. Type to compose a new post.',exact:true});
    await editor.waitFor({state:'visible',timeoutMs:15000});
    stage="sender";
    if(await dialog.getByRole('img',{name:`${req.viewer}'s profile picture`,exact:true}).count()<1)
      throw fail('account_mismatch','Composer author did not match.');
    stage="empty_draft";
    if((await editor.innerText()).trim())throw fail('not_submitted','Existing draft preserved; not overwritten.');
    stage="fill";
    await editor.fill(req.text);
    stage="draft_match";
    if((await editor.innerText()).trim()!==req.text.trim())throw fail('not_submitted','Draft did not match.');
    if(req.check_composer) {
    stage="clear";
      await editor.fill('');
    stage="cancel";
      await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
      const discard=dialog.getByRole('button',{name:"Don't save",exact:true});
      if(await discard.count()) await discard.click();
    stage="closed";
      await dialog.waitFor({state:'hidden',timeoutMs:10000});
      return {status:'composer_verified',username:req.viewer,text:req.text,published:false};
    }
    attempted=true;
    await dialog.getByRole('button',{name:'Post',exact:true}).click();
    await dialog.waitFor({state:'hidden',timeoutMs:20000});
    const deadline=Date.now()+25000;let href;
    do {
      href=(await tab.playwright.evaluate(ownLinks,{viewer:req.viewer})).find(h=>!before.has(h));
      if(href)break;
      await new Promise(resolve=>setTimeout(resolve,700));
    } while(Date.now()<deadline);
    if(!href)throw fail('send_unconfirmed','No published permalink found.');
    const url=`https://www.threads.com${href}`,code=href.split('/post/')[1].split(/[/?#]/)[0];
    const page=await readPage({url,kind:'post',root_code:code});
    const post=findPost(page,code);
    if(post?.user?.username!==req.viewer||post?.caption?.text!==req.text||post?.text_post_app_info?.is_reply)
      throw fail('send_unconfirmed','Standalone post read-back did not match.');
    return {status:'sent',username:req.viewer,text:req.text,url,in_reply_to:null};
  } catch(error) {
    throw fail(attempted?'send_unconfirmed':'not_submitted',attempted
      ? 'Post was attempted but could not be verified; do not resend.'
      : `Post preparation failed at ${stage}; no post was sent. (${error.name || 'Error'})`);
  }
}

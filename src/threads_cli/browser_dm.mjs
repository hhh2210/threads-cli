/** Bounded private-message data for an explicitly selected conversation. */
export function extractDM({raw=null}={}) {
  let thread=raw?.get_slide_thread;
  if(!raw){function walk(x){if(!x||typeof x!=='object')return;
    if(x.result?.data?.get_slide_thread)thread=x.result.data.get_slide_thread;
    for(const v of Object.values(x))walk(v);}
    for(const s of document.querySelectorAll('script[type="application/json"]')){
      try{walk(JSON.parse(s.textContent));}catch{}}
  }
  if(!thread?.id||!Array.isArray(thread.messages?.edges))return JSON.stringify({ready:false});
  const members=(thread.members?.nodes||[]).map(u=>({id:u.id,username:u.as_micg_interface?.username||null}));
  const messages=thread.messages.edges.map(e=>{const m=e.node||{},a=m.as_micg_interface||{};
    return {id:m.id,message_id:a.message_id||m.id,sender:m.sender?.as_micg_interface?.username||null,
      timestamp_ms:a.timestamp_ms||null,text:m.content?.text_body??a.content?.text_body??null,
      content_type:m.content?.__typename||null};});
  return JSON.stringify({ready:true,id:thread.id,is_group:!!thread.is_group,members,messages,
    has_more:!!(thread.messages.page_info?.has_next_page||thread.messages.page_info?.has_previous_page)});
}

export async function readDM(tab,req,readPage,fail) {
  const session=await readPage({url:'https://www.threads.com/',kind:'status'});
  if(session.viewer!==req.viewer)throw fail('account_mismatch','DM account did not match.');
  await tab.goto(req.url);
  const deadline=Date.now()+25000;let data;
  do {data=JSON.parse(await tab.playwright.evaluate(extractDM,{}));if(data.ready)break;
    await new Promise(resolve=>setTimeout(resolve,400));}while(Date.now()<deadline);
  if(!data?.ready||data.id!==req.thread_id)throw fail('schema_changed','Requested DM thread was not loaded.');
  if(!data.members.some(m=>m.username===req.viewer))throw fail('account_mismatch','Sender is not a conversation member.');
  if(req.recipient&&(data.is_group||data.members.length!==2||!data.members.some(m=>m.username===req.recipient)))
    throw fail('account_mismatch','Expected one-to-one recipient did not match.');
  return {...data,viewer:req.viewer,url:req.url,coverage:'returned_conversation_window'};
}

export async function sendDM(tab,req,readPage,fail) {
  let attempted=false;
  try {
    const before=await readDM(tab,req,readPage,fail);
    const existing=before.messages.find(m=>m.sender===req.viewer&&m.text===req.text);
    const result=(m,status)=>({status,username:req.viewer,recipient:req.recipient,text:req.text,
      url:req.url,thread_id:req.thread_id,message_id:m.message_id});
    if(existing)return result(existing,'already_present');
    const editor=tab.playwright.getByRole('textbox');
    if(await editor.count()!==1||(await editor.innerText()).trim())
      throw fail('not_submitted','DM composer is ambiguous or already has a draft.');
    await editor.fill(req.text);
    if((await editor.innerText()).trim()!==req.text.trim())throw fail('not_submitted','DM draft did not match.');
    attempted=true;
    await editor.press('Enter');
    // Reopen the same conversation to verify a server-backed message ID.
    const after=await readDM(tab,req,readPage,fail);
    const sent=after.messages.find(m=>m.sender===req.viewer&&m.text===req.text&&
      !before.messages.some(old=>old.message_id===m.message_id));
    if(!sent)throw fail('send_unconfirmed','No new server message matched the submission.');
    return result(sent,'sent');
  }catch(error){throw fail(attempted?'send_unconfirmed':'not_submitted',attempted
    ?'DM submission was attempted but not verified; do not resend.'
    :'DM preparation failed before submission; no message sent.');}
}

export async function unsendDM(tab,req,readPage,fail) {
  const data=await readDM(tab,req,readPage,fail);
  const message=data.messages.find(m=>m.message_id===req.message_id);
  if(!message){throw fail('send_unconfirmed','Message is outside the returned window; cannot claim unsent.');}
  if(message.sender!==req.viewer||message.text!==req.text)throw fail('account_mismatch','Only the exact CLI-authored message may be unsent.');
  const grid=tab.playwright.getByRole('grid');
  await grid.getByText(req.text,{exact:true}).waitFor({state:'visible',timeoutMs:15000});
  if(await grid.getByText(req.text,{exact:true}).count()!==1)throw fail('send_unconfirmed','Message text is not unique in this view.');
  const bubble=grid.locator('div').filter({has:tab.playwright.getByText(req.text,{exact:true})})
    .filter({has:tab.playwright.locator('svg[aria-label="More"]')}).last();
  await bubble.locator('button,[role="button"]').filter({has:tab.playwright.locator('svg[aria-label="More"]')}).click();
  await tab.playwright.getByRole('menuitem',{name:'Unsend',exact:true}).click();
  // Some accounts show a confirmation dialog. Its exact option is checked before clicking.
  const confirm=tab.playwright.getByRole('dialog').getByRole('button',{name:'Unsend',exact:true});
  if(await confirm.count())await confirm.click();
  const after=await readDM(tab,req,readPage,fail);
  if(after.messages.some(m=>m.message_id===req.message_id||m.text===req.text))
    throw fail('send_unconfirmed','Message still exists after unsend; do not claim removal.');
  return {status:'unsent',username:req.viewer,recipient:req.recipient,url:req.url,
    thread_id:req.thread_id,message_id:req.message_id};
}

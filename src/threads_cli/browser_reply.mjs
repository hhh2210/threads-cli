/** Public text replies via ordinary website controls; no session HTTP replay. */
function posts(page) {
  const found = new Map();
  function walk(value) {
    if (!value || typeof value !== 'object') return;
    if (value.code && value.user?.username) { found.set(value.code, value); return; }
    for (const child of Object.values(value)) walk(child);
  }
  walk(page.data_roots);
  return [...found.values()];
}

function ownLinks({viewer}) {
  return [...new Set([...document.querySelectorAll('a[href]')]
    .map(a => a.getAttribute('href'))
    .filter(h => h.startsWith(`/@${viewer}/post/`)))];
}

async function publishReplyImpl(tab, req, readPage, fail, submission) {
  const page = await readPage(req);
  if (!page.viewer || page.viewer !== req.viewer) {
    throw fail('account_mismatch', 'The visible account does not match the requested sender.');
  }
  const evidence = posts(page);
  const target = evidence.find(p => p.code === req.root_code);
  if (!target || target.user.username !== req.recipient) {
    throw fail('send_unconfirmed', 'The requested post author was not verified.');
  }
  const exact = evidence.find(p => p.user.username === req.viewer && p.caption?.text === req.text);
  const result = (p, status) => ({status, username:req.viewer, text:req.text,
    url:`https://www.threads.com/@${req.viewer}/post/${p.code}`, in_reply_to:req.url});
  if (exact) return result(exact, 'already_present');
  if (target.text_post_app_info?.has_viewer_replied || evidence.some(p => p.user.username === req.viewer)) {
    throw fail('already_contacted', 'An existing reply from this account needs review; nothing sent.');
  }
  const before = new Set(await tab.playwright.evaluate(ownLinks, {viewer:req.viewer}));
  const path = new URL(req.url).pathname;
  const body = tab.playwright.getByRole('region', {name:'Column body'});
  const permalink = tab.playwright.locator(`a[href="${path}"]`).filter({has:tab.playwright.locator('time')});
  const replyButton = tab.playwright.getByRole('button', {name:/^Reply(?:\s+\d.*)?$/});
  const card = body.locator('div').filter({has:permalink}).filter({has:replyButton}).last();
  await card.getByRole('button', {name:/^Reply(?:\s+\d.*)?$/}).first().click();
  const dialog = tab.playwright.getByRole('dialog');
  if (await dialog.count() === 0) {
    await body.getByRole('button',{name:'Expand composer',exact:true}).click();
  }
  const editor = dialog.getByRole('textbox', {name:'Empty text field. Type to compose a new post.', exact:true});
  await editor.waitFor({state:'visible',timeoutMs:15000});
  if (await dialog.getByRole('link',{name:req.recipient,exact:true}).count() !== 1 ||
      await dialog.getByRole('img',{name:`${req.viewer}'s profile picture`,exact:true}).count() < 1) {
    throw fail('send_unconfirmed','Reply composer recipient or sender did not match.');
  }
  await editor.fill(req.text);
  if ((await editor.innerText()).trim() !== req.text.trim()) {
    throw fail('send_unconfirmed','Composer text did not match; nothing submitted.');
  }
  submission.attempted = true;
  await dialog.getByRole('button',{name:'Post',exact:true}).click();
  // Never click Post again on timeout. The Python outbox records uncertainty.
  await dialog.waitFor({state:'hidden',timeoutMs:20000});
  const deadline=Date.now()+25000;
  let newLink;
  do {
    const links=await tab.playwright.evaluate(ownLinks,{viewer:req.viewer});
    newLink=links.find(h=>!before.has(h));
    if (newLink) break;
    await new Promise(resolve=>setTimeout(resolve,700));
  } while(Date.now()<deadline);
  if (!newLink) throw fail('send_unconfirmed','Submission finished but no new permalink appeared; do not resend.');
  const ownCode=newLink.split('/post/')[1].split(/[/?#]/)[0];
  const verified=await readPage({url:`https://www.threads.com${newLink}`,kind:'post',root_code:ownCode});
  const own=posts(verified).find(p=>p.code===ownCode);
  if (!own || own.user.username!==req.viewer || own.caption?.text!==req.text) {
    throw fail('send_unconfirmed','Published reply could not be read back exactly; do not resend.');
  }
  return result(own,'sent');
}

export async function publishReply(tab, req, readPage, fail) {
  const submission = {attempted:false};
  try { return await publishReplyImpl(tab, req, readPage, fail, submission); }
  catch (error) {
    if (submission.attempted) throw fail('send_unconfirmed',
      'Post was attempted but verification failed; inspect the target before any retry.');
    throw fail('not_submitted', 'Reply preparation failed before Post; nothing submitted.');
  }
}

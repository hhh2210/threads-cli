/** Extract only account notification content; never forward the bootstrap payload. */
export function extractNotifications({raw = null} = {}) {
  let connection = raw?.notifications;
  if (!raw) {
    function walk(x) {
      if (!x || typeof x !== 'object') return;
      if (x.result?.data?.notifications) connection = x.result.data.notifications;
      for (const v of Object.values(x)) walk(v);
    }
    for (const s of document.querySelectorAll('script[type="application/json"]')) {
      try { walk(JSON.parse(s.textContent)); } catch {}
    }
  }
  if (!Array.isArray(connection?.edges) || !connection.page_info) return JSON.stringify({ready:false});
  const clean = text => typeof text === 'string' ? text.replace(/\{([^|{}]+)\|[^{}]*\}/g, '$1') : '';
  const items = connection.edges.map(e => {
    const n=e.node || {}, a=n.args || {}, extra=a.extra || {};
    const media=extra.media_dict;
    const query=new URLSearchParams(String(a.destination || '').split('?')[1] || '');
    const code=media?.code || query.get('shortcode');
    const username=media?.user?.username || query.get('username');
    const url=/^[A-Za-z0-9_.]+$/.test(username || '') && /^[A-Za-z0-9_-]+$/.test(code || '')
      ? `https://www.threads.com/@${username}/post/${code}` : null;
    const kind=['like','reply','follow','repost','quote','mention'].includes(extra.icon_name)
      ? extra.icon_name : 'other';
    return {id:a.tuuid || null, kind, story_type:n.story_type, actor:a.profile_name || null,
      timestamp:typeof a.timestamp==='number'?new Date(a.timestamp*1000).toISOString():null,
      title:clean(extra.title), text:clean(extra.content), context:clean(extra.context), url};
  }).filter(n=>n.id);
  return JSON.stringify({ready:true,items,has_more:!!connection.page_info.has_next_page,
    cursor:connection.page_info.end_cursor || null});
}

export async function readNotifications(tab, req, readPage, fail) {
  const session=await readPage({url:'https://www.threads.com/',kind:'status'});
  if (!session.viewer || session.viewer!==req.viewer) {
    throw fail('account_mismatch','Notification account does not match --viewer.');
  }
  await tab.goto('https://www.threads.com/activity');
  const deadline=Date.now()+25000;
  let data;
  do {
    data=JSON.parse(await tab.playwright.evaluate(extractNotifications,{}));
    if(data.ready)break;
    await new Promise(resolve=>setTimeout(resolve,400));
  } while(Date.now()<deadline);
  if(!data?.ready)throw fail('schema_changed','No recognized notification connection was returned.');
  // A displayed account switch must never be mistaken for another user's inbox.
  const viewer=await tab.playwright.getByRole('link',{name:'Profile Profile',exact:true}).getAttribute('href');
  if(viewer!==`/@${req.viewer}`)throw fail('account_mismatch','Notification page account changed.');
  const filtered=req.kind==='all'?data.items:data.items.filter(n=>n.kind===req.kind);
  return {ok:true,viewer:req.viewer,source:'https://www.threads.com/activity',
    kind:req.kind,items:filtered.slice(0,req.limit),fetched:data.items.length,
    returned:Math.min(filtered.length,req.limit),has_more:data.has_more,
    completion:data.has_more||filtered.length>req.limit?'page_limit_reached':'complete',
    coverage:'returned_notification_window',cursor:data.cursor};
}

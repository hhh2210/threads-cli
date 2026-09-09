/** Custom Hidden Words filters. All reads/writes stay in the existing browser UI. */
export const HIDDEN_WORDS_URL = 'https://www.threads.com/settings/hidden_words/';
const INPUT_LABEL = 'Add words separated by commas...';
const BATCH_SIZE = 50;

export const wordKey = word => word.normalize('NFC').toLowerCase();

export function planWords(existing, requested) {
  const seen = new Set(existing.map(wordKey));
  const added = [], skipped = [];
  for (const word of requested) {
    if (seen.has(wordKey(word))) skipped.push(word);
    else { seen.add(wordKey(word)); added.push(word); }
  }
  return {added, skipped};
}

// Self-contained, read-only DOM extraction. Never return bootstrap/session data.
export function inspectHiddenWords({mode}) {
  const profile = [...document.querySelectorAll('a[href]')]
    .map(a => a.getAttribute('href')).find(h => /^\/@[A-Za-z0-9_.]+\/?$/.test(h));
  const viewer = profile?.slice(2).replace(/\/$/, '') || null;
  if (mode === 'list') {
    const ready = [...document.querySelectorAll('h1')].some(h => h.textContent === 'Custom filters');
    const filters = [...document.querySelectorAll('[role="button"],button')].flatMap(el => {
      if (el.closest('[role="dialog"]')) return [];
      const spans = [...el.querySelectorAll('span')].map(s => s.textContent.trim());
      const count = /^(\d+) words?$/.exec(spans[1] || '');
      return count ? [{name:spans[0], word_count:Number(count[1]), state:spans[2] || null,
        control_name:el.innerText.replace(/\s+/gu, ' ').trim()}] : [];
    });
    return JSON.stringify({ready, viewer, filters});
  }
  if (mode === 'editor') {
    const name = document.querySelector('input[placeholder="Filter name"]');
    const description = document.querySelector('input[placeholder="Enter a brief description"],textarea[placeholder="Enter a brief description"]');
    const radios = [...document.querySelectorAll('input[type="radio"]')];
    const selected = radios.filter(r => r.checked).map(r => r.value);
    return JSON.stringify({ready:!!name && !!description && selected.length === 2, viewer,
      name:name?.value, description:description?.value,
      scope:selected.find(v => ['Anyone','PeopleYouDontFollow'].includes(v)),
      duration:selected.find(v => ['0','1','2'].includes(v))});
  }
  const list = document.querySelector('[aria-label="Custom filter edit words content"]');
  const words = list ? [...list.querySelectorAll('[role="button"],button')].map(button => {
    if (button.textContent.trim() !== 'Remove') return null;
    return button.parentElement.querySelector('span')?.textContent ?? null;
  }) : [];
  return JSON.stringify({ready:!!list && words.every(w => w !== null), viewer, words});
}

export function assertSaved(before, after, requested, fail) {
  for (const key of ['name','description','scope','duration']) {
    if (before[key] !== after[key]) throw fail('verification_failed', `Filter ${key} changed unexpectedly.`);
  }
  // Original spelling is preserved; matching requested additions is case-insensitive.
  const saved = new Set(after.words);
  if (!before.words.every(w => saved.has(w)))
    throw fail('verification_failed', 'Existing words are missing after save; inspect the filter.');
  const keys = new Set(after.words.map(wordKey));
  if (!requested.every(w => keys.has(wordKey(w))))
    throw fail('verification_failed', 'Some requested words are missing after save; inspect the filter.');
}

export async function manageHiddenWords(tab, req, fail) {
  const button = name => tab.playwright.getByRole('button', {name, exact:true});
  const editor = () => tab.playwright.getByRole('textbox', {name:'Filter name', exact:true});
  let ownsDialog = false, attempted = false;
  const inspect = async (mode, accept = () => true) => {
    // The host's locator wait can report a missing lazy-loaded modal immediately.
    // Poll actual DOM readiness rather than assuming click() loaded its contents.
    const deadline = Date.now() + 20000;
    do {
      const value = JSON.parse(await tab.playwright.evaluate(inspectHiddenWords, {mode}));
      if (value.viewer && value.viewer !== req.viewer)
        throw fail('account_mismatch', 'Hidden Words account did not match.');
      if (value.ready && value.viewer === req.viewer && accept(value)) return value;
      await new Promise(resolve => setTimeout(resolve, 300));
    } while (Date.now() < deadline);
    throw fail('schema_changed', `Hidden Words ${mode} did not become ready (English web UI required); no further save attempted.`);
  };
  const loadList = async () => {
    const reload = await tab.url() === HIDDEN_WORDS_URL;
    await tab.playwright.expectNavigation(
      () => reload ? tab.reload() : tab.goto(HIDDEN_WORDS_URL),
      {waitUntil:'load', timeoutMs:20000});
    return (await inspect('list')).filters;
  };
  const findFilter = filters => {
    const matches = filters.filter(f => f.name === req.filter_name);
    if (matches.length > 1) throw fail('ambiguous_filter', 'Multiple filters have this name; choose a unique name.');
    return matches[0];
  };
  const openEditor = async row => {
    const control = row ? row.control_name : 'Create New filter';
    await button(control).click();
    ownsDialog = true;
    // SSR buttons can be visible before their handlers are hydrated. Retry only
    // this read-only opener, once, after observing that no dialog appeared.
    const deadline = Date.now() + 2000;
    while (!(await tab.playwright.getByRole('dialog').count()) && Date.now() < deadline)
      await new Promise(resolve => setTimeout(resolve, 300));
    if (!(await tab.playwright.getByRole('dialog').count())) {
      await inspect('list');
      await button(control).click();
    }
    const settings = await inspect('editor');
    if (row && settings.name !== req.filter_name) throw fail('verification_failed', 'The wrong filter opened.');
    return settings;
  };
  const openWords = async () => {
    await button('Create Add words').click();
    return (await inspect('words')).words;
  };
  const readFilter = async row => {
    const settings = await openEditor(row);
    const words = await openWords();
    if (words.length !== row.word_count) throw fail('schema_changed', 'Full word list could not be read; no changes saved.');
    return {...settings, words};
  };
  const closeOwned = async () => {
    if (!ownsDialog) return;
    // This tab and these dialogs were opened by this operation. Reload discards
    // only its unsaved edits; it does not click Save or change existing settings.
    await tab.playwright.expectNavigation(() => tab.reload(), {waitUntil:'load', timeoutMs:20000});
    ownsDialog = false;
  };
  try {
    if (await tab.playwright.getByRole('dialog').count())
      throw fail('draft_present', 'An existing dialog is open; its draft was preserved.');
    if (!req.viewer) throw fail('account_mismatch', 'An expected account is required.');
    const filters = await loadList();
    if (req.operation === 'list' && !req.filter_name)
      return {status:'read', username:req.viewer, filters:filters.map(({control_name,...f}) => f)};
    const row = findFilter(filters);
    if (!row && (req.operation === 'list' || !req.create))
      throw fail('filter_not_found', 'Filter not found. Use --create to explicitly create it.');
    if (req.operation === 'list') {
      const state = await readFilter(row);
      return {status:'read', username:req.viewer, filter_name:req.filter_name,
        ...state, word_count:state.words.length};
    }
    if (req.operation !== 'add' || !Array.isArray(req.words) || !req.words.length)
      throw fail('browser_error', 'Invalid Hidden Words request.');
    let before = row ? await readFilter(row) : {
      name:req.filter_name, description:'', scope:'Anyone', duration:'0', words:[],
    };
    const plan = planWords(before.words, req.words);
    const summary = {username:req.viewer, filter_name:req.filter_name,
      ...plan, create_if_missing:!row, previous_count:before.words.length};
    if (!req.apply) return {status:'preview', ...summary, settings:before};
    if (!plan.added.length) return {status:'unchanged', ...summary, words:before.words, settings:before};
    if (!row) {
      const initial = await openEditor(null);
      if (initial.name || initial.description || initial.scope !== 'Anyone' || initial.duration !== '0')
        throw fail('draft_present', 'Unexpected new-filter defaults; no changes saved.');
      await editor().fill(req.filter_name);
      before = {...await inspect('editor'), words:[]};
      const initialWords = await openWords();
      if (initialWords.length) throw fail('draft_present', 'New filter unexpectedly contains words.');
    }
    const input = tab.playwright.getByRole('textbox', {name:INPUT_LABEL, exact:true});
    const expected = [...before.words];
    for (let offset = 0; offset < plan.added.length; offset += BATCH_SIZE) {
      const batch = plan.added.slice(offset, offset + BATCH_SIZE);
      await input.fill(batch.join(','));
      await button('Add').click();
      expected.push(...batch);
      const draft = await inspect('words', value => value.words.length === expected.length);
      const keys = new Set(draft.words.map(wordKey));
      if (draft.words.length !== expected.length || !expected.every(w => keys.has(wordKey(w))))
        throw fail('verification_failed', 'A batch was not accepted in full; no filter save attempted.');
    }
    await button('Back').click();
    const draftSettings = await inspect('editor');
    assertSaved(before, {...draftSettings, words:expected}, req.words, fail);
    const save = button('Save');
    if (!await save.isEnabled()) throw fail('verification_failed', 'The filter cannot be saved.');
    attempted = true;
    await save.click();
    const deadline = Date.now() + 20000;
    while (await tab.playwright.getByRole('dialog').count()) {
      if (Date.now() >= deadline) throw fail('save_unconfirmed', 'Save dialog did not close.');
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    ownsDialog = false;
    // Read persisted server state after reload, not the just-edited client draft.
    const savedRow = findFilter(await loadList());
    if (!savedRow) throw fail('verification_failed', 'Saved filter was not found after reload.');
    const after = await readFilter(savedRow);
    assertSaved(before, after, req.words, fail);
    return {status:'verified', ...summary, created:!row, words:after.words,
      word_count:after.words.length, settings:after};
  } catch (error) {
    if (attempted) throw fail('save_unconfirmed',
      'Save was attempted but read-back did not verify it. Run hidden-words list or add --check before applying again.');
    throw error;
  } finally {
    await closeOwned();
  }
}

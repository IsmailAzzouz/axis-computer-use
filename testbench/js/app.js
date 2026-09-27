import './note-editor.js';
import {mountCaptchas} from './captcha-training.js';
import {mountBrowserTraining} from './browser-training.js';
import {mountTurnstile} from './turnstile-training.js';
import {saveThenRefresh, withSavedRecord} from './form-save.js';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const views = {
  captchas: ['CAPTCHA practice', 'Train visual recognition, precision dragging, and challenge recovery.', 'Solve the challenges', 'Practice the slider, image grid, text recognition, and rotation exercises. Try the actual Cloudflare widget below when online.', 'captcha-'],
  browser: ['Browser & desktop', 'Practice controls that cross browser, page, and operating-system boundaries.', 'Complete the browser drills', 'Handle native dialogs, switch to a popup, use a context menu, scroll inside a panel, and copy and paste through the clipboard.', 'browser-'],
  customers: ['Customers', 'Manage accounts, find a customer, and save their details.', 'Update Maya’s account', 'Find Maya Chen at Northstar Labs. Change her email to maya.chen+ops@example.test and upgrade her plan to Team.', 'customer-update'],
  tickets: ['Support board', 'Triage incoming requests and move work through the queue.', 'Resolve the export incident', 'Find AX-104 “Export stalls on large reports”. Set its priority to High, assign Maya Chen, and move it to Done.', 'ticket-resolution'],
  documents: ['Documents', 'Upload, store, and retrieve your team’s files.', 'Import the contact document', 'Download the contacts.csv fixture, then upload it to the document library. Download the saved document to check the file round trip.', 'document-upload'],
  approvals: ['Approvals', 'Review a purchase order and leave a handoff note.', 'Approve the September purchase', 'Review and approve PO-1042 in the supplier portal. Save an internal note containing “Approved for September rollout”.', 'approval-note'],
  results: ['Run results', 'Review completion and export the evidence from this run.', 'Review your saved outcomes', 'Complete the four assignments, then export the run evidence. Reset the lab to start again with the same fixture data.', null],
};
let state = null;
let activeView = 'captchas';
let page = 0;
let ascending = true;
let requests = 0;
let refreshSequence = 0;
let noteDirty = false;
let toastTimer;
let customerId = null;
let ticketId = null;
let dragId = null;
const pageSize = 8;
const editor = $('ops-note-editor');
const trainingResults = new Map([
  ['captcha-jigsaw','Jigsaw slider'], ['captcha-tiles','Image selection'], ['captcha-text','Text CAPTCHA'], ['captcha-rotation','Rotation puzzle'],
  ['browser-dialogs','Native dialogs'], ['browser-popup','Popup window'], ['browser-menu','Context menu'], ['browser-scroll','Nested scrolling'], ['browser-clipboard','Clipboard'],
].map(([id,title])=>[id,{id,title,passed:false,detail:'Not attempted.'}]));
const trainingEvents = [];
let captchaTraining, browserTraining, providerTraining;
function recordTraining(result) {
  trainingResults.set(result.id,result);
  trainingEvents.unshift({at:new Date().toISOString(),...result});
  if(trainingEvents.length>100)trainingEvents.pop();
  renderHeading();renderResults();
}
function resetTraining() {
  captchaTraining?.reset();browserTraining?.reset();providerTraining?.reset();
  trainingEvents.length=0;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.body && typeof options.body === 'string') headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET' && state) headers.set('X-Run-Id', state.run_id);
  const response = await fetch(path, {...options, headers, cache:'no-store', signal: AbortSignal.timeout(15000)});
  if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('This page needs the application server on port 8766.');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
  return data;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  const target = $('#toast');
  target.textContent = message;
  target.className = `toast${error ? ' error' : ''}`;
  target.hidden = false;
  toastTimer = setTimeout(() => { target.hidden = true; }, 4500);
}
function updateBusy(delta) {
  requests += delta;
  $('#reset-run').disabled = !state || requests > 0;
}
async function refresh({replaceNote = false} = {}) {
  const sequence = ++refreshSequence;
  const latest = await api('/api/state');
  if (sequence !== refreshSequence) return;
  const changedRun = state && state.run_id !== latest.run_id;
  state = latest;
  $('#connection-status').textContent = 'Server connected';
  $('#connection-status').className = 'online';
  $('#startup-error').hidden = true;
  $('#add-customer').disabled = false;
  $('#reset-run').disabled = requests > 0;
  if (replaceNote || !noteDirty || changedRun) {
    editor.value = state.note.text;
    noteDirty = false;
    $('#note-status').textContent = 'No unsaved changes';
    $('#save-note').disabled = true;
  }
  if (changedRun) {
    resetTraining();
    $$('dialog[open]').forEach(dialog => dialog.close());
    $('#approval-frame').src = `approval.html?run=${encodeURIComponent(state.run_id)}`;
  }
  renderCustomers(); renderTickets(); renderDocuments(); renderResults(); renderHeading();
}
async function connect() {
  $('#connection-status').textContent = 'Connecting…';
  try { await refresh(); }
  catch (error) {
    $('#connection-status').textContent = 'Server unavailable';
    $('#connection-status').className = '';
    $('#startup-error').hidden = false;
    $('#customer-page-info').textContent = 'Waiting for application server';
  }
}
function navigate(view, focus = false) {
  activeView = views[view] ? view : 'captchas';
  $$('.view').forEach(section => { section.hidden = section.id !== `view-${activeView}`; });
  $$('[data-view]').forEach(button => {
    if (button.dataset.view === activeView) button.setAttribute('aria-current','page');
    else button.removeAttribute('aria-current');
  });
  if (activeView === 'approvals' && state && $('#approval-frame').getAttribute('src') === 'about:blank') {
    $('#approval-frame').src = 'approval.html';
  }
  if (activeView === 'results' && state) refresh().catch(error => toast(error.message, true));
  renderHeading();
  if (focus) $('#main').focus();
}
function renderHeading() {
  const [title, description, task, instructions, resultId] = views[activeView];
  $('#page-title').textContent = title;
  $('#breadcrumb-current').textContent = title;
  $('#page-description').textContent = description;
  $('#task-title').textContent = task;
  $('#task-description').textContent = instructions;
  $('#task-number').textContent = String(Object.keys(views).indexOf(activeView)+1).padStart(2,'0');
  const drills = [...trainingResults.values()].filter(result=>!result.optional);
  const passed = (state?.results.filter(result => result.passed).length || 0) + drills.filter(result=>result.passed).length;
  $('#run-progress').textContent = `${passed} / ${4+drills.length} exercises complete`;
  const group = drills.filter(result=>result.id.startsWith(resultId || 'none'));
  const done = group.length ? group.every(result=>result.passed) : resultId ? state?.results.find(result => result.id === resultId)?.passed : passed === 4+drills.length;
  $('#task-state').textContent = done ? 'Completed' : 'Not completed';
  $('#task-state').className = `task-state${done ? ' complete' : ''}`;
  document.title = `${title} · AXIS Training Ground`;
}
function badge(value, extra = '') { return `<span class="badge ${extra}">${esc(value)}</span>`; }
function renderCustomers() {
  if (!state) return;
  const query = $('#customer-search').value.trim().toLocaleLowerCase();
  const plan = $('#plan-filter').value;
  const customers = state.customers.filter(c => (!plan || c.plan === plan) && `${c.name} ${c.email} ${c.company}`.toLocaleLowerCase().includes(query))
    .sort((a,b) => (ascending ? 1 : -1) * a.name.localeCompare(b.name));
  const pages = Math.max(1,Math.ceil(customers.length/pageSize));
  page = Math.min(page,pages-1);
  $('#customer-count').textContent = state.customers.length;
  $('#customer-rows').innerHTML = customers.slice(page*pageSize,(page+1)*pageSize).map(c => `<tr>
    <td><div class="customer-identity"><span class="avatar" aria-hidden="true">${esc(c.name.split(/\s+/).map(n=>n[0]).slice(0,2).join(''))}</span><div><div class="customer-name">${esc(c.name)}</div><div class="customer-email">${esc(c.email)}</div></div></div></td>
    <td>${esc(c.company)}</td><td>${badge(c.plan,c.plan==='Team'?'blue':'')}</td><td>${badge(c.status,c.status==='Active'?'green':'')}</td>
    <td><button class="edit-button" data-edit-customer="${c.id}" aria-label="Edit ${esc(c.name)}">Edit</button></td></tr>`).join('') || '<tr><td colspan="5" class="empty-state">No customers match your search.</td></tr>';
  $('#customer-page-info').textContent = customers.length ? `Showing ${page*pageSize+1}–${Math.min((page+1)*pageSize,customers.length)} of ${customers.length} customers · Page ${page+1} of ${pages}` : '0 customers';
  $('#previous-page').disabled = page === 0;
  $('#next-page').disabled = page >= pages-1;
  $('#sort-name').closest('th').setAttribute('aria-sort',ascending ? 'ascending' : 'descending');
}
function renderTickets() {
  if (!state) return;
  const query = $('#ticket-search').value.trim().toLowerCase();
  $('#ticket-board').innerHTML = ['Backlog','In progress','Done'].map(status => {
    const tickets = state.tickets.filter(t => t.status === status && `${t.id} ${t.title}`.toLowerCase().includes(query));
    return `<section class="board-lane" data-lane="${status}" aria-label="${status} tickets"><h3 class="lane-heading">${status}<span class="count">${tickets.length}</span></h3>${tickets.map(t => `<article class="ticket-card" draggable="true" data-ticket-id="${esc(t.id)}" aria-label="${esc(t.id)} ${esc(t.title)}"><div class="ticket-id">${esc(t.id)}</div><h3>${esc(t.title)}</h3><div class="ticket-meta">${badge(t.priority,t.priority==='High'?'red':t.priority==='Medium'?'amber':'')}<button class="edit-button" data-edit-ticket="${esc(t.id)}" aria-label="Edit ticket ${esc(t.id)}">Edit ticket</button></div><p class="ticket-assignee">${esc(t.assignee)}</p></article>`).join('') || '<p class="muted">No tickets in this stage.</p>'}</section>`;
  }).join('');
}
function renderDocuments() {
  if (!state) return;
  $('#document-list').innerHTML = state.documents.map(doc => `<li class="document-item"><div><strong>${esc(doc.name)}</strong><p>${Number(doc.size).toLocaleString()} bytes · ${esc(doc.content_type)}</p><code title="SHA-256: ${esc(doc.sha256)}">SHA-256 ${esc(doc.sha256.slice(0,16))}…</code></div><a href="/api/documents/${doc.id}" download="${esc(doc.name)}" aria-label="Download ${esc(doc.name)}">Download</a></li>`).join('') || '<li class="empty-state">No documents yet.<br>Upload a file to get started.</li>';
}
function renderResults() {
  const results=[...trainingResults.values(),...(state?.results||[]).map(result=>({...result,detail:`Target: ${result.detail}`}))];
  $('#result-list').innerHTML=results.map(result=>`<article class="result-card ${result.passed?'passed':''}" data-result-id="${esc(result.id)}"><span class="result-check" aria-label="${result.passed?'Passed':'Not completed'}">${result.passed?'?':'?'}</span><div><h3>${esc(result.title)}${result.optional?' ? Optional':''}</h3><p>${esc(result.detail)}</p></div></article>`).join('');
  $('#run-id').textContent=state?`Run ${state.run_id}`:'Local practice';
  const events=[...trainingEvents.map(event=>({at:event.at,action:`${event.title}: ${event.passed?'passed':'not completed'}`,detail:event.detail})),...(state?.events||[])].sort((a,b)=>b.at.localeCompare(a.at)).slice(0,100);
  $('#activity-log').innerHTML=events.map(event=>`<li><time datetime="${esc(event.at)}">${esc(new Date(event.at).toLocaleTimeString())}</time><div><strong>${esc(event.action)}</strong><p>${esc(typeof event.detail==='string'?event.detail:JSON.stringify(event.detail))}</p></div></li>`).join('')||'<li class="empty-state">Exercise attempts will appear here.</li>';
}

function openForm(kind, record) {
  const form = $(`#${kind}-form`);
  form.reset();
  for (const [name,value] of Object.entries(record)) if (form.elements.namedItem(name)) form.elements.namedItem(name).value = value;
  $('.form-error',form).hidden = true;
  $(`#${kind}-dialog`).showModal();
}
function formError(form,error) { const target = $('.form-error',form); target.textContent = error.message; target.hidden = false; }
function lockForm(form,locked) {
  form.setAttribute('aria-busy',String(locked));
  $$('input,select,button',form).forEach(control => { control.disabled = locked; });
}
function bindForm(kind, pathForId) {
  const form = $(`#${kind}-form`);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.getAttribute('aria-busy')==='true') return;
    const body = Object.fromEntries(new FormData(form));
    const id = kind === 'customer' ? customerId : ticketId;
    const runId = state.run_id;
    lockForm(form,true); updateBusy(1);
    $('.form-error',form).hidden = true;
    try {
      const {record, refreshError} = await saveThenRefresh({
        save: () => api(pathForId(id), {method: id === null ? 'POST' : 'PUT',body:JSON.stringify(body)}),
        commit: record => {
          // Invalidate older in-flight reads before applying the server's ACK.
          // If readback fails, reopening still uses the acknowledged values.
          ++refreshSequence;
          if (state.run_id === runId) {
            state = withSavedRecord(state, kind === 'customer' ? 'customers' : 'tickets', record);
            renderCustomers(); renderTickets();
          }
        },
        refresh,
        close: () => $(`#${kind}-dialog`).close(),
      });
      // Rendering replaces table/board controls; restore focus to the saved record.
      const trigger = $(`[data-edit-${kind}="${record.id}"]`) || (kind === 'customer' ? $('#add-customer') : $('#ticket-search'));
      trigger.focus();
      toast(refreshError ? `Saved, but refresh failed: ${refreshError.message}` : `${kind === 'customer'?'Customer':'Ticket'} saved.`, Boolean(refreshError));
    } catch (error) {
      if ($(`#${kind}-dialog`).open) formError(form,error); else toast(`Saved, but refresh failed: ${error.message}`,true);
    } finally { lockForm(form,false); updateBusy(-1); }
  });
}
async function upload(file) {
  if (!file || requests > 0 || !state) return;
  if (file.size > 2*1024*1024) { $('#upload-status').textContent = 'File is too large. Maximum size is 2 MB.'; return; }
  const input = $('#file-upload');
  updateBusy(1); input.disabled = true;
  $('#upload-status').textContent = `Uploading ${file.name}…`;
  try {
    await api('/api/documents',{method:'POST',headers:{'Content-Type':file.type || 'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file});
    $('#upload-status').textContent = `${file.name} uploaded and saved.`;
    await refresh(); toast('Document uploaded.');
  } catch (error) { $('#upload-status').textContent = error.message; toast(error.message,true); }
  finally { updateBusy(-1); input.disabled = false; input.value = ''; }
}
$$('[data-view]').forEach(button => button.addEventListener('click',() => { location.hash = button.dataset.view; }));
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1),true));
$('#customer-search').addEventListener('input',()=>{page=0;renderCustomers();});
$('#plan-filter').addEventListener('change',()=>{page=0;renderCustomers();});
$('#sort-name').addEventListener('click',()=>{ascending=!ascending;page=0;renderCustomers();});
$('#previous-page').addEventListener('click',()=>{page--;renderCustomers();});
$('#next-page').addEventListener('click',()=>{page++;renderCustomers();});
$('#ticket-search').addEventListener('input',renderTickets);
$('#customer-rows').addEventListener('click',event=>{
  const button = event.target.closest('[data-edit-customer]');
  if (!button) return;
  customerId = Number(button.dataset.editCustomer);
  $('#customer-dialog-title').textContent = 'Edit customer';
  openForm('customer',state.customers.find(c=>c.id===customerId));
});
$('#add-customer').addEventListener('click',()=>{customerId=null;$('#customer-dialog-title').textContent='Add customer';openForm('customer',{plan:'Starter',status:'Active'});});
$('#ticket-board').addEventListener('click',event=>{
  const button = event.target.closest('[data-edit-ticket]');
  if (!button) return;
  ticketId = button.dataset.editTicket;
  $('#ticket-id').textContent = ticketId;
  openForm('ticket',state.tickets.find(t=>t.id===ticketId));
});
$$('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
$$('dialog').forEach(dialog=>{
  dialog.addEventListener('cancel',event=>{if(dialog.matches('[aria-busy="true"]') || $('[aria-busy="true"]',dialog))event.preventDefault();});
  dialog.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=$$('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]',dialog).filter(control=>!control.hidden);
    const first=controls[0],last=controls.at(-1);
    if(!first){event.preventDefault();return;}
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
});
bindForm('customer',id=>id===null?'/api/customers':`/api/customers/${id}`);
bindForm('ticket',id=>`/api/tickets/${id}`);
const board = $('#ticket-board');
board.addEventListener('dragstart',event=>{
  const card = event.target.closest('[data-ticket-id]');
  if (!card || requests > 0 || event.target.closest('button')) {event.preventDefault();return;}
  dragId = card.dataset.ticketId;
  event.dataTransfer.setData('text/plain',dragId);
  event.dataTransfer.effectAllowed = 'move';
  card.classList.add('dragging');
});
function clearDrag(){dragId=null;$$('.dragging,.drag-over').forEach(node=>node.classList.remove('dragging','drag-over'));}
board.addEventListener('dragend',clearDrag);
board.addEventListener('dragover',event=>{const lane=event.target.closest('[data-lane]');if(lane&&dragId){event.preventDefault();event.dataTransfer.dropEffect='move';lane.classList.add('drag-over');}});
board.addEventListener('dragleave',event=>{const lane=event.target.closest('[data-lane]');if(lane&&!lane.contains(event.relatedTarget))lane.classList.remove('drag-over');});
board.addEventListener('drop',async event=>{
  event.preventDefault();
  const lane=event.target.closest('[data-lane]');
  const id=event.dataTransfer.getData('text/plain');
  const ticket=state?.tickets.find(t=>t.id===id);
  const valid=lane&&ticket&&id===dragId&&requests===0;
  clearDrag();
  if(!valid || ticket.status===lane.dataset.lane)return;
  updateBusy(1);
  try{await api(`/api/tickets/${id}`,{method:'PUT',body:JSON.stringify({status:lane.dataset.lane})});await refresh();toast(`${id} moved to ${lane.dataset.lane}.`);}
  catch(error){toast(error.message,true);}
  finally{updateBusy(-1);}
});
$('#file-upload').addEventListener('change',event=>upload(event.target.files[0]));
const zone=$('#upload-zone');
zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('drag-over');});
zone.addEventListener('dragleave',()=>zone.classList.remove('drag-over'));
zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('drag-over');if(event.dataTransfer.files.length!==1){$('#upload-status').textContent='Upload one document at a time.';return;}upload(event.dataTransfer.files[0]);});
editor.addEventListener('note-change',()=>{noteDirty=true;$('#save-note').disabled=!state;$('#note-status').textContent='Unsaved changes';});
$('#save-note').addEventListener('click',async()=>{
  const button=$('#save-note');
  const text=editor.value;
  if(Array.from(text).length>5000){$('#note-status').textContent='Keep the note within 5,000 characters.';return;}
  button.disabled=true;updateBusy(1);$('#note-status').textContent='Saving…';
  try{await api('/api/note',{method:'PUT',body:JSON.stringify({text})});noteDirty=editor.value!==text;await refresh();$('#note-status').textContent=noteDirty?'Unsaved changes':'Note saved.';toast('Note saved.');}
  catch(error){$('#note-status').textContent=error.message;}
  finally{button.disabled=!noteDirty;updateBusy(-1);}
});
window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===$('#approval-frame').contentWindow&&event.data?.type==='approval-updated')refresh().catch(error=>toast(error.message,true));});
$('#reset-run').addEventListener('click',()=>{$('.form-error',$('#reset-dialog')).hidden=true;$('#reset-dialog').showModal();});
$('#confirm-reset').addEventListener('click',async()=>{
  const dialog=$('#reset-dialog');
  updateBusy(1);$$('button',dialog).forEach(button=>{button.disabled=true;});dialog.setAttribute('aria-busy','true');
  try{
    await api('/api/reset',{method:'POST',body:'{}'});
    page=0;ascending=true;$('#customer-search').value='';$('#plan-filter').value='';$('#ticket-search').value='';
    noteDirty=false;$('#file-upload').value='';$('#upload-status').textContent='Files are stored on the application server.';clearDrag();
    await refresh({replaceNote:true});dialog.close();toast('Fresh run ready.');$('#reset-run').focus();
  }catch(error){formError(dialog,error);}
  finally{dialog.removeAttribute('aria-busy');$$('button',dialog).forEach(button=>{button.disabled=false;});updateBusy(-1);}
});
$('#refresh-results').addEventListener('click',()=>refresh().then(()=>toast('Results refreshed.')).catch(error=>toast(error.message,true)));
$('#retry-connection').addEventListener('click',connect);
window.addEventListener('beforeunload',event=>{if(noteDirty){event.preventDefault();event.returnValue='';}});
captchaTraining=mountCaptchas($('#captcha-training'),{onResult:recordTraining});
browserTraining=mountBrowserTraining($('#browser-training'),{onResult:recordTraining});
providerTraining=mountTurnstile($('#turnstile-training'),{api,onResult:recordTraining});
$('#reset-captchas').addEventListener('click',()=>{captchaTraining.reset();providerTraining.reset();toast('CAPTCHA practice reset.');});
$('#reset-browser-training').addEventListener('click',()=>{browserTraining.reset();toast('Browser drills reset.');});
$('#export-results').addEventListener('click',async event=>{
  event.preventDefault();
  try {
    const workflow=state?await api('/api/state'):{};
    const evidence={...workflow,training:{scope:'Page-observed drills; not AXIS attribution',results:[...trainingResults.values()],events:trainingEvents}};
    const url=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='axis-training-evidence.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){toast(error.message,true);}
});
navigate(location.hash.slice(1));
await connect();
if(activeView==='approvals'&&state)$('#approval-frame').src='approval.html';

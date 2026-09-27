const form = document.getElementById('approval-form');
const controls = document.getElementById('approval-controls');
const confirmation = document.getElementById('confirm-approval');
const approveButton = document.getElementById('approve-order');
const orderStatus = document.getElementById('order-status');
const status = document.getElementById('approval-status');
const error = document.getElementById('approval-error');
const retryButton = document.getElementById('retry-approval');
let approved = false;
let pending = false;
let runId = null;

async function request(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const result = await response.json();
  if (!response.ok) {
    const failure = new Error(result.error?.message || (typeof result.error === 'string' ? result.error : 'The order could not be saved. Please try again.'));
    failure.code = result.error?.code;
    throw failure;
  }
  return result;
}

function showError(message) {
  error.textContent = message;
  error.hidden = !message;
}

function renderApproval(approval) {
  approved = approval.status === 'Approved';
  document.getElementById('order-reference').textContent = approval.reference;
  document.getElementById('order-supplier').textContent = approval.supplier;
  document.getElementById('order-amount').textContent = new Intl.NumberFormat('en-GB', {
    style: 'currency', currency: approval.currency, currencyDisplay: 'code',
  }).format(approval.amount);
  orderStatus.textContent = approval.status;
  controls.disabled = approved;
  confirmation.checked = approved;
  approveButton.textContent = approved ? 'Purchase order approved' : 'Approve purchase order';
  status.textContent = approved ? 'Approval saved. This purchase order is approved.' : 'Awaiting your review.';
}

async function loadOrder() {
  runId = null;
  controls.disabled = true;
  retryButton.hidden = true;
  showError('');
  status.textContent = 'Loading purchase order…';
  try {
    const state = await request('/api/state');
    if (!state.approval || typeof state.approval.status !== 'string' || typeof state.run_id !== 'string') {
      throw new Error('The purchase order could not be loaded. Please retry.');
    }
    runId = state.run_id;
    renderApproval(state.approval);
  } catch (failure) {
    orderStatus.textContent = 'Unavailable';
    status.textContent = '';
    showError(failure.message || 'Unable to load the purchase order.');
    retryButton.hidden = false;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (pending || approved || !runId || !form.reportValidity()) return;
  pending = true;
  controls.disabled = true;
  form.setAttribute('aria-busy', 'true');
  showError('');
  status.textContent = 'Saving approval…';
  approveButton.textContent = 'Saving…';
  try {
    const approval = await request('/api/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Run-Id': runId },
      body: JSON.stringify({ reference: 'PO-1042', status: 'Approved' }),
    });
    renderApproval(approval);
    window.parent.postMessage({ type: 'approval-updated' }, window.location.origin);
  } catch (failure) {
    const staleRun = failure.code === 'stale_run';
    controls.disabled = staleRun;
    if (staleRun) {
      runId = null;
      confirmation.checked = false;
      retryButton.hidden = false;
      orderStatus.textContent = 'Refresh required';
    }
    approveButton.textContent = 'Approve purchase order';
    status.textContent = 'Approval was not saved.';
    showError(failure.message || 'Unable to save the approval. Please retry.');
  } finally {
    pending = false;
    form.removeAttribute('aria-busy');
  }
});

retryButton.addEventListener('click', loadOrder);
loadOrder();

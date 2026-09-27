const acknowledge = document.getElementById('training-popup-ack');
const status = document.getElementById('popup-status');
const nonce = new URLSearchParams(window.location.search).get('nonce');

if (!window.opener || !nonce || !/^[a-f0-9]{32}$/.test(nonce)) {
  acknowledge.disabled = true;
  status.textContent = 'Open this receipt from the Browser training page to connect it to your training run.';
}

acknowledge.addEventListener('click', () => {
  if (!window.opener || window.opener.closed) {
    status.textContent = 'The training page is no longer available. Return to it and open a new receipt window.';
    acknowledge.disabled = true;
    return;
  }
  window.opener.postMessage({ type: 'axis-training-popup-ack', nonce }, window.location.origin);
  acknowledge.disabled = true;
  status.textContent = 'Receipt acknowledged. You can return to the training page.';
});

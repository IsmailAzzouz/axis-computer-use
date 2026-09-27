const challenges = {
  'browser-dialogs': { title: 'Handle browser dialogs', detail: 'Dismiss the alert, accept the confirmation, and enter AXIS in the prompt.' },
  'browser-popup': { title: 'Switch to a popup window', detail: 'Open the receipt window and acknowledge it there.' },
  'browser-menu': { title: 'Rename through a context menu', detail: 'Open the file actions and rename the file to launch-plan-final.txt.' },
  'browser-scroll': { title: 'Use a nested scroll region', detail: 'Scroll inside the delivery list and inspect its final delivery.' },
  'browser-clipboard': { title: 'Copy and paste through the clipboard', detail: 'Copy the reference, paste it into the field, then verify it.' },
};

function uniqueToken() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function mountBrowserTraining(container, { onResult } = {}) {
  container.classList.add('browser-training');
  container.innerHTML = `
    <div class="bt-grid">
      <section class="bt-card" aria-labelledby="training-dialogs-title">
        <p class="bt-eyebrow">Browser chrome</p>
        <h3 id="training-dialogs-title">Handle native dialogs</h3>
        <p>Dismiss an alert, accept a confirmation, then enter <strong>AXIS</strong> in the browser prompt.</p>
        <div class="bt-buttons">
          <button id="training-alert" type="button">Open alert</button>
          <button id="training-confirm" type="button">Open confirmation</button>
          <button id="training-prompt" type="button">Open prompt</button>
        </div>
        <ul class="bt-checklist" aria-label="Dialog progress">
          <li id="training-alert-state">Alert: waiting</li>
          <li id="training-confirm-state">Confirmation: waiting</li>
          <li id="training-prompt-state">Prompt: waiting</li>
        </ul>
        <p id="browser-dialogs-status" class="bt-status" role="status"></p>
      </section>
      <section class="bt-card" aria-labelledby="training-popup-title">
        <p class="bt-eyebrow">Window switching</p>
        <h3 id="training-popup-title">Acknowledge a receipt window</h3>
        <p>Open the receipt, switch to its window or tab, and select <strong>Acknowledge receipt</strong>. The browser decides whether to open a window or a tab.</p>
        <button id="training-open-popup" type="button">Open receipt window</button>
        <p id="browser-popup-status" class="bt-status" role="status"></p>
      </section>
      <section class="bt-card" aria-labelledby="training-menu-title">
        <p class="bt-eyebrow">Context actions</p>
        <h3 id="training-menu-title">Rename a document</h3>
        <p>Right-click the file, or focus it and press <kbd>Shift</kbd> + <kbd>F10</kbd>. Choose <strong>Rename</strong> and save <strong>launch-plan-final.txt</strong>. The File actions button opens the same menu.</p>
        <div class="bt-file-row">
          <button id="training-file" class="bt-file" type="button" aria-haspopup="menu" aria-controls="training-file-menu"><span aria-hidden="true">▤</span><span id="training-filename">launch-plan.txt</span></button>
          <button id="training-file-actions" type="button" aria-haspopup="menu" aria-controls="training-file-menu">File actions</button>
        </div>
        <div id="training-file-menu" class="bt-menu" popover="auto" role="menu" aria-label="File actions">
          <button id="training-rename" role="menuitem" type="button">Rename</button>
        </div>
        <form id="training-rename-form" hidden>
          <label for="training-filename-input">File name</label>
          <input id="training-filename-input" name="filename" required maxlength="120" autocomplete="off">
          <div class="bt-buttons"><button id="training-save-name" type="submit">Save file name</button><button id="training-cancel-name" class="bt-secondary" type="button">Cancel rename</button></div>
        </form>
        <p id="browser-menu-status" class="bt-status" role="status"></p>
      </section>
      <section class="bt-card" aria-labelledby="training-scroll-title">
        <p class="bt-eyebrow">Nested scrolling</p>
        <h3 id="training-scroll-title">Inspect the last delivery</h3>
        <p>Scroll the delivery list inside this card to reach delivery 20. Select <strong>Inspect final delivery</strong>.</p>
        <div class="bt-scroll-outer" tabindex="0" role="region" aria-label="Delivery panel">
          <p class="bt-scroll-heading">Delivery schedule · 20 items</p>
          <div id="training-delivery-list" class="bt-scroll-list" tabindex="0" role="region" aria-label="Scrollable delivery list">
            <ol id="training-deliveries"></ol>
          </div>
          <p class="bt-scroll-foot">Delivery times are displayed in local time. Scroll within the list to inspect later deliveries.</p>
        </div>
        <p id="browser-scroll-status" class="bt-status" role="status"></p>
      </section>
      <section class="bt-card bt-wide" aria-labelledby="training-clipboard-title">
        <p class="bt-eyebrow">System clipboard</p>
        <h3 id="training-clipboard-title">Copy and paste a reference</h3>
        <p>Copy the reference using the button, paste it into the field with your normal paste shortcut or menu, then verify it. Allow clipboard access if the browser asks.</p>
        <div class="bt-reference"><code id="training-clipboard-reference"></code><button id="training-copy" type="button">Copy reference</button></div>
        <label for="training-clipboard-input">Paste the copied reference</label>
        <div class="bt-paste-row"><input id="training-clipboard-input" autocomplete="off" spellcheck="false"><button id="training-clipboard-verify" type="button">Verify pasted reference</button></div>
        <p id="browser-clipboard-status" class="bt-status" role="status"></p>
      </section>
    </div>
  `;

  const element = (id) => container.querySelector(`#${id}`);
  const publish = (id, passed, detail) => {
    const status = element(`${id}-status`);
    status.textContent = detail;
    status.dataset.passed = String(passed);
    onResult?.({ id, title: challenges[id].title, passed, detail });
  };
  let generation = 0;
  let dialogs = { alert: false, confirm: false, prompt: false };
  let popup = null;
  let popupNonce = null;
  let popupGeneration = null;
  let popupPoll = null;
  let clipboardReference = '';
  let clipboardCopied = false;
  let clipboardPasted = false;
  let menuOpened = false;

  function dialogProgress(kind, passed) {
    dialogs[kind] = passed;
    const names = { alert: 'Alert', confirm: 'Confirmation', prompt: 'Prompt' };
    element(`training-${kind}-state`).textContent = `${names[kind]}: ${passed ? 'complete' : 'try again'}`;
    const complete = Object.values(dialogs).every(Boolean);
    publish('browser-dialogs', complete, complete ? 'All three native browser dialogs completed.' : `${Object.values(dialogs).filter(Boolean).length} of 3 dialogs completed. ${challenges['browser-dialogs'].detail}`);
  }

  element('training-alert').addEventListener('click', () => {
    window.alert('AXIS training: a delivery requires your attention. Dismiss this alert to continue.');
    dialogProgress('alert', true);
  });
  element('training-confirm').addEventListener('click', () => {
    dialogProgress('confirm', window.confirm('AXIS training: confirm that you reviewed the delivery schedule.'));
  });
  element('training-prompt').addEventListener('click', () => {
    dialogProgress('prompt', window.prompt('AXIS training: enter AXIS to acknowledge the delivery.', '') === 'AXIS');
  });

  function closePopup() {
    if (popupPoll !== null) window.clearInterval(popupPoll);
    popupPoll = null;
    if (popup && !popup.closed) popup.close();
    popup = null;
    popupNonce = null;
    popupGeneration = null;
  }

  element('training-open-popup').addEventListener('click', () => {
    closePopup();
    popupNonce = uniqueToken();
    popupGeneration = generation;
    popup = window.open(`/assets/training-popup.html?nonce=${encodeURIComponent(popupNonce)}`, `axis_receipt_${popupNonce}`, 'popup,width=520,height=420');
    if (!popup) {
      publish('browser-popup', false, 'The browser blocked the receipt window. Allow popups for this site, then try again.');
      return;
    }
    popup.focus();
    publish('browser-popup', false, 'Receipt window opened. Switch to it and acknowledge the receipt.');
    const openedGeneration = generation;
    popupPoll = window.setInterval(() => {
      if (openedGeneration !== generation) return;
      if (popup?.closed) {
        closePopup();
        publish('browser-popup', false, 'The receipt window was closed without acknowledgement. Open it again to complete the task.');
      }
    }, 500);
  });

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || !popup || event.source !== popup || popupGeneration !== generation) return;
    if (event.data?.type !== 'axis-training-popup-ack' || event.data.nonce !== popupNonce) return;
    closePopup();
    publish('browser-popup', true, 'Receipt acknowledged in its separate browser window.');
  });

  const menu = element('training-file-menu');
  const file = element('training-file');
  function openMenu(event) {
    event.preventDefault();
    if (typeof menu.showPopover !== 'function') {
      publish('browser-menu', false, 'This browser does not support native popovers. Open the lab in a browser with Popover API support.');
      return;
    }
    const bounds = file.getBoundingClientRect();
    const pointer = event.type === 'contextmenu' && (event.clientX || event.clientY);
    const x = pointer ? event.clientX : bounds.left;
    const y = pointer ? event.clientY : bounds.bottom + 4;
    menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - 198))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - 70))}px`;
    if (!menu.matches(':popover-open')) menu.showPopover();
    menuOpened = true;
    element('training-rename').focus();
  }
  file.addEventListener('click', openMenu);
  file.addEventListener('contextmenu', openMenu);
  file.addEventListener('keydown', (event) => {
    if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) openMenu(event);
  });
  element('training-file-actions').addEventListener('click', openMenu);
  menu.addEventListener('keydown', (event) => {
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      element('training-rename').focus();
    }
    if (event.key === 'Escape') file.focus();
  });
  element('training-rename').addEventListener('click', () => {
    menu.hidePopover();
    element('training-rename-form').hidden = false;
    element('training-filename-input').value = element('training-filename').textContent;
    element('training-filename-input').focus();
    element('training-filename-input').select();
  });
  element('training-cancel-name').addEventListener('click', () => {
    element('training-rename-form').hidden = true;
    file.focus();
  });
  element('training-rename-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    const name = element('training-filename-input').value.trim();
    if (!name) {
      publish('browser-menu', false, 'Enter a file name before saving.');
      return;
    }
    element('training-filename').textContent = name;
    element('training-rename-form').hidden = true;
    const passed = menuOpened && name === 'launch-plan-final.txt';
    publish('browser-menu', passed, passed ? 'File renamed to launch-plan-final.txt through the native popover menu.' : `File renamed to ${name}. Rename it to launch-plan-final.txt to complete the task.`);
    file.focus();
  });

  for (let index = 1; index <= 20; index += 1) {
    const row = document.createElement('li');
    const name = document.createElement('span');
    name.textContent = `Delivery ${String(index).padStart(2, '0')} · Dock ${((index - 1) % 4) + 1}`;
    row.append(name);
    if (index === 20) {
      const button = document.createElement('button');
      button.id = 'training-scroll-target';
      button.type = 'button';
      button.textContent = 'Inspect final delivery';
      button.addEventListener('click', () => {
        const list = element('training-delivery-list');
        const reachedEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 8;
        publish('browser-scroll', reachedEnd, reachedEnd ? 'Delivery 20 inspected after reaching the end of the nested list.' : 'Scroll inside the delivery list until its final row is visible.');
      });
      row.append(button);
    } else {
      const time = document.createElement('span');
      time.className = 'bt-delivery-time';
      time.textContent = `${String(8 + Math.floor((index - 1) / 4)).padStart(2, '0')}:${String(((index - 1) % 4) * 15).padStart(2, '0')}`;
      row.append(time);
    }
    element('training-deliveries').append(row);
  }

  element('training-copy').addEventListener('click', async () => {
    const startedGeneration = generation;
    clipboardCopied = false;
    clipboardPasted = false;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser context. Use localhost or HTTPS.');
      await navigator.clipboard.writeText(clipboardReference);
      if (startedGeneration !== generation) return;
      clipboardCopied = true;
      publish('browser-clipboard', false, 'Reference copied to the system clipboard. Paste it into the field, then verify.');
    } catch (failure) {
      if (startedGeneration !== generation) return;
      publish('browser-clipboard', false, failure.name === 'NotAllowedError' ? 'The browser denied clipboard access. Allow clipboard access for this site and try again.' : `Could not copy the reference: ${failure.message}`);
    }
  });
  element('training-clipboard-input').addEventListener('paste', (event) => {
    clipboardPasted = event.clipboardData?.getData('text/plain') === clipboardReference;
  });
  element('training-clipboard-verify').addEventListener('click', () => {
    const passed = clipboardCopied && clipboardPasted && element('training-clipboard-input').value === clipboardReference;
    publish('browser-clipboard', passed, passed ? 'The reference was copied with the Clipboard API and pasted correctly.' : 'Use Copy reference, paste into the field, then verify the exact reference. Typing the reference does not test paste.');
  });

  function reset() {
    generation += 1;
    closePopup();
    dialogs = { alert: false, confirm: false, prompt: false };
    for (const [kind, name] of Object.entries({ alert: 'Alert', confirm: 'Confirmation', prompt: 'Prompt' })) {
      element(`training-${kind}-state`).textContent = `${name}: waiting`;
    }
    if (typeof menu.hidePopover === 'function' && menu.matches(':popover-open')) menu.hidePopover();
    menuOpened = false;
    element('training-rename-form').hidden = true;
    element('training-filename').textContent = 'launch-plan.txt';
    element('training-filename-input').value = '';
    element('training-delivery-list').scrollTop = 0;
    container.querySelector('.bt-scroll-outer').scrollTop = 0;
    clipboardReference = `AXIS-${uniqueToken().slice(0, 12).toUpperCase()}`;
    clipboardCopied = false;
    clipboardPasted = false;
    element('training-clipboard-reference').textContent = clipboardReference;
    element('training-clipboard-input').value = '';
    for (const [id, challenge] of Object.entries(challenges)) publish(id, false, challenge.detail);
  }

  reset();
  return { reset };
}

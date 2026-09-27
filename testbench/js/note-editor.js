class OpsNoteEditor extends HTMLElement {
  constructor() {
    super();
    const shadow = this.attachShadow({ mode: 'open' });
    const template = document.createElement('template');
    template.innerHTML = `
      <style>
        :host { display: block; color: #0f172a; font: inherit; }
        * { box-sizing: border-box; }
        #note-label { display: block; margin: 0 0 6px; font-weight: 600; }
        #note-help, #note-count { margin: 6px 0; color: #475569; font-size: 13px; line-height: 1.5; }
        #note-body { min-height: 145px; max-height: 350px; overflow: auto; padding: 12px; border: 1px solid #94a3b8; border-radius: 8px; background: #fff; color: #0f172a; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; cursor: text; }
        #note-body:focus-visible { outline: 3px solid #0d9488; outline-offset: 2px; }
        #note-body[aria-invalid="true"] { border-color: #b91c1c; }
        #note-count.invalid { color: #b91c1c; }
      </style>
      <span id="note-label">Approval note</span>
      <p id="note-help">Record the reason for your approval. Plain text, up to 5,000 characters.</p>
      <div id="note-body" contenteditable="true" role="textbox" aria-label="Approval note" aria-describedby="note-help note-count" aria-multiline="true" spellcheck="true" tabindex="0"></div>
      <p id="note-count">0 / 5,000 characters</p>
    `;
    shadow.append(template.content.cloneNode(true));
    this._editor = shadow.getElementById('note-body');
    this._count = shadow.getElementById('note-count');
    try {
      this._editor.contentEditable = 'plaintext-only';
    } catch {
      // Older browsers retain the native editable control and use text-only paste below.
    }
    this._editor.addEventListener('paste', (event) => {
      if (this._editor.contentEditable === 'plaintext-only') return;
      event.preventDefault();
      this._insertText(event.clipboardData?.getData('text/plain') || '');
    });
    this._editor.addEventListener('drop', (event) => {
      if (this._editor.contentEditable === 'plaintext-only') return;
      // Prevent rich HTML drops in browsers without plaintext-only editing support.
      event.preventDefault();
    });
    this._editor.addEventListener('input', () => this._changed());
    shadow.getElementById('note-label').addEventListener('click', () => this._editor.focus());
  }

  connectedCallback() {
    // Preserve a .value assigned before the browser upgrades this custom element.
    if (Object.prototype.hasOwnProperty.call(this, 'value')) {
      const value = this.value;
      delete this.value;
      this.value = value;
    }
    this._updateCount();
  }

  get value() {
    return this._editor.innerText.replace(/\r\n?/g, '\n');
  }

  set value(value) {
    this._editor.textContent = String(value ?? '').replace(/\r\n?/g, '\n');
    this._updateCount();
  }

  focus(options) {
    this._editor.focus(options);
  }

  _insertText(text) {
    this._editor.focus();
    // The native insertion command preserves browser undo history where available.
    if (document.execCommand('insertText', false, text)) return;
    const selection = this.shadowRoot.getSelection?.() || window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!this._editor.contains(range.commonAncestorContainer)) return;
    range.deleteContents();
    const node = document.createTextNode(text);
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    this._changed();
  }

  _updateCount() {
    const length = Array.from(this.value).length;
    const invalid = length > 5000;
    this._count.textContent = `${length.toLocaleString('en-US')} / 5,000 characters${invalid ? ' — shorten the note before saving.' : ''}`;
    this._count.classList.toggle('invalid', invalid);
    this._editor.setAttribute('aria-invalid', String(invalid));
  }

  _changed() {
    this._updateCount();
    this.dispatchEvent(new CustomEvent('note-change', {
      bubbles: true,
      composed: true,
      detail: { value: this.value },
    }));
  }
}

customElements.define('ops-note-editor', OpsNoteEditor);

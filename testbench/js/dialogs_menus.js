/**
 * AXIS Testbench - Dialogs, Popups, Context Menus & Toasts
 * Accessible (WAI-ARIA modal dialogs, focus trapping, escape dismissal),
 * destructive double-confirmation, right-click context menu, and floating toast notifications.
 */

class DialogsManager {
  constructor() {
    this.previouslyFocusedElement = null;
  }

  init() {
    this.initModalDialog();
    this.initConfirmDialog();
    this.initContextMenu();
  }

  // ================================================================
  // 1. Accessible Modal Dialog with Focus Trap
  // ================================================================
  initModalDialog() {
    this.btnOpenModal = document.getElementById("btn-open-modal");
    this.modalBackdrop = document.getElementById("modal-backdrop");
    this.btnCloseModal = document.getElementById("btn-close-modal");
    this.btnCancelModal = document.getElementById("btn-cancel-modal");
    this.modalForm = document.getElementById("modal-form");
    this.modalStatus = document.getElementById("modal-status");

    if (!this.modalBackdrop || !this.btnOpenModal) return;

    this.btnOpenModal.addEventListener("click", () => this.openModal());

    const closeModal = () => this.closeModal();
    if (this.btnCloseModal) this.btnCloseModal.addEventListener("click", closeModal);
    if (this.btnCancelModal) this.btnCancelModal.addEventListener("click", closeModal);

    // Dismiss on backdrop click
    this.modalBackdrop.addEventListener("click", (e) => {
      if (e.target === this.modalBackdrop) {
        this.closeModal();
      }
    });

    // Escape key & focus trapping
    window.addEventListener("keydown", (e) => {
      if (!this.modalBackdrop.classList.contains("open")) return;

      if (e.key === "Escape") {
        this.closeModal();
        return;
      }

      if (e.key === "Tab") {
        this.trapFocus(e, this.modalBackdrop);
      }
    });

    // Modal Form Submission
    if (this.modalForm) {
      this.modalForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = document.getElementById("modal-input-name");
        const val = input ? input.value.trim() : "";

        if (!val) {
          this.setModalState("error", "Profile name cannot be empty");
          return;
        }

        this.setModalState("loading");
        setTimeout(() => {
          this.setModalState("success", `Profile "${val}" saved`);
          this.showToast("Success", `Profile configuration for "${val}" updated`, "success");
          window.botDetector.recordEvent("MODAL", `Profile "${val}" saved from modal`, e.isTrusted);
          setTimeout(() => this.closeModal(), 500);
        }, 300);
      });
    }
  }

  openModal() {
    this.previouslyFocusedElement = document.activeElement;
    this.modalBackdrop.classList.add("open");
    this.modalBackdrop.setAttribute("aria-hidden", "false");

    // Focus first focusable element
    const firstInput = this.modalBackdrop.querySelector("input, button");
    if (firstInput) firstInput.focus();

    window.botDetector.recordEvent("POPUP", "Opened modal dialog", true);
  }

  closeModal() {
    this.modalBackdrop.classList.remove("open");
    this.modalBackdrop.setAttribute("aria-hidden", "true");
    if (this.previouslyFocusedElement) {
      this.previouslyFocusedElement.focus();
    }
    window.botDetector.recordEvent("POPUP", "Closed modal dialog", true);
  }

  trapFocus(e, container) {
    const focusables = container.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusables.length === 0) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  setModalState(state, message = "") {
    if (!this.modalStatus) return;
    this.modalStatus.className = "status-alert";

    if (state === "loading") {
      this.modalStatus.className += " info";
      this.modalStatus.textContent = "Saving preferences...";
      this.modalStatus.style.display = "flex";
    } else if (state === "success") {
      this.modalStatus.className += " success";
      this.modalStatus.textContent = message;
      this.modalStatus.style.display = "flex";
    } else if (state === "error") {
      this.modalStatus.className += " error";
      this.modalStatus.textContent = message;
      this.modalStatus.style.display = "flex";
    } else {
      this.modalStatus.style.display = "none";
    }
  }

  // ================================================================
  // 2. Destructive Double-Confirmation Dialog
  // ================================================================
  initConfirmDialog() {
    this.btnTriggerDelete = document.getElementById("btn-trigger-delete");
    this.confirmInput = document.getElementById("confirm-keyword-input");
    this.btnExecuteDelete = document.getElementById("btn-execute-delete");
    this.confirmStatus = document.getElementById("confirm-status");

    if (!this.confirmInput || !this.btnExecuteDelete) return;

    this.confirmInput.addEventListener("input", (e) => {
      const match = e.target.value.trim() === "DELETE";
      this.btnExecuteDelete.disabled = !match;
    });

    this.btnExecuteDelete.addEventListener("click", (e) => {
      this.btnExecuteDelete.disabled = true;
      if (this.confirmStatus) {
        this.confirmStatus.className = "status-alert success";
        this.confirmStatus.textContent = "Action confirmed: Environment purged successfully.";
        this.confirmStatus.style.display = "flex";
      }
      this.showToast("Purged", "Environment data deleted cleanly", "danger");
      window.botDetector.recordEvent("CONFIRM", "Destructive action confirmed with typed keyword", e.isTrusted);
    });
  }

  // ================================================================
  // 3. Custom Context Menu
  // ================================================================
  initContextMenu() {
    this.targetArea = document.getElementById("context-menu-target");
    this.menu = document.getElementById("custom-context-menu");

    if (!this.targetArea || !this.menu) return;

    this.targetArea.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const rect = this.targetArea.getBoundingClientRect();
      this.menu.style.left = `${e.clientX}px`;
      this.menu.style.top = `${e.clientY}px`;
      this.menu.classList.add("open");
      this.menu.setAttribute("aria-hidden", "false");

      window.botDetector.recordEvent("CONTEXT", `Opened custom context menu at (${e.clientX}, ${e.clientY})`, e.isTrusted);
    });

    // Close on document click
    window.addEventListener("click", () => {
      if (this.menu.classList.contains("open")) {
        this.menu.classList.remove("open");
        this.menu.setAttribute("aria-hidden", "true");
      }
    });

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.menu.classList.contains("open")) {
        this.menu.classList.remove("open");
        this.menu.setAttribute("aria-hidden", "true");
      }
    });

    // Menu item actions
    this.menu.querySelectorAll(".context-menu-item").forEach((item) => {
      item.addEventListener("click", (e) => {
        const action = item.dataset.action;
        this.showToast("Context Action", `Executed: ${action}`, "info");
        window.botDetector.recordEvent("CONTEXT", `Clicked context action: ${action}`, e.isTrusted);
      });
    });
  }

  // ================================================================
  // 4. Toast Notification System
  // ================================================================
  showToast(title, message, type = "info", duration = 3500) {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");

    toast.innerHTML = `
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-msg">${message}</div>
      </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-8px)";
      toast.style.transition = "opacity 0.2s, transform 0.2s";
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }
}

window.dialogsManager = new DialogsManager();

/**
 * AXIS Testbench - Drag & Drop and File Selection Module
 * Handles:
 * 1. HTML5 File Dropzone + File Selector Dialog
 * 2. Draggable Kanban / Sortable Task Cards with keyboard accessibility
 */

class DragDropManager {
  constructor() {
    this.files = [];
    this.draggedElement = null;
  }

  init() {
    this.initFileDropzone();
    this.initKanban();
  }

  // ================================================================
  // 1. File Dropzone & Selection
  // ================================================================
  initFileDropzone() {
    this.dropzone = document.getElementById("file-dropzone");
    this.fileInput = document.getElementById("file-input-control");
    this.fileList = document.getElementById("file-list");
    this.dropzoneCard = document.getElementById("dropzone-card");
    this.dropzoneStatus = document.getElementById("dropzone-status");
    this.btnClearFiles = document.getElementById("btn-clear-files");

    if (!this.dropzone || !this.fileInput) return;

    // Click dropzone to trigger native file dialog
    this.dropzone.addEventListener("click", () => {
      this.fileInput.click();
    });

    this.dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        this.fileInput.click();
      }
    });

    // File input change
    this.fileInput.addEventListener("change", (e) => {
      this.handleSelectedFiles(Array.from(e.target.files || []));
    });

    // HTML5 Drag events
    this.dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.dropzone.classList.add("dragover");
    });

    this.dropzone.addEventListener("dragleave", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.dropzone.classList.remove("dragover");
    });

    this.dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.dropzone.classList.remove("dragover");

      if (e.dataTransfer && e.dataTransfer.files) {
        this.handleSelectedFiles(Array.from(e.dataTransfer.files));
        window.botDetector.recordEvent("DROP", `Files dropped onto dropzone (${e.dataTransfer.files.length} items)`, e.isTrusted);
      }
    });

    if (this.btnClearFiles) {
      this.btnClearFiles.addEventListener("click", (e) => {
        e.stopPropagation();
        this.clearFiles();
      });
    }
  }

  handleSelectedFiles(newFiles) {
    if (newFiles.length === 0) return;

    this.setDropzoneState("loading");

    setTimeout(() => {
      const MAX_SIZE = 50 * 1024 * 1024; // 50MB
      let hasError = false;
      let errorMsg = "";

      for (const file of newFiles) {
        if (file.size > MAX_SIZE) {
          hasError = true;
          errorMsg = `File "${file.name}" exceeds 50MB limit`;
          break;
        }
      }

      if (hasError) {
        this.setDropzoneState("error", errorMsg);
        window.botDetector.recordEvent("FILE", errorMsg, true, "warn");
        return;
      }

      this.files.push(...newFiles);
      this.renderFileList();
      this.setDropzoneState("success", `${this.files.length} file(s) loaded successfully`);
      window.botDetector.recordEvent("FILE", `Loaded ${newFiles.length} file(s)`, true);
    }, 200);
  }

  renderFileList() {
    if (!this.fileList) return;
    this.fileList.innerHTML = "";

    if (this.files.length === 0) {
      this.setDropzoneState("empty");
      return;
    }

    this.files.forEach((file, index) => {
      const item = document.createElement("div");
      item.className = "file-item";

      const info = document.createElement("div");
      info.className = "file-info";
      info.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        <div>
          <div class="file-name" title="${file.name}">${file.name}</div>
          <div class="file-size">${this.formatBytes(file.size)}</div>
        </div>
      `;

      const removeBtn = document.createElement("button");
      removeBtn.className = "file-remove-btn";
      removeBtn.setAttribute("aria-label", `Remove ${file.name}`);
      removeBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      `;

      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.files.splice(index, 1);
        this.renderFileList();
        if (this.files.length === 0) {
          this.setDropzoneState("empty");
        }
      });

      item.appendChild(info);
      item.appendChild(removeBtn);
      this.fileList.appendChild(item);
    });
  }

  clearFiles() {
    this.files = [];
    if (this.fileInput) this.fileInput.value = "";
    this.renderFileList();
    this.setDropzoneState("empty");
  }

  formatBytes(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }

  setDropzoneState(state, message = "") {
    if (!this.dropzoneCard || !this.dropzoneStatus) return;

    this.dropzoneCard.classList.remove("state-loading", "state-success", "state-empty", "state-error");
    this.dropzoneStatus.className = "status-alert";

    if (state === "loading") {
      this.dropzoneCard.classList.add("state-loading");
      this.dropzoneStatus.className += " info";
      this.dropzoneStatus.textContent = "Processing files...";
      this.dropzoneStatus.style.display = "flex";
    } else if (state === "success") {
      this.dropzoneCard.classList.add("state-success");
      this.dropzoneStatus.className += " success";
      this.dropzoneStatus.textContent = message;
      this.dropzoneStatus.style.display = "flex";
    } else if (state === "error") {
      this.dropzoneCard.classList.add("state-error");
      this.dropzoneStatus.className += " error";
      this.dropzoneStatus.textContent = message;
      this.dropzoneStatus.style.display = "flex";
    } else {
      this.dropzoneCard.classList.add("state-empty");
      this.dropzoneStatus.style.display = "none";
    }
  }

  // ================================================================
  // 2. Draggable Kanban Cards
  // ================================================================
  initKanban() {
    const columns = document.querySelectorAll(".kanban-col");
    const items = document.querySelectorAll(".kanban-item");

    items.forEach((item) => {
      item.setAttribute("draggable", "true");
      item.setAttribute("tabindex", "0");

      item.addEventListener("dragstart", (e) => {
        this.draggedElement = item;
        item.classList.add("dragging");
        e.dataTransfer.setData("text/plain", item.id);
        e.dataTransfer.effectAllowed = "move";
      });

      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        columns.forEach(col => col.classList.remove("drag-target"));
      });

      // Keyboard accessibility (Space/Enter to pick up, Arrow keys to move)
      item.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          const currentParent = item.closest(".kanban-col");
          const targetCol = currentParent.id === "col-todo"
            ? document.getElementById("col-done")
            : document.getElementById("col-todo");

          if (targetCol) {
            targetCol.appendChild(item);
            this.updateColumnCounts();
            window.botDetector.recordEvent("KANBAN", `Moved "${item.textContent.trim()}" to ${targetCol.id} via keyboard`, e.isTrusted);
          }
        }
      });
    });

    columns.forEach((col) => {
      col.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        col.classList.add("drag-target");
      });

      col.addEventListener("dragleave", () => {
        col.classList.remove("drag-target");
      });

      col.addEventListener("drop", (e) => {
        e.preventDefault();
        col.classList.remove("drag-target");

        if (this.draggedElement) {
          col.appendChild(this.draggedElement);
          this.updateColumnCounts();
          window.botDetector.recordEvent("KANBAN", `Dropped "${this.draggedElement.textContent.trim()}" into ${col.id}`, e.isTrusted);
          this.draggedElement = null;
        }
      });
    });

    this.updateColumnCounts();
  }

  updateColumnCounts() {
    const todoCol = document.getElementById("col-todo");
    const doneCol = document.getElementById("col-done");
    const todoBadge = document.getElementById("badge-todo-count");
    const doneBadge = document.getElementById("badge-done-count");

    if (todoCol && todoBadge) {
      const count = todoCol.querySelectorAll(".kanban-item").length;
      todoBadge.textContent = count;
    }
    if (doneCol && doneBadge) {
      const count = doneCol.querySelectorAll(".kanban-item").length;
      doneBadge.textContent = count;
    }
  }
}

window.dragDropManager = new DragDropManager();

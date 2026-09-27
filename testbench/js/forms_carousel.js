/**
 * AXIS Testbench - Forms, Gestures, Carousel & Dynamic Mutations
 * Handles:
 * 1. Touch/Mouse Swipe Carousel with flick velocity & dot pagination
 * 2. Searchable Combobox Autocomplete with keyboard navigation
 * 3. Multi-Select Tag Input with chip deletion
 * 4. Anti-Paste & International Unicode Layout Testing
 * 5. Dynamic DOM Mutations with 4-state lifecycle (Empty, Loading, Success, Error)
 */

class FormsCarouselManager {
  constructor() {
    this.carousel = {
      currentIndex: 0,
      totalCards: 5,
      cardWidth: 176, // 160px width + 16px gap
      isDragging: false,
      startX: 0,
      currentTranslate: 0,
      prevTranslate: 0,
      startTime: 0
    };

    this.tags = ["Production", "AXIS"];
    this.comboboxOptions = [
      "Chrome DevTools Protocol (CDP)",
      "OS Accessibility Engine (A11y)",
      "Computer Vision & OCR Fallback",
      "Humanized Bezier Kinematics",
      "Model Context Protocol (MCP)",
      "Deterministic Action Tracing"
    ];
  }

  init() {
    this.initCarousel();
    this.initCombobox();
    this.initTagInput();
    this.initProtectedInputs();
    this.initDynamicMutations();
  }

  // ================================================================
  // 1. Swipeable Gesture Carousel
  // ================================================================
  initCarousel() {
    this.viewport = document.getElementById("carousel-viewport");
    this.track = document.getElementById("carousel-track");
    this.btnPrev = document.getElementById("btn-carousel-prev");
    this.btnNext = document.getElementById("btn-carousel-next");
    this.dotsContainer = document.getElementById("carousel-dots");
    this.gestureLabel = document.getElementById("gesture-direction-label");

    if (!this.viewport || !this.track) return;

    this.renderCarouselDots();

    // Button navigation
    if (this.btnPrev) {
      this.btnPrev.addEventListener("click", () => this.navigateCarousel(this.carousel.currentIndex - 1));
    }
    if (this.btnNext) {
      this.btnNext.addEventListener("click", () => this.navigateCarousel(this.carousel.currentIndex + 1));
    }

    // Drag / Swipe Gestures
    this.track.addEventListener("mousedown", (e) => {
      this.carousel.isDragging = true;
      this.carousel.startX = e.clientX;
      this.carousel.startTime = performance.now();
      this.track.style.transition = "none";
    });

    window.addEventListener("mousemove", (e) => {
      if (!this.carousel.isDragging) return;
      const currentX = e.clientX;
      const diff = currentX - this.carousel.startX;
      this.carousel.currentTranslate = this.carousel.prevTranslate + diff;
      this.track.style.transform = `translateX(${this.carousel.currentTranslate}px)`;
    });

    window.addEventListener("mouseup", (e) => {
      if (!this.carousel.isDragging) return;
      this.carousel.isDragging = false;
      this.track.style.transition = "transform 0.3s cubic-bezier(0.2, 1, 0.3, 1)";

      const movedBy = this.carousel.currentTranslate - this.carousel.prevTranslate;
      const duration = performance.now() - this.carousel.startTime;
      const velocity = Math.abs(movedBy) / Math.max(duration, 1);

      // Flick or drag threshold
      if (velocity > 0.4 || Math.abs(movedBy) > 60) {
        if (movedBy < 0) {
          this.navigateCarousel(this.carousel.currentIndex + 1);
          if (this.gestureLabel) this.gestureLabel.textContent = "Gesture: Swipe Left";
        } else {
          this.navigateCarousel(this.carousel.currentIndex - 1);
          if (this.gestureLabel) this.gestureLabel.textContent = "Gesture: Swipe Right";
        }
      } else {
        // Snap back
        this.updateCarouselPosition();
      }

      window.botDetector.recordEvent("GESTURE", `Carousel drag ended (offset: ${movedBy.toFixed(0)}px)`, e.isTrusted);
    });
  }

  navigateCarousel(newIndex) {
    const clamped = Math.max(0, Math.min(this.carousel.totalCards - 1, newIndex));
    this.carousel.currentIndex = clamped;
    this.updateCarouselPosition();
    this.updateCarouselDots();
  }

  updateCarouselPosition() {
    this.carousel.currentTranslate = -this.carousel.currentIndex * this.carousel.cardWidth;
    this.carousel.prevTranslate = this.carousel.currentTranslate;
    if (this.track) {
      this.track.style.transform = `translateX(${this.carousel.currentTranslate}px)`;
    }
  }

  renderCarouselDots() {
    if (!this.dotsContainer) return;
    this.dotsContainer.innerHTML = "";

    for (let i = 0; i < this.carousel.totalCards; i++) {
      const dot = document.createElement("button");
      dot.className = `carousel-dot ${i === 0 ? 'active' : ''}`;
      dot.setAttribute("aria-label", `Slide ${i + 1}`);
      dot.addEventListener("click", () => this.navigateCarousel(i));
      this.dotsContainer.appendChild(dot);
    }
  }

  updateCarouselDots() {
    if (!this.dotsContainer) return;
    const dots = this.dotsContainer.querySelectorAll(".carousel-dot");
    dots.forEach((dot, idx) => {
      dot.classList.toggle("active", idx === this.carousel.currentIndex);
    });
  }

  // ================================================================
  // 2. Searchable Combobox Autocomplete
  // ================================================================
  initCombobox() {
    this.comboboxInput = document.getElementById("combobox-input");
    this.comboboxListbox = document.getElementById("combobox-listbox");
    this.comboboxStatus = document.getElementById("combobox-status");

    if (!this.comboboxInput || !this.comboboxListbox) return;

    let highlightedIdx = -1;

    const renderOptions = (filter = "") => {
      this.comboboxListbox.innerHTML = "";
      const matches = this.comboboxOptions.filter(opt =>
        opt.toLowerCase().includes(filter.toLowerCase())
      );

      if (matches.length === 0) {
        const empty = document.createElement("div");
        empty.className = "combobox-option";
        empty.style.color = "var(--text-muted)";
        empty.textContent = "No matching modules found";
        this.comboboxListbox.appendChild(empty);
        return;
      }

      matches.forEach((opt, idx) => {
        const optionEl = document.createElement("div");
        optionEl.className = `combobox-option ${idx === highlightedIdx ? 'highlighted' : ''}`;
        optionEl.setAttribute("role", "option");
        optionEl.textContent = opt;

        optionEl.addEventListener("click", () => {
          this.selectComboboxOption(opt);
        });

        this.comboboxListbox.appendChild(optionEl);
      });
    };

    this.comboboxInput.addEventListener("focus", () => {
      this.comboboxListbox.classList.add("open");
      this.comboboxInput.setAttribute("aria-expanded", "true");
      renderOptions(this.comboboxInput.value);
    });

    this.comboboxInput.addEventListener("input", (e) => {
      highlightedIdx = -1;
      this.comboboxListbox.classList.add("open");
      this.comboboxInput.setAttribute("aria-expanded", "true");
      renderOptions(e.target.value);
    });

    // Keyboard navigation
    this.comboboxInput.addEventListener("keydown", (e) => {
      const options = this.comboboxListbox.querySelectorAll(".combobox-option[role='option']");

      if (e.key === "ArrowDown") {
        e.preventDefault();
        highlightedIdx = Math.min(options.length - 1, highlightedIdx + 1);
        this.highlightOption(options, highlightedIdx);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        highlightedIdx = Math.max(0, highlightedIdx - 1);
        this.highlightOption(options, highlightedIdx);
      } else if (e.key === "Enter" && highlightedIdx >= 0 && options[highlightedIdx]) {
        e.preventDefault();
        this.selectComboboxOption(options[highlightedIdx].textContent);
      } else if (e.key === "Escape") {
        this.comboboxListbox.classList.remove("open");
        this.comboboxInput.setAttribute("aria-expanded", "false");
      }
    });

    // Dismiss on click outside
    document.addEventListener("click", (e) => {
      if (!this.comboboxInput.contains(e.target) && !this.comboboxListbox.contains(e.target)) {
        this.comboboxListbox.classList.remove("open");
        this.comboboxInput.setAttribute("aria-expanded", "false");
      }
    });
  }

  highlightOption(options, idx) {
    options.forEach((opt, i) => opt.classList.toggle("highlighted", i === idx));
    if (options[idx]) options[idx].scrollIntoView({ block: "nearest" });
  }

  selectComboboxOption(val) {
    if (!this.comboboxInput) return;
    this.comboboxInput.value = val;
    this.comboboxListbox.classList.remove("open");
    this.comboboxInput.setAttribute("aria-expanded", "false");

    if (this.comboboxStatus) {
      this.comboboxStatus.textContent = `Selected: ${val}`;
      this.comboboxStatus.style.display = "block";
    }

    window.botDetector.recordEvent("FORM", `Combobox selected "${val}"`, true);
  }

  // ================================================================
  // 3. Multi-Select Tag Input
  // ================================================================
  initTagInput() {
    this.tagContainer = document.getElementById("tags-container");
    this.tagInput = document.getElementById("tags-inner-input");

    if (!this.tagContainer || !this.tagInput) return;

    this.renderTags();

    this.tagInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        const val = this.tagInput.value.trim().replace(/^,+|,+$/g, "");
        if (val && !this.tags.includes(val)) {
          this.tags.push(val);
          this.tagInput.value = "";
          this.renderTags();
          window.botDetector.recordEvent("TAGS", `Added tag "${val}"`, e.isTrusted);
        }
      } else if (e.key === "Backspace" && this.tagInput.value === "" && this.tags.length > 0) {
        const removed = this.tags.pop();
        this.renderTags();
        window.botDetector.recordEvent("TAGS", `Deleted tag "${removed}"`, e.isTrusted);
      }
    });
  }

  renderTags() {
    if (!this.tagContainer || !this.tagInput) return;

    // Remove existing chips
    this.tagContainer.querySelectorAll(".tag-chip").forEach(c => c.remove());

    this.tags.forEach((tag, index) => {
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.textContent = tag;

      const removeBtn = document.createElement("button");
      removeBtn.className = "tag-remove-btn";
      removeBtn.setAttribute("aria-label", `Remove tag ${tag}`);
      removeBtn.innerHTML = "&times;";

      removeBtn.addEventListener("click", () => {
        this.tags.splice(index, 1);
        this.renderTags();
      });

      chip.appendChild(removeBtn);
      this.tagContainer.insertBefore(chip, this.tagInput);
    });
  }

  // ================================================================
  // 4. Protected Form Fields
  // ================================================================
  initProtectedInputs() {
    const pasteInput = document.getElementById("input-anti-paste");
    const pasteStatus = document.getElementById("anti-paste-feedback");
    const pwdInput = document.getElementById("input-masked-pwd");
    const btnTogglePwd = document.getElementById("btn-toggle-pwd");

    if (pasteInput && pasteStatus) {
      pasteInput.addEventListener("paste", (e) => {
        e.preventDefault();
        pasteStatus.className = "status-alert error";
        pasteStatus.textContent = "Paste blocked by security policy. Keystrokes required.";
        pasteStatus.style.display = "flex";
        window.botDetector.recordEvent("SECURITY", "Paste attempt blocked on protected field", e.isTrusted, "warn");
      });

      pasteInput.addEventListener("input", () => {
        pasteStatus.className = "status-alert success";
        pasteStatus.textContent = `Valid keystroke sequence received (${pasteInput.value.length} chars)`;
        pasteStatus.style.display = "flex";
      });
    }

    if (pwdInput && btnTogglePwd) {
      btnTogglePwd.addEventListener("click", () => {
        const isPwd = pwdInput.type === "password";
        pwdInput.type = isPwd ? "text" : "password";
        btnTogglePwd.setAttribute("aria-label", isPwd ? "Hide password" : "Show password");
      });
    }
  }

  // ================================================================
  // 5. Dynamic DOM Mutations (Testing wait_for & wait_for_text)
  // ================================================================
  initDynamicMutations() {
    this.btnTriggerMutation = document.getElementById("btn-trigger-mutation");
    this.mutationArea = document.getElementById("mutation-target-area");
    this.mutationCard = document.getElementById("mutation-card");

    if (!this.btnTriggerMutation || !this.mutationArea) return;

    this.btnTriggerMutation.addEventListener("click", (e) => {
      // 1. Loading State
      this.setMutationState("loading");

      setTimeout(() => {
        // 2. Success State: Inject target DOM element
        this.setMutationState("success");
        window.botDetector.recordEvent("MUTATION", "Dynamic DOM node injected after 800ms wait", e.isTrusted);
      }, 800);
    });

    const btnClear = document.getElementById("btn-clear-mutation");
    if (btnClear) {
      btnClear.addEventListener("click", () => this.setMutationState("empty"));
    }
  }

  setMutationState(state) {
    if (!this.mutationCard || !this.mutationArea) return;

    this.mutationCard.classList.remove("state-loading", "state-success", "state-empty", "state-error");

    if (state === "loading") {
      this.mutationCard.classList.add("state-loading");
      this.mutationArea.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; color:var(--accent);">
          <div class="spinner"></div>
          <span style="font-size:13px;">Asynchronous worker executing pipeline...</span>
        </div>
      `;
    } else if (state === "success") {
      this.mutationCard.classList.add("state-success");
      this.mutationArea.innerHTML = `
        <div id="async-verified-payload" class="status-alert success" style="width:100%; display:flex;">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="currentColor" style="flex-shrink:0;">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
          </svg>
          <span><strong>Dynamic Mutation Loaded:</strong> AXIS_PAYLOAD_READY_4920</span>
        </div>
      `;
    } else {
      this.mutationCard.classList.add("state-empty");
      this.mutationArea.innerHTML = `
        <span style="font-size: 13px; color: var(--text-muted);">Idle - No active mutation. Ready for trigger.</span>
      `;
    }
  }
}

window.formsCarouselManager = new FormsCarouselManager();

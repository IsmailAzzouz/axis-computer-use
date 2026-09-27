/**
 * AXIS Testbench - Captcha Verification Engine
 * Implements 3 real-world CAPTCHA systems:
 * 1. GeeTest Jigsaw Slider (Kinematics & Bezier cutout)
 * 2. Cloudflare Turnstile Checkbox (Dwell & Token clearance)
 * 3. 3x3 Tile Grid Challenge (Object classification & timing)
 */

class CaptchaEngine {
  constructor() {
    this.jigsaw = {
      targetX: 280,
      targetY: 80,
      pieceSize: 42,
      isDragging: false,
      startX: 0,
      currentX: 0,
      trajectory: [],
      maxSlide: 396 // 440px track width - 44px handle
    };

    this.turnstile = {
      isVerifying: false,
      isVerified: false,
      token: null
    };

    this.tileGrid = {
      targetCategory: "traffic-light",
      selectedTiles: new Set(),
      targetIndices: [1, 4, 7] // 0-indexed tiles containing target
    };
  }

  // ----------------------------------------------------------------
  // Initialize All Captchas
  // ----------------------------------------------------------------
  init() {
    this.initJigsawCaptcha();
    this.initTurnstileCaptcha();
    this.initTileGridCaptcha();
  }

  // ================================================================
  // 1. GeeTest-style Jigsaw Puzzle Slider
  // ================================================================
  initJigsawCaptcha() {
    this.bgCanvas = document.getElementById("bg-canvas");
    this.pieceCanvas = document.getElementById("piece-canvas");
    this.sliderHandle = document.getElementById("slider-handle");
    this.trackProgress = document.getElementById("track-progress");
    this.trackHint = document.getElementById("track-hint");
    this.jigsawStatus = document.getElementById("jigsaw-status");
    this.btnReloadJigsaw = document.getElementById("btn-reload-jigsaw");

    if (!this.bgCanvas || !this.pieceCanvas || !this.sliderHandle) return;

    this.bgCtx = this.bgCanvas.getContext("2d");
    this.pieceCtx = this.pieceCanvas.getContext("2d");

    this.resetJigsaw();

    // Mouse drag handlers
    const onMouseDown = (e) => {
      this.jigsaw.isDragging = true;
      this.jigsaw.startX = e.clientX;
      this.jigsaw.trajectory = [{
        x: e.clientX,
        y: e.clientY,
        t: performance.now(),
        isTrusted: e.isTrusted
      }];
      document.body.style.userSelect = "none";
    };

    const onMouseMove = (e) => {
      if (!this.jigsaw.isDragging) return;
      const dx = e.clientX - this.jigsaw.startX;
      const clampedX = Math.max(0, Math.min(this.jigsaw.maxSlide, dx));
      this.jigsaw.currentX = clampedX;

      this.sliderHandle.style.left = `${clampedX + 2}px`;
      this.trackProgress.style.width = `${clampedX + 20}px`;
      this.pieceCanvas.style.left = `${clampedX}px`;

      this.jigsaw.trajectory.push({
        x: e.clientX,
        y: e.clientY,
        t: performance.now(),
        isTrusted: e.isTrusted
      });
    };

    const onMouseUp = (e) => {
      if (!this.jigsaw.isDragging) return;
      this.jigsaw.isDragging = false;
      document.body.style.userSelect = "";

      this.jigsaw.trajectory.push({
        x: e.clientX,
        y: e.clientY,
        t: performance.now(),
        isTrusted: e.isTrusted
      });

      this.verifyJigsaw();
    };

    this.sliderHandle.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    if (this.btnReloadJigsaw) {
      this.btnReloadJigsaw.addEventListener("click", () => this.resetJigsaw());
    }
  }

  // Draw Jigsaw Puzzle Slot & Piece
  // Complexity: O(1)
  resetJigsaw() {
    this.setJigsawState("loading");

    // Randomize target position between 180 and 360
    this.jigsaw.targetX = Math.floor(180 + Math.random() * 180);
    this.jigsaw.targetY = 70;
    this.jigsaw.currentX = 0;
    this.jigsaw.trajectory = [];

    this.sliderHandle.style.left = "2px";
    this.trackProgress.style.width = "0px";
    this.pieceCanvas.style.left = "0px";

    // Draw background texture
    this.drawBackgroundScene(this.bgCtx);

    // Draw cutout on background
    this.bgCtx.save();
    this.createJigsawPath(this.bgCtx, this.jigsaw.targetX, this.jigsaw.targetY, this.jigsaw.pieceSize);
    this.bgCtx.fillStyle = "rgba(0, 0, 0, 0.65)";
    this.bgCtx.fill();
    this.bgCtx.lineWidth = 2;
    this.bgCtx.strokeStyle = "rgba(255, 255, 255, 0.4)";
    this.bgCtx.stroke();
    this.bgCtx.restore();

    // Draw piece on piece canvas
    this.pieceCtx.clearRect(0, 0, this.pieceCanvas.width, this.pieceCanvas.height);
    this.pieceCtx.save();
    this.createJigsawPath(this.pieceCtx, this.jigsaw.targetX, this.jigsaw.targetY, this.jigsaw.pieceSize);
    this.pieceCtx.clip();
    this.drawBackgroundScene(this.pieceCtx);
    this.pieceCtx.lineWidth = 2;
    this.pieceCtx.strokeStyle = "#3b82f6";
    this.pieceCtx.stroke();
    this.pieceCtx.restore();

    this.setJigsawState("empty");
  }

  // Draw procedural geometric scenery (no external images required)
  drawBackgroundScene(ctx) {
    ctx.clearRect(0, 0, 440, 200);

    // Dark sky gradient
    const sky = ctx.createLinearGradient(0, 0, 0, 160);
    sky.addColorStop(0, "#090d16");
    sky.addColorStop(1, "#1e293b");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, 440, 200);

    // Procedural grid skyline
    ctx.fillStyle = "#111827";
    for (let x = 0; x < 440; x += 32) {
      const h = 40 + ((x * 13) % 90);
      ctx.fillRect(x, 200 - h, 28, h);
    }

    // Windows in buildings
    ctx.fillStyle = "#38bdf8";
    for (let x = 4; x < 440; x += 32) {
      const h = 40 + ((x * 13) % 90);
      for (let y = 200 - h + 8; y < 190; y += 14) {
        if ((x + y) % 3 === 0) {
          ctx.fillRect(x + 4, y, 6, 6);
        }
      }
    }

    // Road / ground
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 185, 440, 15);
  }

  // Creates the jigsaw tab notch path
  createJigsawPath(ctx, x, y, s) {
    const tabR = s * 0.22;
    ctx.beginPath();
    ctx.moveTo(x, y);
    // Top tab
    ctx.lineTo(x + s * 0.4, y);
    ctx.arc(x + s * 0.5, y - tabR * 0.6, tabR, 0.8 * Math.PI, 0.2 * Math.PI, false);
    ctx.lineTo(x + s, y);
    // Right tab
    ctx.lineTo(x + s, y + s * 0.4);
    ctx.arc(x + s + tabR * 0.6, y + s * 0.5, tabR, 1.3 * Math.PI, 0.7 * Math.PI, false);
    ctx.lineTo(x + s, y + s);
    // Bottom
    ctx.lineTo(x, y + s);
    // Left edge
    ctx.closePath();
  }

  verifyJigsaw() {
    this.setJigsawState("loading");

    const deltaX = Math.abs(this.jigsaw.currentX - this.jigsaw.targetX);
    const posValid = deltaX <= 4.0;

    // Evaluate kinematics
    const result = window.botDetector.evaluateTrajectory(this.jigsaw.trajectory);

    setTimeout(() => {
      if (posValid && result.isHuman) {
        this.setJigsawState("success", `Verified! Delta=${deltaX.toFixed(1)}px, Human Score=${result.score}%`);
        window.botDetector.recordEvent("CAPTCHA", `GeeTest Jigsaw passed (Score=${result.score}%)`, true);
      } else {
        const reason = !posValid
          ? `Misaligned position (Delta: ${deltaX.toFixed(1)}px)`
          : `Bot kinematics detected: ${result.reasons.join(", ")}`;
        this.setJigsawState("error", reason);
        window.botDetector.recordEvent("BOT", `GeeTest Jigsaw failed (${reason})`, false, "bot");
      }
    }, 250);
  }

  setJigsawState(state, message = "") {
    const card = document.getElementById("jigsaw-card");
    if (!card || !this.jigsawStatus) return;

    card.classList.remove("state-loading", "state-success", "state-empty", "state-error");
    this.jigsawStatus.className = "status-alert";

    if (state === "loading") {
      card.classList.add("state-loading");
      this.jigsawStatus.className += " info";
      this.jigsawStatus.textContent = "Analyzing kinematics & target precision...";
      this.jigsawStatus.style.display = "flex";
    } else if (state === "success") {
      card.classList.add("state-success");
      this.jigsawStatus.className += " success";
      this.jigsawStatus.textContent = message;
      this.jigsawStatus.style.display = "flex";
    } else if (state === "error") {
      card.classList.add("state-error");
      this.jigsawStatus.className += " error";
      this.jigsawStatus.textContent = message;
      this.jigsawStatus.style.display = "flex";
    } else {
      card.classList.add("state-empty");
      this.jigsawStatus.style.display = "none";
    }
  }

  // ================================================================
  // 2. Cloudflare Turnstile-style Checkbox
  // ================================================================
  initTurnstileCaptcha() {
    this.turnstileBox = document.getElementById("turnstile-box");
    this.turnstileCheck = document.getElementById("turnstile-check");
    this.turnstileStatus = document.getElementById("turnstile-status");

    if (!this.turnstileBox || !this.turnstileCheck) return;

    this.turnstileCheck.addEventListener("click", () => {
      if (this.turnstile.isVerifying || this.turnstile.isVerified) return;

      this.setTurnstileState("loading");
      const clickCheck = window.botDetector.evaluateClick(this.turnstileCheck);

      // Verify browser markers & dwell
      setTimeout(() => {
        const isBot = window.botDetector.metrics.webdriverDetected || clickCheck.dwell < 30;

        if (!isBot) {
          this.turnstile.isVerified = true;
          this.turnstile.token = `0.cf-axis-${Math.random().toString(36).substring(2, 12)}`;
          this.setTurnstileState("success", `Verification Token: ${this.turnstile.token}`);
          window.botDetector.recordEvent("CAPTCHA", "Turnstile challenge verified", true);
        } else {
          this.setTurnstileState("error", "Automated environment detected. Verification blocked.");
          window.botDetector.recordEvent("BOT", "Turnstile challenge failed bot check", false, "bot");
        }
      }, 700);
    });
  }

  setTurnstileState(state, message = "") {
    const card = document.getElementById("turnstile-card");
    if (!card || !this.turnstileStatus) return;

    card.classList.remove("state-loading", "state-success", "state-empty", "state-error");
    this.turnstileStatus.className = "status-alert";

    if (state === "loading") {
      this.turnstile.isVerifying = true;
      card.classList.add("state-loading");
      this.turnstileCheck.innerHTML = '<div class="spinner"></div>';
      this.turnstileStatus.className += " info";
      this.turnstileStatus.textContent = "Verifying browser integrity...";
      this.turnstileStatus.style.display = "flex";
    } else if (state === "success") {
      this.turnstile.isVerifying = false;
      card.classList.add("state-success");
      this.turnstileCheck.classList.add("checked");
      this.turnstileCheck.innerHTML = '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>';
      this.turnstileStatus.className += " success";
      this.turnstileStatus.textContent = message;
      this.turnstileStatus.style.display = "flex";
    } else if (state === "error") {
      this.turnstile.isVerifying = false;
      card.classList.add("state-error");
      this.turnstileCheck.innerHTML = "";
      this.turnstileStatus.className += " error";
      this.turnstileStatus.textContent = message;
      this.turnstileStatus.style.display = "flex";
    }
  }

  // ================================================================
  // 3. hCaptcha/reCAPTCHA-style 3x3 Tile Grid
  // ================================================================
  initTileGridCaptcha() {
    this.gridContainer = document.getElementById("captcha-3x3-grid");
    this.btnVerifyGrid = document.getElementById("btn-verify-grid");
    this.btnReloadGrid = document.getElementById("btn-reload-grid");
    this.gridStatus = document.getElementById("grid-status");

    if (!this.gridContainer) return;

    this.renderTileGrid();

    if (this.btnVerifyGrid) {
      this.btnVerifyGrid.addEventListener("click", () => this.verifyTileGrid());
    }
    if (this.btnReloadGrid) {
      this.btnReloadGrid.addEventListener("click", () => this.renderTileGrid());
    }
  }

  // Renders 9 canvas tiles with distinct vector markers
  renderTileGrid() {
    this.tileGrid.selectedTiles.clear();
    this.setGridState("empty");
    this.gridContainer.innerHTML = "";

    // Pick 3 random target tiles
    const indices = [0, 1, 2, 3, 4, 5, 6, 7, 8].sort(() => 0.5 - Math.random());
    this.tileGrid.targetIndices = indices.slice(0, 3);

    for (let i = 0; i < 9; i++) {
      const tile = document.createElement("div");
      tile.className = "grid-tile";
      tile.setAttribute("role", "checkbox");
      tile.setAttribute("aria-checked", "false");
      tile.setAttribute("tabindex", "0");
      tile.dataset.index = i;

      const canvas = document.createElement("canvas");
      canvas.width = 100;
      canvas.height = 100;
      canvas.className = "tile-canvas";
      const ctx = canvas.getContext("2d");

      const isTarget = this.tileGrid.targetIndices.includes(i);
      this.drawTileGraphic(ctx, isTarget, i);

      const checkmark = document.createElement("div");
      checkmark.className = "tile-checkmark";
      checkmark.innerHTML = '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>';

      tile.appendChild(canvas);
      tile.appendChild(checkmark);

      // Tile selection handler
      const toggleTile = () => {
        if (this.tileGrid.selectedTiles.has(i)) {
          this.tileGrid.selectedTiles.delete(i);
          tile.classList.remove("selected");
          tile.setAttribute("aria-checked", "false");
        } else {
          this.tileGrid.selectedTiles.add(i);
          tile.classList.add("selected");
          tile.setAttribute("aria-checked", "true");
        }
      };

      tile.addEventListener("click", toggleTile);
      tile.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleTile();
        }
      });

      this.gridContainer.appendChild(tile);
    }
  }

  drawTileGraphic(ctx, isTarget, index) {
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, 100, 100);

    if (isTarget) {
      // Traffic Light vector graphic
      ctx.fillStyle = "#334155";
      ctx.fillRect(38, 15, 24, 65);
      // Red light
      ctx.fillStyle = "#ef4444";
      ctx.beginPath();
      ctx.arc(50, 28, 7, 0, Math.PI * 2);
      ctx.fill();
      // Amber light
      ctx.fillStyle = "#f59e0b";
      ctx.beginPath();
      ctx.arc(50, 47, 7, 0, Math.PI * 2);
      ctx.fill();
      // Green light
      ctx.fillStyle = "#10b981";
      ctx.beginPath();
      ctx.arc(50, 66, 7, 0, Math.PI * 2);
      ctx.fill();
    } else {
      // Non-target graphic (e.g. geometric tree or building)
      ctx.fillStyle = "#1e293b";
      ctx.beginPath();
      ctx.moveTo(20, 80);
      ctx.lineTo(50, 25);
      ctx.lineTo(80, 80);
      ctx.closePath();
      ctx.fill();
    }
  }

  verifyTileGrid() {
    this.setGridState("loading");

    setTimeout(() => {
      const selectedArr = Array.from(this.tileGrid.selectedTiles).sort();
      const targetArr = [...this.tileGrid.targetIndices].sort();

      const isMatch = selectedArr.length === targetArr.length &&
        selectedArr.every((val, index) => val === targetArr[index]);

      if (isMatch) {
        this.setGridState("success", "Correct! All target tiles verified.");
        window.botDetector.recordEvent("CAPTCHA", "3x3 Tile Grid solved successfully", true);
      } else {
        this.setGridState("error", "Incorrect tiles selected. Please try again.");
        window.botDetector.recordEvent("BOT", "3x3 Tile Grid failed selection", false, "warn");
      }
    }, 400);
  }

  setGridState(state, message = "") {
    const card = document.getElementById("grid-card");
    if (!card || !this.gridStatus) return;

    card.classList.remove("state-loading", "state-success", "state-empty", "state-error");
    this.gridStatus.className = "status-alert";

    if (state === "loading") {
      card.classList.add("state-loading");
      this.gridStatus.className += " info";
      this.gridStatus.textContent = "Verifying tile classification...";
      this.gridStatus.style.display = "flex";
    } else if (state === "success") {
      card.classList.add("state-success");
      this.gridStatus.className += " success";
      this.gridStatus.textContent = message;
      this.gridStatus.style.display = "flex";
    } else if (state === "error") {
      card.classList.add("state-error");
      this.gridStatus.className += " error";
      this.gridStatus.textContent = message;
      this.gridStatus.style.display = "flex";
    } else {
      card.classList.add("state-empty");
      this.gridStatus.style.display = "none";
    }
  }
}

window.captchaEngine = new CaptchaEngine();

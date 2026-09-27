/**
 * AXIS Testbench - Real-World Bot Detection & Biometrics Engine
 * Analyzes kinematics (curvature, velocity, jitter, dwell), keystroke dynamics,
 * event trustworthiness (isTrusted), and browser automation markers.
 */

class BotDetector {
  constructor() {
    this.mouseHistory = [];
    this.keyHistory = [];
    this.lastMouseMoveTime = performance.now();
    this.hoverStartTime = 0;
    this.currentHoverElement = null;

    // Metrics aggregates
    this.metrics = {
      isTrustedRatio: 1.0,
      pathCurvature: 1.0,
      velocityProfile: "Unknown",
      microJitterStdDev: 0.0,
      dwellDurationMs: 0,
      typingCadenceStdDev: 0.0,
      webdriverDetected: false,
      overallScore: 100
    };

    this.listeners = [];
    this.initEventListeners();
    this.runEnvironmentChecks();
  }

  // ----------------------------------------------------------------
  // Real-time Event Listeners
  // ----------------------------------------------------------------
  initEventListeners() {
    // Mouse movement telemetry
    window.addEventListener("mousemove", (e) => {
      const now = performance.now();
      this.mouseHistory.push({
        x: e.clientX,
        y: e.clientY,
        t: now,
        isTrusted: e.isTrusted
      });

      // Keep recent 120 points for sliding window analysis
      if (this.mouseHistory.length > 120) {
        this.mouseHistory.shift();
      }

      this.lastMouseMoveTime = now;
      this.recordEvent("MOUSE", `Move to (${e.clientX}, ${e.clientY}) [trusted=${e.isTrusted}]`, e.isTrusted);
    }, { passive: true });

    // Hover dwell tracking
    document.addEventListener("mouseover", (e) => {
      this.hoverStartTime = performance.now();
      this.currentHoverElement = e.target;
    }, { passive: true });

    // Keystroke cadence tracking
    window.addEventListener("keydown", (e) => {
      const now = performance.now();
      this.keyHistory.push({
        key: e.key,
        keyDownTime: now,
        keyUpTime: null,
        isTrusted: e.isTrusted
      });

      if (this.keyHistory.length > 50) {
        this.keyHistory.shift();
      }

      this.analyzeKeystrokes();
      this.recordEvent("KEY", `Keydown "${e.key.length === 1 ? e.key : '[' + e.key + ']'}"`, e.isTrusted);
    }, { passive: true });

    window.addEventListener("keyup", (e) => {
      const now = performance.now();
      const last = this.keyHistory.find(k => k.key === e.key && k.keyUpTime === null);
      if (last) {
        last.keyUpTime = now;
      }
      this.analyzeKeystrokes();
    }, { passive: true });
  }

  // ----------------------------------------------------------------
  // Browser Environment & Fingerprint Checks
  // ----------------------------------------------------------------
  runEnvironmentChecks() {
    // Check navigator.webdriver
    const isWebdriver = Boolean(navigator.webdriver);
    this.metrics.webdriverDetected = isWebdriver;

    if (isWebdriver) {
      this.recordEvent("ENV", "navigator.webdriver is TRUE (Automated Browser)", false, "bot");
    } else {
      this.recordEvent("ENV", "navigator.webdriver is FALSE (Normal User Agent)", true);
    }

    // Check viewport sanity
    const dimensionsValid = window.innerWidth > 0 && window.innerHeight > 0;
    if (!dimensionsValid) {
      this.recordEvent("ENV", "Invalid window dimensions (0x0 headless container)", false, "bot");
    }
  }

  // ----------------------------------------------------------------
  // Trajectory Kinematics Analyzer
  // Complexity: O(N) where N is the number of trajectory coordinates
  // ----------------------------------------------------------------
  evaluateTrajectory(coords) {
    if (!coords || coords.length < 5) {
      return {
        isHuman: false,
        score: 10,
        reason: "Insufficient trajectory data points (< 5)"
      };
    }

    const n = coords.length;
    const start = coords[0];
    const end = coords[n - 1];

    // 1. Direct Euclidean distance
    const euclideanDist = Math.hypot(end.x - start.x, end.y - start.y);
    if (euclideanDist < 5) {
      return { isHuman: false, score: 20, reason: "Movement distance too small" };
    }

    // 2. Arc length & Curvature
    let arcLength = 0;
    let untrustedCount = 0;
    const velocities = [];

    for (let i = 1; i < n; i++) {
      const p0 = coords[i - 1];
      const p1 = coords[i];
      const stepDist = Math.hypot(p1.x - p0.x, p1.y - p0.y);
      const dt = Math.max((p1.t - p0.t), 1); // ms
      arcLength += stepDist;
      velocities.push(stepDist / dt); // px/ms

      if (p1.isTrusted === false) {
        untrustedCount++;
      }
    }

    const curvature = arcLength / euclideanDist;
    this.metrics.pathCurvature = Number(curvature.toFixed(3));

    // 3. Perpendicular Jitter (physiological tremor)
    // Line equation from start to end: A*x + B*y + C = 0
    const A = end.y - start.y;
    const B = start.x - end.x;
    const C = end.x * start.y - start.x * end.y;
    const denom = Math.hypot(A, B) || 1;

    let perpDistances = [];
    for (let i = 1; i < n - 1; i++) {
      const p = coords[i];
      const dist = Math.abs(A * p.x + B * p.y + C) / denom;
      perpDistances.push(dist);
    }

    const meanDist = perpDistances.reduce((a, b) => a + b, 0) / (perpDistances.length || 1);
    const variance = perpDistances.reduce((sum, d) => sum + Math.pow(d - meanDist, 2), 0) / (perpDistances.length || 1);
    const jitterStdDev = Math.sqrt(variance);
    this.metrics.microJitterStdDev = Number(jitterStdDev.toFixed(2));

    // 4. Velocity Profile (Fitts' Law check: acceleration -> coast -> deceleration)
    const midIdx = Math.floor(velocities.length / 2);
    const peakVelocity = Math.max(...velocities);
    const endingVelocity = velocities[velocities.length - 1] || 0;
    const deceleratedAtEnd = endingVelocity <= peakVelocity * 0.8;
    this.metrics.velocityProfile = deceleratedAtEnd ? "Decelerated (Human)" : "Constant/Linear (Bot)";

    // 5. Compute Trust Penalty & Final Human Probability
    let score = 100;
    const reasons = [];

    // Synthetic events flag
    if (untrustedCount > 0) {
      score -= 50;
      reasons.push("Untrusted synthetic DOM events detected");
    }

    // Zero jitter penalty (robotic straight line)
    if (jitterStdDev < 0.05 && curvature < 1.002) {
      score -= 40;
      reasons.push("Perfect linear path with zero physiological tremor");
    }

    // Lack of deceleration penalty
    if (!deceleratedAtEnd && peakVelocity > 0.5) {
      score -= 20;
      reasons.push("Instant stop without kinetic deceleration");
    }

    // Velocity uniformness check (e.g. fixed interval bot steps)
    const velDiffs = [];
    for (let i = 1; i < velocities.length; i++) {
      velDiffs.push(Math.abs(velocities[i] - velocities[i - 1]));
    }
    const avgVelDiff = velDiffs.reduce((a, b) => a + b, 0) / (velDiffs.length || 1);
    if (avgVelDiff < 0.001) {
      score -= 30;
      reasons.push("Uniform step intervals with zero velocity variance");
    }

    score = Math.max(0, Math.min(100, score));
    const isHuman = score >= 60;

    return {
      isHuman,
      score,
      curvature,
      jitterStdDev,
      deceleratedAtEnd,
      reasons: reasons.length > 0 ? reasons : ["Valid human kinematics curve"]
    };
  }

  // ----------------------------------------------------------------
  // Keystroke Cadence Analysis
  // Complexity: O(M) where M is recent keystrokes
  // ----------------------------------------------------------------
  analyzeKeystrokes() {
    const completed = this.keyHistory.filter(k => k.keyUpTime !== null);
    if (completed.length < 4) return;

    // Flight times (interval between keydown[i] and keydown[i-1])
    const flightTimes = [];
    for (let i = 1; i < completed.length; i++) {
      flightTimes.push(completed[i].keyDownTime - completed[i - 1].keyDownTime);
    }

    const mean = flightTimes.reduce((a, b) => a + b, 0) / flightTimes.length;
    const variance = flightTimes.reduce((sum, ft) => sum + Math.pow(ft - mean, 2), 0) / flightTimes.length;
    const stdDev = Math.sqrt(variance);

    this.metrics.typingCadenceStdDev = Number(stdDev.toFixed(1));

    // If stdDev is near 0 with multiple keys, it's an automated script
    if (stdDev < 2.0 && flightTimes.length >= 5) {
      this.recordEvent("BOT", `Uniform typing detected (StdDev=${stdDev}ms)`, false, "bot");
    }
  }

  // ----------------------------------------------------------------
  // Click Dwell Time Evaluation
  // ----------------------------------------------------------------
  evaluateClick(targetElement) {
    const now = performance.now();
    const dwell = this.hoverStartTime > 0 ? (now - this.hoverStartTime) : 0;
    this.metrics.dwellDurationMs = Math.round(dwell);

    const isInstant = dwell < 35; // Instantaneous click without dwell
    if (isInstant) {
      this.recordEvent("BOT", `Instant click with ${dwell.toFixed(0)}ms dwell time`, false, "warn");
    }
    return { dwell, isInstant };
  }

  // ----------------------------------------------------------------
  // Telemetry Log & Notification Dispatcher
  // ----------------------------------------------------------------
  recordEvent(category, message, isTrusted = true, level = "info") {
    const entry = {
      timestamp: new Date().toISOString().substring(11, 23),
      category,
      message,
      isTrusted,
      level
    };

    // Notify registered UI observers
    for (const listener of this.listeners) {
      listener(entry, this.metrics);
    }
  }

  subscribe(listener) {
    this.listeners.push(listener);
  }
}

// Instantiate singleton
window.botDetector = new BotDetector();

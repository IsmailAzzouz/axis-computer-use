// Local perception exercises. These are not an integration with a CAPTCHA provider.
let mountCount = 0;

function randomSource(seed) {
  let state = Number(seed) >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

function cityScene(canvas, random, traffic = false) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  ctx.save();
  ctx.scale(width / 480, height / 260);
  const sky = ctx.createLinearGradient(0, 0, 0, 260);
  sky.addColorStop(0, '#8dcced');
  sky.addColorStop(1, '#e6f3ec');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, 480, 260);
  ctx.fillStyle = '#fff9d0';
  ctx.beginPath(); ctx.arc(50 + random() * 360, 32, 18, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ffffffb8';
  for (let cloud = 0; cloud < 3; cloud++) {
    const x = 20 + random() * 390;
    const y = 22 + random() * 52;
    ctx.beginPath(); ctx.ellipse(x, y, 36, 9, 0, 0, Math.PI * 2); ctx.fill();
  }
  const colors = ['#b87763', '#e7bc8c', '#d6dad5', '#749fac', '#d0a680'];
  for (let x = -10; x < 480; x += 61) {
    const tall = 74 + random() * 78;
    ctx.fillStyle = colors[Math.floor(random() * colors.length)];
    ctx.fillRect(x, 195 - tall, 57, tall);
    ctx.fillStyle = '#324c5f';
    ctx.fillRect(x - 2, 191 - tall, 61, 5);
    for (let y = 205 - tall; y < 185; y += 23) {
      for (let win = x + 8; win < x + 50; win += 19) {
        ctx.fillStyle = random() > .4 ? '#def2ef' : '#466b7d';
        ctx.fillRect(win, y, 10, 13);
      }
    }
  }
  ctx.fillStyle = '#9faa9c'; ctx.fillRect(0, 192, 480, 18);
  ctx.fillStyle = '#52616b'; ctx.fillRect(0, 210, 480, 50);
  ctx.strokeStyle = '#e9d89b'; ctx.lineWidth = 3; ctx.setLineDash([26, 22]);
  ctx.beginPath(); ctx.moveTo(0, 244); ctx.lineTo(480, 244); ctx.stroke(); ctx.setLineDash([]);
  const treeX = 30 + random() * 170;
  ctx.fillStyle = '#76604d'; ctx.fillRect(treeX, 145, 8, 64);
  ctx.fillStyle = '#427957'; ctx.beginPath(); ctx.arc(treeX + 4, 143, 26, 0, Math.PI * 2); ctx.fill();
  const carX = 200 + random() * 170;
  ctx.fillStyle = ['#e6b347', '#4d93b5', '#bd5d54'][Math.floor(random() * 3)];
  ctx.fillRect(carX, 216, 51, 14); ctx.fillRect(carX + 10, 208, 27, 13);
  ctx.fillStyle = '#cde7e9'; ctx.fillRect(carX + 14, 210, 18, 7);
  ctx.fillStyle = '#203747';
  for (const offset of [10, 41]) { ctx.beginPath(); ctx.arc(carX + offset, 230, 5, 0, Math.PI * 2); ctx.fill(); }
  const poleX = 290 + random() * 90;
  ctx.fillStyle = '#3e4d56'; ctx.fillRect(poleX + 14, 94, 7, 113);
  if (traffic) {
    ctx.fillStyle = '#202a31'; ctx.fillRect(poleX, 77, 35, 90);
    for (const [index, color] of ['#f65e56', '#f9c94e', '#48c68a'].entries()) {
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(poleX + 17.5, 94 + index * 27, 10, 0, Math.PI * 2); ctx.fill();
    }
  } else {
    ctx.fillStyle = '#f1f2e4'; ctx.fillRect(poleX - 10, 84, 54, 28);
    ctx.fillStyle = '#4d6b7c'; ctx.font = 'bold 16px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('P', poleX + 17, 104);
  }
  ctx.restore();
}

function jigsawPath(ctx, x, y) {
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 17, y);
  ctx.bezierCurveTo(x + 11, y - 15, x + 39, y - 15, x + 33, y);
  ctx.lineTo(x + 50, y); ctx.lineTo(x + 50, y + 17);
  ctx.bezierCurveTo(x + 65, y + 11, x + 65, y + 39, x + 50, y + 33);
  ctx.lineTo(x + 50, y + 50); ctx.lineTo(x, y + 50); ctx.closePath();
}

export function mountCaptchas(container, { onResult = () => {}, seed } = {}) {
  const random = randomSource(seed ?? globalThis.crypto.getRandomValues(new Uint32Array(1))[0]);
  const prefix = `captcha-${++mountCount}`;
  const definitions = [
    ['jigsaw', 'Fit the puzzle piece', 'Move the cut-out into its matching gap. Drag the piece or use the slider, then verify.'],
    ['tiles', 'Find the traffic lights', 'Select every image containing a traffic light. Select an image again to remove it.'],
    ['text', 'Read the distorted text', 'Read the five characters in the image and enter them below. Letter case does not matter.'],
    ['rotation', 'Turn the image upright', 'Rotate the scene until the sky is above the road and the arrow points straight up.'],
  ];
  container.innerHTML = `<div class="captcha-grid">${definitions.map(([id, title, description], index) => `
    <article class="captcha-card" data-captcha="${id}" aria-labelledby="${prefix}-${id}-title">
      <div class="captcha-card-heading"><span class="captcha-number">0${index + 1}</span><div><p class="captcha-kind">Local training exercise</p><h2 id="${prefix}-${id}-title">${title}</h2></div></div>
      <p class="captcha-instructions">${description}</p>
      <div class="captcha-exercise"></div>
      <div class="captcha-actions"><button class="button" type="button" data-action="verify">Verify</button><button class="button secondary" type="button" data-action="refresh">New challenge</button></div>
      <p class="captcha-feedback" role="status" aria-live="polite">Ready for an attempt.</p>
    </article>`).join('')}</div>`;

  const cards = new Map();
  for (const [id, title] of definitions) {
    const element = container.querySelector(`[data-captcha="${id}"]`);
    cards.set(id, { element, title, exercise: element.querySelector('.captcha-exercise'), feedback: element.querySelector('.captcha-feedback'), passed: false });
  }
  const emit = (id, passed, detail) => {
    const card = cards.get(id);
    card.passed = passed;
    card.feedback.textContent = detail;
    card.feedback.classList.toggle('passed', passed);
    card.feedback.classList.toggle('failed', !passed);
    onResult({ id: `captcha-${id}`, title: card.title, passed, detail });
  };
  const clear = (id, message = 'Ready for an attempt.') => {
    const card = cards.get(id);
    if (card.passed) emit(id, false, 'Challenge changed; verify again.');
    card.feedback.textContent = message;
    card.feedback.classList.remove('passed', 'failed');
  };
  const setup = (id, regenerate, verify) => {
    const card = cards.get(id);
    card.reset = () => { clear(id); regenerate(); };
    card.element.querySelector('[data-action="refresh"]').addEventListener('click', card.reset);
    card.element.querySelector('[data-action="verify"]').addEventListener('click', verify);
  };

  const jigsaw = cards.get('jigsaw');
  jigsaw.exercise.innerHTML = `<canvas class="captcha-wide-canvas" width="480" height="260" role="img" aria-label="City scene with a movable puzzle piece and a matching gap"></canvas><label for="${prefix}-piece">Puzzle position<input id="${prefix}-piece" type="range" min="0" max="100" step="0.1" value="0"></label>`;
  const puzzleCanvas = jigsaw.exercise.querySelector('canvas');
  const puzzleRange = jigsaw.exercise.querySelector('input');
  const background = document.createElement('canvas'); background.width = 480; background.height = 260;
  const puzzle = { x: 260, y: 125, grabbed: false, offset: 0 };
  const pieceX = () => 14 + Number(puzzleRange.value) / 100 * 390;
  const drawPuzzle = () => {
    const ctx = puzzleCanvas.getContext('2d');
    ctx.clearRect(0, 0, 480, 260); ctx.drawImage(background, 0, 0);
    jigsawPath(ctx, puzzle.x, puzzle.y);
    ctx.fillStyle = '#12212cc9'; ctx.fill(); ctx.strokeStyle = '#ffffffcc'; ctx.lineWidth = 2; ctx.stroke();
    ctx.save(); jigsawPath(ctx, pieceX(), puzzle.y); ctx.clip();
    ctx.drawImage(background, pieceX() - puzzle.x, 0); ctx.restore();
    jigsawPath(ctx, pieceX(), puzzle.y); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
  };
  const movePiece = () => { clear('jigsaw', 'Press Verify when the piece fits.'); drawPuzzle(); };
  puzzleRange.addEventListener('input', movePiece);
  const logicalPoint = event => {
    const rect = puzzleCanvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width * 480, y: (event.clientY - rect.top) / rect.height * 260 };
  };
  puzzleCanvas.addEventListener('pointerdown', event => {
    const point = logicalPoint(event);
    if (point.x < pieceX() - 5 || point.x > pieceX() + 65 || point.y < puzzle.y - 16 || point.y > puzzle.y + 55) return;
    puzzle.grabbed = true; puzzle.offset = point.x - pieceX();
    puzzleCanvas.setPointerCapture(event.pointerId); event.preventDefault();
  });
  puzzleCanvas.addEventListener('pointermove', event => {
    if (!puzzle.grabbed) return;
    puzzleRange.value = String(Math.max(0, Math.min(100, (logicalPoint(event).x - puzzle.offset - 14) / 390 * 100)));
    movePiece();
  });
  const releasePiece = () => { puzzle.grabbed = false; };
  puzzleCanvas.addEventListener('pointerup', releasePiece);
  puzzleCanvas.addEventListener('pointercancel', releasePiece);
  puzzleCanvas.addEventListener('lostpointercapture', releasePiece);
  setup('jigsaw', () => {
    puzzle.grabbed = false; puzzle.x = 225 + Math.floor(random() * 135); puzzle.y = 102 + Math.floor(random() * 56);
    puzzleRange.value = '0'; cityScene(background, random, true); drawPuzzle();
  }, () => {
    const passed = Math.abs(pieceX() - puzzle.x) <= 5;
    emit('jigsaw', passed, passed ? 'Passed — the piece fits the gap.' : 'The edges do not line up yet. Adjust the piece and try again.');
  });

  const tiles = cards.get('tiles');
  tiles.exercise.innerHTML = '<div class="captcha-tiles" role="group" aria-label="Traffic light image grid"></div>';
  const tileGrid = tiles.exercise.firstElementChild;
  let targets = new Set();
  const selected = new Set();
  setup('tiles', () => {
    selected.clear();
    const indices = Array.from({ length: 9 }, (_, i) => i);
    for (let i = 8; i > 0; i--) { const next = Math.floor(random() * (i + 1)); [indices[i], indices[next]] = [indices[next], indices[i]]; }
    targets = new Set(indices.slice(0, 3 + Math.floor(random() * 3)));
    tileGrid.replaceChildren();
    for (let i = 0; i < 9; i++) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'captcha-tile'; button.setAttribute('aria-label', `Tile ${i + 1}`); button.setAttribute('aria-pressed', 'false');
      const canvas = document.createElement('canvas'); canvas.width = 240; canvas.height = 180; canvas.setAttribute('aria-hidden', 'true');
      const number = document.createElement('span'); number.className = 'captcha-tile-number'; number.textContent = String(i + 1); number.setAttribute('aria-hidden', 'true');
      cityScene(canvas, random, targets.has(i)); button.append(canvas, number);
      button.addEventListener('click', () => {
        clear('tiles', 'Press Verify when every traffic light image is selected.');
        selected.has(i) ? selected.delete(i) : selected.add(i);
        button.setAttribute('aria-pressed', String(selected.has(i)));
      });
      tileGrid.append(button);
    }
  }, () => {
    const passed = selected.size === targets.size && [...targets].every(index => selected.has(index));
    emit('tiles', passed, passed ? 'Passed — you selected all the traffic lights.' : 'That selection is not complete or contains another scene. Change your selection and retry.');
  });

  const textCard = cards.get('text');
  textCard.exercise.innerHTML = `<canvas class="captcha-text-canvas" width="480" height="170" role="img" aria-label="Five distorted letters and numbers to transcribe"></canvas><label for="${prefix}-answer">Characters in the image<input id="${prefix}-answer" type="text" maxlength="12" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="Enter the five characters"></label>`;
  const textCanvas = textCard.exercise.querySelector('canvas');
  const textInput = textCard.exercise.querySelector('input');
  let answer = '';
  textInput.addEventListener('input', () => clear('text', 'Press Verify to check your transcription.'));
  const verifyText = () => {
    const passed = textInput.value.trim().toUpperCase() === answer;
    emit('text', passed, passed ? 'Passed — the characters match.' : 'Those characters do not match. Try again or request a new image.');
  };
  textInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); verifyText(); } });
  setup('text', () => {
    const alphabet = '234679ACDEFGHJKMNPQRTUVWXYZ';
    answer = Array.from({ length: 5 }, () => alphabet[Math.floor(random() * alphabet.length)]).join('');
    textInput.value = '';
    const ctx = textCanvas.getContext('2d'); ctx.fillStyle = '#eaf2ec'; ctx.fillRect(0, 0, 480, 170);
    for (let i = 0; i < 65; i++) { ctx.fillStyle = '#4d8f8560'; ctx.beginPath(); ctx.arc(random() * 480, random() * 170, 1 + random() * 2, 0, Math.PI * 2); ctx.fill(); }
    ctx.font = 'bold 69px Georgia, serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    [...answer].forEach((char, index) => {
      ctx.save(); ctx.translate(67 + index * 86, 82 + (random() - .5) * 22); ctx.rotate((random() - .5) * .42);
      ctx.transform(1, (random() - .5) * .15, (random() - .5) * .18, 1, 0, 0);
      ctx.fillStyle = ['#203e57', '#305650', '#574459'][index % 3]; ctx.fillText(char, 0, 0); ctx.restore();
    });
    ctx.strokeStyle = '#668e7c9c'; ctx.lineWidth = 1.6;
    for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.moveTo(0, random() * 170); ctx.bezierCurveTo(150, random() * 170, 320, random() * 170, 480, random() * 170); ctx.stroke(); }
  }, verifyText);

  const rotation = cards.get('rotation');
  rotation.exercise.innerHTML = `<canvas class="captcha-rotation-canvas" width="320" height="320" role="img" aria-label="Rotating city scene with an orientation arrow"></canvas><label for="${prefix}-rotation">Image rotation<input id="${prefix}-rotation" type="range" min="0" max="359" step="1" value="0"></label>`;
  const rotationCanvas = rotation.exercise.querySelector('canvas');
  const rotationRange = rotation.exercise.querySelector('input');
  const rotationBackground = document.createElement('canvas'); rotationBackground.width = 480; rotationBackground.height = 260;
  let startingAngle = 0;
  const drawRotation = () => {
    const ctx = rotationCanvas.getContext('2d');
    ctx.fillStyle = '#e9f0ef'; ctx.fillRect(0, 0, 320, 320);
    ctx.save(); ctx.beginPath(); ctx.arc(160, 160, 148, 0, Math.PI * 2); ctx.clip();
    ctx.translate(160, 160); ctx.rotate((startingAngle + Number(rotationRange.value)) * Math.PI / 180);
    ctx.drawImage(rotationBackground, -240, -160, 480, 320);
    ctx.fillStyle = '#ffffffeb'; ctx.beginPath(); ctx.arc(0, -107, 24, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = '#234f49'; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(0, -91); ctx.lineTo(0, -121); ctx.moveTo(-9, -110); ctx.lineTo(0, -121); ctx.lineTo(9, -110); ctx.stroke(); ctx.restore();
    ctx.strokeStyle = '#a7c2ba'; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(160, 160, 149, 0, Math.PI * 2); ctx.stroke();
  };
  rotationRange.addEventListener('input', () => { clear('rotation', 'Press Verify when the image is upright.'); drawRotation(); });
  setup('rotation', () => {
    startingAngle = 40 + Math.floor(random() * 280); rotationRange.value = '0';
    cityScene(rotationBackground, random, true); drawRotation();
  }, () => {
    const angle = (startingAngle + Number(rotationRange.value)) % 360;
    const passed = Math.min(angle, 360 - angle) <= 5;
    emit('rotation', passed, passed ? 'Passed — the scene is upright.' : 'The scene is still tilted. Adjust the rotation and retry.');
  });

  const reset = () => { for (const card of cards.values()) card.reset(); };
  reset();
  return { reset };
}

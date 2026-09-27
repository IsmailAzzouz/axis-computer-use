let scriptPromise;
function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    const timer = setTimeout(fail, 12000);
    function fail() {
      clearTimeout(timer); script.remove(); scriptPromise = null;
      reject(new Error('Cloudflare could not load. Check your connection or content blocker, then retry. Local challenges still work.'));
    }
    script.onerror = fail;
    script.onload = () => {
      clearTimeout(timer);
      if (window.turnstile) window.turnstile.ready(() => resolve(window.turnstile));
      else fail();
    };
    document.head.append(script);
  });
  return scriptPromise;
}

export function mountTurnstile(container, {api, onResult}) {
  container.innerHTML = `<article class="panel provider-card">
    <div><p class="eyebrow">ACTUAL PROVIDER WIDGET · OPTIONAL ONLINE EXERCISE</p><h2>Cloudflare Turnstile</h2>
    <p id="provider-mode" class="muted">Official interactive test mode. This exercises the provider widget and its server validation, not production bot resistance.</p></div>
    <div class="provider-actions"><button id="load-turnstile" class="button secondary">Load Cloudflare widget</button><button id="verify-turnstile" class="button" disabled>Validate token</button></div>
    <div id="turnstile-widget"></div><p id="turnstile-status" role="status">Requires an internet connection. No account is needed for the official test mode.</p>
    <a class="text-link" href="https://developers.cloudflare.com/turnstile/troubleshooting/testing/" target="_blank" rel="noopener">About Cloudflare test mode</a>
  </article>`;
  const load = container.querySelector('#load-turnstile');
  const verify = container.querySelector('#verify-turnstile');
  const status = container.querySelector('#turnstile-status');
  let generation = 0, widget, token = null, mode = 'test';
  const report = (passed, detail) => onResult({id:'provider-turnstile',title:'Cloudflare Turnstile',passed,detail,optional:true,mode});
  function reset() {
    generation++;
    if (widget !== undefined && window.turnstile) window.turnstile.remove(widget);
    widget = undefined; token = null; verify.disabled = true; load.disabled = false;
    load.textContent = 'Load Cloudflare widget';
    status.textContent = 'Requires an internet connection. No account is needed for the official test mode.';
    report(false, 'Not attempted. Optional online provider exercise.');
  }
  load.addEventListener('click', async () => {
    reset();
    const current = generation;
    load.disabled = true; status.textContent = 'Connecting to Cloudflare…';
    try {
      const config = await api('/api/turnstile/config');
      if (current !== generation) return;
      mode = config.mode;
      if (mode === 'unconfigured') throw new Error('Both Turnstile environment keys must be configured, or neither for official test mode.');
      container.querySelector('#provider-mode').textContent = config.description;
      const provider = await loadTurnstile();
      if (current !== generation) return;
      const fail = message => {
        if (current !== generation) return;
        token = null; verify.disabled = true; status.textContent = message; report(false,message);
      };
      widget = provider.render(container.querySelector('#turnstile-widget'), {
        sitekey:config.sitekey, action:config.action, theme:'light', size:'flexible',
        callback: value => {
          if (current !== generation) return;
          token = value; verify.disabled = false;
          status.textContent = 'Widget completed. Validate the token with Cloudflare to finish.';
        },
        'error-callback': () => {fail('Cloudflare could not complete this challenge. Reload the widget to retry.');return true;},
        'expired-callback': () => fail('The token expired. Reload the widget to retry.'),
        'timeout-callback': () => fail('The challenge timed out. Reload the widget to retry.'),
      });
      status.textContent = 'Complete the Cloudflare widget, then validate the token.';
      load.textContent = 'Reload Cloudflare widget';
    } catch (error) {
      if (current === generation) {status.textContent = error.message; report(false,error.message);}
    } finally {if (current === generation) load.disabled = false;}
  });
  verify.addEventListener('click', async () => {
    if (!token) return;
    const current = generation;
    const submitted = token;
    token = null; verify.disabled = true; status.textContent = 'Validating with Cloudflare…';
    try {
      const result = await api('/api/turnstile/verify',{method:'POST',body:JSON.stringify({token:submitted})});
      if (current !== generation) return;
      status.textContent = result.message; report(result.success === true,result.message);
    } catch(error) {
      if (current === generation) {status.textContent = error.message;report(false,error.message);}
    }
  });
  return {reset};
}

// Сканер штрихкодов прямо на странице (для телефона и планшета с камерой).
// Камера открывается поверх кассы или прайса; «Готово» закрывает её — и вы на том же месте, заказ сохранён.
//   openScanner({ mode: 'cart',  onProduct: p => …, onUnknown: code => … })   — касса: каждый скан → в заказ
//   openScanner({ mode: 'price', onProduct: p => …, onUnknown: code => … })   — товары: проверка прайса

// Касание + небольшой экран = телефон: сканер и Telegram открываем прямо здесь, а не через QR для второго устройства
const isTouch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window;

function loadQrLib() {
  if (window.Html5Qrcode) return Promise.resolve();
  return new Promise((ok, fail) => {
    const s = Object.assign(document.createElement('script'), { src: 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js' });
    s.onload = ok; s.onerror = () => fail(new Error('Не загрузилась библиотека сканера. Проверьте интернет.'));
    document.head.append(s);
  });
}

async function openScanner({ mode = 'cart', onProduct, onUnknown } = {}) {
  const box = document.createElement('div');
  box.className = 'scan-overlay';
  box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-label', 'Сканер штрихкодов');
  box.innerHTML = `
    <div class="so-top">
      <b>${mode === 'cart' ? 'Сканер → в заказ' : 'Сканер → прайс'}</b>
      <button type="button" class="so-done" id="soDone">Готово</button>
    </div>
    <div id="soReader" class="so-reader"></div>
    <div class="so-panel">
      <p class="so-msg" id="soMsg">Наведите камеру на штрихкод товара.</p>
      <ul class="so-list" id="soList"></ul>
      <form class="so-manual" id="soManual"><input inputmode="numeric" placeholder="Или введите штрихкод…" aria-label="Штрихкод вручную"><button type="submit" class="ghost">OK</button></form>
    </div>`;
  document.body.append(box);
  document.body.classList.add('no-scroll');
  const $s = id => box.querySelector('#' + id);
  const FRAME = { idle: '#ffffff', busy: '#f2b705', ok: '#1e8e4e', bad: '#e0574f' };
  const frame = c => box.querySelectorAll('#qr-shaded-region > div').forEach(d => { d.style.backgroundColor = c; });
  const say = (t, cls = '') => { $s('soMsg').textContent = t; $s('soMsg').className = 'so-msg ' + cls; };
  let scanner = null, paused = false, last = { code: '', seen: 0 }, count = 0;

  const close = async () => {
    try { if (scanner) { await scanner.stop(); scanner.clear(); } } catch {}
    box.remove(); document.body.classList.remove('no-scroll');
    document.removeEventListener('keydown', onKey);
  };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  $s('soDone').onclick = close;

  async function handle(code) {
    code = String(code).trim();
    if (!code) return;
    const now = Date.now();
    // Тот же товар считаем снова, только если его убрали из кадра хотя бы на 0,7 с
    if (code === last.code) { const gap = now - last.seen; last.seen = now; if (paused || gap < 700) return; }
    else if (paused) return;
    last = { code, seen: now }; paused = true; frame(FRAME.busy);
    if (navigator.vibrate) navigator.vibrate(60);
    const p = await api('/api/products/barcode/' + encodeURIComponent(code)).catch(() => null);
    if (p) {
      frame(FRAME.ok);
      onProduct && onProduct(p);
      count++;
      say(mode === 'cart' ? `✓ ${p.name} — ${money(p.price)} → в заказе` : `Уже в прайсе: ${p.name} — ${money(p.price)}`, 'ok');
      const li = document.createElement('li'); li.textContent = `${p.name} · ${money(p.price)}`; $s('soList').prepend(li);
      while ($s('soList').children.length > 4) $s('soList').lastChild.remove();
      setTimeout(() => { frame(FRAME.idle); paused = false; }, 900);
    } else {
      frame(FRAME.bad);
      if (onUnknown) { await close(); onUnknown(code); return; }
      say(`Штрихкод ${code} не найден в прайсе`, 'bad');
      setTimeout(() => { frame(FRAME.idle); paused = false; }, 1500);
    }
  }
  $s('soManual').onsubmit = e => { e.preventDefault(); const inp = e.target.elements[0]; last.code = ''; paused = false; handle(inp.value); inp.value = ''; };

  if (!window.isSecureContext) { say('Камера работает только по защищённому адресу (https).', 'bad'); return; }
  try {
    await loadQrLib();
    const F = Html5QrcodeSupportedFormats;
    scanner = new Html5Qrcode('soReader', { formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39], verbose: false });
    await scanner.start({ facingMode: 'environment' },
      { fps: 12, qrbox: (w, h) => ({ width: Math.min(w * 0.85, 360), height: Math.min(h * 0.4, 170) }) },
      text => handle(text), () => {});
  } catch (err) {
    say('Нет доступа к камере. Разрешите камеру в настройках браузера или введите штрихкод вручную.', 'bad');
  }
}

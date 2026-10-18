// Дәптер AI — веб-приложение магазина (без фреймворков)

const view = document.getElementById('view');
const money = n => new Intl.NumberFormat('ru-RU').format(n) + ' ₸';
const fmtDate = (v, opt = { day: 'numeric', month: 'short' }) => {
  const d = new Date(String(v).length === 10 ? v + 'T00:00' : String(v).replace(' ', 'T'));
  if (isNaN(d)) return String(v ?? '');
  if (uiLang !== 'kk') return new Intl.DateTimeFormat('ru-RU', opt).format(d);
  // Браузеры пишут казахские месяцы как «M10», поэтому названия — свои
  const full = ['қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан'];
  const short = ['қаң.', 'ақп.', 'нау.', 'сәу.', 'мам.', 'мау.', 'шіл.', 'там.', 'қыр.', 'қаз.', 'қар.', 'жел.'];
  const month = (opt.month === 'long' ? full : short)[d.getMonth()];
  const parts = [opt.day ? `${d.getDate()} ${month}` : month];
  if (opt.year) parts.push(String(d.getFullYear()));
  if (opt.hour) parts.push(d.toTimeString().slice(0, 5));
  return parts.join(opt.hour ? ', ' : ' ');
};
const esc = s => String(s ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// ---------- API ----------
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) { location.href = '/login'; throw new Error('Нужно войти'); }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === 'string' ? data.detail : 'Проверьте поля формы') : 'Ошибка сервера');
  return data;
}

// ---------- QR, который открывает сканер на телефоне ----------
async function showScannerQr(card, mode) {
  const s = await api('/api/scanner');
  const what = mode === 'price'
    ? 'Наводите на штрихкод: сканер проверит, есть ли товар в прайсе, и предложит добавить новый.'
    : 'Наводите на штрихкод: товар сразу добавится в заказ на кассе. Второй скан того же товара — ещё +1 шт.';
  card.innerHTML = s.available ? `
    <div class="consent">
      <div class="qr-box"><img src="/api/scanner/qr.svg?mode=${mode}&t=${Date.now()}" alt="QR для открытия сканера" width="170" height="170"></div>
      <div>
        <h2>Сканер на телефоне</h2>
        <p>Отсканируйте QR камерой телефона — откроется сканер. ${what}</p>
        <p class="sub">QR действует 15 минут, пароль на телефоне вводить не нужно. Если касса открыта на телефоне —
          <a href="/scan?mode=${mode}">откройте сканер прямо здесь</a>.</p>
      </div>
    </div>` : `<p class="notice-line">Ссылка для телефона не найдена. Запустите сайт файлом «Запустить Дәптер.bat» и откройте его по ссылке из окна.</p>`;
  card.hidden = false;
}

// ---------- WhatsApp: бесплатно, через ссылку wa.me — отправляет сам продавец одним касанием ----------
let shopInfo = null;
function waLink(phone, text) {
  let d = String(phone || '').replace(/\D/g, '');
  if (d.length === 11 && d[0] === '8') d = '7' + d.slice(1);
  if (d.length === 10 && d[0] === '7') d = '7' + d;
  return 'https://wa.me/' + (d.length === 11 ? d : '') + '?text=' + encodeURIComponent(text);
}
function openWhatsApp(phone, text) { window.open(waLink(phone, text), '_blank', 'noopener'); }
// Тексты на языке покупателя
const WA = {
  consent: (lang, name, sum, link) => lang === 'kk'
    ? `Сәлеметсіз бе, ${name}! «${shopInfo?.name || 'Дүкен'}» дүкеніндегі қарызыңыз: ${sum}. Растау үшін сілтемені ашып, «Растаймын» басыңыз: ${link}`
    : `Здравствуйте, ${name}! Ваш долг в магазине «${shopInfo?.name || 'Магазин'}»: ${sum}. Чтобы подтвердить, откройте ссылку и нажмите «Растаймын»: ${link}`,
  receipt: (lang, name, paid, left) => lang === 'kk'
    ? `Рахмет, ${name}! «${shopInfo?.name || 'Дүкен'}» дүкені ${paid} төлемді қабылдады. ${left > 0 ? 'Қалған қарыз: ' + money(left) + '.' : 'Қарыз толық жабылды ✅'}`
    : `Спасибо, ${name}! Магазин «${shopInfo?.name || 'Магазин'}» принял оплату ${paid}. ${left > 0 ? 'Остаток долга: ' + money(left) + '.' : 'Долг полностью закрыт ✅'}`,
};

// ---------- фото: камера телефона или файл → уменьшенный JPEG (data URL) ----------
function pickPhoto() {
  return new Promise(resolve => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept: 'image/*' });
    input.setAttribute('capture', 'environment'); // на телефоне сразу открывается камера
    input.onchange = () => input.files[0] ? shrinkImage(input.files[0]).then(resolve) : resolve(null);
    input.click();
  });
}

function shrinkImage(file, max = 1024) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const cv = Object.assign(document.createElement('canvas'), { width: Math.round(img.width * k), height: Math.round(img.height * k) });
      cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(img.src);
      resolve(cv.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

// ---------- уведомления ----------
let toastTimer;
function toast(text, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2600);
}

// ---------- живая синхронизация ----------
const listeners = new Set();
function connectLive() {
  const live = document.getElementById('live');
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  ws.onopen = () => { live.textContent = '● онлайн'; live.classList.add('on'); };
  ws.onclose = e => {
    live.textContent = '● офлайн'; live.classList.remove('on');
    if (e.code === 4401) { location.href = '/login'; return; }
    setTimeout(connectLive, 2000);
  };
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    globalEvents(msg);
    listeners.forEach(fn => fn(msg));
  };
  window.liveSocket = ws;
}

let hiddenAt = 0;
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { hiddenAt = Date.now(); return; }
  if (Date.now() - hiddenAt < 1500) return;
  if (!window.liveSocket || window.liveSocket.readyState > 1) connectLive();
  listeners.forEach(fn => fn({ type: 'refresh' }));
});

// ---------- страницы ----------
const pages = {
  kassa: renderKassa,          // web/kassa.js
  products: renderProducts,
  customers: renderCustomers,  // web/customers.js
  debts: renderDebts,          // web/debts.js
  cabinet: renderCabinet,      // web/cabinet.js
  settings: renderSettings,    // web/settings.js
};

// События бота показываем на любом экране
function globalEvents(msg) {
  if (msg.type === 'consent_changed') toast(msg.status === 'confirmed' ? `✅ ${msg.customer} подтвердил(а) долг` : `❌ ${msg.customer} отклонил(а) долг`, msg.status !== 'confirmed');
  if (msg.type === 'customer_says_paid') toast(`💳 ${msg.customer} говорит, что оплатил(а). Проверьте Kaspi`);
  if (msg.type === 'owner_linked') toast('Владелец подключён к боту');
}

function soon(title, text) {
  view.innerHTML = `<div class="page-head"><h1>${title}</h1></div><div class="soon">${text}</div>`;
}

function route() {
  const page = pages[location.hash.slice(1)] ? location.hash.slice(1) : 'kassa';
  document.querySelectorAll('.tabs a').forEach(a => {
    const on = a.dataset.page === page;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  listeners.clear();
  if (window.stopVoice) window.stopVoice();
  pages[page]();
}

// ---------- Товары ----------
async function renderProducts() {
  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>Товары</h1>
        <p class="hint">Прайс магазина. По нему касса сама считает сумму: продавец говорит «нан», система знает цену. Синонимы помогают понять разные слова для одного товара.</p>
      </div>
      <input class="search" id="q" type="search" placeholder="Поиск: название, синоним, штрихкод…" aria-label="Поиск товара">
    </div>

    <form class="card form-grid" id="addForm">
      <label class="wide">Название<input name="name" id="f-name" required maxlength="120" placeholder="Нан"></label>
      <label class="wide">Синонимы (через запятую)<input name="synonyms" id="f-syn" placeholder="хлеб, батон"></label>
      <label>Цена, ₸<input name="price" id="f-price" type="number" min="0" step="1" required placeholder="200"></label>
      <label>Ед.<input name="unit" id="f-unit" value="шт" maxlength="10"></label>
      <label>Штрихкод<input name="barcode" id="f-barcode" inputmode="numeric" placeholder="необязательно…"></label>
      <button type="submit">Добавить</button>
      <div class="ai-row wide-all">
        <button type="button" class="ghost" id="aiPhoto">📷 Заполнить по фото ценника (ИИ)</button>
        <button type="button" class="ghost" id="phoneScanP">📱 Сканер на телефоне</button>
        <img id="pendingPhoto" class="thumb" alt="Фото нового товара" width="40" height="40" hidden>
        <span class="sub" id="aiPhotoStatus"></span>
      </div>
    </form>
    <div class="card scanner-card" id="scannerCardP" hidden></div>

    <div class="table-wrap">
      <table>
        <thead><tr><th class="num-col">№</th><th></th><th>Название</th><th>Синонимы</th><th style="text-align:right">Цена</th><th>Ед.</th><th>Штрихкод</th><th></th></tr></thead>
        <tbody id="rows"><tr><td colspan="8" class="empty">Загрузка…</td></tr></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('rows');
  const q = document.getElementById('q');
  let editingId = null;
  let pendingPhoto = null;   // фото для нового товара, прикрепляется после «Добавить»
  let photoVer = Date.now();

  async function load() {
    const items = await api('/api/products?q=' + encodeURIComponent(q.value));
    if (!items.length) {
      rows.innerHTML = `<tr><td colspan="8" class="empty">${q.value ? 'Ничего не найдено' : 'Прайс пуст. Добавьте первый товар выше.'}</td></tr>`;
      return;
    }
    rows.innerHTML = items.map((p, i) => p.id === editingId ? editRow(p, i) : viewRow(p, i)).join('');
  }

  const viewRow = (p, i) => `
    <tr data-id="${p.id}">
      <td class="num-col">${i + 1}</td>
      <td class="ph">${p.photo ? `<img class="thumb" src="/api/products/${p.id}/photo?${photoVer}" alt="" width="40" height="40">` : ''}<button class="ghost small" data-act="photo" title="Сфотографировать товар" aria-label="Фото товара">📷</button></td>
      <td><b>${esc(p.name)}</b></td>
      <td class="syn">${esc(p.synonyms)}</td>
      <td class="num">${money(p.price)}</td>
      <td>${esc(p.unit)}</td>
      <td class="code">${esc(p.barcode || '—')}</td>
      <td class="actions">
        <button class="ghost small" data-act="edit">Изменить</button>
        <button class="danger small" data-act="del">Удалить</button>
      </td>
    </tr>`;

  const editRow = (p, i) => `
    <tr data-id="${p.id}" class="editing">
      <td class="num-col">${i + 1}</td>
      <td></td>
      <td><input data-f="name" value="${esc(p.name)}" aria-label="Название"></td>
      <td><input data-f="synonyms" value="${esc(p.synonyms)}" aria-label="Синонимы"></td>
      <td><input data-f="price" type="number" min="0" value="${p.price}" aria-label="Цена" style="width:110px"></td>
      <td><input data-f="unit" value="${esc(p.unit)}" aria-label="Единица" style="width:70px"></td>
      <td><input data-f="barcode" value="${esc(p.barcode || '')}" aria-label="Штрихкод"></td>
      <td class="actions">
        <button class="small" data-act="save">Сохранить</button>
        <button class="ghost small" data-act="cancel">Отмена</button>
      </td>
    </tr>`;

  rows.addEventListener('click', async e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const tr = btn.closest('tr');
    const id = Number(tr.dataset.id);
    const act = btn.dataset.act;
    try {
      if (act === 'photo') {
        const img = await pickPhoto();
        if (!img) return;
        await api(`/api/products/${id}/photo`, { method: 'POST', body: { image: img } });
        photoVer = Date.now(); toast('Фото сохранено'); await load();
      }
      if (act === 'edit') { editingId = id; await load(); }
      if (act === 'cancel') { editingId = null; await load(); }
      if (act === 'save') {
        const val = f => tr.querySelector(`[data-f="${f}"]`).value;
        await api('/api/products/' + id, { method: 'PUT', body: {
          name: val('name'), synonyms: val('synonyms'), price: Number(val('price')), unit: val('unit'), barcode: val('barcode') || null,
        }});
        editingId = null; toast('Сохранено'); await load();
      }
      if (act === 'del') {
        if (btn.dataset.confirm !== '1') {
          btn.dataset.confirm = '1'; btn.textContent = 'Точно удалить?';
          setTimeout(() => { btn.dataset.confirm = ''; btn.textContent = 'Удалить'; }, 3000);
          return;
        }
        await api('/api/products/' + id, { method: 'DELETE' });
        toast('Товар удалён'); await load();
      }
    } catch (err) { toast(err.message, true); }
  });

  document.getElementById('addForm').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target.elements; // form.name — это имя самой формы, поэтому берём поля через elements
    try {
      const created = await api('/api/products', { method: 'POST', body: {
        name: f.name.value, synonyms: f.synonyms.value, price: Number(f.price.value), unit: f.unit.value, barcode: f.barcode.value || null,
      }});
      if (pendingPhoto) await api(`/api/products/${created.id}/photo`, { method: 'POST', body: { image: pendingPhoto } });
      toast('Товар добавлен');
      pendingPhoto = null; document.getElementById('pendingPhoto').hidden = true; document.getElementById('aiPhotoStatus').textContent = '';
      e.target.reset(); f.unit.value = 'шт'; f.name.focus();
      await load();
    } catch (err) { toast(err.message, true); }
  });

  // Фото ценника → ИИ заполняет название, цену и синонимы
  if (isTouch) document.getElementById('phoneScanP').textContent = '📷 Сканер штрихкодов';
  document.getElementById('phoneScanP').onclick = () => {
    if (isTouch) {
      // Телефон: камера прямо здесь; незнакомый штрихкод сразу попадает в форму нового товара
      openScanner({ mode: 'price', onUnknown: code => {
        document.getElementById('f-barcode').value = code;
        document.getElementById('f-name').focus();
        toast('Новый штрихкод ' + code + ': впишите название и цену');
      } });
      return;
    }
    const card = document.getElementById('scannerCardP');
    if (!card.hidden) { card.hidden = true; return; }
    showScannerQr(card, 'price');
  };
  document.getElementById('aiPhoto').onclick = async () => {
    const st = document.getElementById('aiPhotoStatus');
    const img = await pickPhoto();
    if (!img) return;
    pendingPhoto = img;
    const prev = document.getElementById('pendingPhoto'); prev.src = img; prev.hidden = false;
    st.textContent = '🤖 ИИ читает ценник…';
    try {
      const r = await api('/api/ai/photo', { method: 'POST', body: { image: img } });
      const f = document.getElementById('addForm').elements;
      f.name.value = r.name; f.synonyms.value = r.synonyms; f.unit.value = r.unit || 'шт';
      if (r.price) f.price.value = r.price;
      st.textContent = `🤖 Готово (уверенность: ${{ high: 'высокая', medium: 'средняя', low: 'низкая' }[r.confidence] || r.confidence}). ${r.price ? '' : 'Цену не видно — впишите. '}Проверьте и нажмите «Добавить».`;
      f.price.focus();
    } catch (err) { st.textContent = err.message; }
  };

  let timer;
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 200); });

  // Другой экран изменил прайс — обновляемся сами
  listeners.add(msg => { if (msg.type === 'products_changed' && editingId === null) load(); });

  await load();
}

// ---------- старт ----------
api('/api/shop').then(s => { shopInfo = s; document.getElementById('shopName').textContent = '«' + s.name + '», ' + s.district; }).catch(() => {});
window.addEventListener('shop-changed', () => api('/api/shop').then(s => (document.getElementById('shopName').textContent = '«' + s.name + '», ' + s.district)));

// Пользователь и выход
api('/api/auth/me').then(u => {
  window.me = u;
  document.getElementById('userName').textContent = u.full_name + (u.is_demo ? ' · демо' : '');
}).catch(() => {});
document.getElementById('logout').onclick = async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  location.href = '/';
};

// Новый аккаунт — подсказка, с чего начать
if (new URLSearchParams(location.search).get('welcome')) {
  history.replaceState(null, '', '/app#products');
  setTimeout(() => toast('Добро пожаловать! Начните с прайса: добавьте товары вручную, сканом или фото ценника.'), 400);
}
window.addEventListener('hashchange', route);
connectLive();
route();

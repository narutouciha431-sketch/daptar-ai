// Касса: фраза (текстом или голосом) → покупатель и корзина → «Оплачено» или «В долг»

const EXAMPLES = [
  'Айгүл апай, екі нан, бір сүт, қарызға',
  'Ерлан, сигареты и вода, в долг',
  'Мадина, два хлеба и сосиски',
  'Сәуле, үш кило картоп, жартысын төледі',
  'Ерлан қарызын төледі екі мың',
  'Кім қарыз?',
];

const fmtQty = q => (Number.isInteger(q) ? q : Number(q).toFixed(2).replace(/\.?0+$/, '')).toString();

async function renderKassa() {
  const state = {
    items: [],             // {product_id, name, qty, price}
    customerId: null,
    newName: '',
    source: 'text',
    rawText: '',
    paidNow: 0,
  };
  let products = [], customers = [];

  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>Касса</h1>
        <p class="hint">Скажите или напишите, кто и что взял — Дәптер сам найдёт покупателя, товары и цены.</p>
      </div>
    </div>

    <div class="kassa">
      <div class="kassa-main">
        <form class="card say" id="sayForm">
          <label class="say-label" for="say">Что взяли?</label>
          <div class="say-input">
            <input id="say" autocomplete="off" spellcheck="false" placeholder="Айгүл апай, екі нан, бір сүт, қарызға…">
          </div>
          <div class="say-actions">
            <button type="button" class="mic" id="mic" aria-label="Голосовой ввод"><span class="dot" aria-hidden="true"></span>Голос</button>
            <span class="lang-seg"><select id="lang" aria-label="Язык голоса">
              <option value="kk-KZ">Қазақша</option>
              <option value="ru-RU">Русский</option>
            </select></span>
            <button type="button" class="scan-btn" id="scanBtn" aria-expanded="false"><span aria-hidden="true">📷</span> Сканер</button>
            <button type="submit" class="go">Разобрать</button>
          </div>
          <div class="voice-status" id="voiceStatus" role="status" aria-live="polite" hidden></div>
          <details class="examples">
            <summary>Примеры фраз</summary>
            <div class="chips">${EXAMPLES.map(e => `<button type="button" class="chip">${esc(e)}</button>`).join('')}</div>
          </details>
        </form>
        <div class="card scan-panel" id="scanPanel" hidden>
          <div class="scan-modes" role="tablist" aria-label="Способ сканирования">
            <button type="button" role="tab" data-scan="barcode">▦ По штрихкоду</button>
            <button type="button" role="tab" data-scan="ai">🤖 По фото (ИИ)</button>
          </div>
          <div id="scanBody"></div>
        </div>

        <div class="card notice" id="notice" role="status" aria-live="polite" hidden></div>

        <section class="card order" aria-labelledby="orderTitle">
          <div class="order-head">
            <h2 id="orderTitle">Заказ</h2>
            <div class="add-row">
              <input id="addProduct" list="productList" autocomplete="off" placeholder="Добавить товар или штрихкод…" aria-label="Добавить товар">
              <datalist id="productList"></datalist>
              <button type="button" class="ghost small" id="clear">Очистить</button>
            </div>
          </div>
          <div class="cust-row">
            <span class="cust-label">Покупатель</span>
            <div class="cust-fields">
              <select id="cust" aria-label="Покупатель"></select>
              <input id="newName" autocomplete="off" placeholder="Имя нового покупателя…" aria-label="Имя нового покупателя" hidden>
            </div>
            <span class="badge" id="custBadge"></span>
          </div>
          <div class="table-wrap flat">
            <table id="cartTable">
              <thead><tr><th>Товар</th><th>Кол-во</th><th style="text-align:right">Цена</th><th style="text-align:right">Сумма</th><th><span class="skip">Убрать</span></th></tr></thead>
              <tbody id="cart"></tbody>
            </table>
          </div>
        </section>
      </div>

      <aside class="kassa-side" aria-label="Оплата">
        <div class="card pay-panel">
          <div class="total-row"><span>Итого</span><b id="total">0 ₸</b></div>
          <div class="debt-opts">
            <label>Заплатил сейчас, ₸<input id="paidNow" type="number" inputmode="numeric" min="0" step="1" value="0"></label>
            <label>Вернуть через<select id="due"><option value="7">7 дней</option><option value="14" selected>14 дней</option><option value="30">30 дней</option></select></label>
          </div>
          <div class="pay-buttons">
            <button class="btn-paid" id="btnPaid">Оплачено</button>
            <button class="btn-debt" id="btnDebt">В долг</button>
          </div>
        </div>
        <details class="card feed-card" id="feedCard" open>
          <summary><h2>Последние операции</h2></summary>
          <ul class="feed" id="feed"><li class="empty">Пока пусто</li></ul>
        </details>
      </aside>
    </div>`;

  // На телефоне лента операций свёрнута, чтобы касса помещалась на экран
  if (window.matchMedia('(max-width: 960px)').matches) document.getElementById('feedCard').open = false;

  const $ = id => document.getElementById(id) || document.createElement('div'); // экран мог смениться, пока шёл запрос

  // ---------- данные ----------
  async function loadRefs() {
    [products, customers] = await Promise.all([api('/api/products'), api('/api/customers')]);
    $('productList').innerHTML = products.map(p => `<option value="${esc(p.name)}">${money(p.price)}${p.barcode ? ' · ' + esc(p.barcode) : ''}</option>`).join('');
    renderCustomerSelect();
  }

  function renderCustomerSelect() {
    const opts = ['<option value="">— без покупателя (продажа) —</option>', '<option value="new">＋ Новый покупатель</option>']
      .concat(customers.map(c => `<option value="${c.id}">${esc(c.name)}${c.balance > 0 ? ' · долг ' + money(c.balance) : ''}</option>`));
    $('cust').innerHTML = opts.join('');
    $('cust').value = state.customerId ? String(state.customerId) : (state.newName ? 'new' : '');
    $('newName').hidden = $('cust').value !== 'new';
    $('newName').value = state.newName;
    const c = customers.find(x => x.id === state.customerId);
    $('custBadge').textContent = c ? (c.balance > 0 ? 'Сейчас должен: ' + money(c.balance) : 'Долгов нет') : '';
    $('custBadge').className = 'badge' + (c && c.balance > 0 ? ' warn' : '');
  }

  async function loadFeed() {
    const rows = await api('/api/sales?limit=12');
    $('feed').innerHTML = rows.length ? rows.map(r => `
      <li>
        <div class="feed-top">
          <b>${esc(r.customer_name || 'Продажа')}</b>
          <span class="pill ${r.kind === 'debt' ? (r.status === 'closed' ? 'ok' : 'warn') : 'ok'}">${r.kind === 'debt' ? (r.status === 'closed' ? 'долг закрыт' : 'в долг') : 'оплачено'}</span>
        </div>
        <div class="feed-items">${esc(r.items_text || '')}</div>
        <div class="feed-meta">${money(r.total)} · ${esc(r.created_at.slice(11, 16))}${r.source === 'voice' ? ' · 🎤' : r.source === 'barcode' ? ' · штрихкод' : ''}</div>
      </li>`).join('') : '<li class="empty">Пока пусто</li>';
  }

  // ---------- корзина ----------
  const total = () => state.items.reduce((s, it) => s + Math.round(it.qty * it.price), 0);

  function renderCart() {
    $('cart').innerHTML = state.items.length ? state.items.map((it, i) => `
      <tr>
        <td><b>${esc(it.name)}</b></td>
        <td><input type="number" min="0.1" step="0.5" value="${fmtQty(it.qty)}" data-i="${i}" class="qty" aria-label="Количество"></td>
        <td class="num">${money(it.price)}</td>
        <td class="num">${money(Math.round(it.qty * it.price))}</td>
        <td class="actions"><button class="ghost small" data-del="${i}" aria-label="Убрать">✕</button></td>
      </tr>`).join('') : `<tr><td colspan="5"><div class="cart-empty"><span class="big" aria-hidden="true">0</span><div><b>Заказ пуст</b>Скажите фразу, нажмите «Примеры фраз» или отсканируйте товар телефоном.</div></div></td></tr>`;
    $('total').textContent = money(total());
    $('cartTable').classList.toggle('is-empty', !state.items.length);
    if (state.paidNow > total()) state.paidNow = total();
    $('paidNow').value = state.paidNow;
  }

  function addItem(p, qty = 1) {
    checkoutRef = null;
    const existing = state.items.find(it => it.product_id === p.id);
    if (existing) existing.qty += qty;
    else state.items.push({ product_id: p.id, name: p.name, qty, price: p.price });
    renderCart();
  }

  function reset() {
    Object.assign(state, { items: [], customerId: null, newName: '', source: 'text', rawText: '', paidNow: 0 });
    $('say').value = '';
    $('notice').hidden = true;
    renderCart(); renderCustomerSelect();
  }

  // ---------- разбор фразы ----------
  let lastParsed = { text: '', at: 0 }, parsing = false;
  async function understand(text, source = 'text') {
    text = text.trim();
    if (!text || parsing) return;
    // Голос сам отправляет фразу; повторное «Разобрать» той же фразы не должно удваивать товары
    if (text === lastParsed.text && Date.now() - lastParsed.at < 8000) return;
    parsing = true;
    const btn = $('sayForm').querySelector('button[type=submit]');
    btn.disabled = true; btn.textContent = 'Разбираю…';
    let r;
    try { r = await api('/api/parse', { method: 'POST', body: { text } }); }
    finally { parsing = false; btn.disabled = false; btn.textContent = 'Разобрать'; }
    lastParsed = { text, at: Date.now() }; // запоминаем только успешный разбор — после ошибки можно повторить
    $('notice').hidden = true;

    if (r.intent === 'who_owes') {
      const debtors = customers.filter(c => c.balance > 0);
      showNotice(`<h2>Кто должен</h2>` + (debtors.length
        ? `<ul class="plain">${debtors.map(c => `<li><b>${esc(c.name)}</b> — ${money(c.balance)}</li>`).join('')}</ul>`
        : '<p>Никто не должен 🎉</p>'));
      return;
    }

    if (r.intent === 'payment') {
      const c = r.customer && customers.find(x => x.id === r.customer.id);
      if (!c) { showNotice(`<p>Понял оплату ${money(r.amount)}, но не нашёл покупателя. Выберите его на странице «Покупатели».</p>`); return; }
      showNotice(`
        <h2>Оплата долга${r.ai ? ' <span class="pill ai">🤖 ИИ</span>' : ''}</h2>
        <p><b>${esc(c.name)}</b> возвращает деньги. Сейчас должен: ${money(c.balance)}.</p>
        <label>Сумма, ₸ (проверьте)<input id="payAmount" type="number" min="1" value="${r.amount}"></label>
        <div class="pay-buttons">
          <button class="btn-paid" data-pay="cash">Принять наличными</button>
          <button class="btn-debt" data-pay="kaspi">Пришло на Kaspi</button>
        </div>`);
      $('notice').querySelectorAll('[data-pay]').forEach(b => b.onclick = async () => {
        try {
          const amount = Number($('payAmount').value);
          if (!(amount > 0)) { toast('Укажите сумму', true); return; }
          const res = await api('/api/payments', { method: 'POST', body: { customer_id: c.id, amount, method: b.dataset.pay } });
          toast(`Принято ${money(res.accepted)}. Осталось: ${money(res.balance)}`);
          reset(); await loadRefs(); loadFeed();
        } catch (err) { toast(err.message, true); }
      });
      return;
    }

    state.source = source;
    state.rawText = text;
    if (r.customer) { state.customerId = r.customer.id; state.newName = ''; }
    else if (r.new_customer_name) { state.customerId = null; state.newName = r.new_customer_name; }
    // Новая фраза — новый заказ: корзина заменяется, а не дополняется
    state.items = [];
    state.paidNow = 0;
    r.items.forEach(it => {
      const p = products.find(x => x.id === it.product_id);
      if (p) addItem(p, it.qty);
    });
    if (r.half_paid) state.paidNow = Math.round(total() / 2);
    renderCart(); renderCustomerSelect();

    const notes = [];
    if (r.ai) notes.push('🤖 <b>Фразу дополнительно разобрал ИИ</b> — проверьте товары и количество.');
    if (r.new_customer_name) notes.push(`Новый покупатель: <b>${esc(r.new_customer_name)}</b>. Проверьте имя.`);
    if (r.unknown.length) notes.push(`Не понял: <b>${esc(r.unknown.join(', '))}</b>. Добавьте товар вручную или в прайс.`);
    if (r.half_paid) notes.push('Половину заплатили сразу, остальное в долг.');
    if (r.kind === 'debt') notes.push('Похоже на долг — нажмите «В долг».');
    if (notes.length) showNotice(notes.map(n => `<p>${n}</p>`).join(''));
    $('btnDebt').classList.toggle('pulse', r.kind === 'debt');
  }

  function showNotice(html) { $('notice').innerHTML = html; $('notice').hidden = false; }

  // После записи долга: QR для подтверждения покупателем в Telegram
  let consentSaleId = null;
  function showConsent(sale, who) {
    consentSaleId = sale.id;
    showNotice(`
      <div class="consent">
        <div class="qr-box"><img src="/api/sales/${sale.id}/qr.svg" alt="QR-код подтверждения долга" width="190" height="190"></div>
        <div>
          <h2>Подтверждение долга</h2>
          <p><b>${esc(who)}</b> должен <b>${money(sale.total - sale.paid_now)}</b> до ${esc(fmtDate(sale.due_date, { day: "numeric", month: "long" }))}.</p>
          <p>Покупатель сканирует QR камерой телефона → открывается Telegram → он нажимает <b>«Растаймын»</b>.</p>
          ${sale.consent_sent ? '<p class="sub">Покупатель уже подключён к боту — запрос отправлен ему в Telegram.</p>' : ''}
          <p class="consent-status" id="consentStatus">⏳ Ждём подтверждения…</p>
          <button type="button" class="ghost small" id="consentSkip">Пропустить</button>
        </div>
      </div>`);
    $('consentSkip').onclick = () => { $('notice').hidden = true; consentSaleId = null; };
  }

  // ---------- оформление ----------
  let checkoutBusy = false, checkoutRef = null;
  async function checkout(kind) {
    if (checkoutBusy) return; // второе нажатие, пока первое ещё в пути
    if (!state.items.length) { toast('Корзина пуста', true); return; }
    const sel = $('cust').value;
    const body = {
      kind,
      items: state.items.map(it => ({ product_id: it.product_id, name: it.name, qty: it.qty, price: it.price })),
      customer_id: sel && sel !== 'new' ? Number(sel) : null,
      new_customer_name: sel === 'new' ? $('newName').value.trim() : null,
      paid_now: Number($('paidNow').value) || 0,
      due_days: Number($('due').value),
      source: state.source,
      raw_text: state.rawText,
      // Один номер на одну операцию: даже если запрос уйдёт дважды, сервер запишет её один раз
      client_ref: checkoutRef || (checkoutRef = Date.now().toString(36) + Math.random().toString(36).slice(2, 8)),
    };
    if (kind === 'debt' && !body.customer_id && !body.new_customer_name) { toast('Выберите покупателя для долга', true); $('cust').focus(); return; }
    checkoutBusy = true;
    $('btnPaid').disabled = $('btnDebt').disabled = true;
    try {
      const sale = await api('/api/sales', { method: 'POST', body });
      checkoutRef = null;
      toast(kind === 'debt' ? `Записано в долг: ${money(sale.total - sale.paid_now)}` : `Оплачено: ${money(sale.total)}`);
      $('btnDebt').classList.remove('pulse');
      const who = body.new_customer_name || (customers.find(c => c.id === body.customer_id) || {}).name || '';
      reset(); await loadRefs(); loadFeed();
      if (kind === 'debt') showConsent(sale, who);
    } catch (err) { toast(err.message, true); }
    finally { checkoutBusy = false; $('btnPaid').disabled = $('btnDebt').disabled = false; }
  }

  // ---------- голос (бесплатное распознавание Chrome) ----------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, voiceText = '';
  function stopVoice() { if (rec) { rec.stop(); } }
  window.stopVoice = () => { if (rec) { rec.onend = null; rec.abort(); rec = null; } };

  $('mic').onclick = () => {
    if (!SR) { toast('Голос работает только в Google Chrome', true); return; }
    if (rec) { stopVoice(); return; }
    rec = new SR();
    rec.lang = $('lang').value;
    rec.continuous = true;
    rec.interimResults = true;
    voiceText = '';
    $('mic').classList.add('on');
    $('voiceStatus').hidden = false;
    $('voiceStatus').textContent = 'Включаю микрофон…';
    rec.onaudiostart = () => { $('voiceStatus').textContent = '🔴 Говорите. Закончили — нажмите 🎤 ещё раз.'; };
    rec.onresult = e => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) voiceText += e.results[i][0].transcript + ' ';
        else interim += e.results[i][0].transcript;
      }
      $('say').value = (voiceText + interim).trim();
    };
    rec.onerror = e => { toast('Голос: ' + (e.error === 'not-allowed' ? 'разрешите доступ к микрофону' : e.error), true); };
    rec.onend = () => {
      rec = null;
      $('mic').classList.remove('on');
      $('voiceStatus').hidden = true;
      if (voiceText.trim()) understand(voiceText, 'voice').catch(err => toast(err.message, true));
    };
    rec.start();
  };

  // ---------- события ----------
  $('sayForm').addEventListener('submit', e => { e.preventDefault(); understand($('say').value).catch(err => toast(err.message, true)); });
  document.querySelectorAll('.chip').forEach(ch => ch.onclick = () => { $('say').value = ch.textContent; understand(ch.textContent).catch(err => toast(err.message, true)); });

  $('cust').onchange = () => {
    const v = $('cust').value;
    state.customerId = v && v !== 'new' ? Number(v) : null;
    if (v !== 'new') state.newName = '';
    renderCustomerSelect();
    if (v === 'new') $('newName').focus();
  };
  $('newName').oninput = () => (state.newName = $('newName').value);
  $('paidNow').oninput = () => (state.paidNow = Math.max(0, Number($('paidNow').value) || 0));

  $('cart').addEventListener('input', e => {
    if (!e.target.classList.contains('qty')) return;
    const it = state.items[Number(e.target.dataset.i)];
    it.qty = Math.max(0.1, Number(e.target.value) || 0.1);
    $('total').textContent = money(total());
    e.target.closest('tr').children[3].textContent = money(Math.round(it.qty * it.price));
  });
  $('cart').addEventListener('click', e => {
    const b = e.target.closest('[data-del]');
    if (b) { state.items.splice(Number(b.dataset.del), 1); renderCart(); }
  });

  $('addProduct').addEventListener('change', async e => {
    const v = e.target.value.trim();
    if (!v) return;
    let p = products.find(x => x.name === v || x.barcode === v);
    if (!p && /^\d{6,}$/.test(v)) p = await api('/api/products/barcode/' + v).catch(() => null);
    if (p) { addItem(p); e.target.value = ''; } else toast('Нет такого товара в прайсе', true);
  });

  $('clear').onclick = () => { reset(); $('btnDebt').classList.remove('pulse'); };

  // Сканер: по штрихкоду (телефон → сразу в заказ) или по фото (ИИ ищет товар в прайсе)
  $('scanBtn').onclick = () => {
    const open = $('scanPanel').hidden;
    $('scanPanel').hidden = !open; $('scanBtn').setAttribute('aria-expanded', open);
    if (open) setScanMode('barcode');
  };
  function setScanMode(m) {
    document.querySelectorAll('[data-scan]').forEach(b => { b.classList.toggle('on', b.dataset.scan === m); b.setAttribute('aria-selected', b.dataset.scan === m); });
    if (m === 'barcode') return showScannerQr($('scanBody'), 'cart');
    $('scanBody').innerHTML = `<p>Сфотографируйте товар — ИИ найдёт похожие в вашем прайсе, а вы подтвердите нужный.</p>
      <button type="button" class="lime" id="aiShot">📷 Сфотографировать товар</button><div id="aiMatch"></div>`;
    $('aiShot').onclick = aiMatch;
  }
  document.querySelectorAll('[data-scan]').forEach(b => b.onclick = () => setScanMode(b.dataset.scan));
  async function aiMatch() {
    const img = await pickPhoto(); if (!img) return;
    const box = $('aiMatch');
    box.innerHTML = `<div class="ai-wait"><img src="${img}" alt="Фото товара" width="96" height="96"><p class="sub">🤖 ИИ ищет товар в прайсе…</p></div>`;
    try {
      const r = await api('/api/ai/match', { method: 'POST', body: { image: img } });
      if (!r.candidates.length) { box.innerHTML = `<p class="notice-line">Похожих товаров в прайсе нет (на фото: ${esc(r.seen)}). Добавьте товар во вкладке «Товары».</p>`; return; }
      box.innerHTML = `<p class="sub">На фото: ${esc(r.seen)}. Это один из них?</p><ul class="match-list">${r.candidates.map((p, i) => `
        <li><span class="m-photo">${p.has_photo ? `<img src="/api/products/${p.id}/photo" alt="" width="48" height="48">` : '📦'}</span>
          <span><b>${esc(p.name)}</b><br><span class="sub">${money(p.price)} · похоже на ${Math.round(p.confidence * 100)}%</span></span>
          <button type="button" class="${i ? 'ghost' : 'lime'}" data-pick="${i}">Да, это он</button></li>`).join('')}</ul>
        <button type="button" class="ghost small" id="aiAgain">Нет, сфотографировать ещё раз</button>`;
      box.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => {
        const p = r.candidates[+b.dataset.pick];
        state.source = 'photo'; addItem(p); toast('Добавлено: ' + p.name);
        box.innerHTML = '';
      });
      $('aiAgain').onclick = aiMatch;
    } catch (err) { box.innerHTML = `<p class="notice-line">${esc(err.message)}</p>`; }
  }
  $('btnPaid').onclick = () => checkout('paid');
  $('btnDebt').onclick = () => checkout('debt');

  // Скан с телефона или изменения на другом экране
  listeners.add(async msg => {
    if (consentSaleId && msg.sale_id === consentSaleId && $('consentStatus')) {
      if (msg.type === 'consent_opened') $('consentStatus').textContent = '📱 Покупатель открыл бота…';
      if (msg.type === 'consent_changed') {
        $('consentStatus').textContent = msg.status === 'confirmed' ? '✅ Покупатель подтвердил долг' : '❌ Покупатель отклонил — проверьте запись';
        $('consentStatus').className = 'consent-status ' + (msg.status === 'confirmed' ? 'ok' : 'bad');
      }
    }
    if (msg.type === 'scan' && msg.product_id) {  // товар найден по фото на телефоне
      const p = products.find(x => x.id === msg.product_id);
      if (p) { state.source = 'photo'; addItem(p); toast('Фото: ' + p.name); }
    }
    if (msg.type === 'scan' && msg.barcode) {
      const p = await api('/api/products/barcode/' + encodeURIComponent(msg.barcode)).catch(() => null);
      if (p) { state.source = 'barcode'; addItem(p); toast('Скан: ' + p.name); }
      else toast('Штрихкод ' + msg.barcode + ' не найден в прайсе', true);
    }
    if (['products_changed', 'customers_changed', 'sale_created', 'payment_created'].includes(msg.type)) {
      await loadRefs(); loadFeed();
    }
  });

  renderCart();
  await loadRefs();
  loadFeed();
  $('say').focus();
}

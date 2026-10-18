// Долги: плитки должников → панель покупателя с разделами «Ждут подтверждения», «Подтверждённые», «Возвраты»

let debtFilter = 'all', debtSort = 'due';

async function renderDebts() {
  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>Долги</h1>
        <p class="hint">Нажмите на человека — откроются его долги, напоминание и приём оплаты.</p>
      </div>
      <div class="sum-box"><span>Всего должны</span><b id="owed">—</b></div>
    </div>
    <div class="debt-tools">
      <div class="seg" role="tablist" aria-label="Фильтр">
        <button type="button" role="tab" data-f="all">Все</button>
        <button type="button" role="tab" data-f="overdue">Просрочены</button>
        <button type="button" role="tab" data-f="pending">Ждут QR</button>
      </div>
      <label class="sort">Сортировка<select id="dSort"><option value="due">по сроку</option><option value="sum">по сумме</option></select></label>
    </div>
    <div id="debtList" class="debt-grid"><p class="empty">Загрузка…</p></div>
    <div class="modal drawer" id="modal" hidden>
      <div class="modal-card card" role="dialog" aria-modal="true" aria-labelledby="mTitle" tabindex="-1">
        <div class="row-between"><h2 id="mTitle"></h2><button class="ghost small" id="mClose">Закрыть</button></div>
        <div id="mBody"></div>
      </div>
    </div>`;

  const $ = id => document.getElementById(id) || document.createElement('div');
  let list = [], openId = null, lastFocus = null;

  async function load() {
    list = await api('/api/debts');
    $('owed').textContent = money(list.reduce((s, d) => s + d.balance, 0));
    document.querySelectorAll('.debt-tools [data-f]').forEach(b => {
      const on = b.dataset.f === debtFilter;
      b.classList.toggle('on', on); b.setAttribute('aria-selected', on);
    });
    $('dSort').value = debtSort;
    let rows = list.filter(d => debtFilter === 'all' || (debtFilter === 'overdue' ? d.overdue : d.pending > 0));
    rows.sort((a, b) => debtSort === 'sum' ? b.balance - a.balance : String(a.due || '9').localeCompare(String(b.due || '9')));
    $('debtList').innerHTML = rows.length ? rows.map(d => `
      <button type="button" class="debt-tile${d.overdue ? ' overdue' : ''}" data-id="${d.id}">
        <span class="dt-name">${esc(d.name)}</span>
        <span class="dt-phone">${esc(d.phone || 'нет телефона')}</span>
        <b class="dt-sum">${money(d.balance)}</b>
        <span class="dt-due">${d.due ? 'до ' + fmtDate(d.due) : 'без срока'}</span>
        <span class="chips-row">
          ${d.overdue ? '<span class="pill bad">просрочен</span>' : ''}
          ${d.pending ? `<span class="pill warn">ждут QR: ${d.pending}</span>` : '<span class="pill ok">подтверждено</span>'}
          ${d.in_bot ? `<span class="pill ok">${d.tg_username ? '@' + esc(d.tg_username) : 'в Telegram'}</span>` : '<span class="pill">нет в боте</span>'}
        </span>
      </button>`).join('') : `<div class="soon">${list.length ? 'Под этот фильтр никто не подходит' : 'Никто не должен 🎉'}</div>`;
    if (openId) openPanel(openId, false);
  }

  function closeModal() {
    $('modal').hidden = true; openId = null;
    if (lastFocus) lastFocus.focus();
  }
  function showModal(title, html) {
    $('mTitle').textContent = title; $('mBody').innerHTML = html;
    if ($('modal').hidden) { lastFocus = document.activeElement; $('modal').hidden = false; }
    document.querySelector('#modal .modal-card').focus();
  }
  $('mClose').onclick = closeModal;
  $('modal').onclick = e => { if (e.target.id === 'modal') closeModal(); };
  $('modal').onkeydown = e => { if (e.key === 'Escape') closeModal(); };

  // ---------- панель покупателя ----------
  async function openPanel(id, focus = true) {
    const d = list.find(x => x.id === id);
    if (!d) { closeModal(); return; }
    openId = id;
    const c = await api('/api/customers/' + id);
    const pending = d.sales.filter(s => s.status === 'pending');
    const confirmed = d.sales.filter(s => s.status === 'confirmed');
    const when = v => fmtDate(v, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    // Одна операция — одна строка «дата, время · сумма»; что купили — по нажатию
    const tx = (s, extra) => `<details class="tx"><summary><span>${when(s.created_at)}</span><b>${money(s.debt)}</b></summary>
      <div class="tx-body"><p>${esc(s.items || 'без списка товаров')}</p>${s.due_date ? `<p class="sub">вернуть до ${fmtDate(s.due_date)}</p>` : ''}${extra || ''}</div></details>`;
    const folder = (cls, title, list, open) => `<details class="folder ${cls}"${open ? ' open' : ''}><summary>📁 ${title} <span>${list.length}</span></summary>
      <div class="folder-body">${list.join('') || '<p class="sub">Пусто</p>'}</div></details>`;
    showModal(d.name, `
      <div class="dp-head">
        <span class="sub">${esc(d.phone || 'нет телефона')}${d.due ? ' · вернуть до ' + fmtDate(d.due) : ''}${d.last_reminder ? ' · напоминали ' + fmtDate(d.last_reminder) : ''}</span>
        <b class="dp-sum">${money(d.balance)}</b>
      </div>
      <div class="dp-actions">
        <button type="button" class="lime" id="pRemind">Напомнить</button>
        <form class="inline-pay" id="pPay">
          <input name="amount" type="number" inputmode="numeric" min="1" max="${d.balance}" placeholder="Сумма…" aria-label="Сумма оплаты" required>
          <select name="method" aria-label="Способ"><option value="cash">Наличные</option><option value="kaspi">Kaspi</option></select>
          <button class="ghost" type="submit">Принять оплату</button>
        </form>
      </div>
      ${folder('warn', 'Ждут подтверждения', pending.map(s => tx(s, `<button type="button" class="ghost small" data-qr="${s.id}">Показать QR</button>`)), true)}
      ${folder('ok', 'Подтверждённые долги', confirmed.map(s => tx(s)), true)}
      ${folder('back', 'Возвраты', c.payments.map(p => `<div class="tx flat"><span>${when(p.created_at)} · ${p.method === 'kaspi' ? 'Kaspi' : 'наличные'}</span><b class="plus">+${money(p.amount)}</b></div>`), false)}
      <div id="pQr"></div>`);
    if (!focus) return;
    $('pRemind').onclick = () => remind(id);
    $('pPay').onsubmit = async e => {
      e.preventDefault();
      try {
        const r = await api('/api/payments', { method: 'POST', body: { customer_id: id, amount: Number(e.target.elements.amount.value), method: e.target.elements.method.value } });
        toast(`Принято ${money(r.accepted)}. Осталось: ${money(r.balance)}`); load();
      } catch (err) { toast(err.message, true); }
    };
    $('mBody').querySelectorAll('[data-qr]').forEach(b => b.onclick = () => {
      $('pQr').innerHTML = `<div class="qr-box"><img src="/api/sales/${b.dataset.qr}/qr.svg" alt="QR-код подтверждения долга" width="220" height="220"></div>
        <p class="sub">Покупатель сканирует QR камерой → Telegram → «Растаймын». Статус обновится сам.</p>`;
      $('pQr').scrollIntoView({ block: 'nearest' });
    });
  }

  // ---------- напоминание ----------
  async function remind(cid) {
    const r = await api('/api/reminders/' + cid);
    showModal('Напоминание: ' + r.name, `
      <p class="sub">Язык покупателя: ${r.lang === 'kk' ? 'қазақша' : 'русский'}. Текст можно изменить.</p>
      <textarea id="rText" rows="7" aria-label="Текст напоминания">${esc(r.plain)}</textarea>
      ${r.kaspi ? '' : '<p class="notice-line">Ссылка Kaspi не указана — добавьте её в «Настройках».</p>'}
      <div class="pay-buttons">
        <button id="sendTg" ${r.telegram ? '' : 'disabled title="Покупатель ещё не подключён к боту"'}>Отправить в Telegram</button>
        <button id="sendWa" class="btn-paid" ${r.phone ? '' : 'disabled title="Нет телефона"'}>Открыть WhatsApp</button>
      </div>
      <button type="button" class="ghost" id="rBack">Назад</button>`);
    $('rBack').onclick = () => openPanel(cid);
    $('sendTg').onclick = async () => {
      try { await api('/api/reminders/' + cid, { method: 'POST', body: { text: $('rText').value, channel: 'telegram' } }); toast('Напоминание отправлено в Telegram'); openPanel(cid); }
      catch (err) { toast(err.message, true); }
    };
    $('sendWa').onclick = async () => {
      const digits = (r.phone || '').replace(/\D/g, '').replace(/^8(\d{10})$/, '7$1');
      window.open('https://wa.me/' + digits + '?text=' + encodeURIComponent($('rText').value), '_blank');
      await api('/api/reminders/' + cid, { method: 'POST', body: { text: $('rText').value, channel: 'whatsapp' } }).catch(() => {});
      openPanel(cid);
    };
  }

  $('debtList').addEventListener('click', e => { const t = e.target.closest('.debt-tile'); if (t) openPanel(Number(t.dataset.id)); });
  document.querySelectorAll('.debt-tools [data-f]').forEach(b => b.onclick = () => { debtFilter = b.dataset.f; load(); });
  $('dSort').onchange = e => { debtSort = e.target.value; load(); };
  listeners.add(msg => { if (['sale_created', 'payment_created', 'consent_changed', 'customers_changed', 'reminder_sent', 'refresh'].includes(msg.type)) load(); });
  await load();
}

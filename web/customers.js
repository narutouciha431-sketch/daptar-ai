// Покупатели: список с долгами, карточка с историей покупок и оплат, приём возврата долга

async function renderCustomers() {
  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>Покупатели</h1>
        <p class="hint">Кто берёт в долг и сколько должен. Телефон нужен для оплаты через Kaspi (переводы идут по номеру) и для напоминаний. Номера карт и счетов не храним.</p>
      </div>
      <input class="search" id="cq" type="search" placeholder="Поиск: имя или телефон…" aria-label="Поиск покупателя">
    </div>

    <form class="card form-grid cust-form" id="custForm">
      <label class="wide">Имя<input name="name" required maxlength="80" placeholder="Айгүл апай…"></label>
      <label>Телефон<input name="phone" type="tel" placeholder="+7 7…"></label>
      <label class="wide">Адрес<input name="address" placeholder="Абай көшесі, 12…"></label>
      <label>Заметка<input name="note" placeholder="с 5-го дома…"></label>
      <label>Язык<select name="language"><option value="kk">Қазақша</option><option value="ru">Русский</option></select></label>
      <button type="submit">Добавить</button>
    </form>

    <div class="cust-layout">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Имя</th><th>Телефон</th><th>Адрес</th><th style="text-align:right">Долг</th><th>Последняя покупка</th></tr></thead>
          <tbody id="crows"><tr><td colspan="5" class="empty">Загрузка…</td></tr></tbody>
        </table>
      </div>
      <aside class="card detail" id="detail"><p class="empty">Выберите покупателя, чтобы увидеть историю и принять оплату.</p></aside>
    </div>`;

  const $ = id => document.getElementById(id) || document.createElement('div'); // экран мог смениться, пока шёл запрос
  let selected = null;

  async function load() {
    const rows = await api('/api/customers?q=' + encodeURIComponent($('cq').value));
    $('crows').innerHTML = rows.length ? rows.map(c => `
      <tr data-id="${c.id}" class="clickable${c.id === selected ? ' selected' : ''}" tabindex="0">
        <td><b>${esc(c.name)}</b>${c.note ? `<div class="sub">${esc(c.note)}</div>` : ''}</td>
        <td class="code">${esc(c.phone || '—')}</td>
        <td>${esc(c.address || '—')}</td>
        <td class="num ${c.balance > 0 ? 'debt' : ''}">${c.balance > 0 ? money(c.balance) : '—'}</td>
        <td>${c.last_sale ? esc(c.last_sale.slice(0, 16)) : '—'}</td>
      </tr>`).join('') : `<tr><td colspan="5" class="empty">${$('cq').value ? 'Никого не найдено' : 'Покупателей пока нет'}</td></tr>`;
  }

  const receipts = {};  // чек после оплаты: покупатель → текст для WhatsApp
  async function showDetail(id) {
    selected = id;
    const c = await api('/api/customers/' + id);
    const history = [
      ...c.sales.map(s => ({ at: s.created_at, html: `
        <li>
          <div class="feed-top"><b>${s.kind === 'debt' ? 'В долг' : 'Покупка'}</b><span>${money(s.total)}</span></div>
          <div class="feed-items">${esc(s.items.map(it => it.name + ' ×' + fmtQty(it.qty)).join(', '))}</div>
          <div class="feed-meta">${esc(s.created_at.slice(0, 16))}${s.kind === 'debt' ? ` <span class="pill ${statusCls(s.status)}">${statusText(s.status)}</span>${s.paid_now ? ' · заплатил сразу ' + money(s.paid_now) : ''}${s.due_date && s.status !== 'closed' ? ' · вернуть до ' + esc(s.due_date) : ''}` : ''}</div>
        </li>` })),
      ...c.payments.map(p => ({ at: p.created_at, html: `
        <li class="pay">
          <div class="feed-top"><b>Вернул долг</b><span class="plus">+${money(p.amount)}</span></div>
          <div class="feed-meta">${esc(p.created_at.slice(0, 16))} · ${p.method === 'kaspi' ? 'Kaspi' : 'наличные'}</div>
        </li>` })),
    ].sort((a, b) => b.at.localeCompare(a.at));

    $('detail').innerHTML = `
      ${c.phone ? `<div class="wa-row"><button type="button" class="wa small" id="cWa">💬 WhatsApp</button>${receipts[id] ? '<button type="button" class="wa small" id="cReceipt">🧾 Чек в WhatsApp</button>' : ''}</div>` : ''}
      <div class="row-between"><h2>${esc(c.name)}</h2><span class="pill big ${c.balance > 0 ? 'warn' : 'ok'}">${c.balance > 0 ? 'Долг: ' + money(c.balance) : 'Долгов нет'}</span></div>
      <p class="sub">${esc([c.phone, c.address, c.language === 'kk' ? 'қазақша' : 'русский'].filter(Boolean).join(' · '))}</p>
      ${c.balance > 0 ? `
        <form class="pay-form" id="payForm">
          <label>Вернул, ₸<input name="amount" type="number" min="1" max="${c.balance}" value="${c.balance}" required></label>
          <select name="method" aria-label="Способ оплаты"><option value="cash">Наличные</option><option value="kaspi">Kaspi</option></select>
          <button type="submit">Принять оплату</button>
        </form>` : ''}
      <h3 class="mt">История</h3>
      <ul class="feed">${history.map(h => h.html).join('') || '<li class="empty">Пока ничего</li>'}</ul>
      <details class="mt"><summary>Изменить данные</summary>
        <form class="edit-form" id="editForm">
          <label>Имя<input name="name" value="${esc(c.name)}" required></label>
          <label>Телефон<input name="phone" value="${esc(c.phone)}"></label>
          <label>Адрес<input name="address" value="${esc(c.address)}"></label>
          <label>Заметка<input name="note" value="${esc(c.note)}"></label>
          <label>Язык<select name="language"><option value="kk"${c.language === 'kk' ? ' selected' : ''}>Қазақша</option><option value="ru"${c.language === 'ru' ? ' selected' : ''}>Русский</option></select></label>
          <button type="submit">Сохранить</button>
        </form>
        <button type="button" class="danger" id="delCust">Удалить покупателя</button>
      </details>`;

    if ($('cWa')) $('cWa').onclick = () => openWhatsApp(c.phone, '');
    if ($('cReceipt')) $('cReceipt').onclick = () => { openWhatsApp(c.phone, receipts[id]); delete receipts[id]; showDetail(id); };
    const pf = $('payForm');
    if (pf) pf.onsubmit = async e => {
      e.preventDefault();
      try {
        const r = await api('/api/payments', { method: 'POST', body: { customer_id: id, amount: Number(pf.elements.amount.value), method: pf.elements.method.value } });
        toast(`Принято ${money(r.accepted)}. Осталось: ${money(r.balance)}`);
        if (c.phone) receipts[id] = WA.receipt(c.language, c.name, money(r.accepted), r.balance);
        await load(); await showDetail(id);
      } catch (err) { toast(err.message, true); }
    };
    $('editForm').onsubmit = async e => {
      e.preventDefault();
      const f = e.target.elements;
      try {
        await api('/api/customers/' + id, { method: 'PUT', body: { name: f.name.value, phone: f.phone.value, address: f.address.value, note: f.note.value, language: f.language.value } });
        toast('Сохранено'); await load(); await showDetail(id);
      } catch (err) { toast(err.message, true); }
    };
    $('delCust').onclick = async () => {
      const warn = c.balance > 0 ? `
У него долг ${money(c.balance)} — он тоже удалится.` : '';
      if (!confirm(`Удалить покупателя «${c.name}» и всю его историю?${warn}
Это нельзя отменить.`)) return;
      try {
        await api('/api/customers/' + id, { method: 'DELETE' });
        selected = null; $('detail').innerHTML = '<p class="empty">Покупатель удалён.</p>';
        toast('Покупатель удалён'); await load();
      } catch (err) { toast(err.message, true); }
    };
    await load();
  }

  const statusCls = s => ({ pending: 'warn', confirmed: 'ok', rejected: 'bad', closed: 'ok' }[s] || '');
  const statusText = s => ({ pending: 'ждёт подтверждения', confirmed: 'подтверждён', rejected: 'отклонён', closed: 'закрыт' }[s] || s);

  $('crows').addEventListener('click', async e => {
    const tr = e.target.closest('tr[data-id]'); if (!tr) return;
    await showDetail(Number(tr.dataset.id));
    if (innerWidth <= 960) $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });  // на телефоне карточка ниже списка
  });
  $('crows').addEventListener('keydown', e => { const tr = e.target.closest('tr[data-id]'); if (tr && e.key === 'Enter') showDetail(Number(tr.dataset.id)); });

  $('custForm').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      const c = await api('/api/customers', { method: 'POST', body: { name: f.name.value, phone: f.phone.value, address: f.address.value, note: f.note.value, language: f.language.value } });
      toast('Покупатель добавлен'); e.target.reset(); await load(); showDetail(c.id);
    } catch (err) { toast(err.message, true); }
  });

  let t;
  $('cq').addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 200); });

  listeners.add(msg => {
    if (['customers_changed', 'sale_created', 'payment_created', 'refresh'].includes(msg.type)) { load(); if (selected) showDetail(selected).catch(() => { selected = null; }); }
  });

  await load();
}

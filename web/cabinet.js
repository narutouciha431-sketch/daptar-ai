// Кабинет магазина: «Просто» — главное за сегодня простыми словами; «Аналитика» — графики и сравнения

let cabinetTab = location.hash === '#cabinet-charts' ? 'charts' : 'simple';
let charts = [];

async function renderCabinet() {
  view.innerHTML = `
    <div class="page-head">
      <div><h1>Кабинет</h1><p class="hint">Как идут дела магазина: деньги, долги, что продаётся.</p></div>
      <div class="seg" role="tablist" aria-label="Вид кабинета">
        <button type="button" role="tab" aria-selected="${cabinetTab === 'simple'}" data-tab="simple" class="${cabinetTab === 'simple' ? 'on' : ''}">Просто</button>
        <button type="button" role="tab" aria-selected="${cabinetTab === 'charts'}" data-tab="charts" class="${cabinetTab === 'charts' ? 'on' : ''}">Аналитика</button>
      </div>
    </div>
    <div id="cab"></div>`;
  document.querySelectorAll('.seg button').forEach(b => b.onclick = () => { cabinetTab = b.dataset.tab; history.replaceState(null, '', cabinetTab === 'charts' ? '#cabinet-charts' : '#cabinet'); renderCabinet(); });
  listeners.add(msg => { if (['sale_created', 'payment_created', 'consent_changed', 'refresh'].includes(msg.type)) draw(); });
  await draw();
}

async function draw() {
  charts.forEach(ch => ch.destroy()); charts = [];
  const cab = document.getElementById('cab');
  if (!cab) return;
  if (cabinetTab === 'simple') await drawSimple(cab); else await drawCharts(cab);
}

// ---------- «Просто» ----------
async function drawSimple(cab) {
  const [r, d] = await Promise.all([api('/api/report'), api('/api/debts')]);
  if (!cab.isConnected) return; // пока грузилось, открыли другую вкладку
  const todo = [];
  if (r.overdue.length) todo.push(`Напомнить ${r.overdue.length} просрочившим покупателям (${money(r.overdue_sum)}) — раздел «Долги».`);
  const pending = d.filter(x => x.pending).length;
  if (pending) todo.push(`${pending} покупателей ещё не подтвердили долг через QR.`);
  if (!todo.length) todo.push('Всё в порядке: просрочек нет 👍');

  cab.innerHTML = `
    <div class="card today"><h2>📋 Что сделать сегодня</h2><ul class="todo">${todo.map(t => `<li>${esc(t)}</li>`).join('')}</ul></div>
    <div class="tiles big-tiles">
      <div class="tile"><i aria-hidden="true">🛒</i><span>Продано сегодня</span><b>${money(r.sold)}</b><small>${r.sales_count} покупок</small></div>
      <div class="tile"><i aria-hidden="true">💵</i><span>Получено денег</span><b>${money(r.cash_in)}</b><small>включая возвраты долгов</small></div>
      <div class="tile warn"><i aria-hidden="true">📒</i><span>Вам должны</span><b>${money(r.owed)}</b><small>${r.debtors_count} человек</small></div>
      <div class="tile ok"><i aria-hidden="true">↩️</i><span>Вернули сегодня</span><b>${money(r.returned)}</b><small>новых долгов: ${money(r.new_debt)}</small></div>
    </div>
    <div class="card ai-card">
      <div class="row-between"><h2>🤖 Советы ИИ</h2><button type="button" class="lime" id="aiTips">Получить советы</button></div>
      <div id="aiTipsBody"><p class="sub">ИИ посмотрит на цифры магазина за 30 дней и подскажет, что сделать. В ИИ уходят только суммы и товары — без имён, телефонов и адресов.</p></div>
    </div>
    <div class="two">
      <div class="card"><h2>Кто должен больше всех</h2>
        <ul class="plain-list">${d.slice(0, 6).map(x => `<li><span>${esc(x.name)}${x.overdue ? ' <span class="pill bad">просрочен</span>' : ''}</span><b>${money(x.balance)}</b></li>`).join('') || '<li class="empty">Никто не должен</li>'}</ul>
      </div>
      <div class="card service-card"><h2>💳 Оплата сервиса Дәптер</h2>
        <p>За ${esc(fmtDate(r.service_month + '-01', { month: 'long', year: 'numeric' }))}: ${+(r.service_rate * 100).toFixed(2)}% от реально полученных денег.</p>
        <ul class="plain-list">
          <li><span>Оплаченные продажи</span><b>${money(r.service_paid)}</b></li>
          <li><span>Возвращённые долги</span><b>${money(r.service_back)}</b></li>
          <li class="total"><span>К оплате за сервис</span><b>${money(r.service_fee)}</b></li>
        </ul>
        <button type="button" class="ghost" id="serviceSend">Прислать счёт с реквизитами в Telegram</button>
      </div>
    </div>`;

  document.getElementById('serviceSend').onclick = async e => {
    e.currentTarget.disabled = true;
    try { await api('/api/service/send', { method: 'POST' }); toast('Счёт отправлен в ваш Telegram'); }
    catch (err) { toast(err.message, true); }
    const b = document.getElementById('serviceSend'); if (b) b.disabled = false;
  };
  document.getElementById('aiTips').onclick = async e => {
    const body = document.getElementById('aiTipsBody');
    e.currentTarget.disabled = true;
    body.innerHTML = '<p class="sub">🤖 ИИ думает… (до 20 секунд)</p>';
    try {
      const t = await api('/api/ai/insights?refresh=1');
      body.innerHTML = `<ol class="tips">${t.tips.map(x => `<li><b>${esc(x.title)}</b><br>${esc(x.text)}</li>`).join('')}</ol><p class="sub">Сгенерировано в ${esc(t.at)}. Это подсказки ИИ, решение за вами.</p>`;
    } catch (err) { body.innerHTML = `<p class="notice-line">${esc(err.message)}</p>`; }
    const b = document.getElementById('aiTips'); if (b) b.disabled = false;
  };
}

// ---------- «Аналитика» ----------
async function drawCharts(cab) {
  const a = await api('/api/analytics?days=30');
  if (!cab.isConnected) return;
  const pct = (now, before) => before ? Math.round((now - before) / before * 100) : null;
  const delta = (now, before, goodUp = true) => {
    const p = pct(now, before);
    if (p === null) return '<small>нет данных за прошлую неделю</small>';
    const good = goodUp ? p >= 0 : p <= 0;
    return `<small class="${good ? 'up' : 'down'}">${p >= 0 ? '▲' : '▼'} ${Math.abs(p)}% к прошлой неделе</small>`;
  };
  const empty = !a.series.some(s => s.count);

  cab.innerHTML = `
    ${empty ? `<div class="notice-line">Пока мало данных для графиков. Для показа можно заполнить демо-историю в «Настройках» (она помечена как демо и удаляется одной кнопкой).</div>` : ''}
    <div class="tiles">
      <div class="tile"><span>Продажи за 7 дней</span><b>${money(a.week.sold)}</b>${delta(a.week.sold, a.prev_week.sold)}</div>
      <div class="tile ok"><span>Вернули долгов за 7 дней</span><b>${money(a.week.returned)}</b>${delta(a.week.returned, a.prev_week.returned)}</div>
      <div class="tile warn"><span>Новые долги за 7 дней</span><b>${money(a.week.new_debt)}</b>${delta(a.week.new_debt, a.prev_week.new_debt, false)}</div>
      <div class="tile"><span>Доля возвращённых долгов</span><b>${a.return_rate === null ? '—' : a.return_rate + '%'}</b><small>за ${a.days} дней</small></div>
    </div>
    <div class="card chart-card"><h2>Продажи по дням: оплачено и в долг</h2><div class="chart-box"><canvas id="cSales" aria-label="График продаж по дням"></canvas></div></div>
    <div class="two">
      <div class="card chart-card"><h2>Долги: новые и возвращённые</h2><div class="chart-box"><canvas id="cDebt" aria-label="График долгов"></canvas></div></div>
      <div class="card chart-card"><h2>Как давно висят долги</h2><div class="chart-box"><canvas id="cAging" aria-label="Возраст долгов"></canvas></div></div>
    </div>
    <div class="card chart-card"><h2>Что продаётся лучше всего (30 дней)</h2><div class="chart-box short"><canvas id="cTop" aria-label="Топ товаров"></canvas></div></div>`;

  if (!window.Chart) { cab.insertAdjacentHTML('afterbegin', '<p class="notice-line">Графики не загрузились: нужен интернет.</p>'); return; }
  const css = getComputedStyle(document.documentElement);
  const C = name => css.getPropertyValue(name).trim();
  Chart.defaults.font.family = C('--f-body');
  Chart.defaults.color = C('--muted');
  const labels = a.series.map(s => s.day.slice(8, 10) + '.' + s.day.slice(5, 7));
  const tick = { callback: v => new Intl.NumberFormat('ru-RU', { notation: 'compact' }).format(v) + ' ₸' };
  const base = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' },
    tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${money(ctx.parsed.y ?? ctx.parsed.x ?? ctx.parsed)}` } } } };

  charts.push(new Chart(document.getElementById('cSales'), { type: 'bar', data: { labels, datasets: [
    { label: 'Оплачено', data: a.series.map(s => s.sold_paid), backgroundColor: C('--ok'), stack: 's' },
    { label: 'В долг', data: a.series.map(s => s.sold_debt), backgroundColor: C('--warn'), stack: 's' },
  ] }, options: { ...base, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, ticks: tick, grid: { color: C('--line') } } } } }));

  charts.push(new Chart(document.getElementById('cDebt'), { type: 'line', data: { labels, datasets: [
    { label: 'Новые долги', data: a.series.map(s => s.new_debt), borderColor: C('--warn'), backgroundColor: C('--warn'), tension: .3, pointRadius: 0 },
    { label: 'Вернули', data: a.series.map(s => s.returned), borderColor: C('--ok'), backgroundColor: C('--ok'), tension: .3, pointRadius: 0 },
  ] }, options: { ...base, scales: { x: { grid: { display: false } }, y: { ticks: tick, grid: { color: C('--line') } } } } }));

  charts.push(new Chart(document.getElementById('cAging'), { type: 'doughnut', data: { labels: Object.keys(a.aging), datasets: [
    { data: Object.values(a.aging), backgroundColor: [C('--ok'), '#c9a227', C('--warn'), C('--bad')], borderColor: C('--surface') },
  ] }, options: { ...base, plugins: { ...base.plugins, tooltip: { callbacks: { label: ctx => `${ctx.label}: ${money(ctx.parsed)}` } } } } }));

  charts.push(new Chart(document.getElementById('cTop'), { type: 'bar', data: { labels: a.top_products.map(p => p.name), datasets: [
    { label: 'Выручка', data: a.top_products.map(p => p.amount), backgroundColor: C('--brand') },
  ] }, options: { ...base, indexAxis: 'y', plugins: { legend: { display: false }, tooltip: base.plugins.tooltip },
    scales: { x: { ticks: tick, grid: { color: C('--line') } }, y: { grid: { display: false } } } } }));
}

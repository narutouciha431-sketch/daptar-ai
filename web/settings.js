// Настройки магазина, подключение владельца к боту, отчёт за сегодня

async function renderSettings() {
  view.innerHTML = `
    <div class="page-head"><div><h1>Настройки</h1><p class="hint">Данные магазина, ссылка Kaspi для оплаты долгов, ставка налога вашего района и подключение владельца к Telegram-боту.</p></div></div>
    <div class="settings">
      <form class="card settings-form" id="profileForm">
        <h2>Профиль</h2>
        <label>ФИО<input name="full_name" required maxlength="100" autocomplete="name"></label>
        <label>Email (логин)<input name="email" readonly></label>
        <label>Телефон<input name="phone" type="tel" required autocomplete="tel"></label>
        <button type="submit">Сохранить профиль</button>
      </form>
      <hr class="sep" aria-hidden="true">
      <form class="card settings-form" id="shopForm">
        <h2>Магазин</h2>
        <label>Название<input name="name" required maxlength="80"></label>
        <label>Район / город<input name="district" required maxlength="80"></label>
        <hr class="sep"><h2>Kaspi для долгов</h2>
        <label>Ссылка или номер Kaspi для оплаты долга<input name="kaspi" maxlength="300" placeholder="ссылка Kaspi Pay или номер телефона…"></label>
        <hr class="sep"><h2>Оплата сервиса Дәптер</h2>
        <p class="sub">Сюда приходит оплата за сервис. Эти данные попадут в счёт, который бот присылает в Telegram из «Кабинета».</p>
        <label>Номер Kaspi для оплаты<input name="service_kaspi" type="tel" maxlength="40" autocomplete="off" placeholder="+7 7XX XXX XX XX…"></label>
        <label>Имя получателя (как показывает Kaspi)<input name="service_name" maxlength="80" autocomplete="off" placeholder="Например, Айгүл С.…"></label>
        <label>Ставка, % (от 0,5 до 2)<input name="service_rate" type="number" min="0.5" max="2" step="0.1" required></label>
        <p class="sub">Считается от реально полученных денег за месяц: оплаченные продажи + возвращённые долги.</p>
        <label>Язык отчётов<select name="language"><option value="kk">Қазақша</option><option value="ru">Русский</option></select></label>
        <label>Время вечернего отчёта<input name="report_time" type="time" required></label>
        <button type="submit">Сохранить</button>
      </form>
      <hr class="sep" aria-hidden="true">
      <div class="card owner">
        <h2>Telegram-бот</h2>
        <div id="botState"></div>
      </div>
      <hr class="sep" aria-hidden="true">
      <div class="card report">
        <div class="row-between"><h2>Отчёт за сегодня</h2><button class="ghost small" id="sendReport">Отправить мне в Telegram</button></div>
        <pre id="reportText" class="report-text">…</pre>
      </div>
      <hr class="sep" aria-hidden="true">
      <div class="card owner">
        <h2>Демо-история для показа</h2>
        <p class="sub">Заполняет 30 дней правдоподобных продаж, долгов и возвратов, чтобы на защите были видны графики кабинета. Долги и возвраты записываются на отдельных демо-покупателей («Демо: …»), настоящие покупатели и их балансы не меняются. Всё демо удаляется одной кнопкой.</p>
        <div class="debt-actions"><button type="button" id="demoSeed">Заполнить демо-историей</button><button type="button" class="danger" id="demoClear">Удалить демо-историю</button></div>
        <div id="demoResetBox" hidden><hr class="sep"><p class="sub">Общий демо-магазин могли изменить другие посетители. Кнопка вернёт прайс, покупателей, историю и долги к исходному виду.</p><button type="button" class="danger" id="demoReset">Сбросить демо-магазин к исходному виду</button></div>
      </div>
      <hr class="sep" aria-hidden="true">
      <form class="card danger-zone" id="deleteForm">
        <h2>Удалить аккаунт</h2>
        <p class="sub">Удалятся аккаунт, магазин, товары с фото, покупатели, продажи, долги, оплаты и напоминания. Восстановить их будет нельзя.</p>
        <label>Пароль для подтверждения<input name="password" type="password" autocomplete="current-password" required></label>
        <button type="submit" class="danger">Удалить аккаунт и все данные</button>
      </form>
    </div>`;

  const $ = id => document.getElementById(id) || document.createElement('div'); // экран мог смениться, пока шёл запрос
  const f = $('shopForm').elements;

  let shopTax = 0.04;
  async function load() {
    const s = await api('/api/shop');
    f.name.value = s.name; f.district.value = s.district;
    f.kaspi.value = s.kaspi_link; shopTax = s.tax_rate;
    f.service_kaspi.value = s.service_kaspi || ''; f.service_name.value = s.service_name || ''; f.service_rate.value = +((s.service_rate || 0.01) * 100).toFixed(2); f.language.value = s.language; f.report_time.value = s.report_time;
    $('botState').innerHTML = !s.bot_enabled
      ? `<p class="notice-line">Бот выключен: впишите токен от @BotFather в файл <code>.env</code> (строка <code>BOT_TOKEN=</code>) и перезапустите сервер.</p>`
      : s.is_demo
        ? `<p class="notice-line">Демо-магазин общий для всех, поэтому Telegram владельца к нему не подключается. Зарегистрируйте свой магазин — там можно.</p>`
      : s.owner_linked
        ? `<p><span class="pill ok">подключён${s.owner_username ? ': @' + esc(s.owner_username) : ''}</span></p>
           <p class="sub">Уведомления о подтверждениях, оплатах и отчёт в ${esc(s.report_time)} приходят только в этот Telegram.</p>
           <button type="button" class="ghost small" id="ownerUnlink">Отвязать Telegram</button>`
        : `<p>Отсканируйте QR телефоном владельца — бот @${esc(s.bot_username)} будет присылать уведомления и вечерний отчёт.</p>
           <div class="qr-box"><img src="/api/shop/owner-qr.svg?${Date.now()}" alt="QR для подключения владельца" width="200" height="200"></div>
           <p class="sub">Или откройте ссылку: <a href="${esc(s.owner_link)}" target="_blank" rel="noopener">${esc(s.owner_link)}</a></p>`;
    $('demoResetBox').hidden = !s.is_demo;
    $('deleteForm').hidden = s.is_demo;
    const un = document.getElementById('ownerUnlink');
    if (un) un.onclick = async () => { await api('/api/shop/owner-unlink', { method: 'POST' }); toast('Telegram отвязан'); load(); };
    const r = await api('/api/report');
    $('reportText').textContent = r.text;
  }

  const pf = $('profileForm').elements;
  api('/api/auth/me').then(u => { pf.full_name.value = u.full_name; pf.email.value = u.email; pf.phone.value = u.phone; });
  $('profileForm').onsubmit = async e => {
    e.preventDefault();
    try {
      const u = await api('/api/auth/profile', { method: 'PUT', body: { full_name: pf.full_name.value, phone: pf.phone.value } });
      pf.phone.value = u.phone;
      document.getElementById('userName').textContent = u.full_name + (u.is_demo ? ' · демо' : '');
      toast('Профиль сохранён');
    } catch (err) { toast(err.message, true); }
  };

  $('shopForm').onsubmit = async e => {
    e.preventDefault();
    try {
      await api('/api/shop', { method: 'PUT', body: {
        name: f.name.value, district: f.district.value, tax_rate: shopTax,
        service_kaspi: f.service_kaspi.value, service_name: f.service_name.value, service_rate: Number(f.service_rate.value) / 100,
        kaspi_link: f.kaspi.value, language: f.language.value, report_time: f.report_time.value,
      }});
      toast('Сохранено'); load(); window.dispatchEvent(new Event('shop-changed'));
    } catch (err) { toast(err.message, true); }
  };
  $('sendReport').onclick = async () => {
    try { await api('/api/report/send', { method: 'POST' }); toast('Отчёт отправлен в Telegram'); }
    catch (err) { toast(err.message, true); }
  };
  $('deleteForm').onsubmit = async e => {
    e.preventDefault();
    if (!confirm('Удалить аккаунт и ВСЕ данные магазина навсегда?')) return;
    try {
      await api('/api/auth/delete', { method: 'POST', body: { password: e.target.elements.password.value } });
      location.href = '/';
    } catch (err) { toast(err.message, true); }
  };
  $('demoReset').onclick = async e => {
    if (!confirm('Вернуть демо-магазин к исходному виду? Всё, что в нём добавили, удалится.')) return;
    e.currentTarget.disabled = true;
    try { await api('/api/demo/reset', { method: 'POST' }); toast('Демо-магазин сброшен'); load(); }
    catch (err) { toast(err.message, true); }
    const b = document.getElementById('demoReset'); if (b) b.disabled = false;
  };
  $('demoSeed').onclick = async () => {
    try { const r = await api('/api/demo/seed', { method: 'POST' }); toast(`Добавлено демо-продаж: ${r.created}`); load(); }
    catch (err) { toast(err.message, true); }
  };
  $('demoClear').onclick = async e => {
    const b = e.currentTarget;
    if (b.dataset.confirm !== '1') { b.dataset.confirm = '1'; b.textContent = 'Точно удалить демо?'; setTimeout(() => { b.dataset.confirm = ''; b.textContent = 'Удалить демо-историю'; }, 3000); return; }
    try { const r = await api('/api/demo/clear', { method: 'POST' }); toast(`Удалено демо-продаж: ${r.deleted}`); b.dataset.confirm = ''; b.textContent = 'Удалить демо-историю'; load(); }
    catch (err) { toast(err.message, true); }
  };
  listeners.add(msg => { if (['owner_linked', 'shop_changed', 'sale_created', 'payment_created'].includes(msg.type)) load(); });
  await load();
}

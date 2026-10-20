let view=0;
const number=value=>Number(value||0).toLocaleString('ru-RU');
const total=row=>Number(row.inputTokens)+Number(row.outputTokens);
const dayLabel=date=>new Date(date+'T12:00:00Z').toLocaleDateString('ru-RU',{day:'numeric',month:'short',timeZone:'UTC'});

export async function renderUsage(c,period=30){
 const version=++view,owner=c.user()?.id;
 c.breadcrumb('Расход токенов');
 c.app.setAttribute('aria-busy','true');
 try{
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  const data=await(await c.request('/usage?days='+period+'&timezone='+encodeURIComponent(timezone))).json();
  if(version!==view||location.hash!=='#usage'||c.user()?.id!==owner)return;
  const sum=data.days.reduce((s,d)=>({inputTokens:s.inputTokens+Number(d.inputTokens),outputTokens:s.outputTokens+Number(d.outputTokens),calls:s.calls+Number(d.calls),unknown:s.unknown+Number(d.unknownCalls),failed:s.failed+Number(d.failedCalls)}),{inputTokens:0,outputTokens:0,calls:0,unknown:0,failed:0});
  const max=Math.max(1,...data.days.map(total));
  c.app.innerHTML=`<div class="page-heading"><div><span class="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span><h1>Расход токенов</h1><p>Ваши обращения к ИИ — по дням, во всех программах.</p></div><a class="button-link" href="#settings">← Мой профиль</a></div>
   <div class="usage-summary"><section class="panel"><span class="muted">За выбранный период</span><strong>${number(total(sum))}</strong><span>токенов</span></section><section class="panel"><span class="muted">Входные</span><strong>${number(sum.inputTokens)}</strong><span>запросы и контекст</span></section><section class="panel"><span class="muted">Выходные</span><strong>${number(sum.outputTokens)}</strong><span>ответы модели</span></section><section class="panel"><span class="muted">Обращения к модели</span><strong>${number(sum.calls)}</strong><span>ответы из кеша не включены</span></section></div>
   <section class="panel usage-panel"><div class="section-heading"><div><h2>Активность по дням</h2><p class="helper">Часовой пояс: ${c.esc(data.timezone)}</p></div><label class="usage-period">Период<select id="usage-period" aria-label="Период статистики">${[7,30,90].map(n=>`<option value="${n}" ${period===n?'selected':''}>${n} дней</option>`).join('')}</select></label></div>
   <div class="usage-legend"><span><i class="usage-input"></i>Входные</span><span><i class="usage-output"></i>Выходные</span></div>
   ${sum.calls===0?'<p class="notice">За этот период обращений к модели не было. После генерации здесь появится ваш расход.</p>':''}
   <div class="usage-chart"><div class="usage-axis"><span>${number(max===1&&!total(sum)?0:max)}</span><span>0</span></div><div class="usage-scroll" tabindex="0" aria-label="Гистограмма расхода токенов. На узком экране доступна горизонтальная прокрутка."><div class="usage-bars" role="group" aria-label="Токены по дням">${data.days.map((d,i)=>`<div class="usage-day"><div class="usage-column" tabindex="0" role="img" aria-label="${c.esc(dayLabel(d.date))}: ${number(d.inputTokens)} входных, ${number(d.outputTokens)} выходных токенов, ${number(d.calls)} обращений${d.unknownCalls?', есть обращения без данных о расходе':''}"><span class="usage-tooltip">${c.esc(dayLabel(d.date))}<br>Входные: ${number(d.inputTokens)}<br>Выходные: ${number(d.outputTokens)}<br>Обращения: ${number(d.calls)}</span><div class="usage-stack" data-input="${Number(d.inputTokens)/max*100}" data-output="${Number(d.outputTokens)/max*100}"><span class="usage-output"></span><span class="usage-input"></span></div></div><span class="usage-date">${(i%Math.max(1,Math.round(period/7))===0&&(period<=7||i<data.days.length-2))||i===data.days.length-1?c.esc(dayLabel(d.date)):''}</span></div>`).join('')}</div></div></div>
   <p class="helper">Включены токены повторных и неудачных ответов, если поставщик сообщил расход. ${sum.failed?`Ответов с ошибкой: ${number(sum.failed)}. `:''}${sum.unknown?`Для ${number(sum.unknown)} обращений поставщик не передал полный расход; их токены не оценивались приблизительно.`:''}</p>
   <details class="usage-table"><summary>Посмотреть точные значения по дням</summary><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Входные</th><th>Выходные</th><th>Всего токенов</th><th>Обращения</th></tr></thead><tbody>${data.days.map(d=>`<tr><th scope="row">${c.esc(d.date)}</th><td>${number(d.inputTokens)}</td><td>${number(d.outputTokens)}</td><td>${number(total(d))}</td><td>${number(d.calls)}</td></tr>`).join('')}</tbody></table></div></details></section>
   <section class="panel"><h2>Всего учтено в аккаунте</h2><p class="usage-lifetime">${number(total(data.allTime))} <span>токенов · ${number(data.allTime.calls)} обращений</span></p>${total(data.legacy)||data.legacy.calls?`<p class="helper">Из них ${number(total(data.legacy))} токенов учтено до запуска дневной статистики. У этих данных нет достоверных дат, поэтому они не включены в гистограмму.</p>`:''}<p class="helper">Общий бюджет программы отключён. Платформа не задаёт лимит длины ответа. Ограничения контекста, ответа и квоты устанавливает поставщик. Счётчик показывает токены, а не стоимость подписки или счёт к оплате.</p></section>`;
  const chart=c.app.querySelector('.usage-bars');chart.style.setProperty('--days',data.days.length);
  c.app.querySelectorAll('.usage-stack').forEach(el=>{el.querySelector('.usage-input').style.height=el.dataset.input+'%';el.querySelector('.usage-output').style.height=el.dataset.output+'%'});
  c.app.querySelector('#usage-period').onchange=async e=>{await renderUsage(c,Number(e.target.value));c.app.querySelector('#usage-period')?.focus()};
 }finally{if(version===view)c.app.removeAttribute('aria-busy')}
}

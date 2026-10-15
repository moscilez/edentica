export function programEditor(s,mode,esc){
 const field=(label,key,value,extra='')=>`<label>${label}<textarea data-edit-field="${esc(key)}" ${extra}>${esc(value)}</textarea></label>`;
 let body='';
 if(mode==='overview')body=field('Название','title',s.title)+field('Цель программы','goal',s.goal)+field('Аудитория','audience',s.audience)+field('Входной уровень','entryLevel',s.entryLevel)+field('Форма обучения','format',s.format)+field('Итоговая аттестация','assessment',s.assessment);
 if(mode==='competencies')body=s.competencies.map(c=>`<h3>${esc(c.id)}</h3>${['title','knowledge','abilities','skills'].map((k,i)=>field(['Результат обучения','Знать','Уметь','Владеть'][i],k,c[k],`data-competency="${esc(c.id)}"`)).join('')}`).join('');
 if(mode==='plan')body=`<div class="table-wrap"><table><thead><tr><th>Тема</th><th>Лекции</th><th>Практика</th><th>Лаб.</th><th>СРС</th></tr></thead><tbody>${s.modules.flatMap(m=>m.topics.map(t=>`<tr><td>${esc(t.id)}<input class="topic-title" data-edit-topic="${esc(t.id)}" value="${esc(t.title)}" aria-label="Название темы ${esc(t.id)}"></td>${['lecture','practice','lab','self'].map(k=>`<td><input type="number" min="0" step="1" data-edit-hours="${esc(t.id)}" data-kind="${k}" value="${t.hours[k]}" aria-label="Часы ${esc(t.id)} ${k}"></td>`).join('')}</tr>`)).join('')}</tbody></table></div><p class="helper">При изменении часов темы также исправьте календарь ниже. Общий объём программы должен остаться ${s.totalHours} часов.</p><div class="table-wrap"><table><thead><tr><th>Занятие</th><th>Темы</th><th>Неделя</th><th>Часы</th></tr></thead><tbody>${s.calendar.sessions.map((x,i)=>`<tr><td>${i+1}</td><td>${esc(x.topicIds.join(', '))}</td><td><input type="number" min="1" data-edit-session="${i}" data-kind="week" value="${x.week}" aria-label="Неделя занятия ${i+1}"></td><td><input type="number" min="1" data-edit-session="${i}" data-kind="hours" value="${x.hours}" aria-label="Часы занятия ${i+1}"></td></tr>`).join('')}</tbody></table></div>`;
 return `<details><summary>Редактировать ${mode==='plan'?'темы и часы':mode==='competencies'?'компетенции':'цель и требования'}</summary><form id="simple-editor" class="form-panel simple-editor">${body}<p class="helper">Изменение снимает согласование. Затронутые материалы будут подготовлены заново после утверждения. Предыдущая версия сохранится.</p><button class="primary" type="submit">Проверить и сохранить изменения</button></form></details>`;
}
export function readProgramEditor(form,skeleton){
 const s=structuredClone(skeleton);
 for(const el of form.querySelectorAll('[data-edit-field]')){if(el.dataset.competency)s.competencies.find(c=>c.id===el.dataset.competency)[el.dataset.editField]=el.value.trim();else s[el.dataset.editField]=el.value.trim()}
 const topics=s.modules.flatMap(m=>m.topics);
 for(const el of form.querySelectorAll('[data-edit-topic]'))topics.find(t=>t.id===el.dataset.editTopic).title=el.value.trim();
 for(const el of form.querySelectorAll('[data-edit-hours]'))topics.find(t=>t.id===el.dataset.editHours).hours[el.dataset.kind]=el.value===''?-1:Number(el.value);
 for(const el of form.querySelectorAll('[data-edit-session]'))s.calendar.sessions[Number(el.dataset.editSession)][el.dataset.kind]=el.value===''?-1:Number(el.value);
 for(const m of s.modules){for(const t of m.topics)t.totalHours=Object.values(t.hours).reduce((n,x)=>n+x,0);m.totalHours=m.topics.reduce((n,t)=>n+t.totalHours,0)}
 return s;
}

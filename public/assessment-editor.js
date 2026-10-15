const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let sequence = 0;

function questionMarkup(question) {
  const group = `answer-${++sequence}`;
  return `<fieldset class="question question-editor" data-question>
    <legend>Вопрос</legend>
    <label>Текст вопроса<input data-question-text value="${escape(question.text)}" maxlength="1000" required></label>
    <p class="subtle">Отметьте один правильный ответ кружком слева.</p>
    <div data-options>${question.options.map((option, index) => optionMarkup(option, group, question.answer === index)).join('')}</div>
    <div class="row actions"><button type="button" class="secondary" data-add-option>+ Вариант ответа</button><button type="button" class="secondary" data-delete-question>Удалить вопрос</button></div>
  </fieldset>`;
}

function optionMarkup(text, group, checked = false) {
  return `<div class="answer-option" data-option>
    <input type="radio" name="${group}" aria-label="Правильный ответ" ${checked ? 'checked' : ''} required>
    <input data-option-text aria-label="Текст варианта ответа" value="${escape(text)}" maxlength="500" required>
    <button type="button" class="secondary" data-delete-option aria-label="Удалить вариант ответа">×</button>
  </div>`;
}

export function assessmentEditor(questions) {
  return `<div data-assessment><h3>Проверка знаний</h3><p class="subtle">От 1 до 30 вопросов. В каждом вопросе — от 2 до 6 вариантов и один правильный ответ.</p><div data-questions>${questions.map(questionMarkup).join('')}</div><button type="button" class="secondary" data-add-question>+ Добавить вопрос</button><p data-assessment-status role="status" aria-live="polite"></p></div>`;
}

export function readQuestions(module) {
  const questions = [...module.querySelectorAll('[data-question]')].map(question => {
    const options = [...question.querySelectorAll('[data-option]')];
    const answer = options.findIndex(option => option.querySelector('input[type=radio]').checked);
    if (answer < 0) throw Error('Выберите правильный ответ для каждого вопроса');
    return {text: question.querySelector('[data-question-text]').value.trim(), options: options.map(option => option.querySelector('[data-option-text]').value.trim()), answer};
  });
  if (!questions.length) throw Error('Добавьте хотя бы один вопрос в каждый модуль');
  if (questions.some(q => !q.text || q.options.some(option => !option))) throw Error('Заполните вопросы и все варианты ответа');
  return questions;
}

document.addEventListener('click', event => {
  const button = event.target.closest('button');
  const editor = button?.closest('[data-assessment]');
  if (!editor) return;
  const status = editor.querySelector('[data-assessment-status]');
  status.textContent = '';
  const question = button.closest('[data-question]');
  if (button.hasAttribute('data-add-question')) {
    const questions = editor.querySelector('[data-questions]');
    if (questions.children.length >= 30) { status.textContent = 'В модуле допускается не более 30 вопросов.'; return; }
    questions.insertAdjacentHTML('beforeend', questionMarkup({text:'', options:['',''], answer:0}));
    questions.lastElementChild.querySelector('[data-question-text]').focus();
  } else if (button.hasAttribute('data-delete-question')) {
    if (editor.querySelectorAll('[data-question]').length <= 1) { status.textContent = 'В модуле должен остаться хотя бы один вопрос.'; return; }
    question.remove();
    editor.querySelector('[data-add-question]').focus();
  } else if (button.hasAttribute('data-add-option')) {
    const options = question.querySelector('[data-options]');
    if (options.children.length >= 6) { status.textContent = 'В вопросе допускается не более 6 вариантов.'; return; }
    options.insertAdjacentHTML('beforeend', optionMarkup('', options.querySelector('input[type=radio]').name));
    options.lastElementChild.querySelector('[data-option-text]').focus();
  } else if (button.hasAttribute('data-delete-option')) {
    const options = question.querySelector('[data-options]');
    if (options.children.length <= 2) { status.textContent = 'В вопросе должно остаться хотя бы два варианта.'; return; }
    const option = button.closest('[data-option]');
    const wasAnswer = option.querySelector('input[type=radio]').checked;
    option.remove();
    if (wasAnswer) status.textContent = 'Правильный вариант удалён. Выберите новый правильный ответ.';
    question.querySelector('[data-add-option]').focus();
  }
});

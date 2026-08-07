const API = "/api";
const state = { view: "home", health: null, documents: [], currentDocument: null, result: null, selectedFile: null, pollTimer: null, resultTab: "summary" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const root = () => $("#viewRoot");
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const fmt = (value) => value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value));
const fmtBytes = (bytes = 0) => bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
const isAiMode = (mode) => ["ai_map_reduce","openrouter_map_reduce","ai_structured_verified","ai_financial_model_v21"].includes(mode);
const typeLabel = (type) => ({annual_report:"Годовой отчет",ifrs_financial_statements:"Отчетность по МСФО",ras_financial_statements:"Отчетность по РСБУ",investor_presentation:"Презентация инвесторам",audit_report:"Аудиторское заключение",corporate_document:"Корпоративный документ",spreadsheet_financial_data:"Финансовая таблица"}[type] || type || "Определяется");

function toast(message, timeout = 3500) {
  const el = $("#toast"); el.textContent = message; el.hidden = false;
  clearTimeout(el._timer); el._timer = setTimeout(() => el.hidden = true, timeout);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { const body = await response.json(); detail = body.detail || body.message || detail; } catch {}
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.text();
}

async function init() {
  bindShell();
  try {
    state.health = await api("/health");
    $("#apiDot").className = "status-dot ok";
    $("#apiStatus").textContent = "API работает";
    $("#aiBadge").textContent = state.health.ai_configured ? `AI: ${state.health.ai_model || "модель подключена"}` : "AI: fallback-режим";
  } catch (error) {
    $("#apiDot").className = "status-dot bad";
    $("#apiStatus").textContent = "API недоступен";
    $("#aiBadge").textContent = "AI: API недоступен";
  }
  await loadDocuments();
  showView("home");
}

function bindShell() {
  $$(".nav-item").forEach(btn => btn.addEventListener("click", () => { showView(btn.dataset.view); $("#sidebar").classList.remove("open"); }));
  $("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
}

const viewMeta = {
  home: ["Обзор", "ВКР-стартап Финансового университета"], upload: ["Новый анализ", "PDF, Excel, CSV и сканированные документы"],
  history: ["История", "Все обработанные документы"], methodology: ["Методология", "Как устроено извлечение и анализ"], settings: ["Настройки", "Состояние интеграций и переменные окружения"]
};

function showView(view) {
  state.view = view;
  $$(".nav-item").forEach(btn => btn.classList.toggle("active", btn.dataset.view === view));
  const [title, subtitle] = viewMeta[view]; $("#topTitle").textContent = title; $("#topSubtitle").textContent = subtitle;
  if (view === "home") renderHome();
  if (view === "upload") renderUpload();
  if (view === "history") renderHistory();
  if (view === "methodology") renderMethodology();
  if (view === "settings") renderSettings();
}

async function loadDocuments() {
  try { state.documents = await api("/documents?limit=100"); } catch { state.documents = []; }
}

function renderHome() {
  const completed = state.documents.filter(d => d.status === "completed").length;
  const pdfCount = state.documents.filter(d => d.original_name?.toLowerCase().endsWith(".pdf")).length;
  root().innerHTML = `<section class="page">
    <div class="hero"><div class="hero-content"><div class="eyebrow">ВКР-СТАРТАП ФИНАНСОВОГО УНИВЕРСИТЕТА</div>
      <h1>Интеллектуальный анализ финансовой отчетности</h1>
      <p>FinSight AI читает годовые отчеты на сотни страниц, отчетность по МСФО и РСБУ, Excel и CSV. Система извлекает текст и таблицы, распознает сканированные формы РСБУ, сохраняет ссылки на страницы, рассчитывает коэффициенты программным кодом и формирует проверяемое аналитическое резюме.</p>
      <div class="university-values"><span>КОМПЕТЕНТНОСТЬ</span><span>ОТВЕТСТВЕННОСТЬ</span><span>ПРЕСТИЖ</span></div>
      <div class="actions"><button class="primary" id="homeUpload">Загрузить документ</button><button class="secondary" id="homeDemo">Запустить демо РСБУ ЛУКОЙЛ</button></div>
    </div><div class="hero-stats"><div class="hero-stat"><strong>${state.documents.length}</strong><small>документов в истории</small></div><div class="hero-stat"><strong>${completed}</strong><small>анализов завершено</small></div><div class="hero-stat"><strong>${pdfCount}</strong><small>PDF-документов</small></div><div class="hero-stat"><strong>24+</strong><small>финансовых коэффициентов</small></div></div></div>
    <div class="section-title"><div><h2>Что анализирует система</h2><p>Два режима: коэффициентный анализ отчетности и комплексный анализ годового отчета.</p></div></div>
    <div class="feature-grid">
      ${feature("PDF", "Годовые отчеты и сканы", "Текстовый слой, координатные таблицы, OCR для страниц без текста, источники по номерам страниц.")}
      ${feature("₽", "Финансовая отчетность", "Баланс, ОФР и ОДДС: ликвидность, рентабельность, долговая нагрузка, маржинальность и денежные потоки.")}
      ${feature("↗", "Операционные KPI", "Добыча, производство, продажи, мощности, ESG, персонал и другие отраслевые показатели за несколько лет.")}
      ${feature("AI", "Готовое AI-резюме", "При подключенном API итоговый анализ формируется автоматически до открытия результата. Модель получает только проверенные показатели и не считает коэффициенты.")}
    </div>
    <div class="section-title"><div><h2>Последние документы</h2></div><button class="secondary" id="allHistory">Открыть историю</button></div>
    ${historyMarkup(state.documents.slice(0,5), true)}
  </section>`;
  $("#homeUpload").onclick = () => showView("upload");
  $("#homeDemo").onclick = startDemo;
  $("#allHistory").onclick = () => showView("history");
  bindHistoryActions();
}
function feature(icon, title, text) { return `<article class="card feature-card"><div class="feature-icon">${icon}</div><h3>${title}</h3><p>${text}</p></article>`; }

function renderUpload() {
  state.selectedFile = null;
  root().innerHTML = `<section class="page"><div class="page-header"><div><h1>Новый анализ</h1><p>Загрузите один документ. Для полного коэффициентного анализа компании отдельно загрузите баланс, ОФР/ОДДС или консолидированную отчетность.</p></div><button class="secondary" id="demoButton">Демо: отчетность РСБУ ЛУКОЙЛ</button></div>
    <div class="upload-grid"><div class="panel"><div class="drop-zone" id="dropZone"><div><div class="drop-icon">⇧</div><h2>Перетащите документ сюда</h2><p>PDF до ${state.health?.max_upload_mb || 80} МБ, XLSX, XLS или CSV. PDF может содержать текст, таблицы, инфографику и сканированные страницы.</p><button class="primary" id="chooseFile">Выбрать файл</button><input id="fileInput" type="file" accept=".pdf,.xlsx,.xls,.csv" hidden /></div></div><div id="fileList" class="file-list"></div></div>
      <aside class="panel"><div class="field"><label>Название компании (необязательно)</label><input id="companyInput" placeholder="Например, ПАО «Компания»" /><small>Если не указано, система попытается определить компанию из документа.</small></div>
        <div class="capability-list">${cap("1","Определение типа","Годовой отчет, МСФО, РСБУ, аудит, презентация или таблица.")}${cap("2","Извлечение","Текст, заголовки, таблицы, годы, единицы измерения и номера страниц.")}${cap("3","Нормализация","Разделение финансовых и операционных показателей, защита от ошибочных сопоставлений.")}${cap("4","Аналитика","Коэффициенты, динамика, риск-флаги, стратегия, ESG и ограничения данных.")}</div>
        <button class="primary hidden" id="startUpload" style="width:100%;margin-top:20px">Начать анализ</button></aside></div></section>`;
  const zone = $("#dropZone"), input = $("#fileInput");
  $("#chooseFile").onclick = () => input.click(); input.onchange = () => selectFile(input.files[0]);
  ["dragenter","dragover"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave","drop"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", e => selectFile(e.dataTransfer.files[0]));
  $("#startUpload").onclick = uploadSelected; $("#demoButton").onclick = startDemo;
}
function cap(n,title,text){return `<div class="capability"><b>${n}</b><div><strong>${title}</strong><small>${text}</small></div></div>`;}
function selectFile(file) {
  if (!file) return; const ext = file.name.split(".").pop().toLowerCase();
  if (!["pdf","xlsx","xls","csv"].includes(ext)) return toast("Поддерживаются PDF, XLSX, XLS и CSV.");
  state.selectedFile = file;
  $("#fileList").innerHTML = `<div class="file-chip"><span>▤</span><b>${escapeHtml(file.name)}</b><span>${fmtBytes(file.size)}</span><button class="danger-btn" id="removeFile">Убрать</button></div>`;
  $("#startUpload").classList.remove("hidden");
  $("#removeFile").onclick = () => { state.selectedFile = null; $("#fileList").innerHTML=""; $("#startUpload").classList.add("hidden"); };
}
async function uploadSelected() {
  if (!state.selectedFile) return toast("Сначала выберите файл.");
  const form = new FormData(); form.append("file", state.selectedFile); const company = $("#companyInput").value.trim(); if (company) form.append("company", company);
  renderProcessing({ original_name: state.selectedFile.name, progress: 0, stage: "Загрузка файла" });
  try { const doc = await api("/documents/upload", { method:"POST", body:form }); state.currentDocument = doc; pollDocument(doc.id); } catch (e) { renderError(e.message); }
}
async function startDemo() {
  showView("upload"); renderProcessing({original_name:"БФО ПАО «ЛУКОЙЛ» по РСБУ за 2025 год",progress:0,stage:"Подготовка проверенного демо РСБУ"});
  try { const doc = await api("/documents/demo", {method:"POST"}); state.currentDocument = doc; pollDocument(doc.id); } catch(e) { renderError(e.message); }
}
function renderProcessing(doc) {
  root().innerHTML = `<section class="page"><div class="panel processing"><div class="processing-head"><div class="spinner"></div><div><h2>Анализ документа</h2><p>${escapeHtml(doc.original_name || "Документ")}</p></div></div><div class="progress"><div id="progressBar" style="width:${doc.progress||0}%"></div></div><div class="progress-meta"><span id="stageText">${escapeHtml(doc.stage||"Подготовка")}</span><b id="progressValue">${doc.progress||0}%</b></div><div class="stage-list"><div class="stage">1. Извлечение текста и OCR</div><div class="stage">2. Распознавание таблиц</div><div class="stage">3. Нормализация показателей</div><div class="stage">4. Финансовые расчеты</div><div class="stage">5. Риски и стратегия</div><div class="stage">6. Проверенное AI-заключение</div></div><div class="alert info">Большой PDF на 100–200 страниц может обрабатываться несколько минут. Не закрывайте вкладку: сервер продолжит работу даже при переходе в историю.</div></div></section>`;
}
async function pollDocument(id) {
  clearTimeout(state.pollTimer);
  try {
    const doc = await api(`/documents/${id}/status`); state.currentDocument = doc;
    if ($("#progressBar")) { $("#progressBar").style.width = `${doc.progress}%`; $("#progressValue").textContent = `${doc.progress}%`; $("#stageText").textContent = doc.stage; }
    if (doc.status === "completed") { await loadDocuments(); await openResult(id); return; }
    if (doc.status === "error") { renderError(doc.error || "Ошибка анализа"); await loadDocuments(); return; }
    state.pollTimer = setTimeout(() => pollDocument(id), 1300);
  } catch (e) { renderError(e.message); }
}
function renderError(message) { root().innerHTML = `<section class="page"><div class="panel empty"><div><b>Анализ не завершен</b><span>${escapeHtml(message)}</span><div class="actions"><button class="primary" id="backUpload">Загрузить другой файл</button></div></div></div></section>`; $("#backUpload").onclick=()=>showView("upload"); }

async function openResult(id) {
  try { state.result = await api(`/documents/${id}/result`); state.currentDocument = state.documents.find(d=>d.id===id) || await api(`/documents/${id}`); state.resultTab="summary"; renderResult(); } catch(e) { toast(e.message); }
}
function pageLink(page) { return `<a class="source-link" href="${API}/documents/${state.result.id}/file#page=${page}" target="_blank">стр. ${page}</a>`; }
function sourceLinks(pages=[]) { return pages.length ? pages.slice(0,8).map(pageLink).join(" ") : "—"; }
function renderResult() {
  const r=state.result,m=r.metadata,a=r.analysis||{}, availableRatios=r.ratios.filter(x=>x.status!=="na");
  root().innerHTML = `<section class="page"><div class="result-header"><div class="doc-icon">${m.document_type==="ras_financial_statements"?"РСБУ":m.document_type==="annual_report"?"AR":"DOC"}</div><div><h1>${escapeHtml(m.company||m.filename)}</h1><div class="meta-row"><span class="pill">${typeLabel(m.document_type)}</span>${m.reporting_year?`<span class="pill">${m.reporting_year} год</span>`:""}<span class="pill">${m.page_count?`${m.page_count} стр.`:`${m.sheet_count||0} листов`}</span><span class="pill">${r.tables.length} таблиц</span><span class="pill">${r.operational_metrics.length} KPI</span>${m.accounting_standard?`<span class="pill">${escapeHtml(m.accounting_standard)}</span>`:""}${m.audit_opinion?`<span class="pill">${escapeHtml(m.audit_opinion)}</span>`:""}${m.matched_verified_profile?`<span class="pill">Сверено с проверенным профилем</span>`:""}</div></div><div class="actions"><button class="secondary" id="csvExport">CSV</button><button class="secondary" id="jsonExport">JSON</button><button class="secondary" id="printReport">PDF / печать</button></div></div>
    ${r.limitations.map(x=>`<div class="alert warn">${escapeHtml(x)}</div>`).join("")}
    <div class="score-grid"><div class="panel score-panel"><div class="score-ring" style="--score:${r.score.value}"><div><strong>${r.score.value}</strong><small>из 100</small></div></div><p>${escapeHtml(r.score.explanation)}</p><span class="pill">${r.score.mode==="financial"?"Финансовая оценка":"Пригодность документа"}</span></div>
      <div class="panel summary-panel"><h2>${isAiMode(a.mode)?`AI-резюме · ${escapeHtml(a.provider||state.health?.ai_model||"подключенная модель")}`:a.mode==="verified_rsbu_demo_fallback"?"Проверенное демо-резюме РСБУ":"Проверенное автоматическое резюме"}</h2><div class="summary-text">${escapeHtml(a.executive_summary||"Резюме формируется")}</div><div class="kpi-grid"><div class="kpi"><small>Финансовые строки</small><strong>${Object.keys(r.financial_metrics).length}</strong><span>нормализовано</span></div><div class="kpi"><small>Коэффициенты</small><strong>${availableRatios.length}</strong><span>доступно для расчета</span></div><div class="kpi"><small>Операционные KPI</small><strong>${r.operational_metrics.length}</strong><span>с источниками</span></div><div class="kpi"><small>Риск-флаги</small><strong>${r.risk_flags.length}</strong><span>требуют проверки</span></div></div></div></div>
    <div class="tabs">${tabButton("summary","Резюме")}${tabButton("financial","Финансы")}${tabButton("operational","Операционные KPI")}${tabButton("tables","Таблицы")}${tabButton("narrative","Риски и стратегия")}${tabButton("sources","Источники")}</div>
    <div id="tabContent"></div></section>`;
  $$(".tab").forEach(btn=>btn.onclick=()=>{state.resultTab=btn.dataset.tab; $$(".tab").forEach(b=>b.classList.toggle("active",b===btn)); renderTab();});
  $("#csvExport").onclick=()=>location.href=`${API}/documents/${r.id}/export.csv`; $("#jsonExport").onclick=()=>location.href=`${API}/documents/${r.id}/export.json`; $("#printReport").onclick=()=>window.print();
  renderTab();
}
function tabButton(id,label){return `<button class="tab ${state.resultTab===id?"active":""}" data-tab="${id}">${label}</button>`;}
function renderTab(){ const r=state.result, el=$("#tabContent"); if(state.resultTab==="summary")el.innerHTML=summaryTab(r); if(state.resultTab==="financial")el.innerHTML=financialTab(r); if(state.resultTab==="operational")el.innerHTML=operationalTab(r); if(state.resultTab==="tables")el.innerHTML=tablesTab(r); if(state.resultTab==="narrative")el.innerHTML=narrativeTab(r); if(state.resultTab==="sources")el.innerHTML=sourcesTab(r); bindTabEvents(); }
function listCard(title,items,cls=""){return `<div class="panel list-card ${cls}"><h3>${title}</h3>${items?.length?`<ul class="clean-list">${items.map(x=>`<li>${escapeHtml(typeof x==="string"?x:x.text||x.title||"")}</li>`).join("")}</ul>`:`<p class="muted">Нет подтвержденных данных.</p>`}</div>`;}
function summaryTab(r){const a=r.analysis||{};const retry=state.health?.ai_configured&&a.ai_error?`<div class="actions"><button class="secondary" id="runAI">Повторить AI-анализ после ошибки</button></div>`:"";const autoNote=isAiMode(a.mode)?`<div class="alert info">Итоговое заключение сформировано автоматически после проверки и нормализации данных. Дополнительный запуск AI не требуется.</div>`:"";return `${autoNote}<div class="two-col">${listCard("Сильные стороны",a.strengths,"good")}${listCard("Слабые стороны",a.weaknesses,"bad")}${listCard("Риски",a.risks,"warn")}${listCard("Действия менеджмента",a.management_actions)}</div><div class="two-col" style="margin-top:14px">${listCard("Стратегические наблюдения",a.strategic_observations)}${listCard("ESG-наблюдения",a.esg_observations)}</div><div class="panel" style="margin-top:14px"><h3>Ограничения данных</h3><ul class="clean-list">${(a.data_limitations||r.limitations||[]).map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>${retry}</div>`;}
const FIN_NAMES={revenue:"Выручка",cogs:"Себестоимость",gross_profit:"Валовая прибыль",commercial_expenses:"Коммерческие расходы",administrative_expenses:"Управленческие расходы",operating_profit:"Прибыль от продаж",interest_income:"Проценты к получению",interest_expense:"Проценты к уплате",profit_before_tax:"Прибыль до налогообложения",net_profit:"Чистая прибыль",cash:"Денежные средства",receivables:"Дебиторская задолженность",inventory:"Запасы",payables:"Кредиторская задолженность",financial_investments:"Финансовые вложения",current_assets:"Оборотные активы",noncurrent_assets:"Внеоборотные активы",assets:"Активы",current_liabilities:"Краткосрочные обязательства",longterm_liabilities:"Долгосрочные обязательства",liabilities:"Обязательства",equity:"Собственный капитал",operating_cash_flow:"Операционный денежный поток",investing_cash_flow:"Инвестиционный денежный поток",financing_cash_flow:"Финансовый денежный поток",capex:"Капитальные затраты",total_debt:"Общий долг"};
function financialTab(r){const metrics=Object.values(r.financial_metrics), ratios=r.ratios;return `${metrics.length?`<div class="panel"><div class="page-header"><div><h2>Нормализованные финансовые показатели</h2><p>Проверьте значения и единицы измерения перед использованием коэффициентов.</p></div><button class="secondary" id="editMetrics">Проверить / исправить</button></div><div class="table-wrap"><table><thead><tr><th>Показатель</th><th>Значения</th><th>Единица</th><th>Источник</th><th>Доверие</th></tr></thead><tbody>${metrics.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong></td><td>${Object.entries(x.values).map(([y,v])=>`<span class="value-badge"><b>${y}</b>&nbsp;${fmt(v)}</span>`).join("")}</td><td>${escapeHtml(x.unit||"—")}</td><td>${sourceLinks(x.source_pages)}</td><td>${x.manually_verified?"Проверено вручную":`${Math.round((x.confidence||0)*100)}%`}</td></tr>`).join("")}</tbody></table></div></div>`:`<div class="alert info">В документе не найден достаточный набор строк баланса, ОФР и ОДДС. Это нормально для годового отчета: загрузите отдельную отчетность по МСФО/РСБУ либо внесите значения вручную.</div><div class="actions"><button class="primary" id="editMetrics">Внести финансовые данные вручную</button></div>`}
  <div class="section-title"><div><h2>Финансовые коэффициенты</h2><p>Все расчеты выполняются кодом с защитой от деления на ноль.</p></div></div><div class="ratio-grid">${ratios.map(x=>`<div class="ratio ${x.status}"><div class="ratio-head"><strong>${escapeHtml(x.name)}</strong><span class="ratio-value">${x.display}</span></div><p>${escapeHtml(x.explanation)}</p><small>${escapeHtml(x.formula)}</small></div>`).join("")}</div><div id="metricEditor"></div>`;}
function operationalTab(r){if(!r.operational_metrics.length)return `<div class="alert info">Надежно распознанные операционные KPI не найдены. Непроверенные OCR-наименования намеренно скрыты, чтобы не показывать искаженные слова и ложные показатели.</div>`;const cats=[...new Set(r.operational_metrics.map(x=>x.category))];return `<div class="panel"><div class="filters"><input id="opSearch" placeholder="Поиск показателя"/><select id="opCategory"><option value="">Все категории</option>${cats.map(x=>`<option>${escapeHtml(x)}</option>`).join("")}</select><span class="pill">${r.operational_metrics.length} показателей</span></div><div id="opTable">${operationalTable(r.operational_metrics)}</div></div>`;}
function operationalTable(items){return `<div class="table-wrap"><table><thead><tr><th>Показатель</th><th>Категория</th><th>Динамика</th><th>Единица</th><th>Страницы</th></tr></thead><tbody>${items.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong></td><td><span class="category">${escapeHtml(x.category)}</span></td><td>${Object.entries(x.values).sort().map(([y,v])=>`<span class="value-badge"><b>${y}</b>&nbsp;${fmt(v)}</span>`).join("")}</td><td>${escapeHtml(x.unit||"—")}</td><td>${sourceLinks(x.source_pages)}</td></tr>`).join("")}</tbody></table></div>`;}
function tablesTab(r){return `<div class="alert info">Показаны первые ${Math.min(r.tables.length,60)} из ${r.tables.length} распознанных таблиц. Таблицы сохраняются как доказательная база и не все являются финансовыми.</div>${r.tables.slice(0,60).map((t,i)=>`<div class="panel table-block"><h3>Таблица ${i+1} ${t.page?`· ${pageLink(t.page)}`:`· лист ${escapeHtml(t.sheet||"")}`} · ${t.row_count}×${t.column_count}</h3><div class="table-wrap raw-table"><table><tbody>${t.rows.slice(0,35).map((row,ri)=>`<tr>${row.map(cell=>ri===0?`<th>${escapeHtml(cell)}</th>`:`<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`).join("")}`;}
function narrativeTab(r){const n=r.narrative||{};return `<div class="section-title"><div><h2>Автоматические риск-флаги</h2></div></div><div class="three-col">${r.risk_flags.map(x=>`<div class="panel risk ${x.severity}"><h3>${escapeHtml(x.title)}</h3><p>${escapeHtml(x.reason)}</p>${sourceLinks(x.source_pages)}</div>`).join("")||`<div class="panel">Риск-флаги не выявлены.</div>`}</div><div class="two-col" style="margin-top:15px">${narrativeList("Стратегия и проекты",n.strategy)}${narrativeList("ESG и устойчивое развитие",n.esg)}${narrativeList("Управление",n.governance)}${narrativeList("Фрагменты о рисках",n.risks)}</div>`;}
function narrativeList(title,items=[]){return `<div class="panel"><h3>${title}</h3>${items.slice(0,15).map(x=>`<div class="narrative-item"><p>${escapeHtml(x.text)}</p>${x.page?pageLink(x.page):""}</div>`).join("")||`<p class="muted">Раздел не найден.</p>`}</div>`;}
function sourcesTab(r){return `<div class="two-col"><div class="panel"><h3>Оглавление и разделы</h3>${r.headings.slice(0,120).map(x=>`<div class="narrative-item"><p>${escapeHtml(x.title)}</p>${x.page?pageLink(x.page):""}</div>`).join("")}</div><div class="panel"><div class="filters"><input type="number" id="pageNumber" min="1" max="${r.metadata.page_count||1}" placeholder="Номер страницы"/><button class="secondary" id="showPage">Показать</button></div><div id="pagePreview">${pagePreview(r,r.source?.pages?.[0]?.page||1)}</div></div></div>`;}
function pagePreview(r,pageNo){const p=(r.source?.pages||[]).find(x=>x.page===Number(pageNo));if(!p)return `<div class="empty"><div><b>Страница не найдена</b></div></div>`;const quality=p.ocr_quality!=null?` · качество ${fmt(p.ocr_quality)}/100`:"";const low=p.ocr&&Number(p.ocr_quality||0)<70;const body=low?`<div class="alert warn">Черновой OCR-текст этой страницы скрыт из-за недостаточной уверенности. Финансовые строки извлекаются отдельно по официальным кодам формы. Используйте ссылку на оригинальную страницу.</div>`:`<pre>${escapeHtml(p.text||"Текстовый слой отсутствует")}</pre>`;return `<div class="page-excerpt"><header><span>Страница ${p.page}${p.ocr?" · OCR":""}${quality}</span>${pageLink(p.page)}</header>${body}</div>`;}

function bindTabEvents(){
  if($("#runAI")) $("#runAI").onclick=runAI;
  if($("#editMetrics")) $("#editMetrics").onclick=renderMetricEditor;
  if($("#opSearch")){ const filter=()=>{const q=$("#opSearch").value.toLowerCase(),cat=$("#opCategory").value;const items=state.result.operational_metrics.filter(x=>(!q||x.name.toLowerCase().includes(q))&&(!cat||x.category===cat));$("#opTable").innerHTML=operationalTable(items);};$("#opSearch").oninput=filter;$("#opCategory").onchange=filter; }
  if($("#showPage")) $("#showPage").onclick=()=>$("#pagePreview").innerHTML=pagePreview(state.result,$("#pageNumber").value);
}
async function runAI(){const btn=$("#runAI");btn.disabled=true;btn.textContent="AI анализирует документ…";try{const data=await api(`/documents/${state.result.id}/ai`,{method:"POST"});if(data.analysis)state.result.analysis=data.analysis;toast(data.ok?"AI-анализ обновлен":"AI API не настроен — оставлен fallback-анализ");renderResult();}catch(e){toast(e.message,6000);btn.disabled=false;}}
function renderMetricEditor(){const r=state.result,reportYear=r.metadata.reporting_year||new Date().getFullYear(),years=[String(reportYear-1),String(reportYear)];const items=Object.entries(FIN_NAMES).map(([key,name])=>{const m=r.financial_metrics[key]||{name,unit:"",values:{}};return `<div class="edit-grid" data-key="${key}"><input class="m-name" value="${escapeHtml(m.name||name)}"/><input class="m-prev" type="number" step="any" placeholder="${years[0]}" value="${m.values?.[years[0]]??""}"/><input class="m-cur" type="number" step="any" placeholder="${years[1]}" value="${m.values?.[years[1]]??""}"/><input class="m-unit" placeholder="Единица" value="${escapeHtml(m.unit||"")}"/></div>`}).join("");$("#metricEditor").innerHTML=`<div class="panel" style="margin-top:16px"><div class="page-header"><div><h2>Проверка и ручная корректировка</h2><p>Периоды: ${years[0]} и ${years[1]}. Пустые строки не участвуют в расчетах.</p></div><button class="secondary" id="closeEditor">Закрыть</button></div><div class="edit-grid header"><span>Показатель</span><span>${years[0]}</span><span>${years[1]}</span><span>Единица</span></div>${items}<div class="actions"><button class="primary" id="saveMetrics">Сохранить и пересчитать</button></div></div>`;$("#closeEditor").onclick=()=>$("#metricEditor").innerHTML="";$("#saveMetrics").onclick=()=>saveMetrics(years);$("#metricEditor").scrollIntoView({behavior:"smooth"});}
async function saveMetrics(years){const financial_metrics={};$$(`.edit-grid[data-key]`,$("#metricEditor")).forEach(row=>{const key=row.dataset.key,values={};if($(".m-prev",row).value!=="")values[years[0]]=Number($(".m-prev",row).value);if($(".m-cur",row).value!=="")values[years[1]]=Number($(".m-cur",row).value);if(Object.keys(values).length)financial_metrics[key]={key,name:$(".m-name",row).value||FIN_NAMES[key],unit:$(".m-unit",row).value,values,source_pages:[],confidence:1};});try{state.result=await api(`/documents/${state.result.id}/financial-metrics`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({financial_metrics})});toast("Данные сохранены, коэффициенты пересчитаны");renderResult();state.resultTab="financial";}catch(e){toast(e.message);}}

function historyMarkup(docs, compact=false){if(!docs.length)return `<div class="panel empty"><div><b>История пока пуста</b><span>Загрузите PDF, Excel или CSV либо запустите демонстрационный анализ.</span></div></div>`;return `<div class="history-list">${docs.map(d=>`<div class="card history-item"><div class="doc-icon">${d.original_name?.toLowerCase().endsWith(".pdf")?"PDF":"XLS"}</div><div class="history-main"><strong>${escapeHtml(d.company||d.original_name)}</strong><small>${escapeHtml(d.original_name)} · ${typeLabel(d.document_type)}${d.reporting_year?` · ${d.reporting_year}`:""}</small></div><span class="history-status ${d.status}">${d.status==="completed"?"Готово":d.status==="error"?"Ошибка":`${d.progress}%`}</span><button class="secondary open-doc" data-id="${d.id}">${d.status==="completed"?"Открыть":"Статус"}</button>${compact?"":`<button class="danger-btn delete-doc" data-id="${d.id}">Удалить</button>`}</div>`).join("")}</div>`;}
function renderHistory(){root().innerHTML=`<section class="page"><div class="page-header"><div><h1>История анализов</h1><p>Файлы и результаты хранятся локально в SQLite и каталоге данных приложения.</p></div><button class="primary" id="historyUpload">Новый анализ</button></div>${historyMarkup(state.documents)}</section>`;$("#historyUpload").onclick=()=>showView("upload");bindHistoryActions();}
function bindHistoryActions(){$$(".open-doc").forEach(btn=>btn.onclick=async()=>{const doc=state.documents.find(d=>d.id===btn.dataset.id);if(doc.status==="completed")openResult(doc.id);else{showView("upload");renderProcessing(doc);pollDocument(doc.id);}});$$(".delete-doc").forEach(btn=>btn.onclick=async()=>{if(!confirm("Удалить документ и результат анализа?"))return;try{await api(`/documents/${btn.dataset.id}`,{method:"DELETE"});await loadDocuments();renderHistory();}catch(e){toast(e.message);}});}

function renderMethodology(){root().innerHTML=`<section class="page"><div class="page-header"><div><h1>Методология</h1><p>Система разделяет извлечение фактов, программные расчеты и языковую интерпретацию.</p></div></div><div class="method-grid">${method(1,"Классификация","Определяется тип документа и подходящий режим анализа.")}${method(2,"Парсинг","PyMuPDF извлекает текст; pdfplumber восстанавливает координатные таблицы.")}${method(3,"OCR","Для сканов используется многоступенчатый Tesseract rus+eng: несколько режимов распознавания, предварительная обработка изображения и выбор результата по оценке качества.")}${method(4,"Нормализация","Строки сопоставляются со справочником финансовых и отраслевых метрик.")}${method(5,"Анализ","Коэффициенты считаются кодом; AI автоматически получает только проверенные факты.")}</div><div class="panel prose" style="margin-top:16px"><h2>Финансовые коэффициенты</h2><p>Current Ratio, Quick Ratio, Cash Ratio, Working Capital, Debt Ratio, Debt/Equity, Net Debt, Net Debt/Equity, Equity Ratio, Interest Coverage, ROA, ROE, Net Margin, Gross Margin, Operating Margin, EBITDA Margin, Asset Turnover, Inventory Turnover, Receivables Turnover, Operating Cash Flow Ratio, OCF Margin, Cash Conversion, Free Cash Flow, Revenue Growth и Net Profit Growth. При отсутствии числителя или знаменателя выводится «недостаточно данных».</p><h2>Годовые отчеты</h2><p>Если документ не содержит полного баланса, ОФР и ОДДС, система не подменяет отсутствующие данные. Она анализирует операционные KPI, риски, стратегию, ESG и корпоративное управление, а оценка 0–100 отражает аналитическую пригодность документа, а не инвестиционную привлекательность компании.</p><h2>Map-reduce для больших PDF</h2><p>При подключенном OpenAI-совместимом AI API итоговое заключение формируется автоматически до открытия результата. Модель получает только нормализованные показатели, коэффициенты и подтвержденные раскрытия; сырой OCR-текст в финансовое резюме не передается.</p><h2>Ограничения</h2><p>Автоматически распознанные таблицы могут требовать проверки, особенно при сложной верстке, объединенных ячейках и OCR. Результат не является аудиторским заключением и не содержит рекомендаций купить или продать ценные бумаги.</p></div></section>`;}
function method(n,title,text){return `<div class="card method-step"><b>${n}</b><h3>${title}</h3><p>${text}</p></div>`;}
function renderSettings(){const h=state.health||{};root().innerHTML=`<section class="page"><div class="page-header"><div><h1>Настройки и интеграции</h1><p>Base URL, модель и секретный ключ задаются только на сервере в <code>.env</code>. Ключ никогда не передается в браузер.</p></div></div><div class="settings-grid"><div class="panel"><h2>Состояние сервера</h2><div class="capability-list">${cap("✓","API",h.status==="ok"?"Работает":"Недоступен")}${cap(h.ai_configured?"✓":"—","AI gateway",h.ai_configured?`${h.ai_model} · ${h.ai_base_url}`:"Используется детерминированный fallback")}${cap(h.ocr_enabled?"✓":"—","OCR",h.ocr_enabled?`Включен, язык ${h.ocr_language||"rus+eng"}; многоступенчатое распознавание`:"Выключен. Для сканов включите OCR.")}${cap("↥","Лимит файла",`${h.max_upload_mb||100} МБ`)}</div></div><div class="panel"><h2>Пример .env для личного API</h2><div class="env-code">AI_BASE_URL=https://your-api.example.com/v1
AI_API_KEY=your-secret-key
AI_MODEL=your-model-name
AUTO_AI=true
ENABLE_OCR=true
OCR_LANGUAGE=rus+eng
OCR_FORM_DPI_SCALE=3.5
OCR_TEXT_DPI_SCALE=2.8
OCR_MAX_PAGES=0
MAX_UPLOAD_MB=100
PORT=8000</div><p class="muted">Для OpenRouter используйте AI_BASE_URL=https://openrouter.ai/api/v1. После изменения .env перезапустите сервер.</p></div></div></section>`;}

document.addEventListener("DOMContentLoaded", init);

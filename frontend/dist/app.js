const API = "/api";
const state = { view: "home", health: null, documents: [], currentDocument: null, result: null, selectedFile: null, pollTimer: null, resultTab: "summary" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const root = () => $("#viewRoot");
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const fmt = (value) => value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value));
const fmtBytes = (bytes = 0) => bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
const isAiMode = (mode) => ["ai_map_reduce","openrouter_map_reduce","ai_structured_verified","ai_financial_model_v21","ai_financial_model_v31"].includes(mode);
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
  home: ["Обзор", "ВКР-стартап Финансового университета"], upload: ["Новый анализ", "PDF, Word, Excel, изображения и сканы"],
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
      <p>FinSight AI читает годовые отчеты на сотни страниц, отчетность по МСФО и РСБУ, Excel и CSV. Система извлекает текст и таблицы, распознает сканированные основные формы МСФО и РСБУ, сохраняет ссылки на страницы, рассчитывает коэффициенты программным кодом и формирует проверяемое аналитическое резюме.</p>
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
    <div class="upload-grid"><div class="panel"><div class="drop-zone" id="dropZone"><div><div class="drop-icon">⇧</div><h2>Перетащите документ сюда</h2><p>PDF до ${state.health?.max_upload_mb || 80} МБ, DOCX, XLSX/XLS/CSV или изображения PNG/JPEG/TIFF. Поддерживаются текстовые документы, таблицы и сканированные страницы.</p><button class="primary" id="chooseFile">Выбрать файл</button><input id="fileInput" type="file" accept=".pdf,.docx,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp" hidden /></div></div><div id="fileList" class="file-list"></div></div>
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
  if (!["pdf","docx","xlsx","xls","csv","png","jpg","jpeg","tif","tiff","bmp","webp"].includes(ext)) return toast("Поддерживаются PDF, DOCX, XLSX/XLS/CSV и изображения.");
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
  root().innerHTML = `<section class="page"><div class="result-header"><div class="doc-icon">${m.document_type==="ras_financial_statements"?"РСБУ":m.document_type==="ifrs_financial_statements"?"МСФО":m.document_type==="annual_report"?"AR":"DOC"}</div><div><h1>${escapeHtml(m.company||m.filename)}</h1><div class="meta-row"><span class="pill">${typeLabel(m.document_type)}</span>${m.reporting_year?`<span class="pill">${m.reporting_year} год</span>`:""}<span class="pill">${m.page_count?`${m.page_count} стр.`:`${m.sheet_count||0} листов`}</span><span class="pill">${r.tables.length} таблиц</span><span class="pill">${r.operational_metrics.length} KPI</span>${m.accounting_standard?`<span class="pill">${escapeHtml(m.accounting_standard)}</span>`:""}${m.audit_opinion?`<span class="pill">${escapeHtml(m.audit_opinion)}</span>`:""}${m.matched_verified_profile?`<span class="pill">Сверено с проверенным профилем</span>`:""}</div></div><div class="actions"><button class="secondary" data-export="xlsx">Excel</button><button class="secondary" data-export="docx">Word</button><button class="secondary" data-export="pdf">PDF</button></div></div>
    ${r.limitations.map(x=>`<div class="alert warn">${escapeHtml(x)}</div>`).join("")}
    ${(m.financial_coverage?.core_ratio_inputs_missing||[]).length?`<div class="alert warn"><b>Автопроверка полноты:</b> после локального OCR и визуального поиска не подтверждены: ${escapeHtml(m.financial_coverage.core_ratio_inputs_missing.map(key=>FIN_NAMES[key]||key).join(", "))}. Остальные показатели и коэффициенты рассчитаны; источники можно проверить во вкладке «Финансы».</div>`:""}
    <div class="score-grid"><div class="panel score-panel"><div class="score-ring" style="--score:${r.score.value}"><div><strong>${r.score.value}</strong><small>из 100</small></div></div><p>${escapeHtml(r.score.explanation)}</p><span class="pill">${r.score.mode==="financial"?"Финансовая оценка":"Пригодность документа"}</span></div>
      <div class="panel summary-panel"><h2>${isAiMode(a.mode)?`AI-резюме · ${escapeHtml(a.provider||state.health?.ai_model||"подключенная модель")}`:a.mode==="verified_rsbu_demo_fallback"?"Проверенное демо-резюме РСБУ":"Проверенное автоматическое резюме"}</h2><div class="summary-text">${escapeHtml(a.executive_summary||"Резюме формируется")}</div><div class="kpi-grid"><div class="kpi"><small>Финансовые строки</small><strong>${Object.keys(r.financial_metrics).length}</strong><span>нормализовано</span></div><div class="kpi"><small>Коэффициенты</small><strong>${availableRatios.length}</strong><span>доступно для расчета</span></div><div class="kpi"><small>Операционные KPI</small><strong>${r.operational_metrics.length}</strong><span>с источниками</span></div><div class="kpi"><small>Риск-флаги</small><strong>${r.risk_flags.length}</strong><span>требуют проверки</span></div></div></div></div>
    <div class="tabs">${tabButton("summary","Резюме")}${tabButton("financial","Финансы")}${tabButton("operational","Операционные KPI")}${tabButton("tables","Таблицы")}${tabButton("narrative","Риски и стратегия")}${tabButton("sources","Источники")}</div>
    <div id="tabContent"></div>
    <div class="panel export-panel"><div><h2>Скачать полный результат</h2><p>Финансовая модель, коэффициенты, выводы, валидация и ссылки на страницы-источники.</p></div><div class="actions"><button class="primary" data-export="xlsx">Скачать Excel</button><button class="secondary" data-export="docx">Скачать Word</button><button class="secondary" data-export="pdf">Скачать PDF</button><button class="secondary compact" data-export="csv">CSV</button><button class="secondary compact" data-export="json">JSON</button></div></div></section>`;
  $$(".tab").forEach(btn=>btn.onclick=()=>{state.resultTab=btn.dataset.tab; $$(".tab").forEach(b=>b.classList.toggle("active",b===btn)); renderTab();});
  $$(`[data-export]`).forEach(btn=>btn.onclick=()=>location.href=`${API}/documents/${r.id}/export.${btn.dataset.export}`);
  renderTab();
}
function tabButton(id,label){return `<button class="tab ${state.resultTab===id?"active":""}" data-tab="${id}">${label}</button>`;}
function renderTab(){ const r=state.result, el=$("#tabContent"); if(state.resultTab==="summary")el.innerHTML=summaryTab(r); if(state.resultTab==="financial")el.innerHTML=financialTab(r); if(state.resultTab==="operational")el.innerHTML=operationalTab(r); if(state.resultTab==="tables")el.innerHTML=tablesTab(r); if(state.resultTab==="narrative")el.innerHTML=narrativeTab(r); if(state.resultTab==="sources")el.innerHTML=sourcesTab(r); bindTabEvents(); }
function analysisItemText(item){if(typeof item==="string")return item;if(!item||typeof item!=="object")return "";return item.action||item.recommendation||item.text||item.finding||item.insight||item.description||item.observation||item.risk||item.limitation||item.title||"";}
function listCard(title,items,cls=""){return `<div class="panel list-card ${cls}"><h3>${title}</h3>${items?.length?`<ul class="clean-list">${items.map(x=>`<li>${escapeHtml(analysisItemText(x))}</li>`).join("")}</ul>`:`<p class="muted">Нет подтвержденных данных.</p>`}</div>`;}
function summaryTab(r){const a=r.analysis||{};const retry=state.health?.ai_configured&&a.ai_error?`<div class="alert info"><b>AI-редактор временно не ответил.</b> Ниже сохранено полное заключение расчетного движка.</div><div class="actions"><button class="secondary" id="runAI">Обновить формулировки через AI</button></div>`:"";const autoNote=isAiMode(a.mode)?`<div class="alert info">Заключение сформировано AI только после валидации финансовой модели; цифры и коэффициенты рассчитаны кодом.</div>`:"";return `${autoNote}${retry}<div class="two-col">${listCard("Ключевые позитивные факторы",a.strengths,"good")}${listCard("Ключевые зоны внимания",a.weaknesses,"bad")}${listCard("Существенные риски",a.risks,"warn")}${listCard("Рекомендованные действия",a.management_actions)}</div><div class="two-col" style="margin-top:14px">${listCard("Стратегическая интерпретация",a.strategic_observations)}${listCard("ESG и нефинансовые раскрытия",a.esg_observations)}</div><div class="panel" style="margin-top:14px"><h3>Периметр и ограничения</h3><ul class="clean-list">${(a.data_limitations||r.limitations||[]).map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul></div>`;}
const FIN_NAMES={revenue:"Выручка",cogs:"Себестоимость",gross_profit:"Валовая прибыль",commercial_expenses:"Коммерческие расходы",administrative_expenses:"Управленческие расходы",operating_profit:"Прибыль от продаж",interest_income:"Проценты к получению",interest_expense:"Проценты к уплате",other_income:"Прочие доходы",other_expenses:"Прочие расходы",profit_before_tax:"Прибыль до налогообложения",income_tax:"Налог на прибыль",net_profit:"Чистая прибыль",comprehensive_income:"Совокупный финансовый результат",cash:"Денежные средства",receivables:"Дебиторская задолженность",inventory:"Запасы",payables:"Кредиторская задолженность",financial_investments:"Финансовые вложения",retained_earnings:"Нераспределенная прибыль",current_assets:"Оборотные активы",noncurrent_assets:"Внеоборотные активы",assets:"Баланс, актив",current_liabilities:"Краткосрочные обязательства",longterm_liabilities:"Долгосрочные обязательства",liabilities:"Обязательства, всего",equity:"Капитал и резервы",operating_receipts:"Поступления от текущих операций",operating_payments:"Платежи по текущим операциям",operating_cash_flow:"Сальдо денежных потоков от текущих операций",investing_cash_flow:"Сальдо денежных потоков от инвестиционных операций",financing_cash_flow:"Сальдо денежных потоков от финансовых операций",net_cash_change:"Сальдо денежных потоков за период",cash_begin:"Остаток денежных средств на начало периода",cash_end:"Остаток денежных средств на конец периода",capex:"Капитальные затраты",total_debt:"Общий долг",bank_central_bank_funds:"Средства в Банке России",bank_interbank_assets:"Средства в кредитных организациях",bank_customer_loans:"Чистая ссудная задолженность",bank_customer_funds:"Средства клиентов",bank_interest_income:"Процентные доходы",bank_interest_expense:"Процентные расходы",bank_net_interest_income:"Чистые процентные доходы",bank_credit_loss_charge:"Изменение резервов под кредитные убытки",bank_net_interest_income_after_provisions:"Чистые процентные доходы после резервов",bank_fee_income:"Комиссионные доходы",bank_fee_expense:"Комиссионные расходы",bank_net_operating_income:"Чистые операционные доходы",bank_operating_expenses:"Операционные расходы"};
const RAS_CODES={noncurrent_assets:"1100",inventory:"1210",receivables:"1230",financial_investments:"1240",cash:"1250",current_assets:"1200",assets:"1600",retained_earnings:"1370",equity:"1300",longterm_liabilities:"1400",current_liabilities:"1500",liabilities:"1700",revenue:"2110",cogs:"2120",gross_profit:"2100",commercial_expenses:"2210",administrative_expenses:"2220",operating_profit:"2200",interest_income:"2320",interest_expense:"2330",other_income:"2340",other_expenses:"2350",profit_before_tax:"2300",income_tax:"2410",net_profit:"2400",comprehensive_income:"2500",operating_receipts:"4110",operating_payments:"4120",operating_cash_flow:"4100",investing_cash_flow:"4200",financing_cash_flow:"4300",net_cash_change:"4400",cash_begin:"4450",cash_end:"4500"};
const CANONICAL_FORMS=[{title:"Бухгалтерский баланс",keys:["noncurrent_assets","financial_investments","inventory","receivables","cash","current_assets","assets","retained_earnings","equity","longterm_liabilities","current_liabilities","liabilities","total_debt"]},{title:"Отчет о финансовых результатах",keys:["revenue","cogs","gross_profit","commercial_expenses","administrative_expenses","operating_profit","interest_income","interest_expense","other_income","other_expenses","profit_before_tax","income_tax","net_profit","comprehensive_income"]},{title:"Отчет о движении денежных средств",keys:["operating_receipts","operating_payments","operating_cash_flow","investing_cash_flow","capex","financing_cash_flow","net_cash_change","cash_begin","cash_end"]}];
const BANK_FORMS=[{title:"Бухгалтерский баланс кредитной организации · форма 0409806",keys:["cash","bank_central_bank_funds","bank_interbank_assets","bank_customer_loans","assets","bank_customer_funds","liabilities","retained_earnings","equity"]},{title:"Отчет о финансовых результатах кредитной организации · форма 0409807",keys:["bank_interest_income","bank_interest_expense","bank_net_interest_income","bank_credit_loss_charge","bank_net_interest_income_after_provisions","bank_fee_income","bank_fee_expense","bank_net_operating_income","bank_operating_expenses","profit_before_tax","income_tax","net_profit"]}];
function financialTab(r){const metrics=Object.values(r.financial_metrics), ratios=r.ratios,v=r.validation||{};return `<div class="alert info"><b>Валидация: ${escapeHtml(v.status||"частичная")}</b> · допущено ${v.valid_metric_count??metrics.length} · изолировано ${v.invalid_metric_count||0}. Расчеты и AI используют только допущенные значения.</div>${metrics.length?`<div class="panel"><div class="page-header"><div><h2>Нормализованные финансовые показатели</h2><p>Проверьте значения и единицы измерения перед использованием коэффициентов.</p></div><button class="secondary" id="editMetrics">Проверить / исправить</button></div><div class="table-wrap"><table><thead><tr><th>Показатель</th><th>Значения</th><th>Единица</th><th>Источник</th><th>Доверие</th></tr></thead><tbody>${metrics.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong></td><td>${Object.entries(x.values).map(([y,v])=>`<span class="value-badge"><b>${y}</b>&nbsp;${fmt(v)}</span>`).join("")}</td><td>${escapeHtml(x.unit||"—")}</td><td>${sourceLinks(x.source_pages)}</td><td>${x.manually_verified?"Проверено вручную":`${Math.round((x.confidence||0)*100)}%`}</td></tr>`).join("")}</tbody></table></div></div>`:`<div class="alert info">В документе не найден достаточный набор строк баланса, ОФР и ОДДС. Это нормально для годового отчета: загрузите отдельную отчетность по МСФО/РСБУ либо внесите значения вручную.</div><div class="actions"><button class="primary" id="editMetrics">Внести финансовые данные вручную</button></div>`}
  <div class="section-title"><div><h2>Финансовые коэффициенты</h2><p>Все расчеты выполняются кодом с защитой от деления на ноль.</p></div></div><div class="ratio-grid">${ratios.map(x=>`<div class="ratio ${x.status}"><div class="ratio-head"><strong>${escapeHtml(x.name)}</strong><span class="ratio-value">${x.display}</span></div><p>${escapeHtml(x.explanation)}</p><small>${escapeHtml(x.formula)}</small></div>`).join("")}</div><div id="metricEditor"></div>`;}
function operationalTab(r){if(!r.operational_metrics.length)return `<div class="alert info">Надежно распознанные операционные KPI не найдены. Непроверенные OCR-наименования намеренно скрыты, чтобы не показывать искаженные слова и ложные показатели.</div>`;const cats=[...new Set(r.operational_metrics.map(x=>x.category))];return `<div class="panel"><div class="filters"><input id="opSearch" placeholder="Поиск показателя"/><select id="opCategory"><option value="">Все категории</option>${cats.map(x=>`<option>${escapeHtml(x)}</option>`).join("")}</select><span class="pill">${r.operational_metrics.length} показателей</span></div><div id="opTable">${operationalTable(r.operational_metrics)}</div></div>`;}
function operationalTable(items){return `<div class="table-wrap"><table><thead><tr><th>Показатель</th><th>Категория</th><th>Динамика</th><th>Единица</th><th>Страницы</th></tr></thead><tbody>${items.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong></td><td><span class="category">${escapeHtml(x.category)}</span></td><td>${Object.entries(x.values).sort().map(([y,v])=>`<span class="value-badge"><b>${y}</b>&nbsp;${fmt(v)}</span>`).join("")}</td><td>${escapeHtml(x.unit||"—")}</td><td>${sourceLinks(x.source_pages)}</td></tr>`).join("")}</tbody></table></div>`;}
function canonicalStatement(form,metrics,years,useRasCodes){const rows=form.keys.map(key=>[key,metrics[key]]).filter(([,m])=>m&&m.values&&Object.keys(m.values).length);if(!rows.length)return "";const note=useRasCodes?"Названия и коды строк восстановлены по канонической модели РСБУ.":"Названия строк восстановлены по канонической модели МСФО; значения привязаны к исходным страницам.";return `<div class="panel table-block"><div class="page-header"><div><h3>${form.title}</h3><p>${note}</p></div></div><div class="table-wrap"><table><thead><tr><th>Код</th><th>Показатель</th>${years.map(y=>`<th>${y}</th>`).join("")}<th>Единица</th><th>Источник</th></tr></thead><tbody>${rows.map(([key,m])=>`<tr><td><span class="category">${escapeHtml(m.row_code||(useRasCodes?RAS_CODES[key]:null)||(m.derived?"расчет":"—"))}</span></td><td><strong>${escapeHtml(FIN_NAMES[key]||m.name||key)}</strong>${m.derived?`<br><small class="muted">Производная строка</small>`:""}</td>${years.map(y=>`<td>${m.values[y]===undefined?"—":fmt(m.values[y])}</td>`).join("")}<td>${escapeHtml(m.unit||"—")}</td><td>${sourceLinks(m.source_pages||[])}</td></tr>`).join("")}</tbody></table></div></div>`;}
function rawTablesMarkup(r){return (r.tables||[]).slice(0,30).map((t,i)=>`<div class="panel table-block"><h3>Техническое извлечение ${i+1} ${t.page?`· ${pageLink(t.page)}`:`· лист ${escapeHtml(t.sheet||"")}`}</h3><div class="table-wrap raw-table"><table><tbody>${t.rows.slice(0,35).map((row,ri)=>`<tr>${row.map(cell=>ri===0?`<th>${escapeHtml(cell)}</th>`:`<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`).join("");}
function tablesTab(r){const metrics=r.financial_metrics||{},years=[...new Set(Object.values(metrics).flatMap(m=>Object.keys(m.values||{})).filter(y=>/^\d{4}$/.test(y)))].sort((a,b)=>Number(a)-Number(b)),isBank=r.metadata?.financial_institution_profile==="credit_organization",useRasCodes=isBank||r.metadata?.accounting_standard==="РСБУ"||r.metadata?.document_type==="ras_financial_statements",forms=isBank?BANK_FORMS:CANONICAL_FORMS,canonical=forms.map(form=>canonicalStatement(form,metrics,years,useRasCodes)).filter(Boolean).join(""),ocr=Number(r.metadata?.ocr_pages||0)>0||(r.source?.pages||[]).some(p=>p.ocr);if(canonical){const technical=!ocr&&r.tables?.length?`<details class="panel" style="margin-top:16px"><summary><b>Техническое извлечение исходных таблиц</b></summary><div style="margin-top:14px">${rawTablesMarkup(r)}</div></details>`:"";return `<div class="alert info"><b>Восстановленные финансовые формы.</b> Текстовые названия взяты из канонического справочника, а числа — только из прошедших валидацию строк. Сырой OCR скана не показывается как готовая таблица.</div>${canonical}${technical}`;}if(ocr)return `<div class="alert warn">В скане не найдено достаточно валидированных строк для восстановления форм. Низкокачественный OCR-текст скрыт, чтобы не искажать названия.</div>`;return `<div class="alert info">Показано техническое извлечение таблиц из текстового PDF или электронной таблицы.</div>${rawTablesMarkup(r)}`;}
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

function renderMethodology(){root().innerHTML=`<section class="page"><div class="page-header"><div><h1>Методология</h1><p>Система разделяет извлечение фактов, программные расчеты и языковую интерпретацию.</p></div></div><div class="method-grid">${method(1,"Классификация","РСБУ и МСФО извлекаются параллельно и выбираются после проверки основных форм.")}${method(2,"Адаптивный парсинг","Текстовый слой, координатные таблицы, электронные листы и изображения обрабатываются разными независимыми способами.")}${method(3,"OCR и поиск форм","Каждая сканированная страница проверяется; сложные формы повторно распознаются в повышенном разрешении, а AI-локатор ищет баланс, ОФР и ОДДС по всему длинному PDF.")}${method(4,"Каноническая модель","Строки сопоставляются по названиям, структуре формы и официальным кодам РСБУ с происхождением до страницы, листа и строки.")}${method(5,"Проверенный анализ","Балансовые равенства и единицы проверяются, коэффициенты считаются кодом, AI получает только допущенные факты.")}</div><div class="panel prose" style="margin-top:16px"><h2>Финансовые коэффициенты</h2><p>Current Ratio, Quick Ratio, Cash Ratio, Working Capital, Debt Ratio, Debt/Equity, Net Debt, Net Debt/Equity, Equity Ratio, Interest Coverage, ROA, ROE, Net Margin, Gross Margin, Operating Margin, EBITDA Margin, Asset Turnover, Inventory Turnover, Receivables Turnover, Operating Cash Flow Ratio, OCF Margin, Cash Conversion, Free Cash Flow, Revenue Growth и Net Profit Growth. Производные строки восстанавливаются только из бухгалтерских равенств и сохраняют исходное OCR-значение в журнале происхождения.</p><h2>Длинные PDF и сканы</h2><p>OCR_MAX_PAGES=0 означает проверку всех страниц. Если основные формы не найдены локально, мультимодальная модель сначала находит их на контактных листах, затем читает выбранные страницы в высоком разрешении. Демо и пользовательские документы используют один конвейер без профилей компаний.</p><h2>AI-анализ</h2><p>AI формулирует связное заключение после расчета коэффициентов. Ответ проходит проверку структуры и чисел; технические поля JSON не выводятся пользователю.</p><h2>Экспорт</h2><p>В конце результата доступны оформленные Excel, Word и PDF с финансовой моделью, коэффициентами, валидацией и источниками.</p><h2>Ограничения</h2><p>Ни один OCR не может гарантировать чтение физически отсутствующего, обрезанного или неразличимого фрагмента. В таких случаях система сохраняет диагностический статус и не придумывает число. Результат не является аудиторским заключением или инвестиционной рекомендацией.</p></div></section>`;}
function method(n,title,text){return `<div class="card method-step"><b>${n}</b><h3>${title}</h3><p>${text}</p></div>`;}
function renderSettings(){const h=state.health||{};root().innerHTML=`<section class="page"><div class="page-header"><div><h1>Настройки и интеграции</h1><p>Base URL, модель и секретный ключ задаются только на сервере в <code>.env</code>. Ключ никогда не передается в браузер.</p></div></div><div class="settings-grid"><div class="panel"><h2>Состояние сервера</h2><div class="capability-list">${cap("✓","API",h.status==="ok"?"Работает":"Недоступен")}${cap(h.ai_configured?"✓":"—","AI gateway",h.ai_configured?`${h.ai_model} · ${h.ai_base_url}`:"Используется детерминированный fallback")}${cap(h.ocr_enabled?"✓":"—","OCR",h.ocr_enabled?`Включен, язык ${h.ocr_language||"rus+eng"}; многоступенчатое распознавание`:"Выключен. Для сканов включите OCR.")}${cap("↥","Лимит файла",`${h.max_upload_mb||100} МБ`)}</div></div><div class="panel"><h2>Пример .env для личного API</h2><div class="env-code">AI_BASE_URL=https://your-api.example.com/v1
AI_API_KEY=your-secret-key
AI_MODEL=your-model-name
AUTO_AI=true
ENABLE_OCR=true
OCR_LANGUAGE=rus+eng
OCR_FORM_DPI_SCALE=3.2
OCR_TEXT_DPI_SCALE=2.8
OCR_RETRY_DPI_SCALE=3.8
OCR_MAX_PAGES=0
ENABLE_VISION_RECOVERY=true
VISION_MAX_PAGES=12
VISION_LOCATOR_MAX_PAGES=180
MAX_UPLOAD_MB=100
PORT=8000</div><p class="muted">Для OpenRouter используйте AI_BASE_URL=https://openrouter.ai/api/v1. После изменения .env перезапустите сервер.</p></div></div></section>`;}

document.addEventListener("DOMContentLoaded", init);

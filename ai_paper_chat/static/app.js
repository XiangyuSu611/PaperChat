let currentPaper = null;
let health = null;
let currentEntryUrl = null;
let providerMap = {};
let zoteroCollections = [];
let pdfRenderToken = 0;
let selectedPdfText = "";
let currentPdfUrl = "";
let pdfZoom = 1;
let apiKeyMasked = false;
const layoutStorageKey = "aiPaperChatLayout";

const $ = (id) => document.getElementById(id);

function setBusy(text) {
  $("health").textContent = text || "";
  $("health").className = text ? "busy" : "";
}

function selectedProvider() {
  return $("provider")?.value || health?.provider || "deepseek";
}

function selectedModel() {
  return $("model")?.value || providerMap[selectedProvider()]?.default_model || health?.model;
}

function populateProviders() {
  providerMap = {};
  (health.providers || []).forEach((provider) => {
    providerMap[provider.id] = provider;
  });
  const providerSelect = $("provider");
  providerSelect.innerHTML = "";
  (health.providers || []).forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.id;
    providerSelect.appendChild(option);
  });
  providerSelect.value = health.provider;
  populateModels();
}

function populateModels() {
  const provider = providerMap[selectedProvider()];
  const modelSelect = $("model");
  modelSelect.innerHTML = "";
  (provider?.models || []).forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label || model.id;
    modelSelect.appendChild(option);
  });
  modelSelect.value = provider?.default_model || health.model;
  updateApiKeyInput();
  setBusy();
}

function updateApiKeyInput() {
  const provider = providerMap[selectedProvider()];
  const input = $("apiKeyInput");
  if (!input) return;
  apiKeyMasked = Boolean(provider?.api_key_present);
  input.value = apiKeyMasked ? "**********" : "";
  input.placeholder = apiKeyMasked ? "**********" : "No API key set";
}

async function saveApiKey() {
  const input = $("apiKeyInput");
  const apiKey = input.value.trim();
  if (!apiKey || apiKey.replaceAll("*", "") === "") {
    alert("Enter a real API key before saving.");
    return;
  }
  setBusy("Saving API key...");
  $("saveApiKeyBtn").disabled = true;
  try {
    const data = await api("/api/settings/llm-key", {
      method: "POST",
      body: JSON.stringify({ provider: selectedProvider(), api_key: apiKey }),
    });
    providerMap[data.provider.id] = data.provider;
    updateApiKeyInput();
    setBusy("API key saved.");
    window.setTimeout(() => setBusy(), 1200);
  } catch (err) {
    alert(err.message);
    setBusy();
  } finally {
    $("saveApiKeyBtn").disabled = false;
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const detail = data.detail || text || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function renderResults(matches, targetId = "results") {
  const root = $(targetId);
  root.innerHTML = "";
  if (!matches.length) {
    root.textContent = "No matches.";
    return;
  }
  matches.forEach((match) => {
    const el = document.createElement("div");
    el.className = "result";
    const pdf = (match.attachments || []).find((a) => a.content_type === "application/pdf" && a.exists);
    el.innerHTML = `<strong>${escapeHtml(match.title || match.key)}</strong><span>${match.key} · ${match.type}${pdf ? " · PDF ready" : " · no PDF"}</span>`;
    el.addEventListener("click", () => loadPaper({ key: match.key }));
    root.appendChild(el);
  });
}

async function loadCollections() {
  const select = $("collectionSelect");
  select.innerHTML = `<option value="">Loading folders...</option>`;
  $("collectionLoadBtn").disabled = true;
  try {
    const data = await api("/api/collections");
    const collections = data.collections || [];
    zoteroCollections = collections;
    select.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = collections.length ? "Select a Zotero folder" : "No Zotero folders";
    select.appendChild(empty);
    collections.forEach((collection) => {
      const option = document.createElement("option");
      option.value = collection.key;
      option.textContent = `${collection.path} (${collection.item_count})`;
      select.appendChild(option);
    });
    $("collectionLoadBtn").disabled = !collections.length;
  } catch (err) {
    select.innerHTML = `<option value="">Folder load failed</option>`;
    $("collectionLoadBtn").disabled = true;
  }
}

async function loadCollectionItems() {
  const key = $("collectionSelect").value;
  if (!key) return;
  setBusy("Loading Zotero folder...");
  $("collectionLoadBtn").disabled = true;
  try {
    const data = await api(`/api/collections/${encodeURIComponent(key)}/items`);
    renderResults(data.matches || [], "collectionResults");
    setBusy();
  } catch (err) {
    alert(err.message);
    setBusy();
  } finally {
    $("collectionLoadBtn").disabled = false;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineMarkdown(text) {
  return renderInlineMath(escapeHtml(text))
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[((?:p|page)\.?\s*(\d+)(?:\s*[-–]\s*(?:p|page)?\.?\s*\d+)?(?:\s*,\s*(?:Table|Fig\.?|Figure)\s*[\w. -]+)?)\]/gi, (match, label, page) => {
      return `<button class="page-cite" type="button" data-page="${page}">[${label}]</button>`;
    });
}

function normalizeMathExpression(expr) {
  return expr
    .replace(/\bargmax\b/g, "\\operatorname*{argmax}")
    .replace(/\bsoftmax\b/g, "\\operatorname{softmax}")
    .replace(/\bargmin\b/g, "\\operatorname*{argmin}");
}

function renderMathExpression(expr, displayMode = false) {
  const source = normalizeMathExpression(expr.trim());
  if (!source) return "";
  if (!globalThis.katex) return escapeHtml(expr);
  try {
    return globalThis.katex.renderToString(source, {
      displayMode,
      throwOnError: false,
      strict: false,
      trust: false,
    });
  } catch {
    return escapeHtml(expr);
  }
}

function renderInlineMath(html) {
  return html
    .replace(/\$\$([^$]+)\$\$/g, (_, expr) => renderMathExpression(expr, true))
    .replace(/\$([^$\n]+)\$/g, (_, expr) => renderMathExpression(expr, false));
}

function looksLikeMathLine(line) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.length > 220 || !trimmed.includes("=")) return false;
  return /[_^]|[α-ωΑ-Ωβγδεζηθικλμνξοπρστυφχψ]/.test(trimmed);
}

function isMarkdownTableSeparator(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitMarkdownTableRow(line) {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return [];
  const body = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  return body.split("|").map((cell) => cell.trim());
}

function renderMarkdownTable(rows) {
  const header = splitMarkdownTableRow(rows[0]);
  const bodyRows = rows.slice(2).map(splitMarkdownTableRow).filter((row) => row.length);
  const thead = `<thead><tr>${header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
  const tbody = `<tbody>${bodyRows.map((row) => {
    const cells = header.map((_, index) => row[index] || "");
    return `<tr>${cells.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`;
  }).join("")}</tbody>`;
  return `<table>${thead}${tbody}</table>`;
}

function renderMarkdown(md) {
  if (!md) return "No note yet. Click Generate Note.";
  const lines = String(md).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let inCode = false;
  let codeLines = [];
  let listType = null;

  function closeList() {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  }

  function closeCode() {
    if (inCode) {
      out.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      inCode = false;
      codeLines = [];
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      if (inCode) closeCode();
      else {
        closeList();
        inCode = true;
        codeLines = [];
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (
      line.includes("|") &&
      index + 1 < lines.length &&
      isMarkdownTableSeparator(lines[index + 1])
    ) {
      closeList();
      const tableRows = [line, lines[index + 1]];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        tableRows.push(lines[index]);
        index += 1;
      }
      index -= 1;
      out.push(renderMarkdownTable(tableRows));
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    if (unordered) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        out.push("<ul>");
      }
      out.push(`<li>${inlineMarkdown(unordered[1])}</li>`);
      continue;
    }

    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        out.push("<ol>");
      }
      out.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      out.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    if (!line.trim()) {
      closeList();
      continue;
    }
    if (looksLikeMathLine(line)) {
      closeList();
      out.push(`<div class="math-block">${renderMathExpression(line, true)}</div>`);
      continue;
    }
    closeList();
    out.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeCode();
  closeList();
  return out.join("\n");
}

function formatPublication(publication) {
  const root = $("publicationMeta");
  if (!root) return;
  if (!publication) {
    root.innerHTML = "";
    return;
  }
  const best = publication.best;
  if (!best) {
    root.innerHTML = `<span class="publication-pill muted-pill">Publication not found</span>`;
    return;
  }
  const statusLabel = publication.status === "found" ? "Published" : "Possible match";
  const venue = best.venue || best.publisher || "venue unknown";
  const year = best.year ? ` · ${best.year}` : "";
  const doi = best.doi ? ` · DOI: ${escapeHtml(best.doi)}` : "";
  const confidence = Number.isFinite(best.confidence) ? ` · ${Math.round(best.confidence * 100)}%` : "";
  const link = best.url
    ? `<a href="${escapeHtml(best.url)}" target="_blank" rel="noreferrer">${escapeHtml(venue)}</a>`
    : escapeHtml(venue);
  root.innerHTML = `
    <span class="publication-pill">${statusLabel}</span>
    <span>${link}${year}${doi}${confidence}</span>
  `;
}

async function refreshPaper() {
  if (!currentPaper) return;
  const data = await api(`/api/paper/${encodeURIComponent(currentPaper)}`);
  $("paperTitle").textContent = data.metadata.title || currentPaper;
  currentEntryUrl = data.metadata.entry_url || `${health.base_url}/?paper=${encodeURIComponent(data.metadata.paper_id)}`;
  $("paperMeta").textContent = `${data.metadata.paper_id} · ${data.metadata.source} · ${data.metadata.pdf_path}`;
  formatPublication(data.metadata.publication);
  pdfZoom = 1;
  renderPdf(`/api/paper/${encodeURIComponent(data.metadata.paper_id)}/preview.pdf`);
  $("note").innerHTML = renderMarkdown(data.note);
  $("chatLog").innerHTML = "";
  (data.history || []).forEach((turn) => {
    addTurn("user", turn.question);
    addTurn("assistant", turn.answer);
  });
  $("noteBtn").disabled = false;
  $("askBtn").disabled = false;
  $("entryBtn").disabled = false;
  $("publicationBtn").disabled = false;
}

function updatePdfZoomControls() {
  $("pdfZoomLabel").textContent = `${Math.round(pdfZoom * 100)}%`;
  const hasPdf = Boolean(currentPdfUrl);
  $("pdfZoomOutBtn").disabled = !hasPdf || pdfZoom <= 0.5;
  $("pdfZoomInBtn").disabled = !hasPdf || pdfZoom >= 2.5;
  $("pdfFitBtn").disabled = !hasPdf || pdfZoom === 1;
}

function getPdfScrollAnchor() {
  const crop = document.querySelector(".pdf-viewer-crop");
  if (!crop) return null;
  return {
    xRatio: crop.scrollLeft / Math.max(1, crop.scrollWidth),
    yRatio: (crop.scrollTop + crop.clientHeight / 2) / Math.max(1, crop.scrollHeight),
  };
}

function restorePdfScrollAnchor(anchor) {
  if (!anchor) return;
  const crop = document.querySelector(".pdf-viewer-crop");
  if (!crop) return;
  crop.scrollLeft = anchor.xRatio * crop.scrollWidth;
  crop.scrollTop = anchor.yRatio * crop.scrollHeight - crop.clientHeight / 2;
}

function setPdfZoom(nextZoom, keepScroll = true) {
  const rounded = Math.round(nextZoom * 10) / 10;
  const clamped = Math.max(0.5, Math.min(2.5, rounded));
  if (!currentPdfUrl || clamped === pdfZoom) return;
  pdfZoom = clamped;
  renderPdf(currentPdfUrl, { keepScroll });
}

async function renderPdf(url = currentPdfUrl, options = {}) {
  currentPdfUrl = url;
  updatePdfZoomControls();
  const scrollAnchor = options.keepScroll ? getPdfScrollAnchor() : null;
  const token = ++pdfRenderToken;
  const viewer = $("pdfViewer");
  hideSelectionBubble();
  viewer.innerHTML = `<div class="pdf-loading">Loading PDF...</div>`;

  if (!window.pdfjsLib) {
    viewer.innerHTML = `<div class="pdf-loading">PDF renderer failed to load.</div>`;
    return;
  }

  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.min.js";

  try {
    const doc = await pdfjsLib.getDocument(url).promise;
    if (token !== pdfRenderToken) return;
    viewer.innerHTML = "";

    for (let pageNo = 1; pageNo <= doc.numPages; pageNo += 1) {
      if (token !== pdfRenderToken) return;
      const page = await doc.getPage(pageNo);
      const baseViewport = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(320, viewer.clientWidth - 18);
      const fitScale = Math.min(1.8, Math.max(0.72, availableWidth / baseViewport.width));
      const scale = fitScale * pdfZoom;
      const viewport = page.getViewport({ scale });
      const outputScale = window.devicePixelRatio || 1;

      const pageEl = document.createElement("div");
      pageEl.className = "pdf-page";
      pageEl.dataset.pageNumber = String(pageNo);
      pageEl.style.width = `${viewport.width}px`;
      pageEl.style.height = `${viewport.height}px`;

      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const context = canvas.getContext("2d");
      context.setTransform(outputScale, 0, 0, outputScale, 0, 0);

      const textLayer = document.createElement("div");
      textLayer.className = "textLayer";
      textLayer.style.setProperty("--scale-factor", scale);

      pageEl.appendChild(canvas);
      pageEl.appendChild(textLayer);
      viewer.appendChild(pageEl);

      await page.render({ canvasContext: context, viewport }).promise;
      const textContent = await page.getTextContent();
      await pdfjsLib.renderTextLayer({
        textContentSource: textContent,
        container: textLayer,
        viewport,
        textDivs: [],
      }).promise;
    }
    if (token === pdfRenderToken) restorePdfScrollAnchor(scrollAnchor);
  } catch (err) {
    if (token === pdfRenderToken) {
      viewer.innerHTML = `<div class="pdf-loading">${escapeHtml(err.message || "PDF rendering failed.")}</div>`;
    }
  }
}

function jumpToPdfPage(pageNumber) {
  const page = Number(pageNumber);
  if (!Number.isFinite(page) || page < 1) return;
  const target = document.querySelector(`.pdf-page[data-page-number="${page}"]`);
  const crop = document.querySelector(".pdf-viewer-crop");
  if (!target || !crop) return;
  const cropRect = crop.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  crop.scrollTo({
    top: crop.scrollTop + targetRect.top - cropRect.top - 12,
    behavior: "smooth",
  });
  target.classList.add("is-targeted");
  window.setTimeout(() => target.classList.remove("is-targeted"), 1200);
}

function hideSelectionBubble() {
  selectedPdfText = "";
  $("selectionBubble")?.classList.remove("is-visible");
}

function showSelectionBubble(event, root) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) {
    hideSelectionBubble();
    return;
  }
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) {
    hideSelectionBubble();
    return;
  }

  const text = selection.toString().replace(/\s+/g, " ").trim();
  if (text.length < 2) {
    hideSelectionBubble();
    return;
  }

  selectedPdfText = text;
  const bubble = $("selectionBubble");
  const rangeRect = selection.getRangeAt(0).getBoundingClientRect();
  const clientX = event?.clientX || rangeRect.left + rangeRect.width / 2;
  const clientY = event?.clientY || rangeRect.top;
  const left = Math.max(8, Math.min(window.innerWidth - 160, clientX - 60));
  const top = Math.max(8, clientY - 42);
  bubble.style.left = `${left}px`;
  bubble.style.top = `${top}px`;
  bubble.classList.add("is-visible");
}

function setupPdfSelection() {
  const viewer = $("pdfViewer");
  const note = $("note");
  const crop = document.querySelector(".pdf-viewer-crop");
  const bubble = $("selectionBubble");
  viewer.addEventListener("mouseup", (event) => window.setTimeout(() => showSelectionBubble(event, viewer), 0));
  viewer.addEventListener("keyup", (event) => window.setTimeout(() => showSelectionBubble(event, viewer), 0));
  note.addEventListener("mouseup", (event) => window.setTimeout(() => showSelectionBubble(event, note), 0));
  note.addEventListener("keyup", (event) => window.setTimeout(() => showSelectionBubble(event, note), 0));
  crop.addEventListener("scroll", hideSelectionBubble);
  note.addEventListener("scroll", hideSelectionBubble);
  bubble.addEventListener("mousedown", (event) => event.preventDefault());
  bubble.addEventListener("click", () => {
    if (!selectedPdfText) return;
    const question = $("question");
    const prefix = question.value.trim() ? `${question.value.trim()}\n\n` : "";
    question.value = `${prefix}${selectedPdfText}`;
    question.focus();
    question.setSelectionRange(question.value.length, question.value.length);
    hideSelectionBubble();
  });
  document.addEventListener("mousedown", (event) => {
    if (!bubble.contains(event.target) && !viewer.contains(event.target) && !note.contains(event.target)) {
      hideSelectionBubble();
    }
  });
}

function setupPdfZoomControls() {
  updatePdfZoomControls();
  const crop = document.querySelector(".pdf-viewer-crop");
  $("pdfZoomOutBtn").addEventListener("click", () => {
    setPdfZoom(pdfZoom - 0.1);
  });
  $("pdfZoomInBtn").addEventListener("click", () => {
    setPdfZoom(pdfZoom + 0.1);
  });
  $("pdfFitBtn").addEventListener("click", () => {
    setPdfZoom(1);
  });
  crop.addEventListener("wheel", (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setPdfZoom(pdfZoom + (event.deltaY < 0 ? 0.1 : -0.1));
  }, { passive: false });
}

function setupPageCitations() {
  document.addEventListener("click", (event) => {
    const cite = event.target.closest?.(".page-cite");
    if (!cite) return;
    event.preventDefault();
    jumpToPdfPage(cite.dataset.page);
  });
}

function applySavedLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(layoutStorageKey) || "{}");
    if (saved.version !== 2 || !saved.chat) {
      localStorage.removeItem(layoutStorageKey);
      return;
    }
    if (saved.pdf) document.documentElement.style.setProperty("--pdf-pane", saved.pdf);
    if (saved.note) document.documentElement.style.setProperty("--note-pane", saved.note);
    if (saved.chat) document.documentElement.style.setProperty("--chat-pane", saved.chat);
  } catch {
    return;
  }
}

function saveLayout(pdfPercent, notePercent, chatPercent) {
  localStorage.setItem(layoutStorageKey, JSON.stringify({
    version: 2,
    pdf: `${pdfPercent}%`,
    note: `${notePercent}%`,
    chat: `${chatPercent}%`,
  }));
}

function setupResizers() {
  const workspace = document.querySelector(".workspace");
  if (!workspace) return;
  const minPercent = 18;
  let frameRequest = null;

  function currentPercents() {
    const width = workspace.getBoundingClientRect().width;
    const columns = getComputedStyle(workspace).gridTemplateColumns.split(" ").map((value) => parseFloat(value));
    const pdf = (columns[0] / width) * 100;
    const note = (columns[2] / width) * 100;
    const chat = (columns[4] / width) * 100;
    return { pdf, note, chat };
  }

  document.querySelectorAll(".resizer").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handle.setPointerCapture?.(event.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing");
      const mode = handle.dataset.resizer;
      const startX = event.clientX;
      const start = currentPercents();
      const width = workspace.getBoundingClientRect().width;

      function onMove(moveEvent) {
        const delta = ((moveEvent.clientX - startX) / width) * 100;
        let pdf = start.pdf;
        let note = start.note;
        let chat = start.chat;
        if (mode === "note-chat") {
          note = Math.max(minPercent, start.note + delta);
          chat = Math.max(minPercent, start.chat - (note - start.note));
          if (chat <= minPercent) {
            chat = minPercent;
            note = start.note + start.chat - minPercent;
          }
        } else {
          pdf = Math.max(minPercent, start.pdf + delta);
          note = Math.max(minPercent, start.note - (pdf - start.pdf));
          if (note <= minPercent) {
            note = minPercent;
            pdf = start.pdf + start.note - minPercent;
          }
        }
        window.cancelAnimationFrame(frameRequest);
        frameRequest = window.requestAnimationFrame(() => {
          document.documentElement.style.setProperty("--pdf-pane", `${pdf}%`);
          document.documentElement.style.setProperty("--note-pane", `${note}%`);
          document.documentElement.style.setProperty("--chat-pane", `${chat}%`);
        });
      }

      function onUp(upEvent) {
        handle.releasePointerCapture?.(upEvent.pointerId);
        handle.classList.remove("dragging");
        document.body.classList.remove("resizing");
        window.cancelAnimationFrame(frameRequest);
        const final = currentPercents();
        saveLayout(
          Math.round(final.pdf * 10) / 10,
          Math.round(final.note * 10) / 10,
          Math.round(final.chat * 10) / 10
        );
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  });
}

function setupSidebarAutoHide() {
  const sidebar = document.querySelector(".sidebar");
  const hotspot = $("sidebarHotspot");
  let closeTimer = null;
  let pinnedByFocus = false;

  function openSidebar() {
    window.clearTimeout(closeTimer);
    sidebar.classList.add("is-open");
  }

  function scheduleClose() {
    if (pinnedByFocus) return;
    window.clearTimeout(closeTimer);
    closeTimer = window.setTimeout(() => sidebar.classList.remove("is-open"), 220);
  }

  hotspot.addEventListener("mouseenter", openSidebar);
  sidebar.addEventListener("mouseenter", openSidebar);
  sidebar.addEventListener("mouseleave", scheduleClose);
  sidebar.addEventListener("focusin", () => {
    pinnedByFocus = true;
    openSidebar();
  });
  sidebar.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!sidebar.contains(document.activeElement)) {
        pinnedByFocus = false;
        scheduleClose();
      }
    }, 0);
  });
}

async function loadPaper(payload) {
  setBusy("Loading and indexing PDF...");
  try {
    const data = await api("/api/load", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentPaper = data.metadata.paper_id;
    await refreshPaper();
    setBusy();
  } catch (err) {
    setBusy();
    alert(err.message);
  }
}

function addTurn(kind, text) {
  const el = document.createElement("div");
  el.className = `turn ${kind === "user" ? "user" : ""}`;
  const body = kind === "user"
    ? `<pre>${escapeHtml(text)}</pre>`
    : `<div class="markdown-body chat-markdown">${renderMarkdown(text)}</div>`;
  el.innerHTML = `<div class="who">${kind === "user" ? "You" : "Paper"}</div>${body}`;
  $("chatLog").appendChild(el);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
}

function renderWaiting(label) {
  return `
    <div class="llm-waiting" role="status" aria-live="polite">
      <span class="thinking-dots" aria-hidden="true">
        <span></span><span></span><span></span>
      </span>
      <span>${escapeHtml(label)}</span>
    </div>
  `;
}

function addWaitingTurn(label) {
  const el = document.createElement("div");
  el.className = "turn thinking-turn";
  el.innerHTML = `<div class="who">Paper</div>${renderWaiting(label)}`;
  $("chatLog").appendChild(el);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
  return el;
}

function setButtonLoading(button, loading, label) {
  if (!button.dataset.defaultText) button.dataset.defaultText = button.textContent;
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  button.setAttribute("aria-busy", loading ? "true" : "false");
  button.textContent = loading ? label : button.dataset.defaultText;
}

async function init() {
  applySavedLayout();
  health = await api("/api/health");
  populateProviders();
  setBusy();
  setupResizers();
  setupSidebarAutoHide();
  setupPdfSelection();
  setupPdfZoomControls();
  setupPageCitations();
  loadCollections();

  $("provider").addEventListener("change", populateModels);
  $("apiKeyInput").addEventListener("focus", () => {
    if (apiKeyMasked) $("apiKeyInput").value = "";
  });
  $("apiKeyInput").addEventListener("blur", () => {
    if (apiKeyMasked && !$("apiKeyInput").value.trim()) updateApiKeyInput();
  });
  $("saveApiKeyBtn").addEventListener("click", saveApiKey);

  $("searchBtn").addEventListener("click", async () => {
    setBusy("Searching Zotero...");
    try {
      const data = await api(`/api/search?q=${encodeURIComponent($("query").value.trim())}`);
      renderResults(data.matches, "results");
      setBusy();
    } catch (err) {
      setBusy();
      alert(err.message);
    }
  });

  $("query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("searchBtn").click();
  });

  $("collectionLoadBtn").addEventListener("click", loadCollectionItems);

  $("collectionSelect").addEventListener("change", () => {
    if ($("collectionSelect").value) loadCollectionItems();
  });

  $("loadPdfBtn").addEventListener("click", () => {
    const pdfPath = $("pdfPath").value.trim();
    if (pdfPath) loadPaper({ pdf_path: pdfPath });
  });

  $("entryBtn").addEventListener("click", async () => {
    if (!currentEntryUrl) return;
    try {
      await navigator.clipboard.writeText(currentEntryUrl);
      setBusy("Entry link copied.");
      window.setTimeout(() => setBusy(), 1200);
    } catch {
      prompt("Copy this entry link:", currentEntryUrl);
    }
  });

  $("publicationBtn").addEventListener("click", async () => {
    if (!currentPaper) return;
    setBusy("Searching publication info...");
    setButtonLoading($("publicationBtn"), true, "Searching...");
    try {
      const data = await api(`/api/paper/${encodeURIComponent(currentPaper)}/publication`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      formatPublication(data.publication);
      if (data.publication?.status === "not_found") {
        setBusy("No final publication found.");
      } else {
        setBusy("Publication info saved.");
      }
      window.setTimeout(() => setBusy(), 1600);
    } catch (err) {
      alert(err.message);
      setBusy();
    } finally {
      setButtonLoading($("publicationBtn"), false);
    }
  });

  $("noteBtn").addEventListener("click", async () => {
    if (!currentPaper) return;
    setBusy("Generating note...");
    setButtonLoading($("noteBtn"), true, "Generating...");
    const previousNote = $("note").innerHTML;
    $("note").innerHTML = renderWaiting("Generating structured reading note...");
    try {
      const data = await api("/api/note", {
        method: "POST",
        body: JSON.stringify({ paper_id: currentPaper, provider: selectedProvider(), model: selectedModel() }),
      });
      $("note").innerHTML = renderMarkdown(data.note);
      setBusy();
    } catch (err) {
      $("note").innerHTML = previousNote;
      alert(err.message);
      setBusy();
    } finally {
      setButtonLoading($("noteBtn"), false);
    }
  });

  async function sendQuestion() {
    const message = $("question").value.trim();
    if (!currentPaper || !message) return;
    $("question").value = "";
    addTurn("user", message);
    setBusy("Asking paper...");
    setButtonLoading($("askBtn"), true, "Asking...");
    const waitingTurn = addWaitingTurn("Thinking...");
    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ paper_id: currentPaper, message, provider: selectedProvider(), model: selectedModel() }),
      });
      waitingTurn.remove();
      addTurn("assistant", data.answer);
      $("sources").textContent = `Retrieved chunks: ${(data.chunks || []).map((c) => c.id).join(", ")}`;
      setBusy();
    } catch (err) {
      waitingTurn.remove();
      alert(err.message);
      setBusy();
    } finally {
      setButtonLoading($("askBtn"), false);
    }
  }

  $("askBtn").addEventListener("click", sendQuestion);

  $("question").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    sendQuestion();
  });

  const params = new URLSearchParams(window.location.search);
  const paper = params.get("paper") || params.get("key");
  if (paper) {
    setBusy("Opening paper entry...");
    try {
      currentPaper = paper;
      await refreshPaper();
      setBusy();
    } catch {
      await loadPaper({ key: paper });
    }
  }
}

init().catch((err) => {
  $("health").textContent = err.message;
});

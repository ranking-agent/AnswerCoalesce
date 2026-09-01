const MODES = {
  enrichment: {
    kicker: "Set enrichment",
    title: "Build an enrichment query",
    description: "Start with two or more entities. AnswerCoalesce will rank concepts that are unexpectedly shared across the set.",
    emptyTitle: "Your enrichment results will appear here",
    emptyCopy: "",
    button: "Run enrichment",
    outputType: "biolink:ChemicalEntity",
    predicate: "biolink:related_to",
    direction: "forward",
    example: ["NCBIGene:5297", "NCBIGene:5298", "NCBIGene:5290"],
  },
  edgar: {
    kicker: "Local rule inference",
    title: "Build an EDGAR query",
    description: "Start with one entity. EDGAR enriches its local neighborhood into rules, then applies those rules to rank new answers.",
    emptyTitle: "Your EDGAR inferences will appear here",
    emptyCopy: "Add one concept, define the target relationship, and let EDGAR learn and apply local rules.",
    button: "Run EDGAR",
    outputType: "biolink:Drug",
    predicate: "biolink:treats",
    direction: "reverse",
    example: ["MONDO:0004975"],
  },
};

const EXCLUDED_PREDICATES = [
  "biolink:causes",
  "biolink:biomarker_for",
  "biolink:contraindicated_for",
  "biolink:contributes_to",
  "biolink:has_adverse_event",
  "biolink:causes_adverse_event",
].join("\n");

const QUALIFIER_TYPE_SUGGESTIONS = [
  { id: "biolink:qualified_predicate", label: "Qualified predicate", placeholder: "biolink:causes" },
  { id: "biolink:object_aspect_qualifier", label: "Object aspect", placeholder: "activity_or_abundance" },
  { id: "biolink:object_direction_qualifier", label: "Object direction", placeholder: "increased" },
  { id: "biolink:causal_mechanism_qualifier", label: "Causal mechanism", placeholder: "activation" },
  { id: "biolink:species_context_qualifier", label: "Species context", placeholder: "NCBITaxon:9606" },
  { id: "biolink:anatomical_context_qualifier", label: "Anatomical context", placeholder: "UBERON:0000955" },
  { id: "biolink:subject_aspect_qualifier", label: "Subject aspect", placeholder: "activity" },
  { id: "biolink:subject_direction_qualifier", label: "Subject direction", placeholder: "increased" },
  { id: "biolink:sex_qualifier", label: "Sex", placeholder: "female" },
];

const state = {
  activeMode: "enrichment",
  searchController: null,
  searchTimer: null,
  resolutionQueue: [],
  biolinkTypes: {},
  biolinkTypesPromise: null,
  enrichment: createModeState("enrichment"),
  edgar: createModeState("edgar"),
};

function createModeState(mode) {
  const config = MODES[mode];
  return {
    entities: [],
    inputType: "",
    outputType: config.outputType,
    predicate: config.predicate,
    direction: config.direction,
    pvalueThreshold: "0.00001",
    maxResults: "25",
    qualifiers: [],
    maxRules: "100",
    excludedPredicates: EXCLUDED_PREDICATES,
    response: null,
    elapsedSeconds: null,
    error: null,
    loading: false,
    queryEntities: [],
    edgarStage: "new",
  };
}

const elements = {
  tabs: [...document.querySelectorAll(".mode-tab")],
  form: document.querySelector("#query-form"),
  modeKicker: document.querySelector("#mode-kicker"),
  composerTitle: document.querySelector("#composer-title"),
  modeDescription: document.querySelector("#mode-description"),
  loadExample: document.querySelector("#load-example"),
  entitySearch: document.querySelector("#entity-search"),
  searchButton: document.querySelector("#search-button"),
  searchResults: document.querySelector("#search-results"),
  pasteBlock: document.querySelector("#paste-block"),
  pasteInput: document.querySelector("#paste-input"),
  resolvePaste: document.querySelector("#resolve-paste"),
  resolutionQueue: document.querySelector("#resolution-queue"),
  resolutionItems: document.querySelector("#resolution-items"),
  addAllResolution: document.querySelector("#add-all-resolution"),
  clearResolution: document.querySelector("#clear-resolution"),
  entityList: document.querySelector("#entity-list"),
  entityCount: document.querySelector("#entity-count"),
  typeBlock: document.querySelector("#type-block"),
  typeOptions: document.querySelector("#type-options"),
  typeHelp: document.querySelector("#type-help"),
  outputType: document.querySelector("#output-type"),
  predicate: document.querySelector("#predicate"),
  directions: [...document.querySelectorAll('input[name="direction"]')],
  forwardLabel: document.querySelector("#forward-label"),
  reverseLabel: document.querySelector("#reverse-label"),
  qualifierRows: document.querySelector("#qualifier-rows"),
  addQualifier: document.querySelector("#add-qualifier"),
  pvalueThreshold: document.querySelector("#pvalue-threshold"),
  maxResults: document.querySelector("#max-results"),
  edgarSettings: document.querySelector("#edgar-settings"),
  maxRules: document.querySelector("#max-rules"),
  excludedPredicates: document.querySelector("#excluded-predicates"),
  queryPreview: document.querySelector("#query-preview"),
  validationMessage: document.querySelector("#validation-message"),
  runQuery: document.querySelector("#run-query"),
  runQueryLabel: document.querySelector("#run-query span"),
  resultsTitle: document.querySelector("#results-title"),
  edgarResultTabs: document.querySelector("#edgar-result-tabs"),
  edgarStageButtons: [...document.querySelectorAll("[data-edgar-stage]")],
  edgarMatchCount: document.querySelector("#edgar-match-count"),
  edgarRuleCount: document.querySelector("#edgar-rule-count"),
  edgarNewCount: document.querySelector("#edgar-new-count"),
  resultSummary: document.querySelector("#result-summary"),
  resultsBody: document.querySelector("#results-body"),
  emptyTitle: document.querySelector("#empty-title"),
  downloadResults: document.querySelector("#download-results"),
  drawerBackdrop: document.querySelector("#drawer-backdrop"),
  resultDrawer: document.querySelector("#result-drawer"),
  closeDrawer: document.querySelector("#close-drawer"),
  drawerTitle: document.querySelector("#drawer-title"),
  drawerBody: document.querySelector("#drawer-body"),
  toast: document.querySelector("#toast"),
};

function currentState() {
  return state[state.activeMode];
}

function shortBiolink(value) {
  return (value || "").replace(/^biolink:/, "").replaceAll("_", " ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isCurie(value) {
  return /^[A-Za-z][A-Za-z0-9_.-]*:\S+$/.test(value);
}

function parseList(value) {
  return [...new Set(
    value
      .split(/[\n,;\t]+/)
      .map((item) => item.trim())
      .filter(Boolean),
  )];
}

function formatNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "n/a";
  }
  const number = Number(value);
  if (number !== 0 && Math.abs(number) < 0.001) {
    return number.toExponential(2);
  }
  return number.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatScore(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "n/a";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function asArray(value) {
  if (value === undefined || value === null) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function normalizeQualifierType(value) {
  const qualifierType = value.trim();
  if (!qualifierType || qualifierType.includes(":")) {
    return qualifierType;
  }
  return `biolink:${qualifierType}`;
}

function qualifierTypeLabel(qualifierType) {
  return QUALIFIER_TYPE_SUGGESTIONS.find(
    (suggestion) => suggestion.id === qualifierType,
  )?.label || shortBiolink(qualifierType);
}

function qualifiersForEdges(edgeOrEdges) {
  const edges = Array.isArray(edgeOrEdges) ? edgeOrEdges : [edgeOrEdges];
  const qualifiers = new Map();
  edges.filter(Boolean).forEach((edge) => {
    asArray(edge.qualifiers).forEach((qualifier) => {
      const type = qualifier.qualifier_type_id || "";
      const value = qualifier.qualifier_value || "";
      if (type && value) {
        qualifiers.set(`${type}\u0000${value}`, { type, value });
      }
    });
  });
  return [...qualifiers.values()];
}

function renderQualifierPills(edgeOrEdges) {
  return qualifiersForEdges(edgeOrEdges).map(({ type, value }) => `
    <span class="meta-pill qualifier">
      ${escapeHtml(qualifierTypeLabel(type))}: ${escapeHtml(shortBiolink(value))}
    </span>
  `).join("");
}

function renderRelationshipQualifiers(edge) {
  const pills = renderQualifierPills(edge);
  return pills ? `<div class="relationship-qualifiers">${pills}</div>` : "";
}

function taxonLabel(taxa = []) {
  if (taxa.includes("NCBITaxon:9606")) {
    return "human";
  }
  if (taxa.includes("NCBITaxon:10090")) {
    return "mouse";
  }
  return taxa[0] || "";
}

function sortCandidates(candidates, term) {
  const query = term.trim();
  const lowerQuery = query.toLowerCase();
  return [...candidates].sort((left, right) => {
    const exactCaseDifference = Number((right.label || "") === query)
      - Number((left.label || "") === query);
    if (exactCaseDifference) {
      return exactCaseDifference;
    }
    const humanDifference = Number((right.taxa || []).includes("NCBITaxon:9606"))
      - Number((left.taxa || []).includes("NCBITaxon:9606"));
    if (humanDifference) {
      return humanDifference;
    }
    const exactDifference = Number((right.label || "").toLowerCase() === lowerQuery)
      - Number((left.label || "").toLowerCase() === lowerQuery);
    if (exactDifference) {
      return exactDifference;
    }
    return Number(right.score || 0) - Number(left.score || 0);
  });
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 3600);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail || `Request failed with HTTP ${response.status}.`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

async function loadBiolinkTypes() {
  try {
    const payload = await fetchJson("/ui-api/biolink-types");
    state.biolinkTypes = payload.types || {};
  } catch (error) {
    console.error("Could not load Biolink type hierarchy.", error);
  }
}

function mostSpecificCategory(categories, requestedType) {
  const requestedDepth = state.biolinkTypes[requestedType]?.depth || 0;
  const concrete = unique(categories).filter((category) => {
    const metadata = state.biolinkTypes[category];
    return metadata && !metadata.abstract && !metadata.mixin;
  });
  const selected = concrete.sort((left, right) => {
    return state.biolinkTypes[right].depth - state.biolinkTypes[left].depth;
  })[0];
  if (!selected || selected === requestedType) {
    return "";
  }
  if (requestedDepth && state.biolinkTypes[selected].depth <= requestedDepth) {
    return "";
  }
  return selected;
}

function syncStateFromForm() {
  const modeState = currentState();
  modeState.outputType = elements.outputType.value.trim();
  modeState.predicate = elements.predicate.value.trim();
  modeState.direction = elements.directions.find((input) => input.checked)?.value || "forward";
  modeState.qualifiers = [...elements.qualifierRows.querySelectorAll(".qualifier-row")].map((row) => ({
    type: row.querySelector(".qualifier-type").value === "__custom__"
      ? row.querySelector(".qualifier-custom-type").value.trim()
      : row.querySelector(".qualifier-type").value,
    value: row.querySelector(".qualifier-value").value.trim(),
  }));
  modeState.pvalueThreshold = elements.pvalueThreshold.value;
  modeState.maxResults = elements.maxResults.value;
  modeState.maxRules = elements.maxRules.value;
  modeState.excludedPredicates = elements.excludedPredicates.value;
}

function renderMode() {
  const config = MODES[state.activeMode];
  const modeState = currentState();
  state.searchController?.abort();
  elements.modeKicker.textContent = config.kicker;
  elements.composerTitle.textContent = config.title;
  elements.modeDescription.textContent = config.description;
  elements.runQueryLabel.textContent = config.button;
  elements.emptyTitle.textContent = config.emptyTitle;
  elements.outputType.value = modeState.outputType;
  elements.predicate.value = modeState.predicate;
  elements.pvalueThreshold.value = modeState.pvalueThreshold;
  elements.maxResults.value = modeState.maxResults;
  elements.maxRules.value = modeState.maxRules;
  elements.excludedPredicates.value = modeState.excludedPredicates;
  elements.edgarSettings.hidden = state.activeMode !== "edgar";
  elements.pasteBlock.hidden = state.activeMode === "edgar";
  elements.directions.forEach((input) => {
    input.checked = input.value === modeState.direction;
  });
  renderQualifierRows();
  elements.tabs.forEach((tab) => {
    const active = tab.dataset.mode === state.activeMode;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  state.resolutionQueue = [];
  elements.pasteInput.value = "";
  elements.entitySearch.value = "";
  hideSearchResults();
  renderResolutionQueue();
  renderEntities();
  renderResults();
}

function renderQualifierRows() {
  const qualifiers = currentState().qualifiers;
  if (!qualifiers.length) {
    elements.qualifierRows.innerHTML = '<p class="empty-inline">No qualifiers. The query uses the base predicate.</p>';
    return;
  }
  elements.qualifierRows.innerHTML = qualifiers.map(renderQualifierRow).join("");
}

function renderQualifierRow(qualifier, index) {
  const knownType = QUALIFIER_TYPE_SUGGESTIONS.find((option) => option.id === qualifier.type);
  const selectedType = knownType?.id || "__custom__";
  const valuePlaceholder = knownType?.placeholder || "Qualifier value";
  return `
    <div class="qualifier-row" data-qualifier-index="${index}">
      <label>
        Type
        <select class="qualifier-type">
          ${QUALIFIER_TYPE_SUGGESTIONS.map((option) => `
            <option value="${escapeHtml(option.id)}" ${option.id === selectedType ? "selected" : ""}>${escapeHtml(option.label)}</option>
          `).join("")}
          <option value="__custom__" ${selectedType === "__custom__" ? "selected" : ""}>Other Biolink qualifier</option>
        </select>
        <input class="qualifier-custom-type" value="${knownType ? "" : escapeHtml(qualifier.type)}" placeholder="biolink:custom_qualifier" spellcheck="false" ${knownType ? "hidden" : ""}>
      </label>
      <label>
        Value
        <input class="qualifier-value" list="qualifier-value-list" value="${escapeHtml(qualifier.value)}" placeholder="${escapeHtml(valuePlaceholder)}" spellcheck="false">
      </label>
      <button class="remove-qualifier" type="button" data-remove-qualifier="${index}" aria-label="Remove qualifier">&times;</button>
    </div>
  `;
}

function getPossibleTypes(entities) {
  if (!entities.length) {
    return { types: [], shared: true };
  }
  const typeSets = entities.map((entity) => new Set(entity.types || []));
  const shared = [...typeSets[0]].filter((type) => typeSets.every((set) => set.has(type)));
  if (shared.length) {
    return { types: shared, shared: true };
  }
  return { types: unique(entities.flatMap((entity) => entity.types || [])), shared: false };
}

function renderEntities() {
  const modeState = currentState();
  elements.entityCount.textContent = String(modeState.entities.length);
  if (!modeState.entities.length) {
    elements.entityList.innerHTML = '<p class="empty-inline">No inputs yet. Search, paste, or load the example.</p>';
    elements.typeBlock.hidden = true;
    modeState.inputType = "";
    updateDirectionLabels();
    updateQueryPreview();
    return;
  }

  elements.entityList.innerHTML = modeState.entities.map((entity, index) => `
    <div class="entity-card" style="animation-delay:${index * 35}ms">
      <div>
        <strong>${escapeHtml(entity.label || entity.curie)}</strong>
        <small>${escapeHtml(entity.curie)}</small>
      </div>
      <button class="remove-entity" type="button" data-remove-curie="${escapeHtml(entity.curie)}" aria-label="Remove ${escapeHtml(entity.label || entity.curie)}">&times;</button>
    </div>
  `).join("");

  elements.entityList.querySelectorAll("[data-remove-curie]").forEach((button) => {
    button.addEventListener("click", () => {
      modeState.entities = modeState.entities.filter((entity) => entity.curie !== button.dataset.removeCurie);
      renderEntities();
    });
  });

  const possible = getPossibleTypes(modeState.entities);
  if (!possible.types.includes(modeState.inputType)) {
    modeState.inputType = possible.types[0] || "";
  }
  elements.typeBlock.hidden = false;
  elements.typeHelp.textContent = possible.shared
    ? "These NodeNorm types are shared by every selected input."
    : "No type is shared by every input. Choose a type intentionally or revise the set.";
  elements.typeOptions.innerHTML = possible.types.length
    ? possible.types.map((type) => `
      <label class="type-option">
        <input type="radio" name="input-type" value="${escapeHtml(type)}" ${type === modeState.inputType ? "checked" : ""}>
        <span>${escapeHtml(shortBiolink(type))}</span>
      </label>
    `).join("")
    : '<p class="empty-inline">NodeNorm returned no semantic types for this input.</p>';
  elements.typeOptions.querySelectorAll('input[name="input-type"]').forEach((input) => {
    input.addEventListener("change", () => {
      modeState.inputType = input.value;
      updateDirectionLabels();
      updateQueryPreview();
    });
  });
  updateDirectionLabels();
  updateQueryPreview();
}

function updateDirectionLabels() {
  const modeState = currentState();
  const inputLabel = shortBiolink(modeState.inputType) || "inputs";
  const outputLabel = shortBiolink(elements.outputType.value.trim()) || "results";
  elements.forwardLabel.textContent = `${inputLabel} -> ${outputLabel}`;
  elements.reverseLabel.textContent = `${outputLabel} -> ${inputLabel}`;
}

async function normalizeAndAdd(candidates, targetMode = state.activeMode) {
  const curies = unique(candidates.map((candidate) => candidate.curie));
  if (!curies.length) {
    return;
  }
  const payload = await fetchJson("/ui-api/normalize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ curies }),
  });
  const modeState = state[targetMode];
  const nextEntities = payload.entities || [];
  if (targetMode === "edgar" && nextEntities.length) {
    modeState.entities = [nextEntities[0]];
    if (curies.length > 1) {
      showToast("EDGAR accepts one input; the first resolved concept was selected.");
    }
  } else {
    const existing = new Set(modeState.entities.map((entity) => entity.curie));
    nextEntities.forEach((entity) => {
      if (!existing.has(entity.curie)) {
        modeState.entities.push(entity);
        existing.add(entity.curie);
      }
    });
  }
  if (state.activeMode === targetMode) {
    renderEntities();
  }
}

async function addCandidate(candidate) {
  const targetMode = state.activeMode;
  try {
    await normalizeAndAdd([candidate], targetMode);
    if (state.activeMode === targetMode) {
      elements.entitySearch.value = "";
      hideSearchResults();
    }
  } catch (error) {
    showToast(`Could not normalize ${candidate.curie}: ${error.message}`);
  }
}

function renderSearchResults(results, directValue = "") {
  const options = [];
  if (isCurie(directValue) && !results.some((result) => result.curie === directValue)) {
    options.push({ curie: directValue, label: `Use ${directValue}`, types: [] });
  }
  options.push(...sortCandidates(results, directValue));
  if (!options.length) {
    elements.searchResults.innerHTML = '<p class="empty-inline">No Name Resolver matches found.</p>';
    elements.searchResults.hidden = false;
    return;
  }
  elements.searchResults.innerHTML = options.map((result, index) => `
    <button class="search-result" type="button" role="option" data-result-index="${index}">
      <span>
        <strong>${escapeHtml(result.label || result.curie)}</strong>
        <small>${escapeHtml(result.curie)}</small>
      </span>
      <span class="result-tags">
        ${taxonLabel(result.taxa) ? `<span class="mini-taxon">${escapeHtml(taxonLabel(result.taxa))}</span>` : ""}
        <span class="mini-type">${escapeHtml(shortBiolink(result.types?.[0]) || "CURIE")}</span>
      </span>
    </button>
  `).join("");
  elements.searchResults.hidden = false;
  elements.searchResults.querySelectorAll("[data-result-index]").forEach((button) => {
    button.addEventListener("click", () => addCandidate(options[Number(button.dataset.resultIndex)]));
  });
}

function hideSearchResults() {
  elements.searchResults.hidden = true;
  elements.searchResults.innerHTML = "";
}

async function searchNames() {
  const query = elements.entitySearch.value.trim();
  const targetMode = state.activeMode;
  if (query.length < 2) {
    hideSearchResults();
    return;
  }
  if (state.searchController) {
    state.searchController.abort();
  }
  state.searchController = new AbortController();
  elements.searchResults.hidden = false;
  elements.searchResults.innerHTML = '<p class="empty-inline">Searching Name Resolver...</p>';
  try {
    const payload = await fetchJson(`/ui-api/resolve?q=${encodeURIComponent(query)}&limit=8`, {
      signal: state.searchController.signal,
    });
    if (state.activeMode === targetMode) {
      renderSearchResults(payload.results || [], query);
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      elements.searchResults.innerHTML = `<p class="empty-inline">${escapeHtml(error.message)}</p>`;
    }
  }
}

async function resolvePastedEntries() {
  const terms = parseList(elements.pasteInput.value);
  const targetMode = state.activeMode;
  if (!terms.length) {
    showToast("Paste at least one name or CURIE.");
    return;
  }
  elements.resolvePaste.disabled = true;
  elements.resolvePaste.textContent = "Resolving...";
  try {
    const names = terms.filter((term) => !isCurie(term));
    let resolvedNames = {};
    if (names.length) {
      const payload = await fetchJson("/ui-api/resolve-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ terms: names, limit: 5 }),
      });
      resolvedNames = payload.results || {};
    }
    if (state.activeMode !== targetMode) {
      return;
    }
    state.resolutionQueue = terms.map((term) => ({
      term,
      candidates: isCurie(term)
        ? [{ curie: term, label: term, types: [] }]
        : sortCandidates(resolvedNames[term] || [], term),
    }));
    renderResolutionQueue();
  } catch (error) {
    showToast(`Name resolution failed: ${error.message}`);
  } finally {
    elements.resolvePaste.disabled = false;
    elements.resolvePaste.textContent = "Resolve pasted entries";
  }
}

function renderResolutionQueue() {
  elements.resolutionQueue.hidden = state.resolutionQueue.length === 0;
  if (!state.resolutionQueue.length) {
    elements.resolutionItems.innerHTML = "";
    return;
  }
  elements.resolutionItems.innerHTML = state.resolutionQueue.map((item, index) => {
    if (!item.candidates.length) {
      return `
        <div class="resolution-item">
          <span class="resolution-term">${escapeHtml(item.term)}</span>
          <span class="resolution-missing">No match</span>
          <button class="text-button" type="button" data-dismiss-resolution="${index}">Dismiss</button>
        </div>
      `;
    }
    return `
      <div class="resolution-item">
        <span class="resolution-term" title="${escapeHtml(item.term)}">${escapeHtml(item.term)}</span>
        <select data-resolution-select="${index}" aria-label="Choose a match for ${escapeHtml(item.term)}">
          ${item.candidates.map((candidate, candidateIndex) => `
            <option value="${candidateIndex}">${escapeHtml(candidate.label || candidate.curie)}${taxonLabel(candidate.taxa) ? ` [${escapeHtml(taxonLabel(candidate.taxa))}]` : ""} - ${escapeHtml(candidate.curie)}</option>
          `).join("")}
        </select>
        <button class="secondary-button compact" type="button" data-add-resolution="${index}">Add</button>
      </div>
    `;
  }).join("");

  elements.resolutionItems.querySelectorAll("[data-add-resolution]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.addResolution);
      const select = elements.resolutionItems.querySelector(`[data-resolution-select="${index}"]`);
      const candidate = state.resolutionQueue[index].candidates[Number(select.value)];
      button.disabled = true;
      button.textContent = "Adding...";
      try {
        await normalizeAndAdd([candidate]);
        state.resolutionQueue.splice(index, 1);
        renderResolutionQueue();
      } catch (error) {
        showToast(`Could not normalize ${candidate.curie}: ${error.message}`);
        button.disabled = false;
        button.textContent = "Add";
      }
    });
  });
  elements.resolutionItems.querySelectorAll("[data-dismiss-resolution]").forEach((button) => {
    button.addEventListener("click", () => {
      state.resolutionQueue.splice(Number(button.dataset.dismissResolution), 1);
      renderResolutionQueue();
    });
  });
}

function selectedResolutionCandidates() {
  return state.resolutionQueue.flatMap((item, index) => {
    if (!item.candidates.length) {
      return [];
    }
    const select = elements.resolutionItems.querySelector(`[data-resolution-select="${index}"]`);
    return [item.candidates[Number(select?.value || 0)]];
  });
}

function buildQuery() {
  syncStateFromForm();
  const modeState = currentState();
  if (!modeState.inputType || !modeState.outputType || !modeState.predicate) {
    return null;
  }
  const inputNode = {
    categories: [modeState.inputType],
  };
  if (state.activeMode === "enrichment") {
    inputNode.ids = [`uuid:answercoalesce-ui-${Date.now().toString(36)}`];
    inputNode.member_ids = modeState.entities.map((entity) => entity.curie);
    inputNode.set_interpretation = "MANY";
  } else {
    inputNode.ids = [modeState.entities[0]?.curie].filter(Boolean);
  }

  const edge = {
    subject: modeState.direction === "forward" ? "input" : "output",
    object: modeState.direction === "forward" ? "output" : "input",
    predicates: [modeState.predicate],
  };
  if (state.activeMode === "edgar") {
    edge.knowledge_type = "inferred";
  }
  const qualifiers = modeState.qualifiers
    .filter((qualifier) => qualifier.type && qualifier.value)
    .map((qualifier) => ({
      qualifier_type_id: normalizeQualifierType(qualifier.type),
      qualifier_value: qualifier.value,
    }));
  if (qualifiers.length) {
    edge.qualifier_constraints = [{
      qualifier_set: qualifiers,
    }];
  }

  const parameters = {
    pvalue_threshold: Number(modeState.pvalueThreshold),
    max_results: Number(modeState.maxResults),
  };
  if (state.activeMode === "edgar") {
    parameters.max_rules = Number(modeState.maxRules);
    parameters.predicate_constraint_style = "exclude";
    parameters.predicate_constraints = parseList(modeState.excludedPredicates);
  }

  return {
    message: {
      query_graph: {
        nodes: {
          input: inputNode,
          output: { categories: [modeState.outputType] },
        },
        edges: { edge_0: edge },
      },
    },
    parameters,
  };
}

function validateQuery() {
  syncStateFromForm();
  const modeState = currentState();
  if (state.activeMode === "enrichment" && modeState.entities.length < 2) {
    return "Enrichment requires at least two input concepts.";
  }
  if (state.activeMode === "edgar" && modeState.entities.length !== 1) {
    return "EDGAR requires exactly one input concept.";
  }
  if (!modeState.inputType) {
    return "Choose an input type returned by NodeNorm.";
  }
  if (!modeState.outputType.startsWith("biolink:")) {
    return "Output type must be a Biolink category.";
  }
  if (!modeState.predicate.startsWith("biolink:")) {
    return "Predicate must be a Biolink predicate.";
  }
  const populatedQualifiers = modeState.qualifiers.filter(
    (qualifier) => qualifier.type || qualifier.value,
  );
  if (populatedQualifiers.some((qualifier) => !qualifier.type || !qualifier.value)) {
    return "Each relationship qualifier needs both a type and a value.";
  }
  const qualifierTypes = populatedQualifiers.map(
    (qualifier) => normalizeQualifierType(qualifier.type),
  );
  if (qualifierTypes.some((qualifierType) => !qualifierType.startsWith("biolink:"))) {
    return "Qualifier types must be Biolink identifiers.";
  }
  if (new Set(qualifierTypes).size !== qualifierTypes.length) {
    return "A qualifier type can appear only once in this qualifier set.";
  }
  const pvalue = Number(modeState.pvalueThreshold);
  if (!Number.isFinite(pvalue) || pvalue < 0 || pvalue > 1) {
    return "P-value threshold must be between 0 and 1.";
  }
  return "";
}

function updateQueryPreview() {
  syncStateFromForm();
  elements.validationMessage.textContent = "";
  const query = buildQuery();
  elements.queryPreview.textContent = query
    ? JSON.stringify(query, null, 2)
    : "Add inputs and choose a NodeNorm type to build a request.";
}

function attributesByType(edge) {
  const values = {};
  (edge?.attributes || []).forEach((attribute) => {
    const key = attribute.attribute_type_id;
    values[key] ??= [];
    const value = attribute.value;
    if (Array.isArray(value)) {
      values[key].push(...value);
    } else {
      values[key].push(value);
    }
  });
  return values;
}

function supportGraphIdsForEdge(edge) {
  return unique(
    asArray(attributesByType(edge)["biolink:support_graphs"]).flat(Infinity),
  );
}

function supportPathsForEdge(edge, edges, auxiliaryGraphs) {
  return supportGraphIdsForEdge(edge).map((graphId) => ({
    id: graphId,
    edges: (auxiliaryGraphs[graphId]?.edges || [])
      .map((supportEdgeId) => ({
        id: supportEdgeId,
        ...edges[supportEdgeId],
      }))
      .filter((supportEdge) => supportEdge.subject && supportEdge.object),
  }));
}

function sourcesForEdges(sourceEdges) {
  return unique(sourceEdges.flatMap(
    (edge) => (edge?.sources || []).map((source) => source.resource_id),
  ));
}

function memberIdsForSetNode(node) {
  return unique((node?.attributes || []).flatMap((attribute) => {
    if (attribute.attribute_type_id !== "biolink:member_ids") {
      return [];
    }
    if (Array.isArray(attribute.value)) {
      return attribute.value;
    }
    if (Array.isArray(attribute.value?.sources)) {
      return attribute.value.sources;
    }
    return typeof attribute.value === "string" ? [attribute.value] : [];
  }));
}

function summarizeResponse(response, modeState) {
  const message = response?.message || {};
  const nodes = message.knowledge_graph?.nodes || {};
  const edges = message.knowledge_graph?.edges || {};
  const auxiliaryGraphs = message.auxiliary_graphs || {};
  const queryEntities = modeState.queryEntities || [];
  return (message.results || []).map((result, index) => {
    const outputId = result.node_bindings?.output?.[0]?.id;
    const node = nodes[outputId] || {};
    const analysis = result.analyses?.[0] || {};
    const edgeId = analysis.edge_bindings?.edge_0?.[0]?.id;
    const edge = edges[edgeId] || {};
    const attributes = attributesByType(edge);
    const supportGraphIds = unique([
      ...supportGraphIdsForEdge(edge),
      ...asArray(analysis.support_graphs).flat(Infinity),
    ]);
    const supportPaths = supportGraphIds.map((graphId) => ({
      id: graphId,
      edges: (auxiliaryGraphs[graphId]?.edges || [])
        .map((supportEdgeId) => ({
          id: supportEdgeId,
          ...edges[supportEdgeId],
        }))
        .filter((supportEdge) => supportEdge.subject && supportEdge.object),
    }));
    const sources = sourcesForEdges([
      edge,
      ...supportPaths.flatMap((path) => path.edges),
    ]);
    const pvalue = (
      attributes["biolink:p_value"]?.[0]
      ?? attributes["biolink:p-value"]?.[0]
    );
    const evidenceNodeIds = new Set(
      supportPaths.flatMap((path) => path.edges.flatMap(
        (supportEdge) => [supportEdge.subject, supportEdge.object],
      )),
    );
    const matchedInputs = queryEntities.filter((entity) => evidenceNodeIds.has(entity.curie));
    return {
      index,
      result,
      outputId,
      name: node.name || outputId || `Result ${index + 1}`,
      categories: node.categories || [],
      score: analysis.score,
      edgeId,
      edge,
      pvalue,
      specificCategory: mostSpecificCategory(node.categories || [], modeState.outputType),
      matchedInputs,
      totalInputs: queryEntities.length,
      supportGraphIds,
      supportPaths,
      sources,
    };
  });
}

function summarizeEdgarStages(response, modeState) {
  const message = response?.message || {};
  const nodes = message.knowledge_graph?.nodes || {};
  const edges = message.knowledge_graph?.edges || {};
  const auxiliaryGraphs = message.auxiliary_graphs || {};
  const inputId = (
    modeState.queryEntities?.[0]?.curie
    || message.query_graph?.nodes?.input?.ids?.[0]
  );
  const setEntry = Object.entries(nodes).find(
    ([, node]) => node.is_set || memberIdsForSetNode(node).length,
  );
  const setId = setEntry?.[0];
  const setNode = setEntry?.[1] || {};
  const memberIds = unique([
    ...memberIdsForSetNode(setNode),
    ...Object.values(edges)
      .filter((edge) => edge.predicate === "biolink:member_of" && edge.object === setId)
      .map((edge) => edge.subject),
  ]);

  const matches = memberIds.map((memberId) => {
    const node = nodes[memberId] || {};
    const directEdges = Object.entries(edges)
      .filter(([, edge]) => (
        (edge.subject === memberId && edge.object === inputId)
        || (edge.subject === inputId && edge.object === memberId)
      ))
      .map(([id, edge]) => ({ id, ...edge }));
    return {
      id: memberId,
      name: node.name || memberId,
      categories: node.categories || [],
      specificCategory: mostSpecificCategory(node.categories || [], modeState.outputType),
      directEdges,
      sources: sourcesForEdges(directEdges),
      node,
    };
  }).sort((left, right) => left.name.localeCompare(right.name));

  const matchById = new Map(matches.map((match) => [match.id, match]));
  const rules = Object.entries(edges).flatMap(([edgeId, edge]) => {
    const touchesSet = edge.subject === setId || edge.object === setId;
    if (!touchesSet || edge.predicate === "biolink:member_of") {
      return [];
    }
    const attributes = attributesByType(edge);
    const pvalue = attributes["biolink:p_value"]?.[0] ?? attributes["biolink:p-value"]?.[0];
    if (pvalue === undefined) {
      return [];
    }
    const ruleId = edge.subject === setId ? edge.object : edge.subject;
    if (!ruleId || ruleId === inputId) {
      return [];
    }
    const node = nodes[ruleId] || {};
    const supportGraphIds = supportGraphIdsForEdge(edge);
    const supportPaths = supportPathsForEdge(edge, edges, auxiliaryGraphs);
    const evidenceNodeIds = new Set(
      supportPaths.flatMap((path) => path.edges.flatMap(
        (supportEdge) => [supportEdge.subject, supportEdge.object],
      )),
    );
    const matchedInputs = memberIds
      .filter((memberId) => evidenceNodeIds.has(memberId))
      .map((memberId) => matchById.get(memberId))
      .filter(Boolean);
    return [{
      id: ruleId,
      edgeId,
      edge,
      name: node.name || ruleId,
      categories: node.categories || [],
      specificCategory: mostSpecificCategory(node.categories || [], ""),
      pvalue,
      matchedInputs,
      totalInputs: memberIds.length,
      supportGraphIds,
      supportPaths,
      sources: sourcesForEdges([
        edge,
        ...supportPaths.flatMap((path) => path.edges),
      ]),
      setId,
    }];
  }).sort((left, right) => (
    Number(left.pvalue) - Number(right.pvalue)
    || left.name.localeCompare(right.name)
  ));

  return {
    setId,
    matches,
    rules,
    newEntities: summarizeResponse(response, modeState),
  };
}

function renderEdgarStageTabs(stages) {
  const activeStage = currentState().edgarStage;
  elements.edgarResultTabs.hidden = false;
  elements.edgarMatchCount.textContent = `${stages.matches.length} found`;
  elements.edgarRuleCount.textContent = `${stages.rules.length} learned`;
  elements.edgarNewCount.textContent = `${stages.newEntities.length} ranked`;
  elements.edgarStageButtons.forEach((button) => {
    const active = button.dataset.edgarStage === activeStage;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function bindResultCards(selector, summaries, openDrawer) {
  elements.resultsBody.querySelectorAll(selector).forEach((card) => {
    const open = () => openDrawer(summaries[Number(card.dataset.resultIndex)]);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
}

function renderEdgarMatches(stages, modeState) {
  const relationshipCount = stages.matches.reduce(
    (total, match) => total + match.directEdges.length,
    0,
  );
  const sourceCount = unique(stages.matches.flatMap((match) => match.sources)).length;
  elements.resultSummary.innerHTML = `
    <div class="summary-stat"><strong>${stages.matches.length}</strong><span>existing matches</span></div>
    <div class="summary-stat"><strong>${relationshipCount}</strong><span>known relationships</span></div>
    <div class="summary-stat"><strong>${sourceCount}</strong><span>evidence sources</span></div>
  `;
  elements.resultSummary.hidden = false;

  if (!stages.matches.length) {
    elements.resultsBody.innerHTML = `
      <div class="empty-state compact-empty">
        <h3>No existing matches were retained</h3>
        <p>EDGAR did not return a direct-answer set for this query.</p>
      </div>
    `;
    return;
  }

  elements.resultsBody.innerHTML = `
    <div class="stage-intro">
      <strong>Entities already known to match the query</strong>
      <span>These form the set EDGAR uses to learn shared rules.</span>
    </div>
    <div class="result-list">
      ${stages.matches.map((match, index) => `
        <article class="result-card stage-result-card" tabindex="0" role="button" data-result-index="${index}" style="animation-delay:${Math.min(index, 12) * 25}ms">
          <span class="result-rank">${index + 1}</span>
          <div class="result-main">
            <h3>${escapeHtml(match.name)}</h3>
            <span class="result-curie">${escapeHtml(match.id)}</span>
            <div class="result-meta">
              ${match.specificCategory ? `<span class="meta-pill">${escapeHtml(shortBiolink(match.specificCategory))}</span>` : ""}
              <span class="meta-pill evidence">${escapeHtml(shortBiolink(match.directEdges[0]?.predicate || modeState.predicate))}</span>
              ${renderQualifierPills(match.directEdges)}
              <span class="meta-pill">${match.sources.length} ${match.sources.length === 1 ? "source" : "sources"}</span>
            </div>
          </div>
          <div class="result-score stage-status">
            <strong>Known</strong>
            <span>match</span>
          </div>
        </article>
      `).join("")}
    </div>
  `;
  bindResultCards("[data-result-index]", stages.matches, openEdgarMatchDrawer);
}

function renderEdgarRules(stages) {
  const coveredMatches = unique(stages.rules.flatMap(
    (rule) => rule.matchedInputs.map((match) => match.id),
  )).length;
  const supportCount = stages.rules.reduce(
    (total, rule) => total + rule.supportGraphIds.length,
    0,
  );
  elements.resultSummary.innerHTML = `
    <div class="summary-stat"><strong>${stages.rules.length}</strong><span>learned rules</span></div>
    <div class="summary-stat"><strong>${coveredMatches}/${stages.matches.length}</strong><span>existing matches covered</span></div>
    <div class="summary-stat"><strong>${supportCount}</strong><span>support graphs</span></div>
  `;
  elements.resultSummary.hidden = false;

  if (!stages.rules.length) {
    elements.resultsBody.innerHTML = `
      <div class="empty-state compact-empty">
        <h3>No learned rules were retained</h3>
        <p>No enrichment rule supported the returned new entities.</p>
      </div>
    `;
    return;
  }

  elements.resultsBody.innerHTML = `
    <div class="stage-intro">
      <strong>Relationships shared by the existing matches</strong>
      <span>Lower p-values indicate stronger enrichment.</span>
    </div>
    <div class="result-list">
      ${stages.rules.map((rule, index) => `
        <article class="result-card rule-result-card" tabindex="0" role="button" data-result-index="${index}" style="--score-width:${Math.max(4, (rule.matchedInputs.length / Math.max(rule.totalInputs, 1)) * 100)}%;animation-delay:${Math.min(index, 12) * 35}ms">
          <span class="result-rank">${index + 1}</span>
          <div class="result-main">
            <h3>${escapeHtml(rule.name)}</h3>
            <span class="result-curie">${escapeHtml(rule.id)}</span>
            <div class="result-meta">
              ${rule.specificCategory ? `<span class="meta-pill">${escapeHtml(shortBiolink(rule.specificCategory))}</span>` : ""}
              <span class="meta-pill evidence">${escapeHtml(shortBiolink(rule.edge.predicate))}</span>
              ${renderQualifierPills(rule.edge)}
              <span class="meta-pill">p ${escapeHtml(formatNumber(rule.pvalue))}</span>
              <span class="meta-pill">${rule.supportGraphIds.length} supports</span>
            </div>
          </div>
          <div class="result-score">
            <strong>${rule.matchedInputs.length}/${rule.totalInputs}</strong>
            <span>matches</span>
          </div>
        </article>
      `).join("")}
    </div>
  `;
  bindResultCards("[data-result-index]", stages.rules, openEdgarRuleDrawer);
}

function renderRankedResults(summaries, modeState, isEdgar = false) {
  const logs = modeState.response.logs || [];
  const evidenceCount = summaries.reduce((total, summary) => total + summary.supportGraphIds.length, 0);
  elements.resultSummary.innerHTML = `
    <div class="summary-stat"><strong>${summaries.length}</strong><span>${isEdgar ? "new entities" : "ranked answers"}</span></div>
    <div class="summary-stat"><strong>${evidenceCount}</strong><span>${isEdgar ? "rule matches" : "support graphs"}</span></div>
    <div class="summary-stat"><strong>${formatNumber(modeState.elapsedSeconds)}s</strong><span>query time</span></div>
  `;
  elements.resultSummary.hidden = false;

  if (!summaries.length) {
    const warnings = logs.filter((log) => log.level === "WARNING" || log.level === "ERROR");
    elements.resultsBody.innerHTML = `
      <div class="empty-state compact-empty">
        <h3>${isEdgar ? "No new entities passed the threshold" : "No ranked answers passed the threshold"}</h3>
        <p>${warnings.length ? escapeHtml(warnings[0].message) : "Try a broader predicate, a higher p-value threshold, or a different output type."}</p>
      </div>
    `;
    return;
  }

  const maxScore = Math.max(...summaries.map((summary) => Number(summary.score) || 0), 0.0001);
  elements.resultsBody.innerHTML = `
    ${isEdgar ? `
      <div class="stage-intro">
        <strong>New entities that match the learned rules</strong>
        <span>Ranked by the combined strength of their matching rules.</span>
      </div>
    ` : ""}
    <div class="result-list">
      ${summaries.map((summary, index) => `
        <article class="result-card" tabindex="0" role="button" data-result-index="${index}" style="--score-width:${Math.max(4, (Number(summary.score || 0) / maxScore) * 100)}%;animation-delay:${Math.min(index, 12) * 35}ms">
          <span class="result-rank">${index + 1}</span>
          <div class="result-main">
            <h3>${escapeHtml(summary.name)}</h3>
            <span class="result-curie">${escapeHtml(summary.outputId)}</span>
            <div class="result-meta">
              ${summary.specificCategory ? `<span class="meta-pill">${escapeHtml(shortBiolink(summary.specificCategory))}</span>` : ""}
              ${isEdgar
                ? `<span class="meta-pill evidence">${summary.supportGraphIds.length} rule matches</span>`
                : `<span class="meta-pill evidence">${summary.matchedInputs.length}/${summary.totalInputs} inputs matched</span>
                   <span class="meta-pill">${summary.supportGraphIds.length} supports</span>`}
              ${renderQualifierPills(summary.edge)}
              ${summary.pvalue !== undefined ? `<span class="meta-pill">p ${escapeHtml(formatNumber(summary.pvalue))}</span>` : ""}
            </div>
          </div>
          <div class="result-score">
            <strong>${escapeHtml(formatScore(summary.score))}</strong>
            <span>score</span>
          </div>
        </article>
      `).join("")}
    </div>
  `;
  bindResultCards("[data-result-index]", summaries, openResultDrawer);
}

function renderResults() {
  const modeState = currentState();
  elements.resultsTitle.textContent = state.activeMode === "edgar" ? "EDGAR results" : "Enrichment results";
  elements.downloadResults.hidden = !modeState.response;
  elements.resultSummary.hidden = true;
  elements.edgarResultTabs.hidden = true;

  if (modeState.loading) {
    elements.resultsBody.innerHTML = `
      <div class="loading-state">
        <div class="query-running"><span class="spinner"></span><span>${state.activeMode === "edgar" ? "Learning local rules and applying them..." : "Calculating set enrichment..."}</span></div>
        <div class="loading-line"></div>
        <div class="loading-line"></div>
        <div class="loading-line"></div>
      </div>
    `;
    return;
  }

  if (modeState.error) {
    elements.resultsBody.innerHTML = `
      <div class="empty-state error-state">
        <h3>The query did not complete</h3>
        <p><code>${escapeHtml(modeState.error)}</code></p>
      </div>
    `;
    return;
  }

  if (!modeState.response) {
    const config = MODES[state.activeMode];
    elements.resultsBody.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="42"></circle>
          <circle cx="37" cy="45" r="8"></circle>
          <circle cx="81" cy="43" r="8"></circle>
          <circle cx="69" cy="82" r="8"></circle>
          <path d="M43 50 63 76M74 49 69 74M45 45h28"></path>
        </svg>
        <h3>${escapeHtml(config.emptyTitle)}</h3>
        ${config.emptyCopy ? `<p>${escapeHtml(config.emptyCopy)}</p>` : ""}
      </div>
    `;
    return;
  }

  if (state.activeMode === "edgar") {
    const stages = summarizeEdgarStages(modeState.response, modeState);
    renderEdgarStageTabs(stages);
    if (modeState.edgarStage === "matches") {
      renderEdgarMatches(stages, modeState);
    } else if (modeState.edgarStage === "rules") {
      renderEdgarRules(stages);
    } else {
      renderRankedResults(stages.newEntities, modeState, true);
    }
    return;
  }

  renderRankedResults(summarizeResponse(modeState.response, modeState), modeState);
}

function nodeName(id, nodes, queryEntities = []) {
  if (id?.startsWith("uuid:")) {
    return state.activeMode === "edgar" ? "Local answer set" : "Input set";
  }
  const resolvedInput = queryEntities.find((entity) => entity.curie === id);
  if (resolvedInput) {
    return resolvedInput.label || resolvedInput.curie;
  }
  return nodes[id]?.name || id;
}

function renderSources(edge) {
  const sources = edge.sources || [];
  if (!sources.length) {
    return "";
  }
  return sources.map((source) => {
    const urls = (source.source_record_urls || [])
      .filter((url) => /^https?:\/\//.test(url))
      .slice(0, 2)
      .map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(source.resource_id)}</a>`)
      .join(", ");
    return urls || escapeHtml(source.resource_id);
  }).join(", ");
}

function renderSupportPaths(paths, nodes, queryEntities, label) {
  if (!paths.length) {
    return "<p>No auxiliary support graphs were attached.</p>";
  }
  return paths.map((path, index) => `
    <details class="evidence-path" ${index === 0 ? "open" : ""}>
      <summary>${escapeHtml(label)} ${index + 1} <span class="source-note">${path.edges.length} edges</span></summary>
      <div class="path-edges">
        ${path.edges.map((supportEdge) => `
          <div class="path-edge">
            ${escapeHtml(nodeName(supportEdge.subject, nodes, queryEntities))}
            <code>-- ${escapeHtml(shortBiolink(supportEdge.predicate))} --&gt;</code>
            ${escapeHtml(nodeName(supportEdge.object, nodes, queryEntities))}
            ${renderRelationshipQualifiers(supportEdge)}
            ${renderSources(supportEdge) ? `<small>Sources: ${renderSources(supportEdge)}</small>` : ""}
          </div>
        `).join("")}
      </div>
    </details>
  `).join("");
}

function showResultDrawer(title, body) {
  elements.drawerTitle.textContent = title;
  elements.drawerBody.innerHTML = body;
  elements.drawerBackdrop.hidden = false;
  elements.resultDrawer.hidden = false;
  elements.closeDrawer.focus();
  document.body.style.overflow = "hidden";
}

function openEdgarMatchDrawer(summary) {
  const response = currentState().response;
  const nodes = response.message?.knowledge_graph?.nodes || {};
  const queryEntities = currentState().queryEntities || [];
  const category = summary.specificCategory || summary.categories[0];
  showResultDrawer(summary.name, `
    <p class="drawer-lead">${escapeHtml(summary.id)}</p>
    <div class="detail-metrics">
      <div class="detail-metric"><strong>${summary.directEdges.length}</strong><span>known relationships</span></div>
      <div class="detail-metric"><strong>${summary.sources.length}</strong><span>evidence sources</span></div>
      <div class="detail-metric"><strong>${escapeHtml(shortBiolink(category) || "n/a")}</strong><span>type</span></div>
    </div>
    <section class="detail-section">
      <h3>Known relationship</h3>
      ${summary.directEdges.length ? summary.directEdges.map((edge) => `
        <div class="relation-line">
          ${escapeHtml(nodeName(edge.subject, nodes, queryEntities))}
          <span class="relation-arrow"> -- ${escapeHtml(shortBiolink(edge.predicate))} --&gt; </span>
          ${escapeHtml(nodeName(edge.object, nodes, queryEntities))}
          ${renderRelationshipQualifiers(edge)}
        </div>
      `).join("") : "<p>The set membership was returned without a direct relationship edge.</p>"}
    </section>
    <section class="detail-section">
      <h3>Evidence sources</h3>
      <p>${summary.sources.length ? summary.sources.map(escapeHtml).join(", ") : "No source metadata was attached."}</p>
    </section>
    <details class="raw-details">
      <summary>Raw direct match</summary>
      <pre>${escapeHtml(JSON.stringify({
        id: summary.id,
        node: summary.node,
        edges: summary.directEdges,
      }, null, 2))}</pre>
    </details>
  `);
}

function openEdgarRuleDrawer(summary) {
  const response = currentState().response;
  const message = response.message || {};
  const nodes = message.knowledge_graph?.nodes || {};
  const queryEntities = currentState().queryEntities || [];
  const subject = nodeName(summary.edge.subject, nodes, queryEntities);
  const object = nodeName(summary.edge.object, nodes, queryEntities);
  showResultDrawer(summary.name, `
    <p class="drawer-lead">${escapeHtml(summary.id)}</p>
    <div class="detail-metrics">
      <div class="detail-metric"><strong>${escapeHtml(formatNumber(summary.pvalue))}</strong><span>p-value</span></div>
      <div class="detail-metric"><strong>${summary.matchedInputs.length}/${summary.totalInputs}</strong><span>existing matches</span></div>
      <div class="detail-metric"><strong>${summary.supportGraphIds.length}</strong><span>support graphs</span></div>
      <div class="detail-metric"><strong>${summary.sources.length}</strong><span>sources</span></div>
    </div>
    <section class="detail-section">
      <h3>Learned rule</h3>
      <div class="relation-line">
        ${escapeHtml(subject)}
        <span class="relation-arrow"> -- ${escapeHtml(shortBiolink(summary.edge.predicate))} --&gt; </span>
        ${escapeHtml(object)}
        ${renderRelationshipQualifiers(summary.edge)}
      </div>
    </section>
    <section class="detail-section">
      <h3>Existing matches supporting this rule</h3>
      <div class="matched-input-list">
        ${summary.matchedInputs.length ? summary.matchedInputs.map((match) => `
          <div class="matched-input">
            <strong>${escapeHtml(match.name)}</strong>
            <code>${escapeHtml(match.id)}</code>
          </div>
        `).join("") : "<p>No individual set members could be recovered from the support graphs.</p>"}
      </div>
    </section>
    <section class="detail-section">
      <h3>Supporting evidence</h3>
      ${renderSupportPaths(summary.supportPaths, nodes, queryEntities, "Support")}
    </section>
    <details class="raw-details">
      <summary>Raw learned rule</summary>
      <pre>${escapeHtml(JSON.stringify({
        edge_id: summary.edgeId,
        edge: summary.edge,
        auxiliary_graphs: Object.fromEntries(summary.supportGraphIds.map(
          (id) => [id, message.auxiliary_graphs?.[id]],
        )),
      }, null, 2))}</pre>
    </details>
  `);
}

function openResultDrawer(summary) {
  const response = currentState().response;
  const message = response.message || {};
  const nodes = message.knowledge_graph?.nodes || {};
  const edge = summary.edge || {};
  const queryEntities = currentState().queryEntities || [];
  const subject = nodeName(edge.subject, nodes, queryEntities);
  const object = nodeName(edge.object, nodes, queryEntities);
  const metrics = state.activeMode === "enrichment"
    ? `
      <div class="detail-metric"><strong>${escapeHtml(formatScore(summary.score))}</strong><span>score</span></div>
      <div class="detail-metric"><strong>${escapeHtml(formatNumber(summary.pvalue))}</strong><span>p-value</span></div>
      <div class="detail-metric"><strong>${summary.matchedInputs.length}/${summary.totalInputs}</strong><span>inputs matched</span></div>
      <div class="detail-metric"><strong>${summary.supportGraphIds.length}</strong><span>support graphs</span></div>
    `
    : `
      <div class="detail-metric"><strong>${escapeHtml(formatScore(summary.score))}</strong><span>score</span></div>
      <div class="detail-metric"><strong>${summary.supportGraphIds.length}</strong><span>rule paths</span></div>
      <div class="detail-metric"><strong>${summary.sources.length}</strong><span>sources</span></div>
    `;

  elements.drawerTitle.textContent = summary.name;
  elements.drawerBody.innerHTML = `
    <p class="drawer-lead">${escapeHtml(summary.outputId)}</p>
    <div class="detail-metrics">
      ${metrics}
    </div>
    <section class="detail-section">
      <h3>Answer relationship</h3>
      <div class="relation-line">
        ${escapeHtml(subject)}
        <span class="relation-arrow"> -- ${escapeHtml(shortBiolink(edge.predicate))} --&gt; </span>
        ${escapeHtml(object)}
        ${renderRelationshipQualifiers(edge)}
      </div>
    </section>
    <section class="detail-section">
      <h3>Evidence sources</h3>
      <p>${summary.sources.length ? summary.sources.map(escapeHtml).join(", ") : "No source metadata was attached."}</p>
    </section>
    ${state.activeMode === "enrichment" ? `
      <section class="detail-section">
        <h3>Matched inputs</h3>
        <div class="matched-input-list">
          ${summary.matchedInputs.length ? summary.matchedInputs.map((entity) => `
            <div class="matched-input">
              <strong>${escapeHtml(entity.label || entity.curie)}</strong>
              <code>${escapeHtml(entity.curie)}</code>
            </div>
          `).join("") : "<p>No selected inputs could be recovered from the support graphs.</p>"}
        </div>
      </section>
    ` : ""}
    <section class="detail-section">
      <h3>Supporting evidence</h3>
      ${renderSupportPaths(
        summary.supportPaths,
        nodes,
        queryEntities,
        state.activeMode === "edgar" ? "Rule path" : "Support",
      )}
    </section>
    <details class="raw-details">
      <summary>Raw TRAPI result</summary>
      <pre>${escapeHtml(JSON.stringify({
        result: summary.result,
        edge_id: summary.edgeId,
        edge: summary.edge,
        auxiliary_graphs: Object.fromEntries(summary.supportGraphIds.map((id) => [id, message.auxiliary_graphs?.[id]])),
      }, null, 2))}</pre>
    </details>
  `;
  showResultDrawer(summary.name, elements.drawerBody.innerHTML);
}

function closeResultDrawer() {
  elements.drawerBackdrop.hidden = true;
  elements.resultDrawer.hidden = true;
  document.body.style.overflow = "";
}

async function runQuery(event) {
  event.preventDefault();
  const validation = validateQuery();
  elements.validationMessage.textContent = validation;
  if (validation) {
    return;
  }
  const modeState = currentState();
  const query = buildQuery();
  if (state.activeMode === "edgar") {
    modeState.edgarStage = "new";
  }
  modeState.queryEntities = modeState.entities.map((entity) => ({
    ...entity,
    types: [...(entity.types || [])],
  }));
  modeState.loading = true;
  modeState.error = null;
  renderResults();
  elements.runQuery.disabled = true;
  const started = performance.now();
  try {
    modeState.response = await fetchJson("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
    });
    await state.biolinkTypesPromise;
    modeState.elapsedSeconds = (performance.now() - started) / 1000;
  } catch (error) {
    modeState.error = error.message;
    modeState.response = null;
  } finally {
    modeState.loading = false;
    elements.runQuery.disabled = false;
    renderResults();
  }
}

async function loadExample() {
  const targetMode = state.activeMode;
  const modeState = state[targetMode];
  elements.loadExample.disabled = true;
  elements.loadExample.textContent = "Loading...";
  try {
    modeState.entities = [];
    await normalizeAndAdd(MODES[targetMode].example.map((curie) => ({ curie })), targetMode);
    modeState.outputType = MODES[targetMode].outputType;
    modeState.predicate = MODES[targetMode].predicate;
    modeState.direction = MODES[targetMode].direction;
    modeState.qualifiers = [];
    if (state.activeMode === targetMode) {
      renderMode();
    }
  } catch (error) {
    showToast(`Could not load the example: ${error.message}`);
  } finally {
    elements.loadExample.disabled = false;
    elements.loadExample.textContent = "Load example";
  }
}

function downloadResponse() {
  const response = currentState().response;
  if (!response) {
    return;
  }
  const blob = new Blob([JSON.stringify(response, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `answercoalesce-${state.activeMode}-${new Date().toISOString().replaceAll(":", "-")}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    syncStateFromForm();
    state.activeMode = tab.dataset.mode;
    renderMode();
  });
});
elements.form.addEventListener("submit", runQuery);
elements.searchButton.addEventListener("click", searchNames);
elements.entitySearch.addEventListener("input", () => {
  window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(searchNames, 280);
});
elements.entitySearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchNames();
  }
  if (event.key === "Escape") {
    hideSearchResults();
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-wrap")) {
    hideSearchResults();
  }
});
elements.resolvePaste.addEventListener("click", resolvePastedEntries);
elements.clearResolution.addEventListener("click", () => {
  state.resolutionQueue = [];
  renderResolutionQueue();
});
elements.addAllResolution.addEventListener("click", async () => {
  const candidates = selectedResolutionCandidates();
  if (!candidates.length) {
    showToast("No resolved candidates are available to add.");
    return;
  }
  elements.addAllResolution.disabled = true;
  elements.addAllResolution.textContent = "Adding...";
  try {
    await normalizeAndAdd(candidates);
    state.resolutionQueue = [];
    renderResolutionQueue();
  } catch (error) {
    showToast(`Could not normalize the selected concepts: ${error.message}`);
  } finally {
    elements.addAllResolution.disabled = false;
    elements.addAllResolution.textContent = "Add selected";
  }
});
elements.loadExample.addEventListener("click", loadExample);
elements.outputType.addEventListener("input", () => {
  syncStateFromForm();
  updateDirectionLabels();
  updateQueryPreview();
});
[
  elements.predicate,
  elements.pvalueThreshold,
  elements.maxResults,
  elements.maxRules,
  elements.excludedPredicates,
].forEach((input) => input.addEventListener("input", updateQueryPreview));
elements.directions.forEach((input) => input.addEventListener("change", updateQueryPreview));
elements.addQualifier.addEventListener("click", () => {
  syncStateFromForm();
  const modeState = currentState();
  const usedTypes = new Set(modeState.qualifiers.map(
    (qualifier) => normalizeQualifierType(qualifier.type),
  ));
  const suggestedType = QUALIFIER_TYPE_SUGGESTIONS.find(
    (qualifierType) => !usedTypes.has(qualifierType.id),
  )?.id || "";
  modeState.qualifiers.push({ type: suggestedType, value: "" });
  renderQualifierRows();
  const lastRow = elements.qualifierRows.querySelector(".qualifier-row:last-child");
  lastRow.querySelector(suggestedType ? ".qualifier-value" : ".qualifier-type").focus();
  updateQueryPreview();
});
elements.qualifierRows.addEventListener("input", (event) => {
  if (event.target.matches(".qualifier-custom-type, .qualifier-value")) {
    updateQueryPreview();
  }
});
elements.qualifierRows.addEventListener("change", (event) => {
  if (!event.target.matches(".qualifier-type")) {
    return;
  }
  const row = event.target.closest(".qualifier-row");
  const customType = row.querySelector(".qualifier-custom-type");
  customType.hidden = event.target.value !== "__custom__";
  if (!customType.hidden) {
    customType.focus();
  }
  updateQueryPreview();
});
elements.qualifierRows.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-remove-qualifier]");
  if (!removeButton) {
    return;
  }
  syncStateFromForm();
  currentState().qualifiers.splice(Number(removeButton.dataset.removeQualifier), 1);
  renderQualifierRows();
  updateQueryPreview();
});
elements.edgarStageButtons.forEach((button) => {
  button.addEventListener("click", () => {
    currentState().edgarStage = button.dataset.edgarStage;
    renderResults();
  });
});
elements.downloadResults.addEventListener("click", downloadResponse);
elements.closeDrawer.addEventListener("click", closeResultDrawer);
elements.drawerBackdrop.addEventListener("click", closeResultDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.resultDrawer.hidden) {
    closeResultDrawer();
  }
});

state.biolinkTypesPromise = loadBiolinkTypes();
renderMode();

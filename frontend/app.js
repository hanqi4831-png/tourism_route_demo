const recommendForm = document.getElementById("recommend-form");
const importForm = document.getElementById("import-form");
const categoryBox = document.getElementById("preferred-categories");
const seasonSelect = document.getElementById("season");
const startPoiSelect = document.getElementById("start-poi");
const mustVisitBox = document.getElementById("must-visit-pois");
const hardFilterBox = document.getElementById("hard-filter-options");
const softRankBox = document.getElementById("soft-rank-options");
const systemLogDiv = document.getElementById("system-log");
const resultsDiv = document.getElementById("results");
const detailsDiv = document.getElementById("details");
const statusText = document.getElementById("status");
const importStatusText = document.getElementById("import-status");
const timeBudgetInput = document.getElementById("time-budget");
const topKInput = document.getElementById("top-k");
const poiFileInput = document.getElementById("poi-file");
const trajectoryFileInput = document.getElementById("trajectory-file");
const poiFileName = document.getElementById("poi-file-name");
const trajectoryFileName = document.getElementById("trajectory-file-name");

const DEFAULT_RESULTS_MESSAGE = "Submit a request to populate recommendation results.";
const DEFAULT_DETAILS_MESSAGE =
  "Click a route card above to inspect the full route details.";
const DEFAULT_PENDING_RECOMMENDATION_LINE = "[Recommend] Pending recommendation request.";
const NONE_LABEL = "None";
const NOT_AVAILABLE_LABEL = "N/A";
const SUMMARY_PREFIX = "Simple cycle route:";
const HIDDEN_REASON_TAGS = new Set(["simple cycle route"]);
const FILE_PICKER_EMPTY_LABEL = "No file chosen";
let latestSystemStats = null;

const PERSONALIZATION_LABELS = {
  time_budget: "Time budget",
  must_visit: "Required POIs",
  start_point: "Start POI",
  type_preference: "Category preference",
  season: "Season",
};

const HARD_FILTER_OPTIONS = [
  { key: "time_budget", label: "Time budget" },
  { key: "must_visit", label: "Required POIs" },
  { key: "start_point", label: "Start POI" },
  { key: "season", label: "Season" },
];

const SOFT_RANK_OPTIONS = [
  {
    key: "time_budget",
    label: "Time budget",
    hint: "Rank routes by how closely their duration matches the budget.",
  },
  {
    key: "must_visit",
    label: "Required POIs",
    hint: "Rank routes by required-POI coverage.",
  },
  {
    key: "start_point",
    label: "Start POI",
    hint: "Rank routes by ease of access from the selected start POI.",
  },
  {
    key: "type_preference",
    label: "Category preference",
    hint: "Rank routes by category preference match and balance.",
  },
  {
    key: "season",
    label: "Season",
    hint: "Rank routes by season fit.",
  },
];

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const data = await response.json();
      if (data && typeof data.detail === "string" && data.detail.trim()) {
        message = data.detail;
      }
    } catch (_) {
      // Keep the default fallback message.
    }
    throw new Error(message);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function stripRouteSummaryPrefix(summary) {
  const text = String(summary || "").trim();
  if (text.toLowerCase().startsWith(SUMMARY_PREFIX.toLowerCase())) {
    return text.slice(SUMMARY_PREFIX.length).trim();
  }
  return text;
}

function getVisibleReasonTags(tags) {
  return (tags || []).filter((tag) => {
    const normalized = String(tag || "").trim().toLowerCase();
    return normalized && !HIDDEN_REASON_TAGS.has(normalized);
  });
}

function resetInputOptions() {
  categoryBox.innerHTML = "";
  mustVisitBox.innerHTML = "";
  seasonSelect.innerHTML = `<option value="">No limit</option>`;
  startPoiSelect.innerHTML = `<option value="">No limit</option>`;
}

function setDetailsPlaceholder(message = DEFAULT_DETAILS_MESSAGE) {
  detailsDiv.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function setResultsPlaceholder(message = DEFAULT_RESULTS_MESSAGE) {
  resultsDiv.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderSystemLogUnavailable(message = "Import poi.csv and trajectory.csv to load system logs.") {
  systemLogDiv.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderSystemLogLines(lines) {
  systemLogDiv.innerHTML = `
    <div class="system-log-block">
      ${lines
        .map((line) => `<div class="system-log-line">${escapeHtml(line)}</div>`)
        .join("")}
    </div>
  `;
}

function selectedCheckedValues(containerEl) {
  return Array.from(containerEl.querySelectorAll("input[type='checkbox']:checked")).map(
    (input) => input.value,
  );
}

function appendCheckbox(containerEl, value, text, groupName) {
  const row = document.createElement("label");
  row.className = "check-row";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = groupName;
  input.value = value;

  const span = document.createElement("span");
  span.textContent = text;

  row.append(input, span);
  containerEl.appendChild(row);
}

function renderHardFilterOptions() {
  hardFilterBox.innerHTML = "";
  HARD_FILTER_OPTIONS.forEach((item) => {
    appendCheckbox(hardFilterBox, item.key, item.label, "hard_filter_keys");
  });
}

function renderSoftRankOptions() {
  softRankBox.innerHTML = "";

  SOFT_RANK_OPTIONS.forEach((item) => {
    const row = document.createElement("div");
    row.className = "rank-row";
    row.dataset.softRow = item.key;

    const textBox = document.createElement("div");

    const title = document.createElement("div");
    title.className = "rank-row-title";
    title.textContent = item.label;

    const hint = document.createElement("div");
    hint.className = "rank-row-hint";
    hint.textContent = item.hint;

    textBox.append(title, hint);

    const select = document.createElement("select");
    select.dataset.softKey = item.key;
    [
      { value: "", text: "Do not use in soft ranking" },
      { value: "1", text: "Priority 1" },
      { value: "2", text: "Priority 2" },
      { value: "3", text: "Priority 3" },
      { value: "4", text: "Priority 4" },
    ].forEach((optionConfig) => {
      const option = document.createElement("option");
      option.value = optionConfig.value;
      option.textContent = optionConfig.text;
      select.appendChild(option);
    });

    row.append(textBox, select);
    softRankBox.appendChild(row);
  });
}

function formatConditionLabel(key) {
  return PERSONALIZATION_LABELS[key] || key;
}

function formatSoftRankGroups(groups) {
  if (!groups || !groups.length) {
    return NONE_LABEL;
  }

  return groups
    .map((group, index) => `Priority ${index + 1}: ${group.map(formatConditionLabel).join(", ")}`)
    .join("; ");
}

function formatSoftRankWeights(weights) {
  const entries = Object.entries(weights || {});
  if (!entries.length) {
    return NONE_LABEL;
  }

  return entries
    .map(([key, value]) => `${formatConditionLabel(key)}=${Number(value).toFixed(2)}`)
    .join(", ");
}

function buildSystemLogLines(stats) {
  const seasons = (stats.available_seasons || []).join(", ") || NONE_LABEL;
  return [
    `[System] POIs=${stats.poi_count ?? 0} | Trajectories=${stats.trajectory_count ?? 0}`,
    `[System] Pair Patterns=${stats.pair_pattern_count ?? 0} | Cycle Patterns=${stats.cycle_pattern_count ?? 0}`,
    `[System] Graph size=${stats.graph_node_count ?? 0} nodes / ${stats.graph_edge_count ?? 0} edges`,
    `[System] Available seasons=${seasons}`,
  ];
}

function buildRecommendLogLines(data) {
  const meta = data.meta || {};
  const summary = meta.personalization_summary || {};
  const hardFilters =
    (summary.hard_filters || []).map(formatConditionLabel).join(", ") || NONE_LABEL;
  const qualityRemoved = meta.quality_filter_removed || {};
  const hardRemoved = meta.web_hard_filter_removed || {};

  return [
    `[Recommend] Mode=${meta.personalization_mode || "unknown"}`,
    `[Recommend] Hard filters=${hardFilters}`,
    `[Recommend] Soft priority=${formatSoftRankGroups(summary.soft_rank_groups || [])}`,
    `[Recommend] After quality=${meta.after_filter_count ?? 0} | After hard filters=${meta.after_web_hard_filter_count ?? 0}`,
    `[Recommend] Quality removals=time=${qualityRemoved.removed_by_time ?? 0}, distance=${qualityRemoved.removed_by_distance ?? 0}, low_cycle_tpi=${qualityRemoved.removed_by_cycle_tpi ?? 0}, length=${qualityRemoved.removed_by_length ?? 0}`,
    `[Recommend] Hard removals=time_budget=${hardRemoved.removed_by_time_budget ?? 0}, required_pois=${hardRemoved.removed_by_must_visit ?? 0}, start_point=${hardRemoved.removed_by_start_point ?? 0}, season=${hardRemoved.removed_by_season ?? 0}`,
    `[Recommend] Fallback=${meta.fallback_reason || NONE_LABEL}`,
  ];
}

function renderSystemLog(stats, recommendLines = [DEFAULT_PENDING_RECOMMENDATION_LINE]) {
  if (!stats) {
    renderSystemLogUnavailable();
    return;
  }

  renderSystemLogLines([...buildSystemLogLines(stats), ...recommendLines]);
}

function renderRoutePoiSeasonDetails(route) {
  const details = route.route_poi_details || [];
  if (!details.length) {
    return `<div class="metric"><span class="metric-label">POI season details:</span> ${NOT_AVAILABLE_LABEL}</div>`;
  }

  const rows = details
    .map((detail) => {
      const suitable = (detail.suitable_seasons || []).join(", ") || "all";
      return `
        <div class="metric-list-item">
          ${escapeHtml(detail.poi_name || detail.poi_id)} (${escapeHtml(detail.poi_id)})
          | Category=${escapeHtml(detail.category || "unknown")}
          | SuitableSeasons=${escapeHtml(suitable)}
        </div>
      `;
    })
    .join("");

  return `
    <div class="metric-group">
      <span class="metric-label">POI season details:</span>
      <div class="metric-list">${rows}</div>
    </div>
  `;
}

function renderRouteCard(route) {
  const card = document.createElement("div");
  card.className = "card";

  const summary = stripRouteSummaryPrefix(
    route.display_route_summary || (route.route_poi_names || []).join(" -> "),
  );
  const visibleTags = getVisibleReasonTags(route.reason_tags);
  const tags = visibleTags
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
  const durationMinutes = Number(route.estimated_total_duration_minutes ?? 0).toFixed(1);
  const distanceKm = Number(route.travel_cost_km ?? 0).toFixed(2);

  card.innerHTML = `
    <div class="card-head">
      <span class="card-rank">Top ${route.rank}</span>
      <span class="card-score">${Number(route.score ?? 0).toFixed(4)}</span>
    </div>
    <h3 class="card-summary">${escapeHtml(summary)}</h3>
    <div class="card-metrics">
      <div class="metric"><span class="metric-label">Cycle:</span> tpi=${Number(route.cycle_tpi ?? 0).toFixed(4)}</div>
      <div class="metric"><span class="metric-label">Travel:</span> ${distanceKm}km, ${durationMinutes}min, ${route.unique_poi_count ?? 0} POIs</div>
      <div class="metric"><span class="metric-label">Fits:</span> time=${Number(route.time_fit_score ?? 0).toFixed(2)}, season=${Number(route.season_fit_score ?? 0).toFixed(2)}, start=${Number(route.start_fit_score ?? 0).toFixed(2)}</div>
    </div>
    <div class="tags">${tags || `<span class="muted">${NONE_LABEL}</span>`}</div>
  `;

  card.addEventListener("click", () => {
    const routePoiNames = (route.route_poi_names || []).map(escapeHtml).join(" -> ");
    const routeCategories = (route.route_categories || []).map(escapeHtml).join(", ") || NONE_LABEL;
    const detailHardFilters =
      (route.personalization_summary?.hard_filters || [])
        .map(formatConditionLabel)
        .join(", ") || NONE_LABEL;
    const detailSoftWeights = formatSoftRankWeights(route.soft_rank_weights || {});
    const recommendationTags = visibleTags.map(escapeHtml).join(", ") || NONE_LABEL;

    detailsDiv.innerHTML = `
      <h3>Route #${route.rank} Details</h3>
      <div class="metric"><span class="metric-label">POI order:</span> ${routePoiNames || NOT_AVAILABLE_LABEL}</div>
      <div class="metric"><span class="metric-label">Category sequence:</span> ${routeCategories}</div>
      <div class="metric"><span class="metric-label">Route structure:</span> path_length=${route.path_length ?? 0}, unique_pois=${route.unique_poi_count ?? 0}</div>
      <div class="metric"><span class="metric-label">Score breakdown:</span> base=${Number(route.base_score ?? 0).toFixed(4)}, personal=${Number(route.personal_score ?? 0).toFixed(4)}, final=${Number(route.score ?? 0).toFixed(4)}</div>
      <div class="metric"><span class="metric-label">Cycle metrics:</span> cycle_tpi=${Number(route.cycle_tpi ?? 0).toFixed(4)}</div>
      <div class="metric"><span class="metric-label">Category profile:</span> dominant=${escapeHtml(route.dominant_category || NOT_AVAILABLE_LABEL)}</div>
      <div class="metric"><span class="metric-label">Required-POI fit:</span> matched=${route.must_visit_match_count ?? 0}, fit=${Number(route.must_visit_fit_score ?? 0).toFixed(4)}</div>
      <div class="metric"><span class="metric-label">Start-point distance:</span> ${route.start_distance_km == null ? NOT_AVAILABLE_LABEL : `${Number(route.start_distance_km).toFixed(2)}km`}</div>
      <div class="metric"><span class="metric-label">Time and season fit:</span> time=${Number(route.time_fit_score ?? 0).toFixed(4)}, dominant_season=${escapeHtml(route.dominant_supporting_season || NOT_AVAILABLE_LABEL)}, season_fit=${Number(route.season_fit_score ?? 0).toFixed(4)}, season_match=${route.season_match_count ?? 0}/${route.season_total_count ?? 0}</div>
      ${renderRoutePoiSeasonDetails(route)}
      <div class="metric"><span class="metric-label">Personalization summary:</span> hard_filters=${escapeHtml(detailHardFilters)}; soft_rank=${escapeHtml(formatSoftRankGroups(route.personalization_summary?.soft_rank_groups || []))}</div>
      <div class="metric"><span class="metric-label">Soft-rank weights:</span> ${escapeHtml(detailSoftWeights)}</div>
      <div class="metric"><span class="metric-label">Recommendation tags:</span> ${recommendationTags}</div>
    `;
  });

  return card;
}

function hasSelectedCategories() {
  return selectedCheckedValues(categoryBox).length > 0;
}

function hasSelectedMustVisit() {
  return selectedCheckedValues(mustVisitBox).length > 0;
}

function hasSelectedSeason() {
  return Boolean(seasonSelect.value);
}

function hasStartPoi() {
  return Boolean(startPoiSelect.value);
}

function hasTimeBudget() {
  return Boolean(timeBudgetInput.value);
}

function getConditionAvailability() {
  return {
    time_budget: hasTimeBudget(),
    must_visit: hasSelectedMustVisit(),
    start_point: hasStartPoi(),
    type_preference: hasSelectedCategories(),
    season: hasSelectedSeason(),
  };
}

function selectedHardFilterKeys() {
  return selectedCheckedValues(hardFilterBox);
}

function syncPersonalizationControls() {
  const availability = getConditionAvailability();

  HARD_FILTER_OPTIONS.forEach((item) => {
    const checkbox = hardFilterBox.querySelector(`input[value="${item.key}"]`);
    if (!checkbox) {
      return;
    }
    checkbox.disabled = !availability[item.key];
    if (!availability[item.key]) {
      checkbox.checked = false;
    }
  });

  const hardSet = new Set(selectedHardFilterKeys());
  SOFT_RANK_OPTIONS.forEach((item) => {
    const row = softRankBox.querySelector(`[data-soft-row="${item.key}"]`);
    if (!row) {
      return;
    }

    const select = row.querySelector("select");
    const hint = row.querySelector(".rank-row-hint");
    const available = availability[item.key] && !hardSet.has(item.key);
    select.disabled = !available;
    if (!available) {
      select.value = "";
    }
    row.classList.toggle("disabled", !available);

    if (!availability[item.key]) {
      hint.textContent = "Provide the corresponding input first.";
    } else if (hardSet.has(item.key)) {
      hint.textContent = "Already selected as a hard filter.";
    } else {
      hint.textContent = item.hint;
    }
  });
}

function buildSoftRankGroups() {
  const rankMap = new Map();
  SOFT_RANK_OPTIONS.forEach((item) => {
    const select = softRankBox.querySelector(`select[data-soft-key="${item.key}"]`);
    if (!select || select.disabled || !select.value) {
      return;
    }

    const rank = Number(select.value);
    if (!rankMap.has(rank)) {
      rankMap.set(rank, []);
    }
    rankMap.get(rank).push(item.key);
  });

  return Array.from(rankMap.entries())
    .sort((left, right) => left[0] - right[0])
    .map((entry) => entry[1]);
}

function updateSelectedFileName(inputEl, outputEl) {
  if (!inputEl || !outputEl) {
    return;
  }

  const selectedFile = inputEl.files && inputEl.files[0];
  outputEl.textContent = selectedFile ? selectedFile.name : FILE_PICKER_EMPTY_LABEL;
}

async function init() {
  statusText.textContent = "Loading system data...";
  latestSystemStats = null;
  resetInputOptions();
  renderHardFilterOptions();
  renderSoftRankOptions();
  renderSystemLogUnavailable("Loading system logs...");
  setResultsPlaceholder();
  setDetailsPlaceholder();

  const [categories, pois, stats] = await Promise.all([
    fetchJson("/api/categories"),
    fetchJson("/api/pois"),
    fetchJson("/api/stats"),
  ]);

  categories.forEach((category) => {
    appendCheckbox(categoryBox, category, category, "preferred_categories");
  });

  (stats.available_seasons || []).forEach((season) => {
    const option = document.createElement("option");
    option.value = season;
    option.textContent = season;
    seasonSelect.appendChild(option);
  });

  pois.forEach((poi) => {
    const option = document.createElement("option");
    option.value = poi.id;
    option.textContent = `${poi.id} - ${poi.name}`;
    startPoiSelect.appendChild(option);
    appendCheckbox(mustVisitBox, poi.id, `${poi.id} - ${poi.name}`, "must_visit_poi_ids");
  });

  latestSystemStats = stats;
  renderSystemLog(latestSystemStats);
  syncPersonalizationControls();
  statusText.textContent = "Ready. Fill in the inputs and generate recommendations.";
}

recommendForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusText.textContent = "Generating recommendations...";
  setResultsPlaceholder("Generating recommendation results...");
  renderSystemLog(latestSystemStats, ["[Recommend] Generating recommendation request..."]);
  setDetailsPlaceholder();

  const payload = {
    preferred_categories: selectedCheckedValues(categoryBox),
    season: seasonSelect.value || null,
    start_poi_id: startPoiSelect.value || null,
    must_visit_poi_ids: selectedCheckedValues(mustVisitBox),
    time_budget_hours: timeBudgetInput.value ? Number(timeBudgetInput.value) : null,
    top_k: topKInput.value ? Number(topKInput.value) : null,
    hard_filter_keys: selectedHardFilterKeys(),
    soft_rank_groups: buildSoftRankGroups(),
  };

  try {
    const data = await fetchJson("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    renderSystemLog(latestSystemStats, buildRecommendLogLines(data));
    const routes = data.routes || [];
    if (!routes.length) {
      setResultsPlaceholder("No routes match the current request.");
      statusText.textContent = "Recommendation completed, but no routes matched the current inputs.";
      return;
    }

    resultsDiv.innerHTML = "";
    routes.forEach((route) => resultsDiv.appendChild(renderRouteCard(route)));
    statusText.textContent =
      "Recommendation completed. Click a route card to inspect the full details.";
  } catch (error) {
    renderSystemLog(latestSystemStats, [`[Recommend] Request failed: ${error.message}`]);
    setResultsPlaceholder("Recommendation failed, so no route cards were generated.");
    statusText.textContent = `Recommendation failed: ${error.message}`;
  }
});

importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const poiFile = poiFileInput.files[0];
  const trajectoryFile = trajectoryFileInput.files[0];
  if (!poiFile || !trajectoryFile) {
    importStatusText.textContent = "Select both poi.csv and trajectory.csv before uploading.";
    return;
  }

  importStatusText.textContent = "Uploading files and rebuilding the system cache...";
  const formData = new FormData();
  formData.append("poi_file", poiFile);
  formData.append("trajectory_file", trajectoryFile);

  try {
    const response = await fetch("/api/data/import", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Data import failed.");
    }

    importStatusText.textContent =
      `Import succeeded. POIs=${data.poi_count}, trajectories=${data.trajectory_count}, cycle_patterns=${data.cycle_pattern_count}`;
    await init();
  } catch (error) {
    importStatusText.textContent = `Data import failed: ${error.message}`;
  }
});

poiFileInput.addEventListener("change", () => updateSelectedFileName(poiFileInput, poiFileName));
trajectoryFileInput.addEventListener("change", () =>
  updateSelectedFileName(trajectoryFileInput, trajectoryFileName),
);
categoryBox.addEventListener("change", syncPersonalizationControls);
mustVisitBox.addEventListener("change", syncPersonalizationControls);
hardFilterBox.addEventListener("change", syncPersonalizationControls);
seasonSelect.addEventListener("change", syncPersonalizationControls);
startPoiSelect.addEventListener("change", syncPersonalizationControls);
timeBudgetInput.addEventListener("input", syncPersonalizationControls);

updateSelectedFileName(poiFileInput, poiFileName);
updateSelectedFileName(trajectoryFileInput, trajectoryFileName);

init().catch((error) => {
  renderSystemLogUnavailable("Import poi.csv and trajectory.csv to load system logs.");
  setResultsPlaceholder();
  setDetailsPlaceholder();
  statusText.textContent = `Initialization failed: ${error.message}`;
});

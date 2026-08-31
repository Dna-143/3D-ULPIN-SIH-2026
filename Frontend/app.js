const elements = {
  datasetName: document.querySelector("#dataset-name"),
  sourceCrs: document.querySelector("#source-crs"),
  verticalReference: document.querySelector("#vertical-reference"),
  threshold: document.querySelector("#threshold"),
  applyAlignment: document.querySelector("#apply-alignment"),
  file: document.querySelector("#geojson-file"),
  fileName: document.querySelector("#file-name"),
  inputSummary: document.querySelector("#input-summary"),
  loadSample: document.querySelector("#load-sample"),
  run: document.querySelector("#run-preview"),
  resultPanel: document.querySelector("#result-panel"),
  errorPanel: document.querySelector("#error-panel"),
  resultTitle: document.querySelector("#result-title"),
  resultStatus: document.querySelector("#result-status"),
  features: document.querySelector("#metric-features"),
  coordinates: document.querySelector("#metric-coordinates"),
  distortion: document.querySelector("#metric-distortion"),
  outliers: document.querySelector("#metric-outliers"),
  origin: document.querySelector("#projection-origin"),
  outlierIds: document.querySelector("#outlier-ids"),
  warnings: document.querySelector("#warnings"),
  raw: document.querySelector("#raw-result"),
  errorPanelTitle: document.querySelector("#error-title"),
  errorDetail: document.querySelector("#error-detail"),
};

let currentRequest = null;

function describeInput(request) {
  const features = request?.geojson?.features?.length ?? 0;
  const controls = request?.control_points?.length ?? 0;
  elements.inputSummary.textContent = `${features} feature(s) · ${controls} control point(s) ready`;
}

function syncFormIntoRequest() {
  if (!currentRequest) throw new Error("Load a sample or choose a GeoJSON file first.");
  return {
    ...currentRequest,
    dataset_name: elements.datasetName.value.trim(),
    source_crs: elements.sourceCrs.value.trim(),
    vertical_reference: elements.verticalReference.value.trim() || null,
    apply_control_alignment: elements.applyAlignment.checked,
    ransac: {
      residual_threshold_m: Number(elements.threshold.value),
      max_trials: currentRequest.ransac?.max_trials ?? 512,
      min_inlier_ratio: currentRequest.ransac?.min_inlier_ratio ?? 0.6,
      random_seed: currentRequest.ransac?.random_seed ?? 42,
    },
  };
}

async function requestPreview(payload) {
  const response = await fetch("/api/v1/ingestions/preview", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data?.error?.message ?? data?.detail?.[0]?.msg ?? "Preview failed");
    error.payload = data;
    throw error;
  }
  return data;
}

function renderResult(result) {
  elements.errorPanel.hidden = true;
  elements.resultPanel.hidden = false;
  elements.resultTitle.textContent = result.status === "accepted" ? "Quality gate passed" : "Passed with traceable warnings";
  elements.resultStatus.textContent = result.status.replaceAll("_", " ").toUpperCase();
  elements.features.textContent = result.quality.feature_count.toLocaleString();
  elements.coordinates.textContent = result.quality.coordinate_count.toLocaleString();
  elements.distortion.textContent = `${result.projection.distortion_estimate.max_scale_error_ppm.toFixed(3)} ppm`;
  const outlierIds = result.control_network?.outlier_ids ?? [];
  elements.outliers.textContent = String(outlierIds.length);
  elements.origin.textContent = `${result.projection.origin.longitude.toFixed(6)}, ${result.projection.origin.latitude.toFixed(6)}`;
  elements.outlierIds.textContent = outlierIds.length ? outlierIds.join(", ") : "None";
  elements.warnings.replaceChildren(
    ...result.quality.warnings.map((warning) => {
      const item = document.createElement("div");
      item.className = "warning";
      item.textContent = `${warning.code}: ${warning.message}`;
      return item;
    }),
  );
  elements.raw.textContent = JSON.stringify(result, null, 2);
  elements.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderError(error) {
  elements.resultPanel.hidden = true;
  elements.errorPanel.hidden = false;
  elements.errorPanelTitle.textContent = error.message;
  elements.errorDetail.textContent = JSON.stringify(error.payload ?? { message: error.message }, null, 2);
  elements.errorPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runFromUi() {
  elements.run.disabled = true;
  elements.run.textContent = "Checking…";
  try {
    const result = await requestPreview(syncFormIntoRequest());
    renderResult(result);
    return result;
  } catch (error) {
    renderError(error);
    throw error;
  } finally {
    elements.run.disabled = false;
    elements.run.textContent = "Run Part 1";
  }
}

elements.loadSample.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/v1/samples/pune");
    if (!response.ok) throw new Error("Could not load the committed Pune sample.");
    currentRequest = await response.json();
    elements.datasetName.value = currentRequest.dataset_name;
    elements.sourceCrs.value = currentRequest.source_crs;
    elements.verticalReference.value = currentRequest.vertical_reference ?? "";
    elements.threshold.value = currentRequest.ransac.residual_threshold_m;
    elements.applyAlignment.checked = currentRequest.apply_control_alignment;
    elements.fileName.textContent = "Committed Pune sample";
    describeInput(currentRequest);
  } catch (error) {
    renderError(error);
  }
});

elements.file.addEventListener("change", async () => {
  const file = elements.file.files?.[0];
  if (!file) return;
  try {
    const geojson = JSON.parse(await file.text());
    currentRequest = {
      dataset_name: elements.datasetName.value.trim() || file.name,
      source_crs: elements.sourceCrs.value.trim() || "EPSG:4326",
      vertical_reference: elements.verticalReference.value.trim() || null,
      geojson,
      control_points: [],
      ransac: { residual_threshold_m: 0.75, max_trials: 512, min_inlier_ratio: 0.6, random_seed: 42 },
      apply_control_alignment: false,
    };
    elements.fileName.textContent = file.name;
    describeInput(currentRequest);
  } catch (error) {
    renderError(new Error(`The selected file is not valid JSON: ${error.message}`));
  }
});

elements.run.addEventListener("click", () => void runFromUi().catch(() => undefined));

function validateToolInput(input) {
  if (!input || typeof input !== "object" || !input.geojson) {
    throw new TypeError("geojson is required");
  }
  return {
    dataset_name: String(input.datasetName ?? "Agent ingestion preview"),
    source_crs: String(input.sourceCrs ?? "EPSG:4326"),
    vertical_reference: input.verticalReference ? String(input.verticalReference) : null,
    geojson: input.geojson,
    control_points: Array.isArray(input.controlPoints) ? input.controlPoints : [],
    ransac: {
      residual_threshold_m: Number(input.residualThresholdM ?? 0.75),
      max_trials: 512,
      min_inlier_ratio: 0.6,
      random_seed: 42,
    },
    apply_control_alignment: Boolean(input.applyControlAlignment),
  };
}

function registerWebMcpTool() {
  const context = typeof document === "undefined" ? undefined : document.modelContext;
  if (!context?.registerTool) return;
  const lifecycle = new AbortController();

  const registration = context.registerTool(
    {
      name: "preview_cadastral_ingestion",
      title: "Preview cadastral ingestion",
      description: "Validate and project one GeoJSON cadastral dataset, test optional survey controls with RANSAC, update the visible quality report, and return a concise non-persistent preview.",
      inputSchema: {
        type: "object",
        properties: {
          datasetName: { type: "string", minLength: 1, maxLength: 120 },
          sourceCrs: { type: "string", default: "EPSG:4326" },
          verticalReference: { type: "string" },
          geojson: { type: "object" },
          controlPoints: { type: "array", items: { type: "object" }, default: [] },
          residualThresholdM: { type: "number", minimum: 0.01, maximum: 100, default: 0.75 },
          applyControlAlignment: { type: "boolean", default: false },
        },
        required: ["geojson"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: true },
      async execute(input) {
        const payload = validateToolInput(input);
        const result = await requestPreview(payload);
        currentRequest = payload;
        renderResult(result);
        return {
          datasetName: result.dataset_name,
          status: result.status,
          featureCount: result.quality.feature_count,
          warningCodes: result.quality.warnings.map((warning) => warning.code),
          outlierControlPointIds: result.control_network?.outlier_ids ?? [],
          projectionOrigin: result.projection.origin,
          outputBoundingBox: result.transformed_geojson.bbox,
        };
      },
    },
    { signal: lifecycle.signal },
  );
  Promise.resolve(registration).catch((error) => console.warn("WebMCP registration failed", error));
  window.addEventListener("pagehide", () => lifecycle.abort(), { once: true });
}

registerWebMcpTool();

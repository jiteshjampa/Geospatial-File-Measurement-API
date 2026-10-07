"use strict";

const map = L.map("map", { zoomControl: true }).setView([20.5937, 78.9629], 4);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const form = document.getElementById("upload-form");
const input = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const button = document.getElementById("upload-button");
const statusMessage = document.getElementById("upload-status");
const summary = document.getElementById("file-summary");
const rows = document.getElementById("feature-rows");
let featureLayer = null;

input.addEventListener("change", () => {
  button.disabled = !input.files.length;
  document.getElementById("file-prompt").textContent =
    input.files.length ? input.files[0].name : "Choose a file or drop it here";
  statusMessage.textContent = "";
  statusMessage.className = "status-message";
});

for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("drag-over");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag-over");
  });
}
dropzone.addEventListener("drop", (event) => {
  if (event.dataTransfer.files.length) {
    input.files = event.dataTransfer.files;
    input.dispatchEvent(new Event("change"));
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = input.files[0];
  if (!file) return;
  button.disabled = true;
  button.querySelector("span:first-child").textContent = "Processing…";
  statusMessage.textContent = "Reading file, transforming coordinates and calculating measurements.";
  statusMessage.className = "status-message";
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/files/", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "The file could not be processed.");
    const measurementResponse = await fetch(`/api/files/${encodeURIComponent(result.id)}/measurements/`);
    const measurements = await measurementResponse.json();
    if (!measurementResponse.ok) throw new Error(measurements.detail || "Could not load measurements.");
    renderResults(result, measurements.features);
    statusMessage.textContent = "File processed successfully. Measurements are ready.";
    statusMessage.className = "status-message success";
  } catch (error) {
    statusMessage.textContent = error.message || "A network error occurred. Please try again.";
    statusMessage.className = "status-message";
  } finally {
    button.disabled = !input.files.length;
    button.querySelector("span:first-child").textContent = "Process file";
  }
});

function formatMeasurement(value, unit) {
  if (value === null || value === undefined) return "—";
  const digits = value >= 10000 ? 0 : value >= 100 ? 1 : 2;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value)} ${unit}`;
}

function renderResults(file, features) {
  summary.classList.remove("hidden");
  document.getElementById("summary-name").textContent = file.filename;
  document.getElementById("summary-crs").textContent = `Source CRS · ${file.crs}`;
  document.getElementById("summary-count").textContent = file.feature_count.toLocaleString();
  document.getElementById("summary-status").textContent = file.status;
  document.getElementById("result-count").textContent = `${features.length} FEATURES`;
  document.getElementById("map-caption").textContent = `${file.filename} · ${features.length} mapped features`;
  const visible = features.slice(0, 100);
  rows.replaceChildren();
  if (!visible.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = "This file contains no features.";
    tr.append(td);
    rows.append(tr);
  }
  for (const feature of visible) {
    const tr = document.createElement("tr");
    for (const text of [
      `#${feature.feature_index + 1}`,
      feature.geometry_type,
      formatMeasurement(feature.area_m2, "m²"),
      formatMeasurement(feature.length_m, "m"),
    ]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.append(td);
    }
    const resultCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `result-badge ${feature.measurement_status}`;
    badge.textContent = feature.measurement_status.replaceAll("_", " ");
    if (feature.message) badge.title = feature.message;
    resultCell.append(badge);
    tr.append(resultCell);
    rows.append(tr);
  }
  const tableNote = document.getElementById("table-note");
  if (features.length > visible.length) {
    tableNote.textContent = `Showing ${visible.length} of ${features.length} features. All measurements remain available through the API.`;
    tableNote.classList.remove("hidden");
  } else {
    tableNote.classList.add("hidden");
  }

  if (featureLayer) map.removeLayer(featureLayer);
  const geojson = features
    .filter((feature) => feature.geometry)
    .map((feature) => ({ type: "Feature", properties: {}, geometry: feature.geometry }));
  featureLayer = L.geoJSON(geojson, {
    style: (feature) => {
      const type = feature.geometry.type;
      const color = type.includes("Polygon") ? "#368467" : "#d99640";
      return { color, weight: 2, fillColor: color, fillOpacity: 0.2 };
    },
    pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
      radius: 6, color: "#536eaa", fillColor: "#91a8dc", fillOpacity: 0.9, weight: 1,
    }),
  }).addTo(map);
  if (featureLayer.getLayers().length) {
    map.fitBounds(featureLayer.getBounds(), { padding: [24, 24], maxZoom: 15 });
  }
}

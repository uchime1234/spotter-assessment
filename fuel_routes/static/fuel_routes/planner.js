"use strict";

const element = (id) => document.getElementById(id);
const form = element("route-form");
const startInput = element("start");
const finishInput = element("finish");
const calculate = element("calculate");
const demo = element("load-demo");
const routeError = element("route-error");
const mapError = element("map-error");
const stopList = element("stops-list");
const stopsEmpty = element("stops-empty");
const mapStatus = element("map-status");

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const unitPrice = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 4,
});
const metricIds = ["route-miles", "total-miles", "fuel-purchased", "fuel-cost"];
const fieldNames = { start: "Start", finish: "Destination" };

const map = initializeMap();
const routeLayer = map ? L.featureGroup().addTo(map) : null;

function initializeMap() {
  if (!window.L) {
    showMapError("The map could not load. You can still calculate a trip and view its fuel plan.");
    return null;
  }
  const instance = L.map("route-map", {
    scrollWheelZoom: false,
    zoomSnap: 0.5,
  }).fitBounds([[25, -124], [49, -67]]);
  const outlinePane = instance.createPane("state-outlines");
  outlinePane.style.zIndex = "250";
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  });
  tiles.once("tileerror", () => loadStateOutlines(instance, tiles));
  tiles.addTo(instance);
  L.control.scale({ imperial: true, metric: false }).addTo(instance);
  return instance;
}

async function loadStateOutlines(instance, tiles) {
  try {
    const response = await fetch(element("route-map").dataset.outlinesUrl);
    if (!response.ok) {
      throw new Error("State outlines unavailable");
    }
    const geometry = await response.json();
    L.geoJSON(geometry, {
      pane: "state-outlines",
      interactive: false,
      attribution: "US Census Bureau",
      style: { color: "#a7b8aa", weight: 1.2, fillColor: "#f4f3e7", fillOpacity: 1 },
    }).addTo(instance);
    const credit = tiles.getAttribution();
    instance.removeLayer(tiles);
    instance.attributionControl.addAttribution(credit);
    showMapError("Basemap unavailable. Showing US state outlines.");
  } catch {
    showMapError("Basemap unavailable. Route and fuel stop overlays can still display.");
  }
}

function showMapError(message) {
  mapError.textContent = message;
  mapError.hidden = false;
}

function parseEndpoint(input) {
  const label = fieldNames[input.name];
  const value = input.value.trim();
  if (!value) {
    throw new Error(`Enter a US street address or coordinates for ${label.toLowerCase()}.`);
  }

  const parts = value.split(",").map((part) => part.trim());
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
  if (parts.length === 2 && parts.every((part) => decimal.test(part))) {
    const [latitude, longitude] = parts.map(Number);
    if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
      throw new Error(`${label} coordinates are out of range. Use latitude (−90 to 90), longitude (−180 to 180).`);
    }
    return { latitude, longitude };
  }
  return value;
}

function showError(message) {
  routeError.textContent = message;
  routeError.hidden = false;
}

function clearError() {
  routeError.hidden = true;
  routeError.textContent = "";
  for (const input of [startInput, finishInput]) {
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
  }
}

function markInvalid(input) {
  input.setAttribute("aria-invalid", "true");
  input.setAttribute("aria-describedby", "route-error");
}

function setLoading(loading) {
  form.setAttribute("aria-busy", String(loading));
  calculate.disabled = loading;
  demo.disabled = loading;
  calculate.querySelector(".spinner").hidden = !loading;
  element("calculate-label").textContent = loading ? "Calculating route…" : "Calculate Route";
}

function clearPlan() {
  for (const id of metricIds) {
    element(id).textContent = "—";
  }
  routeLayer?.clearLayers();
  stopList.replaceChildren();
  stopList.hidden = true;
  stopsEmpty.textContent = "Calculate a route to see your fuel plan.";
  stopsEmpty.hidden = false;
  mapStatus.textContent = "Awaiting route";
}

function messageFrom(value) {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object") {
    return Object.values(value).map(messageFrom).filter(Boolean).join(" ");
  }
  return "";
}

function responseError(response, data) {
  if (typeof data?.detail === "string") {
    return data.detail;
  }
  for (const input of [startInput, finishInput]) {
    if (data?.[input.name]) {
      markInvalid(input);
    }
  }
  const fields = Object.entries(fieldNames)
    .filter(([key]) => data?.[key])
    .map(([key, label]) => `${label}: ${messageFrom(data[key])}`);
  return fields.join(" ") || `The request failed (HTTP ${response.status}). Please try again.`;
}

function stopDetails(stop) {
  const name = document.createElement("strong");
  name.textContent = stop.station_name;
  const purchase = document.createElement("p");
  purchase.textContent = `${unitPrice.format(stop.price_per_gallon_usd)} / gal · Buy ${number.format(stop.gallons_purchased)} gal`;
  return [name, purchase];
}

function renderPlan(plan) {
  const totalGallons = plan.fuel_stops.reduce(
    (sum, stop) => sum + Number(stop.gallons_purchased), 0,
  );
  element("route-miles").textContent = number.format(plan.route_miles);
  element("total-miles").textContent = number.format(plan.total_miles_estimate);
  element("fuel-purchased").textContent = number.format(totalGallons);
  element("fuel-cost").textContent = currency.format(plan.estimated_fuel_purchases_usd);
  element("vehicle-range").textContent = number.format(plan.tank_gallons * plan.miles_per_gallon);
  element("tank-gallons").textContent = number.format(plan.tank_gallons);
  element("initial-gallons").textContent = number.format(plan.initial_gallons);
  element("efficiency").textContent = number.format(plan.miles_per_gallon);

  const synthetic = plan.catalog_mode === "synthetic";
  const mode = element("data-mode");
  mode.dataset.mode = plan.catalog_mode;
  mode.textContent = synthetic ? "Synthetic demo" : "Authorized real data";
  element("mode-note").textContent = synthetic
    ? "Synthetic route for demonstration only. Never use for navigation."
    : "Authorized station data. Detour mileage is estimated.";

  for (const stop of plan.fuel_stops) {
    const item = document.createElement("li");
    item.append(...stopDetails(stop));
    stopList.append(item);
  }
  stopList.hidden = plan.fuel_stops.length === 0;
  stopsEmpty.hidden = plan.fuel_stops.length > 0;
  stopsEmpty.textContent = "No fuel purchases are needed for this route.";
  const count = plan.fuel_stops.length;
  mapStatus.textContent = `${count} fuel ${count === 1 ? "stop" : "stops"} planned`;

  if (routeLayer) {
    renderMap(plan);
  }
}

function renderMap(plan) {
  L.geoJSON(plan.geometry, {
    style: { color: "#196e53", weight: 6, opacity: 0.93 },
  }).addTo(routeLayer);

  plan.fuel_stops.forEach((stop, index) => {
    const popup = document.createElement("div");
    popup.append(...stopDetails(stop));
    L.marker([stop.latitude, stop.longitude], {
      icon: L.divIcon({
        className: "fuel-marker",
        html: String(index + 1),
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      }),
      alt: stop.station_name,
      title: stop.station_name,
    }).bindPopup(popup).addTo(routeLayer);
  });
  const bounds = routeLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [26, 26], maxZoom: 12 });
  }
}

demo.addEventListener("click", () => {
  startInput.value = "36.154, -95.9928";
  finishInput.value = "39.1031, -84.512";
  clearError();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (calculate.disabled) {
    return;
  }
  clearError();
  clearPlan();

  const payload = {};
  for (const input of [startInput, finishInput]) {
    try {
      payload[input.name] = parseEndpoint(input);
    } catch (error) {
      markInvalid(input);
      showError(error.message);
      input.focus();
      return;
    }
  }

  setLoading(true);
  mapStatus.textContent = "Calculating…";
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(responseError(response, data));
    }
    if (!data?.geometry || !Array.isArray(data.fuel_stops)) {
      throw new Error("The server returned an incomplete fuel plan. Please try again.");
    }
    renderPlan(data);
  } catch (error) {
    clearPlan();
    mapStatus.textContent = "Route unavailable";
    showError(error instanceof TypeError
      ? "The planner could not reach the server. Check your connection and try again."
      : error.message);
  } finally {
    setLoading(false);
  }
});

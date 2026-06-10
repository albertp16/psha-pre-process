/* ─── PSHA Pre-Process - app.js ─── */

// ── State ──
let qaqcLog = [];
let sessionParams = {};

// ── Theme ──
function syncThemeButton() {
  var dark = document.documentElement.dataset.theme === 'dark';
  var icon = document.getElementById('theme-icon');
  var label = document.getElementById('theme-label');
  if (icon) icon.textContent = dark ? '☀️' : '🌙';
  if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
}
function toggleTheme() {
  var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('theme', next);
  syncThemeButton();
}
syncThemeButton();

// ── Navigation ──
document.querySelectorAll('.sidebar a[data-page]').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.sidebar a').forEach(x => x.classList.remove('active'));
    a.classList.add('active');
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + a.dataset.page).classList.add('active');
    if (a.dataset.page === 'catalog' && window._catMap) window._catMap.resize();
  });
});

// ── File upload UI ──
document.querySelectorAll('.file-upload input[type=file]').forEach(inp => {
  inp.addEventListener('change', () => {
    const p = inp.parentElement;
    if (inp.files.length) {
      p.classList.add('has-file');
      const names = Array.from(inp.files).map(f => f.name).join(', ');
      p.childNodes[0].textContent = names + ' ';
      const cols = p.parentElement.querySelector('[id$="-cols"]');
      if (cols) cols.style.display = '';
    }
  });
});

// ── Helpers ──
function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.toggle('error', type === 'error');
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), type === 'error' ? 5000 : 3000);
}

function spin(id, on) {
  const s = document.getElementById(id);
  if (s) s.classList.toggle('show', on);
}

// Site preset dropdown (Declustering): a preset fills and locks the lat/lon
// fields; "Custom (user input)" unlocks them for manual entry.
function applySitePreset() {
  var sel = document.getElementById('dec-site');
  var lat = document.getElementById('dec-slat');
  var lon = document.getElementById('dec-slon');
  if (!sel || !lat || !lon) return;
  if (sel.value === 'custom') {
    lat.readOnly = false;
    lon.readOnly = false;
    lat.focus();
    toast('Enter the site latitude and longitude');
  } else {
    var parts = sel.value.split(',');
    lat.value = parts[0];
    lon.value = parts[1];
    lat.readOnly = true;
    lon.readOnly = true;
  }
}

// Disable a Run button (and show its spinner) while a request is in flight.
function busy(btnId, spinId, on) {
  spin(spinId, on);
  const b = document.getElementById(btnId);
  if (!b) return;
  if (on) {
    b.dataset.label = b.textContent;
    b.disabled = true;
    b.textContent = 'Running…';
  } else {
    b.disabled = false;
    if (b.dataset.label) b.textContent = b.dataset.label;
  }
}

function addQAQC(module, message) {
  qaqcLog.push({ time: new Date().toISOString(), module, message });
}

function downloadBlob(content, filename, type) {
  type = type || 'text/csv';
  const blob = new Blob([content], { type: type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildTable(rows, cols, rowClass) {
  if (!rows || !rows.length) return '<p style="color:var(--text2)">No data</p>';
  var h = '<div class="tbl-scroll" style="max-height:500px;overflow:auto"><table><tr>';
  cols.forEach(function(c) { h += '<th>' + c + '</th>'; });
  h += '</tr>';
  for (var i = 0; i < rows.length; i++) {
    var cls = rowClass ? rowClass(rows[i]) : '';
    h += cls ? '<tr class="' + cls + '">' : '<tr>';
    cols.forEach(function(c) {
      var v = rows[i][c];
      h += '<td>' + (v !== null && v !== undefined && v !== '' ? v : '-') + '</td>';
    });
    h += '</tr>';
  }
  h += '</table></div>';
  h += '<p style="color:var(--text2);font-size:12px">' + rows.length + ' rows</p>';
  return h;
}

function plotHTML(b64, downloadName) {
  downloadName = downloadName || 'plot.png';
  return '<img class="plot-img" src="data:image/png;base64,' + b64 + '">' +
    '<button class="btn btn-secondary" style="margin-top:8px" onclick="downloadPlotImg(this,\'' + downloadName + '\')">Download PNG</button>';
}

function downloadPlotImg(btn, name) {
  const img = btn.previousElementSibling;
  const a = document.createElement('a');
  a.href = img.src;
  a.download = name || 'plot.png';
  a.click();
}

// Append either the uploaded file or the use_default flag to a FormData.
// Returns false (with a toast) when neither input is available.
function appendCatalogInput(fd, prefix) {
  var fileEl = document.getElementById(prefix + '-file');
  var useDef = document.getElementById(prefix + '-usedefault');
  if (fileEl && fileEl.files.length) {
    fd.append('file', fileEl.files[0]);
    return fileEl.files[0].name;
  }
  if (useDef && useDef.checked) {
    fd.append('use_default', '1');
    return 'PHIVOLCS default catalog';
  }
  toast('Upload a catalog or tick "Use PHIVOLCS default catalog"', 'error');
  return false;
}

// ── Mapbox helpers ──
function getMapboxToken() {
  // Priority: any page-level token input > server-provided token
  var ids = ['dec-mapbox', 'cat-mapbox'];
  for (var i = 0; i < ids.length; i++) {
    var inp = document.getElementById(ids[i]);
    if (inp && inp.value.trim()) return inp.value.trim();
  }
  if (typeof MAPBOX_TOKEN === 'string' && MAPBOX_TOKEN.length > 10) return MAPBOX_TOKEN;
  return null;
}

function getMapStyle(selectId) {
  var sel = document.getElementById(selectId || 'dec-mapstyle');
  return sel ? sel.value : 'mapbox://styles/mapbox/satellite-streets-v12';
}

function buildMapboxMap(containerId, siteLat, siteLon, events, title) {
  var container = document.getElementById(containerId);
  if (!container) return;

  var token = getMapboxToken();
  if (!token) {
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text2)">No Mapbox token provided. Enter token above or set MAPBOX_TOKEN env var for interactive maps.</div>';
    return;
  }

  // Dynamically load mapbox if not loaded
  if (typeof mapboxgl === 'undefined') {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css';
    document.head.appendChild(link);
    var script = document.createElement('script');
    script.src = 'https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.js';
    script.onload = function () { initMap(containerId, token, siteLat, siteLon, events, title); };
    document.head.appendChild(script);
  } else {
    initMap(containerId, token, siteLat, siteLon, events, title);
  }
}

function initMap(containerId, token, siteLat, siteLon, events, title) {
  mapboxgl.accessToken = token;

  var map = new mapboxgl.Map({
    container: containerId,
    style: getMapStyle('dec-mapstyle'),
    center: [siteLon, siteLat],
    zoom: 6,
    preserveDrawingBuffer: true
  });

  map.addControl(new mapboxgl.NavigationControl());
  map.addControl(new mapboxgl.FullscreenControl());

  map.on('load', function () {
    // Site marker
    new mapboxgl.Marker({ color: '#3b82f6' })
      .setLngLat([siteLon, siteLat])
      .setPopup(new mapboxgl.Popup().setHTML('<strong>Site</strong>'))
      .addTo(map);

    // Earthquake points as GeoJSON
    var features = events.map(function (e) {
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [e.lon, e.lat] },
        properties: { mag: e.mag, depth: e.depth || 0 }
      };
    });

    map.addSource('earthquakes-' + containerId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: features }
    });

    addEqCircleLayer(map, containerId);

    // 300km radius circle
    var circle300 = createGeoJSONCircle([siteLon, siteLat], 300);
    map.addSource('radius-' + containerId, { type: 'geojson', data: circle300 });
    map.addLayer({
      id: 'radius-line-' + containerId,
      type: 'line',
      source: 'radius-' + containerId,
      paint: { 'line-color': '#3b82f6', 'line-width': 2, 'line-dasharray': [4, 2] }
    });

    wireEqPopups(map, containerId, function (props) {
      return '<strong>M ' + Number(props.mag).toFixed(1) + '</strong><br>Depth: ' +
             Number(props.depth).toFixed(1) + ' km';
    });
  });
}

// Magnitude-scaled circle layer shared by all maps.
function addEqCircleLayer(map, containerId) {
  map.addLayer({
    id: 'eq-circles-' + containerId,
    type: 'circle',
    source: 'earthquakes-' + containerId,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'mag'], 4, 3, 5, 5, 6, 8, 7, 14, 8, 20],
      'circle-color': ['interpolate', ['linear'], ['get', 'mag'], 4, '#fef08a', 5, '#fb923c', 6, '#ef4444', 7, '#b91c1c', 8, '#7f1d1d'],
      'circle-opacity': 0.75,
      'circle-stroke-width': 0.5,
      'circle-stroke-color': '#000'
    }
  });
}

function wireEqPopups(map, containerId, htmlFn) {
  map.on('click', 'eq-circles-' + containerId, function (e) {
    var props = e.features[0].properties;
    var coords = e.features[0].geometry.coordinates;
    new mapboxgl.Popup().setLngLat(coords).setHTML(htmlFn(props)).addTo(map);
  });
  map.on('mouseenter', 'eq-circles-' + containerId, function () { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'eq-circles-' + containerId, function () { map.getCanvas().style.cursor = ''; });
}

function downloadMap(containerId, filename) {
  var canvas = document.getElementById(containerId).querySelector('canvas');
  if (!canvas) { toast('Map not ready'); return; }
  var a = document.createElement('a');
  a.download = filename;
  a.href = canvas.toDataURL('image/png');
  a.click();
}

// Build the Mapbox legend as a white sidebar panel.
// Circle colour AND size encode magnitude; focal depth is a catalog statistic
// (shown in the click popup, not as a map symbol). `showSite` adds the site
// pin + 300 km ring rows used by the declustering maps.
function buildDecLegend(d, suffix, source, showSite) {
  if (showSite === undefined) showSite = true;
  var mb = d.mag_bins || {};
  var magRows = [
    { c: '#fef08a', dia: 8,  label: '< 4.0',     n: mb.lt4 },
    { c: '#fb923c', dia: 13, label: '4.0 – 4.9', n: mb.m4 },
    { c: '#ef4444', dia: 18, label: '5.0 – 5.9', n: mb.m5 },
    { c: '#b91c1c', dia: 25, label: '6.0 – 6.9', n: mb.m6 },
    { c: '#7f1d1d', dia: 32, label: '≥ 7.0',     n: mb.ge7 }
  ];
  // Focal-depth classes (USGS): shallow 0–70, intermediate 70–300, deep 300–700 km.
  var dc = d.depth_classes || {};
  var depthRows = [
    { c: '#93c5fd', label: 'Shallow (< 70 km)',        n: dc.shallow },
    { c: '#3b82f6', label: 'Intermediate (70–300 km)', n: dc.intermediate },
    { c: '#1e3a8a', label: 'Deep (300–700 km)',        n: dc.deep }
  ];
  var nTxt = function (v) { return v == null ? '' : ' <span style="color:var(--text2)">(n=' + v + ')</span>'; };
  var head = function (t) { return '<div style="font-weight:600; color:var(--accent); margin:12px 0 6px">' + t + '</div>'; };

  var s = '';
  s += '<div id="map-legend-' + suffix + '" style="width:230px; flex-shrink:0; margin:12px 0; padding:14px 16px; ' +
       'box-sizing:border-box; background:var(--surface); border:1px solid var(--border); border-left:4px solid var(--accent); ' +
       'border-radius:4px; box-shadow:0 1px 3px rgba(0,0,0,0.08); ' +
       "font-family:'Inter', sans-serif; color:var(--text); font-size:13px; line-height:1.5; overflow-y:auto;\">";

  s += '<div style="font-weight:700; letter-spacing:1.5px; color:var(--accent); margin-bottom:4px">LEGEND</div>';
  s += '<div style="font-size:11px; color:var(--text2); margin-bottom:8px">Circle colour &amp; size = magnitude</div>';

  s += head('Magnitude');
  magRows.forEach(function (r) {
    s += '<div style="display:flex; align-items:center; margin:5px 0">' +
         '<span style="width:34px; flex-shrink:0; display:inline-flex; justify-content:center; align-items:center; margin-right:8px">' +
         '<span style="width:' + r.dia + 'px; height:' + r.dia + 'px; border-radius:50%; background:' + r.c +
         '; border:0.5px solid #555; display:inline-block"></span></span>' +
         '<span>' + r.label + nTxt(r.n) + '</span></div>';
  });

  if (showSite) {
    s += head('Site &amp; extent');
    s += '<div style="display:flex; align-items:center; margin:5px 0">' +
         '<span style="width:34px; flex-shrink:0; text-align:center; margin-right:8px">' +
         '<svg width="13" height="17" viewBox="0 0 24 30" style="vertical-align:middle">' +
         '<path d="M12 0C6 0 1.5 4.5 1.5 10.5 1.5 18 12 30 12 30s10.5-12 10.5-19.5C22.5 4.5 18 0 12 0z" fill="#3b82f6"/>' +
         '<circle cx="12" cy="10.5" r="4" fill="#fff"/></svg></span>' +
         '<span>Site location</span></div>';
    s += '<div style="display:flex; align-items:center; margin:5px 0">' +
         '<span style="width:34px; flex-shrink:0; display:inline-flex; justify-content:center; align-items:center; margin-right:8px">' +
         '<span style="width:24px; border-top:2px dashed #3b82f6; display:inline-block"></span></span>' +
         '<span>300 km radius</span></div>';
  }

  s += head('Focal depth');
  s += '<div style="font-size:11px; color:var(--text2); margin:-2px 0 6px; font-style:italic">' +
       'Catalog distribution (USGS classes) — not drawn on map; shown on click.</div>';
  depthRows.forEach(function (r) {
    s += '<div style="display:flex; align-items:center; margin:4px 0">' +
         '<span style="width:14px; height:14px; border-radius:2px; background:' + r.c +
         '; display:inline-block; margin-right:8px; flex-shrink:0"></span>' +
         '<span>' + r.label + nTxt(r.n) + '</span></div>';
  });
  if (dc.unknown) {
    s += '<div style="font-size:11px; color:var(--text2); margin-top:2px">' + dc.unknown + ' event(s) without depth.</div>';
  }

  s += '<div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border); color:var(--text); font-size:12px">';
  s += '<div>Source: ' + (source || 'Uploaded catalog') + '</div>';
  if (showSite) s += '<div>Radius: 300 km</div>';
  s += '<div>Total events: ' + (d.n_total != null ? d.n_total : '') + '</div>';
  s += '<div>Period: ' + (d.catalog_period || '—') + '</div>';
  s += '</div>';

  s += '</div>';
  return s;
}

function createGeoJSONCircle(center, radiusKm) {
  var points = 64;
  var coords = [];
  for (var i = 0; i <= points; i++) {
    var angle = (i / points) * 2 * Math.PI;
    var dx = radiusKm * Math.cos(angle);
    var dy = radiusKm * Math.sin(angle);
    var lat = center[1] + (dy / 111.32);
    var lon = center[0] + (dx / (111.32 * Math.cos(center[1] * Math.PI / 180)));
    coords.push([lon, lat]);
  }
  return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [coords] } };
}


// ════════════════════════════════════════════
// CATALOG PAGE (PHIVOLCS default catalogue + map + audit status)
// ════════════════════════════════════════════
async function loadCatalogPage() {
  try {
    var r = await fetch('/api/catalog_info');
    var d = await r.json();
    if (!d.available) {
      document.getElementById('cat-summary').innerHTML =
        '<div class="result-card"><p style="color:var(--warn)">' + (d.error || 'Catalogue not available') + '</p></div>';
      return;
    }
    window._catInfo = d;

    var a = d.audit;
    var badge;
    if (a && a.status === 'pass') {
      badge = '<span style="background:#16a34a;color:#fff;padding:4px 10px;border-radius:6px;font-weight:700">AUDIT PASS</span>';
    } else if (a) {
      badge = '<span style="background:#dc2626;color:#fff;padding:4px 10px;border-radius:6px;font-weight:700">AUDIT ' + String(a.status).toUpperCase() + '</span>';
    } else {
      badge = '<span style="background:#6b7280;color:#fff;padding:4px 10px;border-radius:6px;font-weight:700">AUDIT NOT RUN</span>';
    }

    var mt = d.mag_type_counts || {};
    var html = '<div class="result-card">';
    html += '<h3>' + d.label + ' &nbsp; ' + badge + '</h3>';
    html += '<div class="metrics">';
    html += '<div class="metric"><div class="value">' + d.total_events + '</div><div class="label">Events</div></div>';
    html += '<div class="metric"><div class="value">' + d.catalog_period + '</div><div class="label">Period</div></div>';
    ['Mw', 'Ms', 'Mb', 'Ml'].forEach(function (k) {
      if (mt[k]) html += '<div class="metric"><div class="value">' + mt[k] + '</div><div class="label">' + k + ' preferred</div></div>';
    });
    html += '</div>';
    if (a) {
      html += '<p style="color:var(--text2);font-size:13px">Capture audit: ' +
        (a.counts.data_cells_reconciled || 0) + ' cells reconciled 1:1 against the source workbook, ' +
        a.n_failures + ' failures, ' + a.n_warnings + ' warning(s). ' +
        'Preferred magnitude = first available of ' + (d.magnitude_preference || []).join(' > ') + ' (no conversion).</p>';
    }
    if (d.n_excluded_from_analysis) {
      html += '<p style="color:var(--text2);font-size:13px">' + d.n_excluded_from_analysis +
        ' event(s) lack a valid origin time (flagged in the audit) and are excluded from time-based analyses; they remain on the map and in catalog.json.</p>';
    }
    html += '</div>';
    document.getElementById('cat-summary').innerHTML = html;

    // Notes + QA flags
    var notes = '<div class="result-card"><h3>Source notes &amp; QA flags</h3><ul style="margin-left:18px">';
    (d.notes || []).forEach(function (n) { notes += '<li style="margin:6px 0">' + escapeHtml(n) + '</li>'; });
    notes += '</ul>';
    var qf = d.qa_flag_counts || {};
    var chips = Object.keys(qf).map(function (k) {
      return '<span style="display:inline-block;background:var(--bg2);border:1px solid var(--border);' +
        'border-radius:12px;padding:2px 10px;margin:3px;font-size:12px">' + k + ': ' + qf[k] + '</span>';
    }).join('');
    if (chips) notes += '<p style="margin-top:8px">' + chips + '</p>';
    if (a && a.warnings && a.warnings.length) {
      notes += '<p style="color:var(--text2);font-size:13px;margin-top:8px">Audit warnings:</p><ul style="margin-left:18px">';
      a.warnings.forEach(function (w) { notes += '<li style="font-size:13px;margin:4px 0">' + escapeHtml(w) + '</li>'; });
      notes += '</ul>';
    }
    notes += '<p style="color:var(--text2);font-size:12px;margin-top:10px">Source file: <code>' +
      d.source_file + '</code> &middot; sha256 <code>' + String(d.source_sha256).slice(0, 16) + '…</code></p>';
    notes += '</div>';
    document.getElementById('cat-notes').innerHTML = notes;

    // Legend + map
    document.getElementById('cat-legend').innerHTML =
      buildDecLegend(d, 'catalog', d.source_file, false);
    loadCatalogMap();
  } catch (e) {
    document.getElementById('cat-summary').innerHTML =
      '<div class="result-card"><p style="color:var(--warn)">Failed to load catalogue info: ' + e.message + '</p></div>';
  }
}

function loadCatalogMap(force) {
  var container = document.getElementById('map-catalog');
  if (!container) return;
  if (window._catMap && !force) return;

  var token = getMapboxToken();
  if (!token) {
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text2)">No Mapbox token. Enter one above or set the MAPBOX_TOKEN env var.</div>';
    return;
  }
  if (typeof mapboxgl === 'undefined') {
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text2)">Mapbox GL JS failed to load (offline?).</div>';
    return;
  }
  if (window._catMap) { window._catMap.remove(); window._catMap = null; }

  mapboxgl.accessToken = token;
  var map = new mapboxgl.Map({
    container: 'map-catalog',
    style: getMapStyle('cat-mapstyle'),
    center: [122.5, 12.0],
    zoom: 4.7,
    preserveDrawingBuffer: true
  });
  window._catMap = map;
  map.addControl(new mapboxgl.NavigationControl());
  map.addControl(new mapboxgl.FullscreenControl());

  map.on('load', function () {
    map.addSource('earthquakes-map-catalog', { type: 'geojson', data: '/data/catalog.geojson' });
    addEqCircleLayer(map, 'map-catalog');
    wireEqPopups(map, 'map-catalog', function (p) {
      var dt = (p.datetime_utc && p.datetime_utc !== 'null') ? String(p.datetime_utc).replace('T', ' ').replace('Z', ' GMT') : 'origin time invalid (flagged)';
      return '<strong>' + p.id + '</strong><br>' +
             'M ' + Number(p.mag).toFixed(1) + ' (' + p.mag_type + ')<br>' +
             'Depth: ' + Number(p.depth_km).toFixed(0) + ' km<br>' + dt;
    });
  });
}


// ════════════════════════════════════════════
// DECLUSTERING
// ════════════════════════════════════════════
async function runDeclustering() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'dec');
  if (!src) return;

  fd.append('lat_col', document.getElementById('dec-lat').value);
  fd.append('lon_col', document.getElementById('dec-lon').value);
  fd.append('mag_col', document.getElementById('dec-mag').value);
  fd.append('time_col', document.getElementById('dec-time').value);
  fd.append('depth_col', document.getElementById('dec-depth').value);
  fd.append('site_lat', document.getElementById('dec-slat').value);
  fd.append('site_lon', document.getElementById('dec-slon').value);
  fd.append('use_gk', document.getElementById('dec-gk').checked ? '1' : '0');
  fd.append('use_gr', document.getElementById('dec-gr').checked ? '1' : '0');
  fd.append('use_uh', document.getElementById('dec-uh').checked ? '1' : '0');

  busy('dec-run', 'dec-spin', true);
  try {
    var r = await fetch('/api/declustering', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('Declustering', d.qaqc);

    var siteLat = parseFloat(document.getElementById('dec-slat').value);
    var siteLon = parseFloat(document.getElementById('dec-slon').value);
    var mapToken = getMapboxToken();
    var showMaps = mapToken ? true : false;

    var methodNames = { gk: 'Gardner & Knopoff (1974)', gr: 'Grünthal', uh: 'Uhrhammer (1986)' };

    // ── Metrics ──
    var html = '<div class="result-card"><h3>Results</h3>';
    html += '<div class="metrics">';
    html += '<div class="metric"><div class="value">' + d.n_total + '</div><div class="label">Total Events</div></div>';
    d.methods_used.forEach(function(m) {
      var s = d.method_stats[m];
      html += '<div class="metric"><div class="value">' + s.mainshocks + '</div><div class="label">' + methodNames[m] + '</div></div>';
    });
    html += '<div class="metric"><div class="value">' + d.n_within_300_main + '</div><div class="label">Mainshocks (300 km)</div></div>';
    html += '</div>';

    html += '<h2>Decluster Windows (Distance &amp; Time vs Magnitude)</h2>';
    html += plotHTML(d.plot_windows, 'decluster_windows.png');

    html += '<h2>Original Catalog</h2>' + plotHTML(d.plot_original, 'original_catalog.png');

    html += '<h2>Declustered Catalogs</h2>';
    if (d.methods_used.length > 1) {
      html += '<div class="plot-compare">';
      d.methods_used.forEach(function(m) {
        html += '<div class="plot-panel"><h4>' + methodNames[m] + '</h4>';
        html += plotHTML(d.method_plots[m], 'declustered_' + m + '.png');
        html += '</div>';
      });
      html += '</div>';
    } else {
      var m0 = d.methods_used[0];
      html += '<h4>' + methodNames[m0] + '</h4>' + plotHTML(d.method_plots[m0], 'declustered_' + m0 + '.png');
    }

    html += '<h2>Magnitude-Time: Before vs After Declustering</h2>';
    if (d.methods_used.length > 1) {
      html += '<div class="plot-compare">';
      d.methods_used.forEach(function(m) {
        html += '<div class="plot-panel"><h4>' + methodNames[m] + '</h4>';
        html += plotHTML(d.method_magtime[m], 'magtime_' + m + '.png');
        html += '</div>';
      });
      html += '</div>';
    } else {
      var m1 = d.methods_used[0];
      html += plotHTML(d.method_magtime[m1], 'magtime_' + m1 + '.png');
    }

    html += '<h2>Magnitude-Time Overlay (All Methods)</h2>';
    html += plotHTML(d.plot_time, 'mag_time_comparison.png');

    // ── Mapbox maps ──
    if (showMaps) {
      var decSource = d.source || src;
      var mapRow = function (mapId, fileName, suffix) {
        return '<div style="display:flex; flex-direction:row; align-items:stretch;">' +
          '<div id="' + mapId + '" class="map-container" style="flex:1; min-height:500px;"></div>' +
          buildDecLegend(d, suffix, decSource, true) +
          '</div>' +
          '<button class="btn btn-secondary" style="margin-top:8px" onclick="downloadMap(\'' + mapId + '\',\'' + fileName + '\')">Download Map</button>';
      };
      html += '<h2>Interactive Maps (Mapbox)</h2>' +
        '<div class="plot-compare">' +
        '  <div class="plot-panel"><h4>Original Catalog</h4>' + mapRow('map-original', 'map_original.png', 'original') + '</div>' +
        '  <div class="plot-panel"><h4>Declustered</h4>' + mapRow('map-declustered', 'map_declustered.png', 'declustered') + '</div>' +
        '</div>' +
        '<div style="margin-top:16px"><h4>Within 300 km</h4>' + mapRow('map-300km', 'map_300km.png', '300km') + '</div>';
    } else {
      html += '<p style="color:var(--text2);margin-top:12px">Enter a Mapbox token above for interactive maps.</p>';
    }

    html += '<h2>Original Catalog Data</h2>' + buildTable(d.table_original, d.table_cols);

    html += '<h2>Download Declustered CSVs</h2><div style="margin-top:8px">';
    window._decMethodCSVs = d.method_csvs;
    d.methods_used.forEach(function(m) {
      html += '<button class="btn btn-secondary" style="margin-right:8px;margin-bottom:8px" ' +
        'onclick="downloadBlob(window._decMethodCSVs[\'' + m + '\'],\'declustered_' + m + '.csv\')">' +
        methodNames[m] + ' CSV</button>';
    });
    html += '</div></div>';

    document.getElementById('dec-results').innerHTML = html;

    if (showMaps && d.map_all && d.map_mainshocks) {
      buildMapboxMap('map-original', siteLat, siteLon, d.map_all, 'Original');
      buildMapboxMap('map-declustered', siteLat, siteLon, d.map_mainshocks, 'Declustered');
      buildMapboxMap('map-300km', siteLat, siteLon, d.map_300km, 'Within 300km');
    }

    toast('Declustering complete');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('dec-run', 'dec-spin', false); }
}


// ════════════════════════════════════════════
// COMPLETENESS
// ════════════════════════════════════════════
function toggleCompMode() {
  var mode = document.querySelector('input[name="comp-mode"]:checked').value;
  document.getElementById('comp-manual-tables').style.display =
    (mode === 'manual' || mode === 'both') ? '' : 'none';
}

async function runCompleteness() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'comp');
  if (!src) return;

  var mode = document.querySelector('input[name="comp-mode"]:checked').value;

  fd.append('mag_col', document.getElementById('comp-mag').value);
  fd.append('time_col', document.getElementById('comp-time').value);
  fd.append('depth_col', document.getElementById('comp-depth').value);
  fd.append('mag_bin', document.getElementById('comp-magbin').value);
  fd.append('time_bin', document.getElementById('comp-timebin').value);
  fd.append('dens_mag_bin', document.getElementById('comp-densmagbin').value);
  fd.append('dens_time_bin', document.getElementById('comp-denstimebin').value);
  fd.append('mode', mode);
  fd.append('d_shallow', document.getElementById('comp-dshallow').value);
  fd.append('d_mid', document.getElementById('comp-dmid').value);
  fd.append('d_deep', document.getElementById('comp-ddeep').value);

  fd.append('compl_whole', document.getElementById('comp-whole').value);
  fd.append('compl_shallow', document.getElementById('comp-shallow').value);
  fd.append('compl_mid', document.getElementById('comp-mid').value);
  fd.append('compl_deep', document.getElementById('comp-deep').value);

  busy('comp-run', 'comp-spin', true);
  try {
    var r = await fetch('/api/completeness', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('Completeness', d.qaqc);

    var dc = d.depth_counts || {};
    var html = '<div class="result-card">';
    html += '<h3>Completeness Analysis – ' + d.mode.charAt(0).toUpperCase() + d.mode.slice(1) + ' Mode</h3>';
    html += '<div class="metrics">';
    html += '<div class="metric"><div class="value">' + d.total_events + '</div><div class="label">Total Events</div></div>';
    if (dc.whole) html += '<div class="metric"><div class="value">' + dc.whole + '</div><div class="label">Whole</div></div>';
    if (dc.shallow) html += '<div class="metric"><div class="value">' + dc.shallow + '</div><div class="label">Shallow</div></div>';
    if (dc['mid-depth']) html += '<div class="metric"><div class="value">' + dc['mid-depth'] + '</div><div class="label">Mid-depth</div></div>';
    if (dc.deep) html += '<div class="metric"><div class="value">' + dc.deep + '</div><div class="label">Deep</div></div>';
    html += '</div>';

    d.sections.forEach(function(sec) {
      html += '<hr><h2>' + sec.label + ' (' + sec.count + ' events)</h2>';

      if (sec.auto_table && sec.auto_table.length) {
        html += '<h4>Automated Completeness (Stepp 1972)</h4>';
        html += buildTable(sec.auto_table.map(function(r) {
          return { Year: r[0], Magnitude: r[1] };
        }), ['Year', 'Magnitude']);
      }
      if (sec.manual_table && sec.manual_table.length) {
        html += '<h4>Manual Completeness</h4>';
        html += buildTable(sec.manual_table.map(function(r) {
          return { Year: r[0], Magnitude: r[1] };
        }), ['Year', 'Magnitude']);
      }
      if (sec.stepp_error) {
        html += '<p style="color:var(--warn)">Stepp error: ' + sec.stepp_error + '</p>';
      }

      sec.plots.forEach(function(p) {
        var fname = p.title.replace(/[^a-zA-Z0-9]/g, '_') + '.png';
        html += '<h4>' + p.title + '</h4>' + plotHTML(p.plot, fname);
      });
    });

    html += '</div>';
    document.getElementById('comp-results').innerHTML = html;
    toast('Completeness analysis done');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('comp-run', 'comp-spin', false); }
}


// ════════════════════════════════════════════
// GUTENBERG-RICHTER
// ════════════════════════════════════════════
async function runGR() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'gr');
  if (!src) return;

  fd.append('mag_col', document.getElementById('gr-mag').value);
  fd.append('time_col', document.getElementById('gr-time').value);
  fd.append('dm', document.getElementById('gr-dm').value);
  fd.append('mc', document.getElementById('gr-mc').value);
  fd.append('m_limit', document.getElementById('gr-mlimit').value);
  fd.append('m_max', document.getElementById('gr-mmax').value);

  busy('gr-run', 'gr-spin', true);
  try {
    var r = await fetch('/api/gutenberg_richter', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('Gutenberg-Richter', d.qaqc);
    sessionParams.gr_a = d.a_value;
    sessionParams.gr_b = d.b_value;
    document.getElementById('gr-results').innerHTML =
      '<div class="result-card">' +
      '<div class="metrics">' +
      '  <div class="metric"><div class="value">' + d.a_value + '</div><div class="label">a-value</div></div>' +
      '  <div class="metric"><div class="value">' + d.b_value + '</div><div class="label">b-value</div></div>' +
      '  <div class="metric"><div class="value">' + d.duration + ' yr</div><div class="label">Duration</div></div>' +
      '  <div class="metric"><div class="value">' + d.n_events + '</div><div class="label">Events >= Mc</div></div>' +
      '</div>' +
      plotHTML(d.plot, 'GR_recurrence.png') +
      '<button class="btn btn-secondary" style="margin-top:8px" onclick="downloadBlob(window._grCSV,\'GR_rates.csv\')">Download Rates CSV</button>' +
      '</div>';
    window._grCSV = d.rates_csv;
    toast('G-R analysis complete');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('gr-run', 'gr-spin', false); }
}


// ════════════════════════════════════════════
// MFD
// ════════════════════════════════════════════
async function runMFD() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'mfd');
  if (!src) return;

  fd.append('mag_col', document.getElementById('mfd-mag').value);
  fd.append('time_col', document.getElementById('mfd-time').value);
  fd.append('depth_col', document.getElementById('mfd-depth').value);
  fd.append('dm', document.getElementById('mfd-dm').value);
  fd.append('min_mag', document.getElementById('mfd-minmag').value);
  fd.append('max_mag', document.getElementById('mfd-maxmag').value);
  fd.append('compl_shallow', document.getElementById('mfd-shallow').value);
  fd.append('compl_mid', document.getElementById('mfd-mid').value);
  fd.append('compl_deep', document.getElementById('mfd-deep').value);

  busy('mfd-run', 'mfd-spin', true);
  try {
    var r = await fetch('/api/mfd', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('MFD', d.qaqc);

    var html = '<div class="result-card">' +
      '<h3>Magnitude-Frequency Distribution</h3>' +
      '<div class="metrics">' +
      '  <div class="metric"><div class="value">' + d.total_events + '</div><div class="label">Total Events</div></div>' +
      '  <div class="metric"><div class="value">' + d.a_value + '</div><div class="label">a-value</div></div>' +
      '  <div class="metric"><div class="value">' + d.b_value + '</div><div class="label">b-value</div></div>' +
      '  <div class="metric"><div class="value">' + d.duration + ' yr</div><div class="label">Duration</div></div>' +
      '</div>';

    html += plotHTML(d.plot, 'MFD_combined.png');

    d.depth_plots.forEach(function (p) {
      var fname = 'MFD_' + p.label.split(' ')[0].toLowerCase() + '.png';
      html += '<h2>' + p.label + ' (n=' + p.count + ')</h2>' + plotHTML(p.plot, fname);
    });

    html += '<h2>OpenQuake MFD Formats</h2>';

    html += '<h3>ArbitraryMFD (per depth class)</h3>';
    d.oq_arbitrary.forEach(function (item) {
      html += '<p style="color:var(--text2);margin-bottom:4px"><strong>' + item.label + '</strong></p>' +
        '<pre style="background:var(--bg2);padding:12px;border-radius:6px;overflow-x:auto;font-size:12px">' +
        escapeHtml(item.xml) + '</pre>';
    });

    html += '<h3>TruncatedGRMFD</h3>' +
      '<pre style="background:var(--bg2);padding:12px;border-radius:6px;overflow-x:auto;font-size:12px">' +
      escapeHtml(d.oq_truncated_gr) + '</pre>';

    html += '<div style="margin-top:12px">' +
      '<button class="btn btn-secondary" onclick="downloadBlob(window._mfdCSV,\'MFD_rates.csv\')">Download Rates CSV</button> ' +
      '<button class="btn btn-secondary" onclick="downloadBlob(window._mfdXML,\'MFD_openquake.xml\',\'text/xml\')">Download OpenQuake XML</button>' +
      '</div>';

    html += '</div>';
    document.getElementById('mfd-results').innerHTML = html;
    window._mfdCSV = d.rates_csv;
    window._mfdXML = d.oq_xml;
    toast('MFD analysis complete');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('mfd-run', 'mfd-spin', false); }
}


// ════════════════════════════════════════════
// MAX MAGNITUDE
// ════════════════════════════════════════════
async function runMmax() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'mmax');
  if (!src) return;

  fd.append('mag_col', document.getElementById('mmax-mag').value);
  fd.append('time_col', document.getElementById('mmax-time').value);
  fd.append('b_value', document.getElementById('mmax-bval').value);
  fd.append('sigma_b', document.getElementById('mmax-sigmab').value);
  fd.append('m_min', document.getElementById('mmax-mmin').value);
  fd.append('input_mmax', document.getElementById('mmax-inputmmax').value);
  fd.append('mmax_sigma', document.getElementById('mmax-sigma').value);
  fd.append('n_bootstraps', document.getElementById('mmax-nboot').value);

  busy('mmax-run', 'mmax-spin', true);
  try {
    var r = await fetch('/api/max_magnitude', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('Max Magnitude', d.qaqc);

    var res = d.results;
    var html = '<div class="result-card">';
    html += '<div class="metrics">';
    html += '<div class="metric"><div class="value">' + res.observed_mmax + '</div><div class="label">Observed Mmax</div></div>';
    html += '<div class="metric"><div class="value">' + res.mmax_plus_05 + '</div><div class="label">Mmax + 0.5</div></div>';
    html += '<div class="metric"><div class="value">' + res.n_events + '</div><div class="label">Events</div></div>';
    html += '<div class="metric"><div class="value">' + res.mag_range + '</div><div class="label">Mag Range</div></div>';
    html += '</div>';

    html += '<h2>Magnitude-Time Distribution</h2>' + plotHTML(d.plot_scatter, 'mmax_scatter.png');
    html += '<h2>Cumulative Moment Release</h2>' + plotHTML(d.plot_moment, 'cumulative_moment.png');
    html += '</div>';

    document.getElementById('mmax-results').innerHTML = html;
    toast('Max magnitude estimation complete');
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('mmax-run', 'mmax-spin', false); }
}

// ── Boot: catalog page is the landing page ──
loadCatalogPage();

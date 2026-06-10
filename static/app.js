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
  cols.forEach(function(c) { h += '<th>' + escapeHtml(String(c)) + '</th>'; });
  h += '</tr>';
  for (var i = 0; i < rows.length; i++) {
    var cls = rowClass ? rowClass(rows[i]) : '';
    h += cls ? '<tr class="' + cls + '">' : '<tr>';
    cols.forEach(function(c) {
      var v = rows[i][c];
      h += '<td>' + (v !== null && v !== undefined && v !== '' ? escapeHtml(String(v)) : '-') + '</td>';
    });
    h += '</tr>';
  }
  h += '</table></div>';
  h += '<p style="color:var(--text2);font-size:12px">' + rows.length + ' rows</p>';
  return h;
}

// Pipeline step notes + warnings returned by the analysis APIs.
function buildPipelineNotes(d) {
  var h = '';
  if (d.pipeline_notes && d.pipeline_notes.length) {
    h += '<h4>Catalogue preparation (BBS Sec. 3.3.5)</h4><ul style="margin-left:18px">';
    d.pipeline_notes.forEach(function (n) {
      h += '<li style="font-size:13px;margin:4px 0;color:var(--text2)">' + escapeHtml(n) + '</li>';
    });
    h += '</ul>';
  }
  if (d.warnings && d.warnings.length) {
    d.warnings.forEach(function (w) {
      h += '<p style="color:var(--warn);font-size:13px;margin:6px 0">&#9888; ' + escapeHtml(w) + '</p>';
    });
  }
  return h;
}

// ── KaTeX helpers (per-event computation details, Mmax page) ──
function renderMath(el, tex, display) {
  if (window.katex) {
    try {
      katex.render(tex, el, { displayMode: !!display, throwOnError: false });
      return;
    } catch (e) { /* fall through to plain text */ }
  }
  el.textContent = tex;   // graceful fallback when the KaTeX CDN is unreachable
}

function sciTex(x) {
  if (!isFinite(x) || x <= 0) return '0';
  var e = Math.floor(Math.log10(x));
  var m = x / Math.pow(10, e);
  return m.toFixed(2) + '\\times 10^{' + e + '}';
}

var SRC_LABELS = {
  mw: 'reported Mw', ms2mw: 'Ms→Mw', mb2mw: 'mb→Mw',
  raw: 'kept as reported', user_coeffs: 'user coefficients',
  harmonized: 'harmonized (step 1)'
};

// Registry of clickable event tables: key -> {events, rel}.
window._evtReg = {};

// Cited method equations (vault Day 16 / Reference Folder), KaTeX-rendered.
function methodEqsMw(rel) {
  return [
    { tex: 'M_w = \\tfrac{2}{3}\\log_{10} M_0 - 10.7\\;(M_0\\,\\mathrm{dyne{\\cdot}cm})' +
           ' \\;\\Longleftrightarrow\\; M_0 = 10^{1.5\\,M_w + 9.05}\\,\\mathrm{N{\\cdot}m}',
      note: rel.moment_cite },
    { tex: 'M_w = ' + rel.ms.a + '\\,M_s + ' + rel.ms.b +
           ' \\quad (' + rel.ms.lo + ' \\le M_s \\le ' + rel.ms.hi + ')',
      note: rel.ms.cite },
    { tex: 'M_w = ' + rel.mb.a + '\\,m_b + ' + rel.mb.b +
           ' \\quad (' + rel.mb.lo + ' \\le m_b \\le ' + rel.mb.hi + ')',
      note: rel.mb.cite }
  ];
}

function methodEqsMmax(rel) {
  return methodEqsMw(rel).concat([
    { tex: '\\hat b = \\log_{10}(e) \\,/\\, (\\bar{m} - m_{min})',
      note: rel.b_cite },
    { tex: '\\hat m_{max} = m^{obs}_{max} + \\frac{E_1(n_2) - E_1(n_1)}{\\beta\\,e^{-n_2}}' +
           ' + m_{min}\\,e^{-n},\\quad n_1 = \\frac{n}{1 - e^{-\\beta(m_{max}-m_{min})}},' +
           '\\quad n_2 = n_1 e^{-\\beta(m_{max}-m_{min})}',
      note: rel.mmax_cite + ' (β = b·ln 10)' }
  ]);
}

function renderMethodEqs(container, eqs) {
  eqs.forEach(function (eq) {
    var row = document.createElement('div');
    row.style.cssText = 'margin:10px 0;padding:8px 12px;background:var(--bg2);border-radius:6px;overflow-x:auto';
    var m = document.createElement('div');
    renderMath(m, eq.tex, true);
    var n = document.createElement('div');
    n.style.cssText = 'font-size:12px;color:var(--text2);margin-top:4px';
    n.textContent = 'Basis: ' + eq.note;
    row.appendChild(m);
    row.appendChild(n);
    container.appendChild(row);
  });
}

function _evtTd(v) { return '<td>' + (v !== null && v !== undefined ? v : '-') + '</td>'; }

function buildEventsRows(events, key) {
  var h = '';
  for (var i = 0; i < events.length; i++) {
    var ev = events[i];
    h += '<tr class="evt-row" data-key="' + key + '" data-i="' + ev._i + '" style="cursor:pointer" ' +
         'title="Click for the cited computation">' +
      '<td>' + escapeHtml(String(ev.id)) + '</td>' +
      '<td>' + escapeHtml(String(ev.date)) + '</td>' +
      _evtTd(ev.ml) + _evtTd(ev.mb) + _evtTd(ev.ms) + _evtTd(ev.mw) +
      '<td>' + (ev.mag !== null && ev.mag !== undefined ? ev.mag : '-') +
        (ev.mag_type ? ' (' + escapeHtml(String(ev.mag_type)) + ')' : '') + '</td>' +
      '<td>' + escapeHtml(SRC_LABELS[ev.src] || String(ev.src)) + '</td>' +
      '<td><strong>' + Number(ev.mw_used).toFixed(2) + '</strong></td>' +
      '<td>' + Number(ev.m0).toExponential(2) + '</td>' +
      '</tr>';
  }
  return h;
}

function buildEventsTable(events, key) {
  var cols = ['ID', 'Date', 'Ml', 'Mb', 'Ms', 'Mw', 'Preferred', 'Mw basis',
              'Mw used', 'M0 (N·m)'];
  var h = '<div class="tbl-scroll" style="max-height:480px;overflow:auto"><table><thead><tr>';
  cols.forEach(function (c) { h += '<th>' + c + '</th>'; });
  h += '</tr></thead><tbody id="evt-body-' + key + '">' + buildEventsRows(events, key) + '</tbody></table></div>';
  h += '<p style="color:var(--text2);font-size:12px">' + events.length +
       ' events — click any row to see its Mw conversion and seismic moment, with citations.</p>';
  return h;
}

function filterEvtTable(key) {
  var inp = document.getElementById('evt-filter-' + key);
  var reg = window._evtReg[key] || {};
  var evs = reg.events || [];
  var q = (inp && inp.value || '').trim().toLowerCase();
  var f = !q ? evs : evs.filter(function (e) {
    return String(e.id).toLowerCase().indexOf(q) >= 0 ||
           String(e.date).indexOf(q) >= 0 ||
           String(e.mag_type || '').toLowerCase().indexOf(q) >= 0 ||
           (SRC_LABELS[e.src] || String(e.src)).toLowerCase().indexOf(q) >= 0;
  });
  var body = document.getElementById('evt-body-' + key);
  if (body) body.innerHTML = buildEventsRows(f, key);
}

function wireEvtTable(key) {
  var el = document.getElementById('evt-table-' + key);
  if (el) {
    el.addEventListener('click', function (e) {
      var tr = e.target.closest('tr.evt-row');
      if (tr) toggleEvtDetail(tr);
    });
  }
}

function evtDetailNode(ev, rel) {
  rel = rel || {};
  var wrap = document.createElement('div');
  wrap.style.cssText = 'padding:10px 8px;background:var(--bg2);border-radius:6px';

  function addLine(tex, note) {
    var m = document.createElement('div');
    renderMath(m, tex, true);
    wrap.appendChild(m);
    if (note) {
      var n = document.createElement('div');
      n.style.cssText = 'font-size:12px;color:var(--text2);margin:2px 0 8px';
      n.textContent = 'Basis: ' + note;
      wrap.appendChild(n);
    }
  }
  function addNote(text) {
    var n = document.createElement('div');
    n.style.cssText = 'font-size:13px;color:var(--text2);margin:2px 0 8px';
    n.textContent = text;
    wrap.appendChild(n);
  }

  var head = document.createElement('div');
  head.style.cssText = 'font-weight:600;margin-bottom:6px';
  head.textContent = 'Event ' + ev.id + ' (' + ev.date + ') — reported: ' +
    ['Ml', 'Mb', 'Ms', 'Mw'].map(function (k) {
      var v = ev[k.toLowerCase()];
      return v !== null && v !== undefined ? k + ' ' + v : null;
    }).filter(Boolean).join(', ');
  wrap.appendChild(head);

  var mwu = Number(ev.mw_used);
  if (ev.src === 'mw') {
    addLine('M_w = ' + mwu.toFixed(2) + '\\;\\;\\text{(reported, preferred)}', rel.mw_cite);
  } else if (ev.src === 'ms2mw' && rel.ms) {
    addLine('M_w = ' + rel.ms.a + '\\,M_s + ' + rel.ms.b + ' = ' +
            rel.ms.a + '(' + ev.ms + ') + ' + rel.ms.b + ' = ' + mwu.toFixed(2),
            rel.ms.cite + ' (valid ' + rel.ms.lo + ' ≤ Ms ≤ ' + rel.ms.hi + ')');
  } else if (ev.src === 'mb2mw' && rel.mb) {
    addLine('M_w = ' + rel.mb.a + '\\,m_b + ' + rel.mb.b + ' = ' +
            rel.mb.a + '(' + ev.mb + ') + ' + rel.mb.b + ' = ' + mwu.toFixed(2),
            rel.mb.cite + ' (valid ' + rel.mb.lo + ' ≤ mb ≤ ' + rel.mb.hi + ')');
  } else if (ev.src === 'raw') {
    if (ev.ms !== null && ev.ms !== undefined && rel.ms &&
        (ev.ms < rel.ms.lo || ev.ms > rel.ms.hi)) {
      addLine('M_s = ' + ev.ms + ' \\notin [' + rel.ms.lo + ',\\,' + rel.ms.hi + ']',
              'outside the cited validity range — kept as reported, not extrapolated (' + rel.ms.cite + ')');
    } else if (ev.mb !== null && ev.mb !== undefined && rel.mb &&
               (ev.mb < rel.mb.lo || ev.mb > rel.mb.hi)) {
      addLine('m_b = ' + ev.mb + ' \\notin [' + rel.mb.lo + ',\\,' + rel.mb.hi + ']',
              'outside the cited validity range — kept as reported, not extrapolated (' + rel.mb.cite + ')');
    } else {
      addNote('No reported Mw/Ms/mb (Ml-only): no folder-backed Ml→Mw relation — magnitude kept as reported.');
    }
    addLine('M_w \\approx ' + mwu.toFixed(2) + '\\;\\;\\text{(reported ' +
            (ev.mag_type || 'scale') + ', unconverted)}');
  } else if (ev.src === 'user_coeffs') {
    addLine('M_w = a\\,M + b = ' + mwu.toFixed(2) + '\\;\\;\\text{(user-supplied coefficients)}');
  } else {
    addLine('M_w = ' + mwu.toFixed(2));
  }

  addLine('M_0 = 10^{1.5\\,M_w + 9.05} = 10^{1.5(' + mwu.toFixed(2) + ') + 9.05} = ' +
          sciTex(Number(ev.m0)) + '\\;\\mathrm{N{\\cdot}m}', rel.moment_cite);
  return wrap;
}

function toggleEvtDetail(tr) {
  var next = tr.nextElementSibling;
  if (next && next.classList.contains('evt-detail')) { next.remove(); return; }
  var reg = window._evtReg[tr.dataset.key] || {};
  var ev = (reg.events || [])[parseInt(tr.dataset.i, 10)];
  if (!ev) return;
  var row = document.createElement('tr');
  row.className = 'evt-detail';
  var cell = document.createElement('td');
  cell.colSpan = 10;
  cell.appendChild(evtDetailNode(ev, reg.rel));
  row.appendChild(cell);
  tr.parentNode.insertBefore(row, tr.nextSibling);
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
  // Focal-depth classes: unified project convention, labels come from the API.
  var dc = d.depth_classes || {};
  var dl = d.depth_class_labels || {};
  var depthRows = [
    { c: '#93c5fd', label: dl.shallow || 'Shallow (0–35 km)',           n: dc.shallow },
    { c: '#3b82f6', label: dl.intermediate || 'Mid-depth (35–70 km)',   n: dc.intermediate },
    { c: '#1e3a8a', label: dl.deep || 'Deep (70–700 km)',               n: dc.deep }
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
       'Catalog distribution (project convention, uniform across pages) — not drawn on map; shown on click.</div>';
  depthRows.forEach(function (r) {
    s += '<div style="display:flex; align-items:center; margin:4px 0">' +
         '<span style="width:14px; height:14px; border-radius:2px; background:' + r.c +
         '; display:inline-block; margin-right:8px; flex-shrink:0"></span>' +
         '<span>' + escapeHtml(r.label) + nTxt(r.n) + '</span></div>';
  });
  if (dc.unknown) {
    s += '<div style="font-size:11px; color:var(--text2); margin-top:2px">' + dc.unknown + ' event(s) without depth.</div>';
  }

  s += '<div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border); color:var(--text); font-size:12px">';
  s += '<div>Source: ' + escapeHtml(String(source || 'Uploaded catalog')) + '</div>';
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

    // Click anywhere on the map: list the top 5 events within 300 km.
    map.addSource('cat-click-radius', {
      type: 'geojson', data: { type: 'FeatureCollection', features: [] }
    });
    map.addLayer({
      id: 'cat-click-radius-line', type: 'line', source: 'cat-click-radius',
      paint: { 'line-color': '#f59e0b', 'line-width': 2, 'line-dasharray': [4, 2] }
    });
    map.on('click', function (e) {
      var hits = map.queryRenderedFeatures(e.point, { layers: ['eq-circles-map-catalog'] });
      if (hits.length) return;   // direct hit on a quake: the popup handles it
      showCatalogTop5(e.lngLat.lat, e.lngLat.lng, map);
    });
  });
}


// ── Catalog: top 5 earthquakes within the clicked area ──
// 300 km matches the site-radius convention used on the Declustering page.
var CAT_CLICK_RADIUS_KM = 300;

function jsHaversineKm(lat1, lon1, lat2, lon2) {
  var R = 6371.0, toRad = Math.PI / 180;
  var dLat = (lat2 - lat1) * toRad, dLon = (lon2 - lon1) * toRad;
  var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
          Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
          Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bearingCompass(lat1, lon1, lat2, lon2) {
  var toRad = Math.PI / 180;
  var dLon = (lon2 - lon1) * toRad;
  var y = Math.sin(dLon) * Math.cos(lat2 * toRad);
  var x = Math.cos(lat1 * toRad) * Math.sin(lat2 * toRad) -
          Math.sin(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.cos(dLon);
  var brng = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(brng / 45) % 8];
}

function ensureCatEvents(cb) {
  if (window._catEvents) { cb(window._catEvents); return; }
  fetch('/data/catalog.json').then(function (r) { return r.json(); }).then(function (p) {
    window._catEvents = (p.events || []).filter(function (ev) {
      return ev.latitude != null && ev.longitude != null;
    });
    cb(window._catEvents);
  }).catch(function () { toast('Could not load catalog.json', 'error'); });
}

function showCatalogTop5(lat, lon, map) {
  ensureCatEvents(function (events) {
    var hits = [];
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      var dist = jsHaversineKm(lat, lon, ev.latitude, ev.longitude);
      if (dist <= CAT_CLICK_RADIUS_KM) hits.push({ ev: ev, dist: dist });
    }
    hits.sort(function (a, b) { return (b.ev.mag || -99) - (a.ev.mag || -99); });
    var top = hits.slice(0, 5);

    if (map && map.getSource('cat-click-radius')) {
      map.getSource('cat-click-radius').setData(
        createGeoJSONCircle([lon, lat], CAT_CLICK_RADIUS_KM));
    }

    var el = document.getElementById('cat-top5');
    if (!el) return;
    var title = 'Top 5 earthquakes within ' + CAT_CLICK_RADIUS_KM + ' km of ' +
      lat.toFixed(3) + '°N, ' + lon.toFixed(3) + '°E';
    var html = '<div class="result-card"><h3>' + title + '</h3>';
    if (!top.length) {
      html += '<p style="color:var(--text2)">No catalogued events within ' +
        CAT_CLICK_RADIUS_KM + ' km of the clicked point.</p></div>';
      el.innerHTML = html;
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    html += '<div class="tbl-scroll" style="overflow-x:auto"><table><thead><tr>' +
      ['No.', 'Magnitude', 'Location Description', 'Date', 'Coordinates', 'Depth (km)']
        .map(function (c) { return '<th>' + c + '</th>'; }).join('') +
      '</tr></thead><tbody>';
    top.forEach(function (h, idx) {
      var ev = h.ev;
      var desc = Math.round(h.dist) + ' km ' +
        bearingCompass(lat, lon, ev.latitude, ev.longitude) + ' of clicked point';
      var date = ev.datetime_utc ? String(ev.datetime_utc).slice(0, 10)
        : (ev.year + '-' + String(ev.month).padStart(2, '0') + '-' +
           String(ev.day).padStart(2, '0') + ' (time flagged)');
      var coords = Number(ev.latitude).toFixed(2) + '°N, ' +
                   Number(ev.longitude).toFixed(2) + '°E';
      html += '<tr>' +
        '<td>' + (idx + 1) + '</td>' +
        '<td><strong>M ' + (ev.mag != null ? Number(ev.mag).toFixed(1) : '—') + '</strong>' +
          (ev.mag_type ? ' (' + escapeHtml(String(ev.mag_type)) + ')' : '') + '</td>' +
        '<td>' + escapeHtml(desc) +
          ' <span style="color:var(--text2)">[' + escapeHtml(String(ev.id)) + ']</span></td>' +
        '<td>' + escapeHtml(date) + '</td>' +
        '<td>' + coords + '</td>' +
        '<td>' + (ev.depth_km != null ? Number(ev.depth_km).toFixed(0) : '—') + '</td>' +
        '</tr>';
    });
    html += '</tbody></table></div>';
    html += '<p style="color:var(--text2);font-size:12px">' + hits.length +
      ' event(s) within the radius; ranked by preferred magnitude. The PHIVOLCS source has ' +
      'no place-name field, so the location is described relative to the clicked point.</p></div>';
    el.innerHTML = html;
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
  fd.append('homogenize', document.getElementById('dec-homog').checked ? '1' : '0');
  fd.append('dedup', document.getElementById('dec-dedup').checked ? '1' : '0');
  fd.append('harmonize_coeffs', document.getElementById('dec-harmonize').value);
  fd.append('mag_type_col', document.getElementById('dec-magtype').value);

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
    html += '<div class="metric"><div class="value">' + d.n_input + '</div><div class="label">Input Events</div></div>';
    html += '<div class="metric"><div class="value">' + d.n_total + '</div><div class="label">After Steps 1–2</div></div>';
    d.methods_used.forEach(function(m) {
      var s = d.method_stats[m];
      html += '<div class="metric"><div class="value">' + s.mainshocks + '</div><div class="label">' + methodNames[m] + '</div></div>';
    });
    html += '<div class="metric"><div class="value">' + d.n_within_300_main + '</div><div class="label">Mainshocks (300 km)</div></div>';
    html += '</div>';
    html += buildPipelineNotes(d);

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
      html += '<hr><h2>' + escapeHtml(String(sec.label)) + ' (' + sec.count + ' events)</h2>';

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
        html += '<p style="color:var(--warn)">Stepp error: ' + escapeHtml(String(sec.stepp_error)) + '</p>';
      }

      sec.plots.forEach(function(p) {
        var fname = p.title.replace(/[^a-zA-Z0-9]/g, '_') + '.png';
        html += '<h4>' + escapeHtml(String(p.title)) + '</h4>' + plotHTML(p.plot, fname);
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
  fd.append('homogenize', document.getElementById('gr-homog').checked ? '1' : '0');
  fd.append('dedup', document.getElementById('gr-dedup').checked ? '1' : '0');
  fd.append('decluster_first', document.getElementById('gr-decluster').checked ? '1' : '0');
  fd.append('compl_whole', document.getElementById('gr-compl').value);

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
      '  <div class="metric"><div class="value">' + d.b_value + ' &plusmn; ' + d.b_stderr + '</div><div class="label">b-value (Aki / Shi&ndash;Bolt)</div></div>' +
      '  <div class="metric"><div class="value">' + (d.completeness_used ? 'per level' : d.duration + ' yr') + '</div><div class="label">Duration</div></div>' +
      '  <div class="metric"><div class="value">' + d.n_events + '</div><div class="label">Events in fit</div></div>' +
      '</div>' +
      buildPipelineNotes(d) +
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
  fd.append('homogenize', document.getElementById('mfd-homog').checked ? '1' : '0');
  fd.append('dedup', document.getElementById('mfd-dedup').checked ? '1' : '0');
  fd.append('decluster_first', document.getElementById('mfd-decluster').checked ? '1' : '0');

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
      '  <div class="metric"><div class="value">' + d.b_value + ' &plusmn; ' + d.b_stderr + '</div><div class="label">b-value (combined)</div></div>' +
      '  <div class="metric"><div class="value">' + d.duration + ' yr</div><div class="label">Duration</div></div>' +
      '</div>';

    html += buildPipelineNotes(d);
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
// MOMENT MAGNITUDE (workflow item 1: homogenize to Mw)
// ════════════════════════════════════════════
async function runMomentMag() {
  var fd = new FormData();
  var src = appendCatalogInput(fd, 'mom');
  if (!src) return;

  fd.append('mag_col', document.getElementById('mom-mag').value);
  fd.append('time_col', document.getElementById('mom-time').value);
  fd.append('mag_type_col', document.getElementById('mom-magtype').value);
  fd.append('harmonize_coeffs', document.getElementById('mom-harmonize').value);

  busy('mom-run', 'mom-spin', true);
  try {
    var r = await fetch('/api/moment_magnitude', { method: 'POST', body: fd });
    var d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    addQAQC('Moment Magnitude', d.qaqc);

    var evs = d.events_detail || [];
    evs.forEach(function (e, i) { e._i = i; });
    window._evtReg['mom'] = { events: evs, rel: d.moment_relations || {} };
    window._momCSV = d.csv;

    var c = d.counts || {};
    var html = '<div class="result-card">';
    html += '<div class="metrics">';
    html += '<div class="metric"><div class="value">' + d.total_events + '</div><div class="label">Events</div></div>';
    [['mw', 'Reported Mw'], ['ms2mw', 'Ms→Mw'], ['mb2mw', 'mb→Mw'],
     ['user_coeffs', 'User coefficients'], ['raw', 'Kept as reported']].forEach(function (p) {
      if (c[p[0]]) html += '<div class="metric"><div class="value">' + c[p[0]] + '</div><div class="label">' + p[1] + '</div></div>';
    });
    html += '</div>';

    html += buildPipelineNotes(d);
    html += '<h2>Method (cited equations)</h2><div id="mom-method"></div>';
    html += '<h2>Magnitude–Time by Mw Basis</h2>' + plotHTML(d.plot, 'mw_homogenization.png');
    if (evs.length) {
      html += '<h2>Event Catalogue — per-event Mw conversion</h2>';
      html += '<div class="form-row"><div class="form-group">' +
        '<label>Filter (id / date / scale / basis)</label>' +
        '<input id="evt-filter-mom" oninput="filterEvtTable(\'mom\')" placeholder="e.g. 1948, Ms, kept"></div></div>';
      html += '<div id="evt-table-mom">' + buildEventsTable(evs, 'mom') + '</div>';
    }
    html += '<button class="btn btn-secondary" style="margin-top:8px" ' +
      'onclick="downloadBlob(window._momCSV,\'catalogue_mw.csv\')">Download homogenized CSV (mag_mw + basis)</button>';
    html += '</div>';

    document.getElementById('mom-results').innerHTML = html;
    var methodEl = document.getElementById('mom-method');
    if (methodEl && d.moment_relations) renderMethodEqs(methodEl, methodEqsMw(d.moment_relations));
    wireEvtTable('mom');
    toast('Homogenization to Mw complete');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('mom-run', 'mom-spin', false); }
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
  fd.append('m_min', document.getElementById('mmax-mmin').value);
  fd.append('homogenize', document.getElementById('mmax-homog').checked ? '1' : '0');
  fd.append('dedup', document.getElementById('mmax-dedup').checked ? '1' : '0');
  fd.append('decluster_first', document.getElementById('mmax-decluster').checked ? '1' : '0');

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
    html += '<div class="metric"><div class="value">' + res.mmax_kijko_sellevoll + '</div><div class="label">Kijko&ndash;Sellevoll Mmax</div></div>';
    html += '<div class="metric"><div class="value">+' + res.ks_increment + '</div><div class="label">K&ndash;S increment</div></div>';
    html += '<div class="metric"><div class="value">' + res.b_used + (res.b_stderr != null ? ' &plusmn; ' + res.b_stderr : '') + '</div><div class="label">b (' + escapeHtml(String(res.b_source)) + ')</div></div>';
    html += '<div class="metric"><div class="value">' + res.n_above_mmin + '</div><div class="label">Events &ge; Mmin ' + res.m_min + '</div></div>';
    html += '<div class="metric"><div class="value">' + escapeHtml(String(res.mag_range)) + '</div><div class="label">Mag Range</div></div>';
    html += '</div>';

    var evs = d.events_detail || [];
    evs.forEach(function (e, i) { e._i = i; });
    window._evtReg['mmax'] = { events: evs, rel: d.moment_relations || {} };

    html += buildPipelineNotes(d);
    html += '<h2>Method (cited equations)</h2><div id="mmax-method"></div>';
    html += '<h2>Magnitude-Time Distribution</h2>' + plotHTML(d.plot_scatter, 'mmax_scatter.png');
    html += '<h2>Cumulative Moment Release</h2>' + plotHTML(d.plot_moment, 'cumulative_moment.png');
    if (evs.length) {
      html += '<h2>Event Catalogue — per-event Mw &amp; moment computation</h2>';
      html += '<div class="form-row"><div class="form-group">' +
        '<label>Filter (id / date / scale / basis)</label>' +
        '<input id="evt-filter-mmax" oninput="filterEvtTable(\'mmax\')" placeholder="e.g. 1948, Ms, kept"></div></div>';
      html += '<div id="evt-table-mmax">' + buildEventsTable(evs, 'mmax') + '</div>';
    }
    html += '</div>';

    document.getElementById('mmax-results').innerHTML = html;
    var methodEl = document.getElementById('mmax-method');
    if (methodEl && d.moment_relations) renderMethodEqs(methodEl, methodEqsMmax(d.moment_relations));
    wireEvtTable('mmax');
    toast('Max magnitude estimation complete');
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { busy('mmax-run', 'mmax-spin', false); }
}

// ── Boot: catalog page is the landing page ──
loadCatalogPage();

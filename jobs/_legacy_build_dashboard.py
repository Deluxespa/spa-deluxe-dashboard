import json, html

d = json.load(open('/tmp/dashboard_data.json'))
DATA_JSON = json.dumps(d, ensure_ascii=False)

COLORS = {
 'Vortex Swimspa': '#2563eb',
 'Vortex Whirlpool': '#1e3a8a',
 'Treesse Whirlpool': '#7c3aed',
 'Sonstiges / unbekannt': '#94a3b8',
 'Fisher Swimspa': '#0d9488',
 'Fisher Whirlpool': '#134e4a',
 'Jacuzzi Whirlpool': '#ea580c',
 'Villeroy & Boch Whirlpool': '#b91c1c',
 'Sauna': '#92400e',
 'Pacific Spa Whirlpool': '#16a34a',
 'One Spa Whirlpool': '#db2777',
 'Jacuzzi Swimspa': '#ca8a04',
 'Wellis Whirlpool': '#0369a1',
 'Pergola / Lamellendach': '#65a30d',
 'Outdoor & Zubehör': '#57534e',
}
COLORS_JSON = json.dumps(COLORS, ensure_ascii=False)

ZONE_PATHS = json.load(open('/tmp/zone_paths.json'))
ZONE_PATHS_JSON = json.dumps(ZONE_PATHS, ensure_ascii=False)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kunden- & Umsatzanalyse — Alter · Region · Produkt</title>
<style>
  :root{
    --bg:#f5f6f8; --card:#ffffff; --text:#1a1d23; --sub:#5b6270; --border:#e4e6ea;
    --accent:#2563eb; --accent-soft:#eef2ff; --good:#16a34a; --bad:#dc2626;
    --shadow: 0 1px 3px rgba(20,20,30,.06), 0 1px 2px rgba(20,20,30,.04);
    --radius: 14px;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;}
  body{
    background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
    padding:28px 20px 80px;
  }
  .wrap{max-width:1280px;margin:0 auto;}
  header.top{margin-bottom:28px;}
  header.top h1{font-size:26px;font-weight:700;margin:0 0 6px;letter-spacing:-.01em;}
  header.top p{margin:0;color:var(--sub);font-size:14px;}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:22px 0 32px;}
  .kpi{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);}
  .kpi .label{font-size:12px;color:var(--sub);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;}
  .kpi .value{font-size:24px;font-weight:700;letter-spacing:-.01em;}
  .kpi .sub{font-size:12px;color:var(--sub);margin-top:4px;}

  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
  @media (max-width:900px){.grid2{grid-template-columns:1fr;}}

  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:20px 22px 22px;margin-bottom:20px;}
  .card h2{font-size:16px;margin:0 0 2px;font-weight:700;}
  .card .desc{font-size:12.5px;color:var(--sub);margin:0 0 16px;}

  .bar-row{display:flex;align-items:center;gap:10px;margin:7px 0;cursor:pointer;padding:3px 4px;border-radius:8px;transition:background .12s;}
  .bar-row:hover{background:#f2f4f7;}
  .bar-row.dim{opacity:.35;}
  .bar-label{width:230px;flex:0 0 230px;font-size:12.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .bar-track{flex:1;background:#eef0f3;border-radius:6px;height:20px;position:relative;overflow:hidden;}
  .bar-fill{height:100%;border-radius:6px;transition:width .5s cubic-bezier(.2,.8,.2,1);}
  .bar-val{flex:0 0 auto;min-width:150px;text-align:right;font-size:12px;color:var(--sub);font-variant-numeric:tabular-nums;}
  .bar-val b{color:var(--text);font-variant-numeric:tabular-nums;}

  table.heat{border-collapse:collapse;width:100%;font-size:11.5px;}
  table.heat th{font-weight:600;color:var(--sub);font-size:11px;padding:6px 4px;text-align:center;border-bottom:1px solid var(--border);}
  table.heat th.rowhead{text-align:left;}
  table.heat td{padding:0;text-align:center;border-bottom:1px solid #f1f2f4;}
  table.heat td.rowhead{text-align:left;padding:6px 8px 6px 2px;font-weight:600;color:var(--text);white-space:nowrap;font-size:12px;}
  .heat-cell{display:flex;flex-direction:column;align-items:center;justify-content:center;height:52px;cursor:default;position:relative;transition:transform .1s;}
  .heat-cell .pct{font-weight:700;font-size:12px;}
  .heat-cell .abs{font-size:9.5px;opacity:.75;margin-top:1px;}
  .heat-cell:hover{outline:2px solid #1a1d23;outline-offset:-2px;z-index:2;}
  .heat-wrap{overflow-x:auto;}

  .legend{display:flex;flex-wrap:wrap;gap:10px 18px;margin:4px 0 18px;}
  .legend-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--sub);}
  .legend-dot{width:10px;height:10px;border-radius:3px;flex:0 0 auto;}

  .callout{background:var(--accent-soft);border:1px solid #dbe4ff;border-radius:10px;padding:14px 16px;font-size:13px;line-height:1.55;margin-top:14px;color:#1e2a4a;min-height:20px;}
  .callout b{color:#0f172a;}
  .callout .muted{color:#5b6690;}
  .map-controls{display:flex;gap:22px;align-items:center;margin-bottom:18px;flex-wrap:wrap;}
  .map-label{font-size:13px;color:var(--sub);display:flex;align-items:center;gap:8px;}
  .map-label select{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:#fff;color:var(--text);}
  .seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  .seg-btn{padding:8px 14px;border:none;background:#fff;cursor:pointer;font-size:13px;color:var(--sub);font-family:inherit;}
  .seg-btn.active{background:var(--accent);color:#fff;}
  .seg-btn:not(:last-child){border-right:1px solid var(--border);}
  .map-wrap{display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;}
  .map-side{flex:1;min-width:240px;}
  .map-legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:6px;font-size:12.5px;color:var(--sub);min-height:18px;}
  .legend-item{display:inline-flex;align-items:center;gap:6px;}
  .legend-dot{width:10px;height:10px;border-radius:3px;display:inline-block;flex:0 0 auto;}
  #germany-svg path.zone{cursor:pointer;transition:opacity .12s,filter .12s;}
  #germany-svg path.zone:hover{opacity:.85;filter:brightness(1.06);}
  #germany-svg text.zone-label{pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;}
  #germany-svg circle.branch-dot{fill:#0f172a;stroke:#fff;stroke-width:2px;pointer-events:none;}
  #germany-svg text.branch-label{pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;font-size:10.5px;font-weight:700;fill:#0f172a;}

  .tag{display:inline-block;background:#eef0f3;color:var(--sub);border-radius:999px;padding:2px 9px;font-size:11px;margin-right:6px;}

  footer{margin-top:36px;color:var(--sub);font-size:11.5px;text-align:center;}
  .note{font-size:11.5px;color:var(--sub);background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:10px 14px;margin:0 0 24px;line-height:1.5;}
  .section-title{font-size:19px;font-weight:700;margin:34px 0 4px;letter-spacing:-.01em;}
  .section-sub{font-size:13px;color:var(--sub);margin:0 0 14px;}
  .year-bar{display:inline-flex;align-items:center;gap:8px;margin:0 0 10px;padding:5px 12px;background:#eef2f7;border:1px solid var(--border);border-radius:999px;font-size:12.5px;color:var(--sub);}
  .year-bar select{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:#fff;color:var(--text);}
</style>
</head>
<body>
<div class="wrap">

  <header class="top">
    <h1>Kunden- &amp; Umsatzanalyse — Alter · PLZ-Region · Produktkategorie</h1>
    <p>Quelle: HubSpot-Export (hubspot-export-summary.csv) · Deal-Namen &rarr; Produktkategorie, Vorname &rarr; geschätzte Alterstendenz, PLZ &rarr; Region</p>
  </header>

  <div class="note">
    ⚠️ <b>Methodik-Hinweis:</b> Es werden keine Kundenalter in HubSpot erfasst. Der Altersbereich ist eine <b>Tendenz-Schätzung</b> auf Basis der statistischen Verbreitung von Vornamen nach Geburtsjahrgang in Deutschland (Namensmoden-Wellen). Produktkategorien wurden aus dem Deal-Namen abgeleitet und Modellvarianten zu Produktfamilien zusammengefasst. Einträge ohne erkennbares Produkt bzw. ohne auswertbaren Vornamen/PLZ erscheinen als „Unbekannt“/„Sonstiges". Alle Zahlen sind Näherungswerte für die strategische Tendenz-Analyse, keine exakten demografischen Daten.
  </div>

  <div class="map-controls" style="margin-bottom:22px;">
    <label class="map-label">📅 Zeitraum:
      <select class="year-select"></select>
    </label>
    <span class="section-sub" style="margin:0;">Wirkt auf alle Auswertungen 1–6 unten.</span>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="year-bar">📅 Zeitraum: <select class="year-select"></select></div>
  <div class="section-title">1) Umsatz nach Altersgruppe</div>
  <p class="section-sub">Geschätzte Alterstendenz auf Basis der Vornamen-Geburtsjahrgänge · 10-Jahres-Bänder</p>
  <div class="card">
    <div id="chart-age"></div>
    <div class="callout" id="callout-age">👆 Klicke auf eine Altersgruppe für Details zu Top-Produkt &amp; Top-Region.</div>
  </div>

  <div class="year-bar">📅 Zeitraum: <select class="year-select"></select></div>
  <div class="grid2">
    <div class="card">
      <h2>2) Umsatz nach PLZ-Region</h2>
      <p class="desc">Gruppiert nach groben Postleitzahlen-Regionen (nicht im Detail)</p>
      <div id="chart-region"></div>
      <div class="callout" id="callout-region">👆 Klicke auf eine Region für Details.</div>
    </div>
    <div class="card">
      <h2>3) Umsatz nach Produktkategorie</h2>
      <p class="desc">Modellvarianten zu Produktfamilien zusammengefasst</p>
      <div id="chart-cat"></div>
      <div class="callout" id="callout-cat">👆 Klicke auf eine Produktkategorie für Details.</div>
    </div>
  </div>

  <div class="year-bar">📅 Zeitraum: <select class="year-select"></select></div>
  <div class="section-title">4) Welche Altersgruppe kauft welches Produkt?</div>
  <p class="section-sub">Farbintensität = Anteil des Umsatzes der Altersgruppe, der auf diese Produktkategorie entfällt (Zeilen-Prozent) · Zahl = € Umsatz</p>
  <div class="card">
    <div class="heat-wrap"><div id="heat-age-cat"></div></div>
  </div>

  <div class="year-bar">📅 Zeitraum: <select class="year-select"></select></div>
  <div class="section-title">5) Welche Produktkategorie verkauft sich in welcher Region am besten?</div>
  <p class="section-sub">Farbintensität = Anteil am Kategorie-Gesamtumsatz (Zeilen-Prozent) · Zahl = € Umsatz</p>
  <div class="card">
    <div class="heat-wrap"><div id="heat-cat-region" style="min-width:900px;"></div></div>
  </div>

  <div class="year-bar">📅 Zeitraum: <select class="year-select"></select></div>
  <div class="section-title">6) Deutschlandkarte — Umsatz &amp; Top-Produktkategorie je Region</div>
  <p class="section-sub">Schematische Kachel-Karte der 10 PLZ-Leitzonen (1. Ziffer der Postleitzahl) · Regionen ohne PLZ/Ausland sind hier nicht darstellbar und fehlen bewusst</p>
  <div class="card">
    <div class="map-controls">
      <label class="map-label">Altersgruppe:
        <select id="map-age-select"></select>
      </label>
      <div class="seg" id="map-mode-seg">
        <button type="button" class="seg-btn active" data-mode="umsatz">Umsatz-Heatmap</button>
        <button type="button" class="seg-btn" data-mode="kategorie">Top-Produktkategorie</button>
      </div>
    </div>
    <div class="map-wrap">
      <svg id="germany-svg" width="100%" style="max-width:360px;flex:0 0 auto;"></svg>
      <div class="map-side">
        <div id="map-legend" class="map-legend"></div>
        <div class="callout" id="callout-map">👆 Klicke auf eine Kachel für Details zur Region.</div>
      </div>
    </div>
  </div>

  <footer>
    Erstellt automatisch aus HubSpot-Rohdaten · Alle Angaben ohne Gewähr, Alterswerte sind statistische Tendenz-Schätzungen, keine Ist-Daten.
  </footer>

</div>

<script id="dashboard-data" type="application/json">__DATA_JSON__</script>
<script id="dashboard-colors" type="application/json">__COLORS_JSON__</script>
<script id="dashboard-zonepaths" type="application/json">__ZONE_PATHS_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
const COLORS = JSON.parse(document.getElementById('dashboard-colors').textContent);
const ZONE_PATHS = JSON.parse(document.getElementById('dashboard-zonepaths').textContent);
const DEFAULT_COLOR = '#64748b';

// ---------- Year filter ----------
let currentYear = 'all';
function cur(){ return DATA.by_year[currentYear]; }

const fmtEUR = new Intl.NumberFormat('de-DE', {style:'currency', currency:'EUR', maximumFractionDigits:0});
const fmtNum = new Intl.NumberFormat('de-DE');
const fmtPct = (v) => (v*100).toFixed(0) + '%';

function colorFor(name){ return COLORS[name] || DEFAULT_COLOR; }

// ---------- KPIs ----------
function renderKPIs(){
  const el = document.getElementById('kpis');
  const totalDeals = cur().total_n;
  const avg = cur().total_umsatz / totalDeals;
  const topCat = cur().categories[0];
  const topRegion = cur().regions[0];
  const items = [
    {label:'Gesamtumsatz', value: fmtEUR.format(cur().total_umsatz), sub: fmtNum.format(totalDeals) + ' Deals'},
    {label:'Ø Umsatz / Deal', value: fmtEUR.format(avg), sub:'über alle Deals'},
    {label:'Stärkste Kategorie', value: topCat.name, sub: fmtEUR.format(topCat.umsatz) + ' · ' + fmtPct(topCat.umsatz/cur().total_umsatz)},
    {label:'Stärkste Region', value: topRegion.name, sub: fmtEUR.format(topRegion.umsatz) + ' · ' + fmtPct(topRegion.umsatz/cur().total_umsatz)},
    {label:'Alterstendenz ermittelt', value: fmtNum.format(totalDeals - cur().no_age) + ' / ' + fmtNum.format(totalDeals), sub: fmtPct((totalDeals-cur().no_age)/totalDeals) + ' der Deals'},
  ];
  el.innerHTML = items.map(it => `
    <div class="kpi">
      <div class="label">${it.label}</div>
      <div class="value">${it.value}</div>
      <div class="sub">${it.sub}</div>
    </div>`).join('');
}

// ---------- Generic bar chart ----------
function renderBars(containerId, rows, opts){
  opts = opts || {};
  const max = Math.max(...rows.map(r=>r.umsatz));
  const el = document.getElementById(containerId);
  el.innerHTML = rows.map(r => {
    const pct = cur().total_umsatz ? (r.umsatz/cur().total_umsatz) : 0;
    const w = max ? (r.umsatz/max*100) : 0;
    return `<div class="bar-row" data-key="${encodeURIComponent(r.name)}">
      <div class="bar-label" title="${r.name}">${r.name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${colorFor(r.name)}"></div></div>
      <div class="bar-val"><b>${fmtEUR.format(r.umsatz)}</b> &nbsp;·&nbsp; ${fmtPct(pct)} &nbsp;·&nbsp; ${fmtNum.format(r.n)} Deals</div>
    </div>`;
  }).join('');
}

// ---------- Cross-filter click handlers ----------
function attachBarClicks(containerId, calloutId, kind){
  const el = document.getElementById(containerId);
  el.querySelectorAll('.bar-row').forEach(row => {
    row.addEventListener('click', () => {
      const key = decodeURIComponent(row.dataset.key);
      el.querySelectorAll('.bar-row').forEach(r2 => r2.classList.toggle('dim', decodeURIComponent(r2.dataset.key) !== key));
      showDetail(calloutId, kind, key);
    });
  });
}
function topFromMap(mapObj, filterFn, labelExtract){
  const entries = Object.entries(mapObj).filter(([k,v]) => filterFn(k) && v>0);
  entries.sort((a,b)=>b[1]-a[1]);
  return entries.map(([k,v]) => ({label: labelExtract(k), umsatz: v}));
}

function showDetail(calloutId, kind, key){
  const el = document.getElementById(calloutId);
  if(kind === 'age'){
    const cats = topFromMap(cur().age_cat, k => k.startsWith(key+'||'), k => k.split('||')[1]);
    const regs = topFromMap(cur().age_region, k => k.startsWith(key+'||'), k => k.split('||')[1]);
    const rowTotal = cats.reduce((s,c)=>s+c.umsatz,0);
    const topCat = cats[0], topReg = regs[0];
    el.innerHTML = `<b>Altersgruppe ${key}</b><span class="muted"> · Gesamtumsatz ${fmtEUR.format(rowTotal)} (${fmtPct(rowTotal/cur().total_umsatz)} vom Gesamtumsatz)</span><br>
      🏆 Top-Produkt: <b>${topCat.label}</b> (${fmtEUR.format(topCat.umsatz)}, ${fmtPct(topCat.umsatz/rowTotal)} dieser Altersgruppe)<br>
      📍 Top-Region: <b>${topReg.label}</b> (${fmtEUR.format(topReg.umsatz)}, ${fmtPct(topReg.umsatz/rowTotal)} dieser Altersgruppe)<br>
      <span class="muted">Weitere Kategorien: ${cats.slice(1,4).map(c=>c.label+' ('+fmtPct(c.umsatz/rowTotal)+')').join(', ') || '–'}</span>`;
  } else if(kind === 'region'){
    const cats = topFromMap(cur().cat_region, k => k.endsWith('||'+key), k => k.split('||')[0]);
    const ages = topFromMap(cur().age_region, k => k.endsWith('||'+key), k => k.split('||')[0]);
    const rowTotal = cats.reduce((s,c)=>s+c.umsatz,0);
    const topCat = cats[0], topAge = ages[0];
    el.innerHTML = `<b>${key}</b><span class="muted"> · Gesamtumsatz ${fmtEUR.format(rowTotal)} (${fmtPct(rowTotal/cur().total_umsatz)} vom Gesamtumsatz)</span><br>
      🏆 Top-Produkt: <b>${topCat.label}</b> (${fmtEUR.format(topCat.umsatz)}, ${fmtPct(topCat.umsatz/rowTotal)} dieser Region)<br>
      🎂 Stärkste Altersgruppe: <b>${topAge ? topAge.label : '–'}</b>${topAge ? ' ('+fmtEUR.format(topAge.umsatz)+', '+fmtPct(topAge.umsatz/rowTotal)+' dieser Region)' : ''}<br>
      <span class="muted">Weitere Kategorien: ${cats.slice(1,4).map(c=>c.label+' ('+fmtPct(c.umsatz/rowTotal)+')').join(', ') || '–'}</span>`;
  } else if(kind === 'cat'){
    const regs = topFromMap(cur().cat_region, k => k.startsWith(key+'||'), k => k.split('||')[1]);
    const ages = topFromMap(cur().age_cat, k => k.endsWith('||'+key), k => k.split('||')[0]);
    const rowTotal = regs.reduce((s,c)=>s+c.umsatz,0);
    const topReg = regs[0], topAge = ages[0];
    const products = DATA.category_products[key] || [];
    el.innerHTML = `<b>${key}</b><span class="muted"> · Gesamtumsatz ${fmtEUR.format(rowTotal)} (${fmtPct(rowTotal/cur().total_umsatz)} vom Gesamtumsatz)</span><br>
      📍 Top-Region: <b>${topReg ? topReg.label : '–'}</b>${topReg ? ' ('+fmtEUR.format(topReg.umsatz)+', '+fmtPct(topReg.umsatz/rowTotal)+' dieser Kategorie)' : ''}<br>
      🎂 Stärkste Altersgruppe: <b>${topAge ? topAge.label : '–'}</b>${topAge ? ' ('+fmtEUR.format(topAge.umsatz)+', '+fmtPct(topAge.umsatz/rowTotal)+' dieser Kategorie)' : ''}<br>
      <span class="muted">Weitere Regionen: ${regs.slice(1,4).map(c=>c.label+' ('+fmtPct(c.umsatz/rowTotal)+')').join(', ') || '–'}</span><br>
      📦 <span class="muted">Enthaltene Produkte/Modelle: ${products.length ? products.map(p=>html_escape(p)).join(', ') : '–'}</span>`;
  }
}

function html_escape(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ---------- Heatmap: Altersgruppe x Kategorie ----------
function renderHeatAgeCat(){
  const ages = cur().ages.filter(a=>a.name!=='Unbekannt').map(a=>a.name);
  const cats = cur().categories.map(c=>c.name);
  let html = '<table class="heat"><thead><tr><th class="rowhead">Altersgruppe</th>' +
    cats.map(c=>`<th>${c}</th>`).join('') + '</tr></thead><tbody>';
  ages.forEach(age => {
    const rowVals = cats.map(c => cur().age_cat[age+'||'+c] || 0);
    const rowTotal = rowVals.reduce((a,b)=>a+b,0);
    html += `<tr><td class="rowhead">${age}</td>`;
    cats.forEach((c,i) => {
      const v = rowVals[i];
      const pct = rowTotal ? v/rowTotal : 0;
      const alpha = Math.min(0.92, 0.08 + pct*1.6);
      const bg = v>0 ? hexToRgba(colorFor(c), alpha) : 'transparent';
      const textColor = alpha>0.55 ? '#fff' : '#334155';
      html += `<td><div class="heat-cell" style="background:${bg};color:${textColor}" title="${age} · ${c}: ${fmtEUR.format(v)} (${fmtPct(pct)} dieser Altersgruppe)">
        ${v>0 ? `<span class="pct">${fmtPct(pct)}</span><span class="abs">${fmtEURshort(v)}</span>` : ''}
      </div></td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  document.getElementById('heat-age-cat').innerHTML = html;
}

// ---------- Heatmap: Kategorie x Region ----------
function renderHeatCatRegion(){
  const cats = cur().categories.map(c=>c.name);
  const regions = cur().regions.map(r=>r.name);
  const shortRegion = (r) => r.replace(/\s*\(.*?\)/,'').trim();
  let html = '<table class="heat"><thead><tr><th class="rowhead">Kategorie</th>' +
    regions.map(r=>`<th>${shortRegion(r)}</th>`).join('') + '</tr></thead><tbody>';
  cats.forEach(cat => {
    const rowVals = regions.map(r => cur().cat_region[cat+'||'+r] || 0);
    const rowTotal = rowVals.reduce((a,b)=>a+b,0);
    html += `<tr><td class="rowhead">${cat}</td>`;
    regions.forEach((r,i) => {
      const v = rowVals[i];
      const pct = rowTotal ? v/rowTotal : 0;
      const alpha = Math.min(0.92, 0.08 + pct*1.8);
      const bg = v>0 ? hexToRgba(colorFor(cat), alpha) : 'transparent';
      const textColor = alpha>0.55 ? '#fff' : '#334155';
      html += `<td><div class="heat-cell" style="background:${bg};color:${textColor}" title="${cat} · ${r}: ${fmtEUR.format(v)} (${fmtPct(pct)} dieser Kategorie)">
        ${v>0 ? `<span class="pct">${fmtPct(pct)}</span><span class="abs">${fmtEURshort(v)}</span>` : ''}
      </div></td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  document.getElementById('heat-cat-region').innerHTML = html;
}

function hexToRgba(hex, a){
  const h = hex.replace('#','');
  const r = parseInt(h.substring(0,2),16), g = parseInt(h.substring(2,4),16), b = parseInt(h.substring(4,6),16);
  return `rgba(${r},${g},${b},${a})`;
}
function fmtEURshort(v){
  if(v >= 1000000) return (v/1000000).toFixed(1).replace('.',',') + 'M €';
  if(v >= 1000) return Math.round(v/1000) + 'k €';
  return Math.round(v) + ' €';
}

// ---------- Deutschlandkarte (echte PLZ-Leitzonen-Umrisse, 1. Ziffer der PLZ) ----------
const ZONE_REGION = {};
Object.entries(DATA.region_zone).forEach(([r,z]) => { ZONE_REGION[z] = r; });
let mapMode = 'umsatz';
let mapAge = 'Alle';

function mapShortLabel(region){
  return region.split(' (')[0].split(' / ')[0];
}

// Heat-Gradient fuer die Umsatz-Ansicht: helles Gelb -> Orange -> tiefes Rot
const HEAT_STOPS = [
  [0.00, [255,247,213]],
  [0.30, [254,204,92]],
  [0.60, [252,141,89]],
  [0.85, [227,74,51]],
  [1.00, [165,15,21]],
];
function heatColor(t){
  t = Math.max(0, Math.min(1, t));
  let a = HEAT_STOPS[0], b = HEAT_STOPS[HEAT_STOPS.length-1];
  for(let i=0;i<HEAT_STOPS.length-1;i++){
    if(t >= HEAT_STOPS[i][0] && t <= HEAT_STOPS[i+1][0]){ a = HEAT_STOPS[i]; b = HEAT_STOPS[i+1]; break; }
  }
  const span = (b[0]-a[0]) || 1;
  const f = (t - a[0]) / span;
  const rgb = a[1].map((c,i) => Math.round(c + (b[1][i]-c)*f));
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

function renderGermanyMap(){
  const svg = document.getElementById('germany-svg');
  const legend = document.getElementById('map-legend');
  const zoneVal = {};
  let maxVal = 0;

  Object.keys(ZONE_PATHS.paths).forEach(z => {
    const region = ZONE_REGION[z];
    if(mapMode === 'umsatz'){
      const v = cur().map_age_region[mapAge+'||'+region] || 0;
      zoneVal[z] = v;
      if(v > maxVal) maxVal = v;
    } else {
      const prefix = mapAge+'||', suffix = '||'+region;
      let bestCat = null, bestV = 0, tot = 0;
      Object.entries(cur().map_age_cat_region).forEach(([k,v]) => {
        if(v>0 && k.startsWith(prefix) && k.endsWith(suffix)){
          const cat = k.slice(prefix.length, k.length - suffix.length);
          tot += v;
          if(v > bestV){ bestV = v; bestCat = cat; }
        }
      });
      zoneVal[z] = {cat: bestCat, val: bestV, tot: tot};
    }
  });

  let svgInner = '';
  Object.entries(ZONE_PATHS.paths).forEach(([z, zp]) => {
    const region = ZONE_REGION[z];
    let fill, title;
    if(mapMode === 'umsatz'){
      const v = zoneVal[z];
      fill = (maxVal>0 && v>0) ? heatColor(v/maxVal) : '#eef1f5';
      title = mapShortLabel(region) + ' — ' + fmtEUR.format(v);
    } else {
      const info = zoneVal[z];
      fill = info.val>0 ? colorFor(info.cat) : '#eef1f5';
      title = info.val>0
        ? mapShortLabel(region) + ' — Top: ' + info.cat + ' (' + fmtEUR.format(info.val) + ', ' + fmtPct(info.val/(info.tot||1)) + ' dieser Region)'
        : mapShortLabel(region) + ' — keine Daten für diese Auswahl';
    }
    svgInner += `<path class="zone" d="${zp.d}" fill="${fill}" stroke="#ffffff" stroke-width="1.3" data-zone="${z}"><title>${title}</title></path>`;
  });
  Object.entries(ZONE_PATHS.paths).forEach(([z, zp]) => {
    svgInner += `<text class="zone-label" x="${zp.lx}" y="${zp.ly+4}" text-anchor="middle" font-size="15" font-weight="700" fill="#0f172a">${z}</text>`;
  });

  DATA.branches.forEach(b => {
    const label = html_escape(b.name);
    svgInner += `<g><circle class="branch-dot" cx="${b.x}" cy="${b.y}" r="6"><title>Filiale ${label} (${b.plz})</title></circle>` +
      `<text class="branch-label" x="${b.x}" y="${b.y-10}" text-anchor="middle">${label}</text></g>`;
  });

  svg.setAttribute('viewBox', `0 0 ${ZONE_PATHS.width} ${ZONE_PATHS.height}`);
  svg.setAttribute('height', ZONE_PATHS.height);
  svg.innerHTML = svgInner;
  svg.querySelectorAll('path.zone').forEach(p => {
    p.addEventListener('click', () => {
      const z = p.getAttribute('data-zone');
      showDetail('callout-map', 'region', ZONE_REGION[z]);
    });
  });

  const branchNote = `<span class="legend-item"><span class="legend-dot" style="background:#0f172a;border-radius:50%;"></span>Filialstandort</span>`;
  if(mapMode === 'umsatz'){
    legend.innerHTML = `<span class="muted">Farbe = Umsatz dieser Altersgruppe in der Region (helles Gelb = wenig, Orange/Rot = viel) · Ziffer = PLZ-Leitzone (1. Ziffer der PLZ)</span><br>${branchNote}`;
  } else {
    const usedCats = [...new Set(Object.values(zoneVal).map(v => v.cat).filter(Boolean))];
    legend.innerHTML = (usedCats.length
      ? usedCats.map(c => `<span class="legend-item"><span class="legend-dot" style="background:${colorFor(c)}"></span>${c}</span>`).join('')
      : '<span class="muted">Keine Daten für diese Auswahl</span>') + ` ${branchNote}`;
  }
}

const mapAgeSelect = document.getElementById('map-age-select');
function populateMapAgeSelect(){
  const prev = mapAgeSelect.value;
  mapAgeSelect.innerHTML = '';
  cur().map_ages.forEach(a => {
    const opt = document.createElement('option');
    opt.value = a;
    opt.textContent = a==='Alle' ? 'Alle Altersgruppen' : (a==='Unbekannt' ? 'Unbekannt (kein Vorname/PLZ)' : a);
    mapAgeSelect.appendChild(opt);
  });
  mapAge = cur().map_ages.includes(prev) ? prev : 'Alle';
  mapAgeSelect.value = mapAge;
}
mapAgeSelect.addEventListener('change', () => { mapAge = mapAgeSelect.value; renderGermanyMap(); });
document.querySelectorAll('#map-mode-seg .seg-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#map-mode-seg .seg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    mapMode = btn.getAttribute('data-mode');
    renderGermanyMap();
  });
});

// ---------- Wire up everything, driven by the year selector ----------
function renderAll(){
  renderKPIs();

  renderBars('chart-age', cur().ages.filter(a=>a.name!=='Unbekannt'), {});
  attachBarClicks('chart-age', 'callout-age', 'age');
  document.getElementById('callout-age').innerHTML = '👆 Klicke auf eine Altersgruppe für Details zu Top-Produkt &amp; Top-Region.';

  renderBars('chart-region', cur().regions, {});
  attachBarClicks('chart-region', 'callout-region', 'region');
  document.getElementById('callout-region').innerHTML = '👆 Klicke auf eine Region für Details.';

  renderBars('chart-cat', cur().categories, {});
  attachBarClicks('chart-cat', 'callout-cat', 'cat');
  document.getElementById('callout-cat').innerHTML = '👆 Klicke auf eine Produktkategorie für Details.';

  renderHeatAgeCat();
  renderHeatCatRegion();

  populateMapAgeSelect();
  document.getElementById('callout-map').innerHTML = '👆 Klicke auf eine Kachel für Details zur Region.';
  renderGermanyMap();
}

// Every "Zeitraum" dropdown (one above the KPIs and one above each of the
// 6 numbered sections) shares the same class and stays in sync: changing
// ANY of them updates currentYear, re-renders everything, and mirrors the
// new value into all the other dropdown instances.
const yearSelects = Array.from(document.querySelectorAll('.year-select'));
(function initYearSelects(){
  yearSelects.forEach(sel => {
    const optAll = document.createElement('option');
    optAll.value = 'all';
    optAll.textContent = 'Gesamt (alle Jahre)';
    sel.appendChild(optAll);
    DATA.years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y;
      opt.textContent = y;
      sel.appendChild(opt);
    });
    sel.value = currentYear;
    sel.addEventListener('change', () => {
      currentYear = sel.value;
      yearSelects.forEach(other => { if (other !== sel) other.value = currentYear; });
      renderAll();
    });
  });
})();

renderAll();
</script>
</body>
</html>
"""

out = HTML_TEMPLATE.replace('__DATA_JSON__', DATA_JSON).replace('__COLORS_JSON__', COLORS_JSON).replace('__ZONE_PATHS_JSON__', ZONE_PATHS_JSON)
outpath = '/Users/robertmedlin/Downloads/hubspot-custom-report-plz-name-summe-2026-08-07/Kunden-Umsatzanalyse-Alter-PLZ-Produkt.html'
with open(outpath, 'w', encoding='utf-8') as f:
    f.write(out)
print('written', outpath, len(out), 'bytes')

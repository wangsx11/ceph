// ============================================================
// utils.js — 公共工具函数、全局数据、导航
// ============================================================

// --- 随机 & 格式化 ---
const R = (a, b) => Math.random() * (b - a) + a;
const RI = (a, b) => Math.floor(R(a, b));
const F = (v, d = 1) => typeof v === 'number' ? v.toFixed(d) : v;
const TS = () => {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map(v => String(v).padStart(2, '0')).join(':');
};

// --- UI组件 ---
function tag(t, c) {
  return `<span class="tag" style="color:${c};background:${c}15;border:1px solid ${c}30">${t}</span>`;
}
function dot(s = 'online') {
  const c = s === 'online' ? '#00e888' : s === 'warning' ? '#ffb020' : '#ff4050';
  return `<div class="dot dot-pulse" style="background:${c};box-shadow:0 0 6px ${c}66"></div>`;
}
function prog(v, mx = 100, c = '#00d0f0') {
  const p = Math.min(v / mx * 100, 100);
  const cc = p > 85 ? '#ff4050' : p > 65 ? '#ffb020' : c;
  return `<div style="display:flex;align-items:center;gap:8px"><div class="prog-track"><div class="prog-fill" style="width:${p}%;background:linear-gradient(90deg,${cc}cc,${cc})"></div></div><span class="mono" style="font-size:11px;color:${cc};min-width:34px;text-align:right">${p.toFixed(0)}%</span></div>`;
}
function chead(title, icon, accent = '#00d0f0', right = '') {
  return `<div class="card-head" style="background:linear-gradient(90deg,${accent}0a,#243a52)"><div class="card-head-l"><div class="card-bar" style="background:${accent}"></div><span style="font-size:13px">${icon}</span><span class="card-title">${title}</span></div><div style="display:flex;align-items:center;gap:8px">${right}</div></div>`;
}
function metric(l, v, u = '', c = '#00d0f0') {
  return `<div class="metric"><div class="metric-v" style="color:${c}">${F(v)}${u ? `<span class="metric-u">${u}</span>` : ''}</div><div class="metric-l">${l}</div></div>`;
}

// --- 军事化命名 ---
const TYPES = ['侦察情报', '装备状态', '指令文书', '兵力部署', '通信日志'];
const TIERS = ['热层', '温层', '冷层'];
const NODES = ['前线指挥所', '后方指挥中心'];
function milName(i) {
  const t = TYPES[i % TYPES.length];
  const s = String(i + 1).padStart(2, '0');
  return `${t}_${String.fromCharCode(65 + i % 3)}${s}`;
}

// --- 全局对象数据 ---
const ALL_OBJS = [];
for (let i = 0; i < 30; i++) {
  ALL_OBJS.push({
    name: milName(i), type: TYPES[i % 5], size: RI(2, 16) + 'KB',
    tier: i < 3 ? '热层' : i < 20 ? '温层' : '冷层',
    createNode: NODES[i % 2], modNode: NODES[(i + 1) % 2],
    time: TS(), status: '正常', ver: RI(1, 5),
    hash: Math.random().toString(16).slice(2, 10),
    heat: R(0.2, 4.5).toFixed(1),
    fields: 'unit(部队番号), location(坐标), strength(兵力数), status(战备状态)'
  });
}

// --- 页面导航 ---
function goPage(name, el) {
  document.querySelectorAll('.pg').forEach(p => p.classList.add('hidden'));
  document.getElementById('pg-' + name).classList.remove('hidden');
  document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
}

// --- 时钟 ---
function tick() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();
}
setInterval(tick, 1000);

import { hide, setError, show } from './ui.js';

const PAGE_SIZE = 50;

const $search = document.getElementById('search');
const $source = document.getElementById('source');
const $sort = document.getElementById('sort');
const $status = document.getElementById('status');
const $error = document.getElementById('error');
const $empty = document.getElementById('empty');
const $list = document.getElementById('list');
const $rows = document.getElementById('rows');
const $pager = document.getElementById('pager');
const $range = document.getElementById('range');
const $prev = document.getElementById('prev');
const $next = document.getElementById('next');

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[character]));
}

function formatDuration(seconds) {
  if (seconds == null) return '\u2014';

  const roundedSeconds = Math.round(seconds);
  const hours = Math.floor(roundedSeconds / 3600);
  const minutes = Math.floor((roundedSeconds % 3600) / 60);
  const remainingSeconds = roundedSeconds % 60;
  const paddedMinutes = String(minutes).padStart(2, '0');
  const paddedSeconds = String(remainingSeconds).padStart(2, '0');
  return hours > 0
    ? `${hours}:${paddedMinutes}:${paddedSeconds}`
    : `${minutes}:${paddedSeconds}`;
}

let offset = 0;
let total = 0;
let requestSeq = 0; // Guards against stale responses overwriting newer ones.
const transcripts = new Map(); // video_id -> transcript text
let searchTimer = null;

function hasFilters() {
  return Boolean($search.value.trim()) || $source.value;
}

async function loadHistory() {
  const sequence = ++requestSeq;
  hide($error);
  hide($empty);
  hide($list);
  hide($pager);
  show($status);

  const params = new URLSearchParams();
  const query = $search.value.trim();
  if (query) params.set('q', query);
  if ($source.value) params.set('source', $source.value);
  params.set('sort', $sort.value);
  params.set('limit', PAGE_SIZE);
  params.set('offset', offset);

  try {
    const response = await fetch(`/ui/history?${params}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    if (sequence !== requestSeq) return; // A newer request superseded this one.
    total = data.total;
    render(data.items);
  } catch (error) {
    if (sequence !== requestSeq) return; // A newer request owns the UI now.
    hide($status);
    setError($error, error.message);
  }
}

function render(items) {
  hide($status);
  $rows.innerHTML = '';

  if (total === 0) {
    $empty.textContent = hasFilters()
      ? 'No transcripts match these filters.'
      : 'No saved transcripts yet \u2014 transcribe a video first.';
    show($empty);
    return;
  }

  for (const item of items) {
    $rows.insertAdjacentHTML('beforeend', rowHtml(item));
  }
  show($list);

  if (total > PAGE_SIZE) {
    const end = Math.min(offset + PAGE_SIZE, total);
    $range.textContent = `${offset + 1}\u2013${end} of ${total}`;
    $prev.disabled = offset === 0;
    $next.disabled = offset + PAGE_SIZE >= total;
    show($pager);
  }
}

function rowHtml(item) {
  const title = item.title
    ? escapeHtml(item.title)
    : `<span class="text-muted">${escapeHtml(item.video_id)}</span>`;
  const channel = item.channel
    ? `<div class="text-xs text-muted mt-0.5">${escapeHtml(item.channel)}</div>`
    : '';
  return `
    <tr class="border-t border-slate-700 cursor-pointer hover:bg-surface/60 transition-colors duration-150" data-vid="${escapeHtml(item.video_id)}">
      <td class="py-2.5 pr-4 align-top">
        <div class="font-medium">${title}</div>
        ${channel}
      </td>
      <td class="py-2.5 pr-4 align-top"><span class="text-xs text-muted bg-surface px-2 py-0.5 rounded">${escapeHtml(item.source)}</span></td>
      <td class="py-2.5 pr-4 align-top text-muted whitespace-nowrap">${escapeHtml(formatDuration(item.duration))}</td>
      <td class="py-2.5 pr-4 align-top text-muted whitespace-nowrap">${escapeHtml(item.upload_date || '\u2014')}</td>
      <td class="py-2.5 align-top text-muted whitespace-nowrap">${escapeHtml(item.created_at ? item.created_at.slice(0, 10) : '')}</td>
    </tr>
    <tr class="hidden" data-detail="${escapeHtml(item.video_id)}">
      <td colspan="5" class="pb-4">
        <div class="flex items-center gap-2">
          <div class="spinner" style="width:16px;height:16px;border-width:2px;"></div>
          <span class="text-muted text-xs">Loading transcript&hellip;</span>
        </div>
      </td>
    </tr>`;
}

async function toggleDetail(videoId) {
  const detailRow = $rows.querySelector(`[data-detail="${CSS.escape(videoId)}"]`);
  if (!detailRow) return;

  if (!detailRow.classList.contains('hidden')) {
    detailRow.classList.add('hidden');
    return;
  }
  detailRow.classList.remove('hidden');

  if (transcripts.has(videoId)) {
    fillDetail(detailRow, transcripts.get(videoId));
    return;
  }
  try {
    const response = await fetch(`/ui/history/${encodeURIComponent(videoId)}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    transcripts.set(videoId, data.transcript);
    fillDetail(detailRow, data.transcript);
  } catch {
    fillDetail(detailRow, 'Failed to load transcript.');
  }
}

function fillDetail(detailRow, text) {
  detailRow.querySelector('td').innerHTML = `
    <pre class="bg-surface rounded-lg p-4 text-sm leading-relaxed whitespace-pre-wrap max-h-[60vh] overflow-y-auto border border-slate-700">${escapeHtml(text)}</pre>`;
}

$rows.addEventListener('click', (event) => {
  const row = event.target.closest('tr[data-vid]');
  if (row) toggleDetail(row.dataset.vid);
});

$search.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    offset = 0;
    loadHistory();
  }, 300);
});
$source.addEventListener('change', () => {
  offset = 0;
  loadHistory();
});
$sort.addEventListener('change', () => {
  offset = 0;
  loadHistory();
});
$prev.addEventListener('click', () => {
  offset = Math.max(0, offset - PAGE_SIZE);
  loadHistory();
});
$next.addEventListener('click', () => {
  offset += PAGE_SIZE;
  loadHistory();
});

loadHistory();

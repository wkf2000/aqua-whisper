import { hide, setError, show } from './ui.js';

const POLL_INTERVAL = 3000;
const POLL_TIMEOUT = 5 * 60 * 1000;

const STAGES = [
  { key: 'checking_saved', label: 'Checking saved videos' },
  { key: 'downloading_subtitles', label: 'Downloading subtitles' },
  { key: 'downloading_audio', label: 'Downloading audio' },
  { key: 'transcribing_audio', label: 'Transcribing audio' },
  { key: 'summarizing', label: 'Generating summary' },
];

const $form = document.getElementById('form');
const $input = document.getElementById('url-input');
const $btn = document.getElementById('submit-btn');
const $status = document.getElementById('status');
const $stageList = document.getElementById('stage-list');
const $error = document.getElementById('error');
const $result = document.getElementById('result');
const $text = document.getElementById('summary-text');
const $source = document.getElementById('source-badge');
const $copyBtn = document.getElementById('copy-btn');

const $spinner = document.createElement('div');
$spinner.className = 'spinner-sm';

const stageItems = STAGES.map((stage) => {
  const item = document.createElement('li');
  item.className = 'flex items-center gap-3';

  const icon = document.createElement('span');
  icon.className = 'w-4 flex justify-center shrink-0';

  const label = document.createElement('span');
  label.textContent = stage.label;

  const note = document.createElement('span');
  note.className = 'text-xs text-muted/50';

  item.append(icon, label, note);
  return { item, icon, label, note };
});

$stageList.replaceChildren(...stageItems.map(({ item }) => item));

// Stage states: 'pending', 'active', 'done', or 'skipped'.
let stageStates = STAGES.map(() => 'pending');
let stageStartedAt = null;
let stageDurations = STAGES.map(() => null);
let stageTimer = null;

function resetStages() {
  stopStageTimer();
  // The first stage is active from the start: the task always begins there.
  stageStates = STAGES.map((_stage, index) => (index === 0 ? 'active' : 'pending'));
  stageStartedAt = Date.now();
  stageDurations = STAGES.map(() => null);
  stageTimer = setInterval(renderStages, 1000);
  renderStages();
}

function setActiveStage(stageKey) {
  const activeIndex = STAGES.findIndex((stage) => stage.key === stageKey);
  if (activeIndex === -1) return; // Unknown stage: keep the current display.
  const currentActiveIndex = stageStates.indexOf('active');
  if (activeIndex <= currentActiveIndex) return;

  const now = Date.now();
  if (currentActiveIndex !== -1 && stageStartedAt !== null) {
    stageDurations[currentActiveIndex] = Math.floor((now - stageStartedAt) / 1000);
  }

  stageStates = stageStates.map((state, index) => {
    if (index === activeIndex) return 'active';
    if (index < activeIndex) return state === 'active' || state === 'done' ? 'done' : 'skipped';
    return 'pending';
  });
  stageStartedAt = now;
  renderStages();
}

function finishStages() {
  const now = Date.now();
  const activeIndex = stageStates.indexOf('active');
  if (activeIndex !== -1 && stageStartedAt !== null) {
    stageDurations[activeIndex] = Math.floor((now - stageStartedAt) / 1000);
  }
  stageStates = stageStates.map((state) => {
    if (state === 'active') return 'done';
    if (state === 'pending') return 'skipped';
    return state;
  });
  stageStartedAt = null;
  stopStageTimer();
  renderStages();
}

function stopStageTimer() {
  if (stageTimer !== null) {
    clearInterval(stageTimer);
    stageTimer = null;
  }
}

function renderStages() {
  const activeIndex = stageStates.indexOf('active');
  const elapsed = stageStartedAt === null ? null : Math.floor((Date.now() - stageStartedAt) / 1000);

  stageItems.forEach(({ icon, label, note }, index) => {
    const state = stageStates[index];

    if (state === 'active') {
      icon.replaceChildren($spinner);
      icon.className = 'w-4 flex justify-center shrink-0';
      label.className = 'text-sm text-slate-50 font-medium';
    } else {
      icon.className = 'w-4 flex justify-center shrink-0 text-sm';
      icon.textContent = state === 'done' ? '✓' : state === 'skipped' ? '–' : '○';
      icon.classList.toggle('text-accent', state === 'done');
      icon.classList.toggle('text-muted/50', state !== 'done');
      label.className = state === 'done' ? 'text-sm text-muted' : 'text-sm text-muted/60';
    }
    const duration = state === 'active' && index === activeIndex
      ? elapsed
      : stageDurations[index];
    note.textContent = state === 'skipped'
      ? 'not needed'
      : duration === null
        ? ''
        : `${duration}s`;
  });
}

function resetUI() {
  hide($status);
  hide($error);
  hide($result);
  resetStages();
  $btn.disabled = false;
}

function copyViaExecCommand(text) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  textarea.setAttribute('aria-hidden', 'true');
  document.body.appendChild(textarea);
  textarea.select();

  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}

let copyResetTimer = null;

function setCopyState(label, colorClass) {
  $copyBtn.classList.remove('text-muted', 'text-accent', 'text-red-400');
  $copyBtn.classList.add(colorClass);
  $copyBtn.textContent = label;
}

function resetCopyButton() {
  clearTimeout(copyResetTimer);
  copyResetTimer = null;
  setCopyState('Copy', 'text-muted');
}

async function handleCopy() {
  const text = $text.textContent;
  let copied = false;

  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      copied = false;
    }
  }
  if (!copied) copied = copyViaExecCommand(text);

  setCopyState(copied ? 'Copied!' : 'Copy failed', copied ? 'text-accent' : 'text-red-400');

  clearTimeout(copyResetTimer);
  copyResetTimer = setTimeout(resetCopyButton, 2000);
}

$copyBtn.addEventListener('click', handleCopy);

async function handleSubmit(event) {
  event.preventDefault();
  resetUI();

  const url = $input.value.trim();
  if (!url) {
    stopStageTimer();
    return;
  }

  $btn.disabled = true;
  show($status);

  try {
    const response = await fetch('/ui/transcript', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_url: url, summarize: true }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.detail || `Request failed (${response.status})`);
    }

    const { task_id: taskId } = await response.json();
    pollResult(taskId);
  } catch (error) {
    stopStageTimer();
    hide($status);
    setError($error, error.message);
    $btn.disabled = false;
  }
}

function pollResult(taskId) {
  const start = Date.now();

  const timer = setInterval(async () => {
    if (Date.now() - start > POLL_TIMEOUT) {
      clearInterval(timer);
      stopStageTimer();
      hide($status);
      setError($error, 'Timed out waiting for summary. Please try again.');
      $btn.disabled = false;
      return;
    }

    try {
      const response = await fetch(`/ui/transcript/${taskId}`);
      const data = await response.json();

      if (data.status === 'pending') {
        if (data.stage) setActiveStage(data.stage);
        return;
      }

      clearInterval(timer);

      if (data.status === 'success') {
        finishStages();
        resetCopyButton();
        $text.textContent = data.summary ?? 'No summary available';
        $source.textContent = `source: ${data.source}`;
        show($result);
      } else {
        stopStageTimer();
        hide($status);
        setError($error, data.error || 'Transcript processing failed.');
      }

      $btn.disabled = false;
    } catch {
      clearInterval(timer);
      stopStageTimer();
      hide($status);
      setError($error, 'Lost connection to the server.');
      $btn.disabled = false;
    }
  }, POLL_INTERVAL);
}

$form.addEventListener('submit', handleSubmit);

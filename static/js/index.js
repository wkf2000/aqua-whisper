import { hide, setError, show } from './ui.js';

const POLL_INTERVAL = 3000;
const SUMMARY_POLL_TIMEOUT = 5 * 60 * 1000;
const DOWNLOAD_POLL_TIMEOUT = 30 * 60 * 1000;

const TRANSCRIPT_STAGES = [
  { key: 'checking_saved', label: 'Checking saved videos' },
  { key: 'downloading_subtitles', label: 'Downloading subtitles' },
  { key: 'downloading_audio', label: 'Downloading audio' },
  { key: 'transcribing_audio', label: 'Transcribing audio' },
  { key: 'summarizing', label: 'Generating summary' },
];

const DOWNLOAD_STAGES = [
  { key: 'probing_video', label: 'Fetching video info' },
  { key: 'downloading_video', label: 'Downloading video' },
];

const $form = document.getElementById('form');
const $input = document.getElementById('url-input');
const $btn = document.getElementById('submit-btn');
const $downloadBtn = document.getElementById('download-btn');
const $status = document.getElementById('status');
const $stageList = document.getElementById('stage-list');
const $error = document.getElementById('error');
const $result = document.getElementById('result');
const $text = document.getElementById('summary-text');
const $source = document.getElementById('source-badge');
const $copyBtn = document.getElementById('copy-btn');
const $downloadResult = document.getElementById('download-result');
const $downloadTitle = document.getElementById('download-title');
const $downloadMeta = document.getElementById('download-meta');
const $downloadLink = document.getElementById('download-link');

const $spinner = document.createElement('div');
$spinner.className = 'spinner-sm';

function setButtonsDisabled(disabled) {
  $btn.disabled = disabled;
  $downloadBtn.disabled = disabled;
}

function createStageTracker(stages) {
  // Stage states: 'pending', 'active', 'done', or 'skipped'.
  let states = [];
  let startedAt = null;
  let durations = [];
  let timer = null;

  const items = stages.map((stage) => {
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

  $stageList.replaceChildren(...items.map(({ item }) => item));

  function stopTimer() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function render() {
    const activeIndex = states.indexOf('active');
    const elapsed = startedAt === null ? null : Math.floor((Date.now() - startedAt) / 1000);

    items.forEach(({ icon, label, note }, index) => {
      const state = states[index];

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
        : durations[index];
      note.textContent = state === 'skipped'
        ? 'not needed'
        : duration === null
          ? ''
          : `${duration}s`;
    });
  }

  function reset() {
    stopTimer();
    // The first stage is active from the start: the task always begins there.
    states = stages.map((_stage, index) => (index === 0 ? 'active' : 'pending'));
    startedAt = Date.now();
    durations = stages.map(() => null);
    timer = setInterval(render, 1000);
    render();
  }

  function setActive(stageKey) {
    const activeIndex = stages.findIndex((stage) => stage.key === stageKey);
    if (activeIndex === -1) return; // Unknown stage: keep the current display.
    const currentActiveIndex = states.indexOf('active');
    if (activeIndex <= currentActiveIndex) return;

    const now = Date.now();
    if (currentActiveIndex !== -1 && startedAt !== null) {
      durations[currentActiveIndex] = Math.floor((now - startedAt) / 1000);
    }

    states = states.map((state, index) => {
      if (index === activeIndex) return 'active';
      if (index < activeIndex) return state === 'active' || state === 'done' ? 'done' : 'skipped';
      return 'pending';
    });
    startedAt = now;
    render();
  }

  function finish() {
    const now = Date.now();
    const activeIndex = states.indexOf('active');
    if (activeIndex !== -1 && startedAt !== null) {
      durations[activeIndex] = Math.floor((now - startedAt) / 1000);
    }
    states = states.map((state) => {
      if (state === 'active') return 'done';
      if (state === 'pending') return 'skipped';
      return state;
    });
    startedAt = null;
    stopTimer();
    render();
  }

  reset();

  return { reset, setActive, finish, stopTimer };
}

function resetUI() {
  hide($status);
  hide($error);
  hide($result);
  hide($downloadResult);
  setButtonsDisabled(false);
}

async function submitTask(url, endpoint, body, stages, pollOptions) {
  resetUI();
  setButtonsDisabled(true);
  show($status);
  const tracker = createStageTracker(stages);

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.detail || `Request failed (${response.status})`);
    }

    const { task_id: taskId } = await response.json();
    pollResult(taskId, tracker, pollOptions);
  } catch (error) {
    tracker.stopTimer();
    hide($status);
    setError($error, error.message);
    setButtonsDisabled(false);
  }
}

function pollResult(taskId, tracker, options) {
  const start = Date.now();

  const timer = setInterval(async () => {
    if (Date.now() - start > options.timeoutMs) {
      clearInterval(timer);
      tracker.stopTimer();
      hide($status);
      setError($error, options.timeoutMessage);
      setButtonsDisabled(false);
      return;
    }

    try {
      const response = await fetch(`${options.statusEndpoint}/${encodeURIComponent(taskId)}`);
      const data = await response.json();

      if (data.status === 'pending') {
        if (data.stage) tracker.setActive(data.stage);
        return;
      }

      clearInterval(timer);

      if (data.status === 'success') {
        tracker.finish();
        options.onResult(data, taskId);
      } else {
        tracker.stopTimer();
        hide($status);
        setError($error, data.error || options.failureMessage);
      }

      setButtonsDisabled(false);
    } catch {
      clearInterval(timer);
      tracker.stopTimer();
      hide($status);
      setError($error, 'Lost connection to the server.');
      setButtonsDisabled(false);
    }
  }, POLL_INTERVAL);
}

function handleSubmit(event) {
  event.preventDefault();
  const url = $input.value.trim();
  if (!url) return;
  submitTask(
    url,
    '/ui/transcript',
    { video_url: url, summarize: true },
    TRANSCRIPT_STAGES,
    {
      statusEndpoint: '/ui/transcript',
      timeoutMs: SUMMARY_POLL_TIMEOUT,
      timeoutMessage: 'Timed out waiting for summary. Please try again.',
      failureMessage: 'Transcript processing failed.',
      onResult: showSummaryResult,
    },
  );
}

function handleDownload() {
  const url = $input.value.trim();
  if (!url) return;
  submitTask(
    url,
    '/ui/download',
    { video_url: url },
    DOWNLOAD_STAGES,
    {
      statusEndpoint: '/ui/download',
      timeoutMs: DOWNLOAD_POLL_TIMEOUT,
      timeoutMessage: 'Timed out waiting for the download. Please try again.',
      failureMessage: 'Video download failed.',
      onResult: showDownloadResult,
    },
  );
}

function showSummaryResult(data) {
  resetCopyButton();
  $text.textContent = data.summary ?? 'No summary available';
  $source.textContent = `source: ${data.source}`;
  show($result);
}

function formatBytes(bytes) {
  if (typeof bytes !== 'number' || Number.isNaN(bytes) || bytes < 0) return '';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function showDownloadResult(data, taskId) {
  const size = formatBytes(data.size_bytes);
  $downloadTitle.textContent = data.title || data.file_name || 'Video';
  $downloadMeta.textContent = size ? `size: ${size}` : '';
  $downloadLink.href = `/ui/download/file/${encodeURIComponent(taskId)}`;
  show($downloadResult);
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

$form.addEventListener('submit', handleSubmit);
$downloadBtn.addEventListener('click', handleDownload);
$copyBtn.addEventListener('click', handleCopy);

const POLL_INTERVAL = 3000;
const POLL_TIMEOUT = 5 * 60 * 1000;

const $form = document.getElementById('form');
const $input = document.getElementById('url-input');
const $btn = document.getElementById('submit-btn');
const $status = document.getElementById('status');
const $error = document.getElementById('error');
const $result = document.getElementById('result');
const $text = document.getElementById('transcript-text');
const $source = document.getElementById('source-badge');
const $copyBtn = document.getElementById('copy-btn');

function show(element) {
  element.classList.remove('hidden');
}

function hide(element) {
  element.classList.add('hidden');
}

function setError(message) {
  $error.querySelector('p').textContent = message;
  show($error);
}

function resetUI() {
  hide($status);
  hide($error);
  hide($result);
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
  if (!url) return;

  $btn.disabled = true;
  show($status);

  try {
    const response = await fetch('/ui/transcript', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_url: url }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.detail || `Request failed (${response.status})`);
    }

    const { task_id: taskId } = await response.json();
    pollResult(taskId);
  } catch (error) {
    hide($status);
    setError(error.message);
    $btn.disabled = false;
  }
}

function pollResult(taskId) {
  const start = Date.now();

  const timer = setInterval(async () => {
    if (Date.now() - start > POLL_TIMEOUT) {
      clearInterval(timer);
      hide($status);
      setError('Timed out waiting for transcript. Please try again.');
      $btn.disabled = false;
      return;
    }

    try {
      const response = await fetch(`/ui/transcript/${taskId}`);
      const data = await response.json();

      if (data.status === 'pending') return;

      clearInterval(timer);
      hide($status);

      if (data.status === 'success') {
        resetCopyButton();
        $text.textContent = data.transcript;
        $source.textContent = `source: ${data.source}`;
        show($result);
      } else {
        setError(data.error || 'Transcript processing failed.');
      }

      $btn.disabled = false;
    } catch {
      clearInterval(timer);
      hide($status);
      setError('Lost connection to the server.');
      $btn.disabled = false;
    }
  }, POLL_INTERVAL);
}

$form.addEventListener('submit', handleSubmit);

// DOM helpers shared by the static pages.

export function show(element) {
  element.classList.remove('hidden');
}

export function hide(element) {
  element.classList.add('hidden');
}

export function setError(element, message) {
  element.querySelector('p').textContent = message;
  show(element);
}

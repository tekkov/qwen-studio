const iconPaths = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  message: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>',
  folder: '<path d="M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"/>',
  'folder-plus': '<path d="M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"/><path d="M12 10v6M9 13h6"/>',
  plug: '<path d="M12 22v-5M9 7V2M15 7V2M7 7h10v4a5 5 0 0 1-10 0z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.1 15a1.7 1.7 0 0 0-1.55-1H2.5v-4h.1A1.7 1.7 0 0 0 4.15 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 8.5 4a1.7 1.7 0 0 0 1-1.55V2.4h4v.1A1.7 1.7 0 0 0 14.55 4a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19 8.5a1.7 1.7 0 0 0 1.55 1h.1v4h-.1A1.7 1.7 0 0 0 19.4 15z"/>',
  file: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M8 10v8M12 10v8M16 10v8M5 6l1 16h12l1-16"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  terminal: '<path d="m4 17 6-5-6-5M12 19h8"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  paperclip: '<path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.4-9.4a4 4 0 0 1 5.7 5.7l-9.5 9.5a2 2 0 0 1-2.8-2.8l8.8-8.8"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/>',
  archive: '<path d="M3 5h18v4H3zM5 9v11h14V9M10 13h4"/>'
};

function renderIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(element => {
    const path = iconPaths[element.dataset.icon];
    if (!path) return;
    element.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  });
}

renderIcons();
window.renderQwenIcons = renderIcons;

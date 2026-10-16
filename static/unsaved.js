(() => {
  const editor = document.querySelector('[data-unsaved-editor]');
  if (!editor) return;
  const values = () => JSON.stringify(Array.from(editor.elements)
    .filter(field => field.name && !field.disabled && !['hidden', 'submit', 'button'].includes(field.type))
    .map(field => [field.name, field.type === 'checkbox' || field.type === 'radio' ? field.checked : field.value]));
  const baseline = values();
  const dirty = () => editor.dataset.unsaved === 'true' || values() !== baseline;
  let leaving = false;
  const confirmLeave = () => !dirty() || window.confirm(editor.dataset.leaveMessage);
  const preferences = new Map(Array.from(document.querySelectorAll('[data-auto-submit]'), field => [field, field.value]));
  document.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    if (event.target !== editor && !confirmLeave()) {
      event.preventDefault();
      for (const [field, value] of preferences) field.value = value;
      return;
    }
    leaving = true;
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
      || link.target === '_blank' || link.hasAttribute('download')) return;
    const url = new URL(link.href, window.location.href);
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
    if (!confirmLeave()) {
      event.preventDefault();
      return;
    }
    leaving = true;
  });
  window.addEventListener('beforeunload', event => {
    if (!leaving && dirty()) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  window.addEventListener('pageshow', () => { leaving = false; });
})();

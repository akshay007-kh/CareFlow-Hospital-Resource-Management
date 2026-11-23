document.addEventListener('DOMContentLoaded', function () {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const toggle = document.getElementById('sidebarToggle');
  const dismiss = document.getElementById('sidebarDismiss');
  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle('open', open);
    if (backdrop) backdrop.classList.toggle('show', open);
    if (toggle) toggle.setAttribute('aria-expanded', String(open));
  }
  if (toggle) toggle.addEventListener('click', () => setSidebar(!sidebar.classList.contains('open')));
  if (dismiss) dismiss.addEventListener('click', () => setSidebar(false));
  if (backdrop) backdrop.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') setSidebar(false); });
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', e => {
      if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
    });
  });
  document.querySelectorAll('.toast-close').forEach(button => {
    button.addEventListener('click', () => button.closest('.toast').remove());
  });
  const printButton = document.getElementById('printReport');
  if (printButton) printButton.addEventListener('click', () => window.print());
});

(() => {
  const list = document.querySelector('[data-order-list]');
  if (list) {
    const hidden = document.querySelector('#id_participant_order');
    let order = [...list.querySelectorAll('li')].filter(li => li.querySelector('input').checked).map(li => li.dataset.memberId);
    const sync = () => {
      const rows = [...list.querySelectorAll('li')];
      const selectedIds = new Set(rows.filter(li => li.querySelector('input').checked).map(li => li.dataset.memberId));
      order = order.filter(id => selectedIds.has(id));
      rows.forEach(li => { if (selectedIds.has(li.dataset.memberId) && !order.includes(li.dataset.memberId)) order.push(li.dataset.memberId); });
      order.forEach(id => list.appendChild(rows.find(li => li.dataset.memberId === id)));
      rows.filter(li => !selectedIds.has(li.dataset.memberId)).forEach(li => list.appendChild(li));
      hidden.value = order.join(',');
      list.querySelectorAll('li').forEach(li => {
        const checked = li.querySelector('input').checked;
        li.classList.toggle('disabled', !checked);
        li.querySelectorAll('[data-move]').forEach(button => { button.disabled = !checked; });
      });
    };
    list.addEventListener('change', event => { if (event.target.matches('input[type="checkbox"]')) sync(); });
    list.addEventListener('click', event => {
      const button = event.target.closest('[data-move]');
      if (!button) return;
      const row = button.closest('li');
      const index = order.indexOf(row.dataset.memberId);
      if (button.dataset.move === 'up' && index > 0) [order[index - 1], order[index]] = [order[index], order[index - 1]];
      if (button.dataset.move === 'down' && index >= 0 && index < order.length - 1) [order[index + 1], order[index]] = [order[index], order[index + 1]];
      sync();
    });
    sync();
  }

  const dashboard = document.querySelector('[data-dashboard]');
  const rosterPanel = document.querySelector('[data-roster-id][data-version]');
  const status = document.querySelector('[data-live-status]');
  const watched = dashboard || rosterPanel;
  if (watched && status) {
    const check = async () => {
      if (document.hidden) return;
      try {
        const response = await fetch('/api/dashboard/', {headers: {'Accept': 'application/json'}});
        if (!response.ok) return;
        const payload = await response.json();
        if (dashboard) {
          const cards = [...dashboard.querySelectorAll('[data-roster-id]')];
          const changed = cards.length !== payload.rosters.length || payload.rosters.some(item => {
            const card = dashboard.querySelector(`[data-roster-id="${item.id}"]`);
            return card && Number(card.dataset.version) !== item.version;
          });
          if (changed) window.location.reload();
        } else {
          const current = payload.rosters.find(item => String(item.id) === rosterPanel.dataset.rosterId);
          if (current && Number(rosterPanel.dataset.version) !== current.version) {
            status.textContent = 'This roster changed on another device. Refresh before taking an action.';
            document.querySelectorAll('a.button, .footer-actions a').forEach(link => {
              if (/complete|substitute|skip|undo|edit|current/.test(link.href)) {
                link.setAttribute('aria-disabled', 'true');
                link.classList.add('stale-action');
              }
            });
          }
        }
      } catch (_) { status.textContent = 'Connection interrupted. Actions will be checked again when the app is reachable.'; }
    };
    window.setInterval(check, 10000);
    window.addEventListener('focus', check);
    document.addEventListener('click', event => {
      if (event.target.closest('.stale-action')) event.preventDefault();
    });
  }
})();

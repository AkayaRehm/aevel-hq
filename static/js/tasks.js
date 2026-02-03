(function() {
  function api(method, path, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function(r) { return r.json(); });
  }

  function loadTasks() {
    return api('GET', '/api/tasks').then(function(data) { return data.tasks || []; });
  }

  function esc(s) { return (s || '').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  function urgencyLabel(u) { return u === 'high' ? 'High' : (u === 'low' ? 'Low' : 'Normal'); }

  function render(tasks) {
    var list = document.getElementById('task-list');
    if (!list) return;
    list.innerHTML = tasks.length ? tasks.map(function(t) {
      var assignee = t.assigned_to ? esc(t.assigned_to) : '';
      var due = t.due_date ? esc(t.due_date) : '';
      var urg = (t.urgency || 'normal');
      var meta = [];
      if (assignee) meta.push('<span class="task-meta task-assignee" title="Assigned to">' + assignee + '</span>');
      if (due) meta.push('<span class="task-meta task-due">Due ' + due + '</span>');
      meta.push('<span class="task-meta task-urgency task-urgency-' + urg + '">' + urgencyLabel(urg) + '</span>');
      return '<li class="task-item ' + (t.done ? 'done' : '') + '" data-id="' + (t.id || '') + '">' +
        '<input type="checkbox" class="task-done" ' + (t.done ? 'checked' : '') + ' aria-label="Mark done">' +
        '<div class="task-body">' +
        '<span class="task-text">' + esc(t.text) + '</span>' +
        (meta.length ? '<div class="task-meta-row">' + meta.join('') + '</div>' : '') +
        '</div>' +
        '<div class="task-actions"><button type="button" class="btn btn-small btn-danger task-delete" aria-label="Delete task">Delete</button></div></li>';
    }).join('') : '<li class="empty-state"><p class="empty-state__title">No tasks yet</p><p>Add one above to get started.</p></li>';
    list.querySelectorAll('.task-done').forEach(function(cb) {
      cb.addEventListener('change', function() {
        var id = cb.closest('.task-item').getAttribute('data-id');
        if (!id) return;
        var item = tasks.find(function(t) { return String(t.id) === id; });
        api('PATCH', '/api/tasks/' + id, { done: !item.done }).then(function() { loadTasks().then(render); });
      });
    });
    list.querySelectorAll('.task-delete').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var row = btn.closest('.task-item');
        var id = row && row.getAttribute('data-id');
        if (!id) return;
        var text = (row.querySelector('.task-text') && row.querySelector('.task-text').textContent) || 'this task';
        if (typeof Aevel !== 'undefined' && Aevel.confirm) {
          Aevel.confirm({ title: 'Delete task', body: 'Delete “‘ + text.substring(0, 40) + (text.length > 40 ? '…”' : '”') + '? This cannot be undone.', confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true }, function() {
            api('DELETE', '/api/tasks/' + id).then(function() { loadTasks().then(render); if (Aevel.toast) Aevel.toast('Task deleted', 'success'); });
          });
        } else {
          api('DELETE', '/api/tasks/' + id).then(function() { loadTasks().then(render); });
        }
      });
    });
  }

  var form = document.getElementById('task-form');
  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      var input = document.getElementById('task-input');
      var text = (input && input.value || '').trim();
      if (!text) return;
      var assignee = (document.getElementById('task-assignee') && document.getElementById('task-assignee').value || '').trim();
      var due = (document.getElementById('task-due') && document.getElementById('task-due').value || '').trim();
      var urgency = (document.getElementById('task-urgency') && document.getElementById('task-urgency').value) || 'normal';
      var body = { text: text, assigned_to: assignee || undefined, due_date: due || undefined, urgency: urgency };
      api('POST', '/api/tasks', body).then(function() {
        input.value = '';
        if (document.getElementById('task-assignee')) document.getElementById('task-assignee').value = '';
        if (document.getElementById('task-due')) document.getElementById('task-due').value = '';
        if (document.getElementById('task-urgency')) document.getElementById('task-urgency').value = 'normal';
        loadTasks().then(render);
        if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Task added', 'success');
      });
    });
  }

  loadTasks().then(render);
})();

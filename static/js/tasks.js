(function() {
  function api(method, path, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function(r) { return r.json(); });
  }

  function loadTasks() {
    return api('GET', '/api/tasks').then(function(data) { return data.tasks || []; });
  }

  function render(tasks) {
    var list = document.getElementById('task-list');
    list.innerHTML = tasks.map(function(t) {
      return '<li class="task-item ' + (t.done ? 'done' : '') + '" data-id="' + (t.id || '') + '">' +
        '<input type="checkbox" class="task-done" ' + (t.done ? 'checked' : '') + '>' +
        '<span class="task-text">' + (t.text || '').replace(/</g, '&lt;') + '</span>' +
        '<div class="task-actions"><button type="button" class="btn btn-small btn-danger task-delete">Delete</button></div></li>';
    }).join('') || '<li class="muted">No tasks</li>';
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
        var id = btn.closest('.task-item').getAttribute('data-id');
        if (!id) return;
        api('DELETE', '/api/tasks/' + id).then(function() { loadTasks().then(render); });
      });
    });
  }

  document.getElementById('task-form').addEventListener('submit', function(e) {
    e.preventDefault();
    var input = document.getElementById('task-input');
    var text = (input.value || '').trim();
    if (!text) return;
    api('POST', '/api/tasks', { text: text }).then(function() {
      input.value = '';
      loadTasks().then(render);
    });
  });

  loadTasks().then(render);
})();

(function() {
  function api(method, path, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function(r) { return r.json(); });
  }

  function loadNotes() {
    return api('GET', '/api/notes').then(function(data) { return data.notes || []; });
  }

  function render(notes) {
    var list = document.getElementById('notes-list');
    list.innerHTML = notes.map(function(n) {
      return '<li class="note-item" data-id="' + (n.id || '') + '">' +
        '<h4>' + (n.title || '').replace(/</g, '&lt;') + '</h4>' +
        '<p>' + (n.body || '').replace(/</g, '&lt;').replace(/\n/g, '<br>') + '</p>' +
        '<div class="note-actions"><button type="button" class="btn btn-small btn-danger note-delete">Delete</button></div></li>';
    }).join('') || '<li class="muted">No notes</li>';
    list.querySelectorAll('.note-delete').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var id = btn.closest('.note-item').getAttribute('data-id');
        if (!id) return;
        api('DELETE', '/api/notes/' + id).then(function() { loadNotes().then(render); });
      });
    });
  }

  document.getElementById('note-form').addEventListener('submit', function(e) {
    e.preventDefault();
    var title = document.getElementById('note-title').value.trim();
    var body = document.getElementById('note-body').value || '';
    if (!title) return;
    api('POST', '/api/notes', { title: title, body: body }).then(function() {
      document.getElementById('note-title').value = '';
      document.getElementById('note-body').value = '';
      loadNotes().then(render);
    });
  });

  loadNotes().then(render);
})();

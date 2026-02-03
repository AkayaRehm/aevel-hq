(function() {
  var monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  var current = new Date();
  var gridEl = document.getElementById('cal-grid');
  var titleEl = document.getElementById('cal-title');
  var eventsListEl = document.getElementById('events-list');
  var calDateInput = document.getElementById('cal-date');

  function api(method, path, body) {
    if (typeof Aevel !== 'undefined' && Aevel.api) {
      return Aevel.api(method, path, body);
    }
    var opts = { method: method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function(r) { return r.json().then(function(data) { if (!r.ok) throw new Error(data.error || 'Request failed'); return data; }); });
  }

  function toDateStr(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function setFormDateToToday() {
    if (calDateInput) calDateInput.value = toDateStr(new Date());
  }

  function loadEvents() {
    return api('GET', '/api/events').then(function(data) { return data.events || []; });
  }

  function renderCalendar() {
    if (!gridEl || !titleEl) return;
    var y = current.getFullYear();
    var m = current.getMonth();
    var todayStr = toDateStr(new Date());
    titleEl.textContent = monthNames[m] + ' ' + y;
    var first = new Date(y, m, 1);
    var last = new Date(y, m + 1, 0);
    var startDay = first.getDay();
    var daysInMonth = last.getDate();
    loadEvents().then(function(events) {
      if (!events) events = [];
      var eventByDate = {};
      var eventIdsByDate = {};
      events.forEach(function(ev) {
        var d = ev.date;
        if (d) {
          if (!eventByDate[d]) eventByDate[d] = [];
          eventByDate[d].push({ id: ev.id, title: (ev.title || '').replace(/</g, '&lt;') });
          eventIdsByDate[d] = (eventIdsByDate[d] || 0) + 1;
        }
      });
      var maxVisible = 4;
      var html = '';
      var dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      dayNames.forEach(function(d) { html += '<div class="cal-cell head">' + d + '</div>'; });
      var pad = startDay;
      var prevMonth = new Date(y, m, 0);
      var prevDays = prevMonth.getDate();
      for (var i = 0; i < pad; i++) {
        html += '<div class="cal-cell other">' + (prevDays - pad + i + 1) + '</div>';
      }
      for (var d = 1; d <= daysInMonth; d++) {
        var dateStr = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
        var dayEvents = eventByDate[dateStr] || [];
        var isToday = dateStr === todayStr;
        var cls = 'cal-cell' + (dayEvents.length ? ' has-event' : '') + (isToday ? ' today' : '') + ' cal-cell-droppable';
        var eventsHtml = '';
        dayEvents.slice(0, maxVisible).forEach(function(ev) {
          eventsHtml += '<span class="cal-cell-event cal-cell-event-draggable" data-event-id="' + ev.id + '" data-event-date="' + dateStr + '" draggable="true" title="Drag to move">' + ev.title + '</span>';
        });
        if (dayEvents.length > maxVisible) {
          eventsHtml += '<span class="cal-cell-event cal-cell-more">+' + (dayEvents.length - maxVisible) + '</span>';
        }
        html += '<div class="' + cls + '" data-date="' + dateStr + '" tabindex="0"><span class="cal-cell-day">' + d + '</span><span class="cal-cell-allday">All day</span><div class="cal-cell-events">' + eventsHtml + '</div></div>';
      }
      var total = pad + daysInMonth;
      var rest = total % 7 ? 7 - (total % 7) : 0;
      for (var j = 0; j < rest; j++) {
        html += '<div class="cal-cell other">' + (j + 1) + '</div>';
      }
      gridEl.innerHTML = html;
      var draggedEventId = null;
      gridEl.querySelectorAll('.cal-cell-event-draggable').forEach(function(span) {
        span.addEventListener('dragstart', function(e) {
          draggedEventId = this.getAttribute('data-event-id');
          e.dataTransfer.setData('text/plain', draggedEventId);
          e.dataTransfer.effectAllowed = 'move';
          this.classList.add('cal-dragging');
        });
        span.addEventListener('dragend', function() {
          this.classList.remove('cal-dragging');
          gridEl.querySelectorAll('.cal-cell-droppable').forEach(function(c) { c.classList.remove('cal-drag-over'); });
        });
      });
      gridEl.querySelectorAll('.cal-cell-droppable').forEach(function(cell) {
        cell.addEventListener('dragover', function(e) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          this.classList.add('cal-drag-over');
        });
        cell.addEventListener('dragleave', function() { this.classList.remove('cal-drag-over'); });
        cell.addEventListener('drop', function(e) {
          e.preventDefault();
          this.classList.remove('cal-drag-over');
          var eventId = e.dataTransfer.getData('text/plain');
          var newDate = this.getAttribute('data-date');
          if (!eventId || !newDate) return;
          api('PATCH', '/api/events/' + eventId, { date: newDate }).then(function(data) {
            renderCalendar();
            if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Event moved', 'success');
          }).catch(function() {});
        });
        cell.addEventListener('click', function(e) {
          if (e.target.classList.contains('cal-cell-event-draggable')) return;
          var date = this.getAttribute('data-date');
          if (date && calDateInput) {
            calDateInput.value = date;
            calDateInput.focus();
          }
        });
      });
      renderEventsList(events, y, m);
    }).catch(function() {
      if (gridEl) gridEl.innerHTML = '';
      if (eventsListEl) eventsListEl.innerHTML = '<li class="empty-state"><p class="empty-state__title">Failed to load events</p></li>';
      if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Failed to load events', 'error');
    });
  }

  var eventFilterQuery = '';
  function renderEventsList(events, y, m) {
    if (!eventsListEl) return;
    var monthStr = String(m + 1).padStart(2, '0');
    var inMonth = events.filter(function(e) {
      return e.date && e.date.startsWith(y + '-' + monthStr);
    }).sort(function(a, b) { return (a.date || '').localeCompare(b.date || ''); });
    var q = (eventFilterQuery || '').trim().toLowerCase();
    if (q) inMonth = inMonth.filter(function(e) { return (e.title || '').toLowerCase().indexOf(q) !== -1; });
    eventsListEl.innerHTML = inMonth.length ? inMonth.map(function(ev) {
      var escapedTitle = (ev.title || '').replace(/</g, '&lt;');
      return '<li class="event-list-item event-list-item-draggable" data-id="' + (ev.id || '') + '" data-date="' + (ev.date || '') + '" data-title="' + escapedTitle + '" draggable="true">' +
        '<span class="event-date">' + (ev.date || '') + '</span><span class="event-label">All day</span><span class="event-title">' + escapedTitle + '</span>' +
        '<div class="event-actions"><button type="button" class="btn btn-small btn-ghost event-edit" aria-label="Edit event">Edit</button>' +
        '<button type="button" class="btn btn-small btn-danger event-delete" data-id="' + (ev.id || '') + '" aria-label="Delete event">Delete</button></div></li>';
    }).join('') : '<li class="empty-state"><p class="empty-state__title">' + (eventFilterQuery ? 'No matching events' : 'No events this month') + '</p><p>Click a day above and add an event.</p></li>';
    eventsListEl.querySelectorAll('.event-delete').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var li = btn.closest('.event-list-item');
        var id = (li && li.getAttribute('data-id')) || btn.getAttribute('data-id');
        if (!id) return;
        var label = (li && li.querySelector('.event-title') && li.querySelector('.event-title').textContent) || 'this event';
        if (typeof Aevel !== 'undefined' && Aevel.confirm) {
          Aevel.confirm({ title: 'Delete event', body: 'Delete “‘ + label.substring(0, 50) + (label.length > 50 ? '…”' : '”') + '?', confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true }, function() {
            api('DELETE', '/api/events/' + id).then(function() { renderCalendar(); if (Aevel.toast) Aevel.toast('Event deleted', 'success'); }).catch(function() {});
          });
        } else {
          api('DELETE', '/api/events/' + id).then(function() { renderCalendar(); }).catch(function() {});
        }
      });
    });
    eventsListEl.querySelectorAll('.event-edit').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var li = btn.closest('.event-list-item');
        var id = li && li.getAttribute('data-id');
        var date = li && li.getAttribute('data-date');
        var title = (li && li.querySelector('.event-title') && li.querySelector('.event-title').textContent) || '';
        if (!id) return;
        var editRow = '<li class="event-edit-row" data-id="' + id + '">' +
          '<input type="date" class="input input-sm event-edit-date" value="' + (date || '') + '">' +
          '<input type="text" class="input input-sm event-edit-title" value="' + (title.replace(/"/g, '&quot;')) + '" placeholder="Title">' +
          '<button type="button" class="btn btn-small btn-primary event-save">Save</button>' +
          '<button type="button" class="btn btn-small btn-ghost event-cancel">Cancel</button></li>';
        li.insertAdjacentHTML('afterend', editRow);
        li.classList.add('hidden');
        var next = li.nextElementSibling;
        var dateInp = next.querySelector('.event-edit-date');
        var titleInp = next.querySelector('.event-edit-title');
        next.querySelector('.event-save').addEventListener('click', function() {
          var newDate = (dateInp && dateInp.value || '').trim();
          var newTitle = (titleInp && titleInp.value || '').trim();
          if (!newDate || !newTitle) { if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Date and title required', 'error'); return; }
          api('PATCH', '/api/events/' + id, { date: newDate, title: newTitle }).then(function() {
            next.remove();
            li.classList.remove('hidden');
            renderCalendar();
            if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Event updated', 'success');
          }).catch(function() {});
        });
        next.querySelector('.event-cancel').addEventListener('click', function() {
          next.remove();
          li.classList.remove('hidden');
        });
      });
    });
    eventsListEl.querySelectorAll('.event-list-item-draggable').forEach(function(li) {
      li.addEventListener('dragstart', function(e) {
        e.dataTransfer.setData('text/plain', this.getAttribute('data-id'));
        e.dataTransfer.effectAllowed = 'move';
        this.classList.add('cal-dragging');
      });
      li.addEventListener('dragend', function() {
        this.classList.remove('cal-dragging');
        if (gridEl) gridEl.querySelectorAll('.cal-cell-droppable').forEach(function(c) { c.classList.remove('cal-drag-over'); });
      });
    });
  }
  var calFilterEl = document.getElementById('cal-filter');
  if (calFilterEl) {
    calFilterEl.addEventListener('input', function() {
      eventFilterQuery = this.value || '';
      loadEvents().then(function(events) {
        if (!events) events = [];
        renderEventsList(events, current.getFullYear(), current.getMonth());
      }).catch(function() {});
    });
  }

  var prevBtn = document.getElementById('cal-prev');
  var nextBtn = document.getElementById('cal-next');
  var todayBtn = document.getElementById('cal-today');
  if (prevBtn) prevBtn.addEventListener('click', function() { current.setMonth(current.getMonth() - 1); renderCalendar(); });
  if (nextBtn) nextBtn.addEventListener('click', function() { current.setMonth(current.getMonth() + 1); renderCalendar(); });
  if (todayBtn) todayBtn.addEventListener('click', function() {
    current = new Date();
    renderCalendar();
    setFormDateToToday();
    if (Aevel && Aevel.toast) Aevel.toast('Showing today', 'success');
  });

  var calForm = document.getElementById('cal-form');
  if (calForm) {
    calForm.addEventListener('submit', function(e) {
      e.preventDefault();
      var dateEl = document.getElementById('cal-date');
      var titleEl = document.getElementById('cal-title-input');
      var date = dateEl && dateEl.value;
      var title = titleEl && titleEl.value && titleEl.value.trim();
      if (!date || !title) return;
      api('POST', '/api/events', { date: date, title: title }).then(function() {
        if (titleEl) titleEl.value = '';
        renderCalendar();
        if (typeof Aevel !== 'undefined' && Aevel.toast) Aevel.toast('Event added', 'success');
      }).catch(function() {});
    });
  }

  setFormDateToToday();
  renderCalendar();
})();

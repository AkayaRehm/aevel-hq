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
      var eventDates = {};
      var eventTitles = {};
      events.forEach(function(ev) {
        var d = ev.date;
        if (d) {
          eventDates[d] = (eventDates[d] || 0) + 1;
          if (!eventTitles[d]) eventTitles[d] = [];
          eventTitles[d].push((ev.title || '').replace(/</g, '&lt;'));
        }
      });
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
        var hasEvent = eventDates[dateStr];
        var isToday = dateStr === todayStr;
        var cls = 'cal-cell' + (hasEvent ? ' has-event' : '') + (isToday ? ' today' : '');
        var titles = (eventTitles[dateStr] || []).slice(0, 2).map(function(t) { return '<span class="cal-cell-event">' + t + '</span>'; }).join('');
        html += '<div class="' + cls + '" data-date="' + dateStr + '"><span class="cal-cell-day">' + d + '</span>' + titles + '</div>';
      }
      var total = pad + daysInMonth;
      var rest = total % 7 ? 7 - (total % 7) : 0;
      for (var j = 0; j < rest; j++) {
        html += '<div class="cal-cell other">' + (j + 1) + '</div>';
      }
      gridEl.innerHTML = html;
      gridEl.querySelectorAll('.cal-cell[data-date]').forEach(function(cell) {
        cell.addEventListener('click', function() {
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

  function renderEventsList(events, y, m) {
    if (!eventsListEl) return;
    var monthStr = String(m + 1).padStart(2, '0');
    var inMonth = events.filter(function(e) {
      return e.date && e.date.startsWith(y + '-' + monthStr);
    }).sort(function(a, b) { return (a.date || '').localeCompare(b.date || ''); });
    eventsListEl.innerHTML = inMonth.length ? inMonth.map(function(ev) {
      return '<li><span class="event-date">' + (ev.date || '') + '</span><span class="event-title">' + (ev.title || '').replace(/</g, '&lt;') + '</span><button type="button" class="btn btn-small btn-danger" data-id="' + (ev.id || '') + '" aria-label="Delete event">Delete</button></li>';
    }).join('') : '<li class="empty-state"><p class="empty-state__title">No events this month</p><p>Click a day above and add an event.</p></li>';
    eventsListEl.querySelectorAll('.btn-danger').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var id = btn.getAttribute('data-id');
        if (!id) return;
        var label = (btn.closest('li') && btn.closest('li').querySelector('.event-title') && btn.closest('li').querySelector('.event-title').textContent) || 'this event';
        if (typeof Aevel !== 'undefined' && Aevel.confirm) {
          Aevel.confirm({ title: 'Delete event', body: 'Delete “‘ + label.substring(0, 50) + (label.length > 50 ? '…”' : '”') + '?', confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true }, function() {
            api('DELETE', '/api/events/' + id).then(function() { renderCalendar(); if (Aevel.toast) Aevel.toast('Event deleted', 'success'); }).catch(function() {});
          });
        } else {
          api('DELETE', '/api/events/' + id).then(function() { renderCalendar(); }).catch(function() {});
        }
      });
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

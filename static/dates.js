(() => {
  const locale = document.documentElement.lang === "nl" ? "nl-NL" : "en-GB";
  const pad = value => String(value).padStart(2, "0");
  const format = day => `${pad(day.getDate())}-${pad(day.getMonth()+1)}-${day.getFullYear()}`;
  function parse(value) {
    const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
    if (!match) return null;
    const day = new Date(0);
    day.setFullYear(+match[3], +match[2]-1, +match[1]);
    day.setHours(12, 0, 0, 0);
    return format(day) === value ? day : null;
  }
  document.querySelectorAll("[data-european-date]").forEach(input => {
    const field = input.closest(".date-field"), toggle = field.querySelector(".date-toggle");
    const calendar = field.querySelector(".date-calendar"), grid = field.querySelector(".date-days");
    let cursor;
    toggle.hidden = false;
    const close = (focus = false) => {
      calendar.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      if (focus) toggle.focus();
    };
    function render(focus = false) {
      field.querySelector(".date-month").textContent = new Intl.DateTimeFormat(locale, {month:"long",year:"numeric"}).format(cursor);
      grid.replaceChildren();
      const first = new Date(cursor);
      first.setDate(1);
      const offset = (first.getDay()+6)%7;
      for (let i=0; i<7; i++) {
        const label = document.createElement("span");
        label.textContent = new Intl.DateTimeFormat(locale, {weekday:"narrow"}).format(new Date(2026, 0, 5+i));
        grid.append(label);
      }
      for (let i=0; i<offset; i++) grid.append(document.createElement("span"));
      const day = new Date(first);
      while (day.getMonth() === first.getMonth()) {
        const button = document.createElement("button"), value = format(day);
        button.type = "button";
        button.textContent = day.getDate();
        button.dataset.date = value;
        button.setAttribute("aria-label", value);
        if (input.value === value) button.setAttribute("aria-current", "date");
        button.addEventListener("click", () => {
          input.value = value;
          input.dispatchEvent(new Event("input", {bubbles:true}));
          input.dispatchEvent(new Event("change", {bubbles:true}));
          close(); input.focus();
        });
        grid.append(button);
        day.setDate(day.getDate()+1);
      }
      if (focus) grid.querySelector(`[data-date="${format(cursor)}"]`)?.focus();
    }
    toggle.addEventListener("click", () => {
      if (!calendar.hidden) { close(); return; }
      cursor = parse(input.value) || new Date();
      calendar.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      render(true);
    });
    field.querySelectorAll("[data-month]").forEach(button => button.addEventListener("click", () => {
      cursor.setDate(1);
      cursor.setMonth(cursor.getMonth() + Number(button.dataset.month));
      render();
    }));
    calendar.addEventListener("keydown", event => {
      if (!event.target.dataset.date) return;
      const movement = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-7, ArrowDown:7}[event.key];
      if (movement) {
        event.preventDefault();
        cursor = parse(event.target.dataset.date);
        cursor.setDate(cursor.getDate() + movement);
        render(true);
      }
    });
    field.addEventListener("keydown", event => {
      if (event.key === "Escape" && !calendar.hidden) { event.preventDefault(); close(true); }
    });
    field.addEventListener("focusout", () => {
      queueMicrotask(() => { if (!field.contains(document.activeElement)) close(); });
    });
    document.addEventListener("click", event => { if (!field.contains(event.target)) close(); });
  });
})();

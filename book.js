// Live price quote and slot warning on the booking form.
(function () {
  const form = document.getElementById("booking-form");
  if (!form) return;
  const venueId = form.dataset.venue;
  const $ = (name) => form.elements[name];
  const quoteBox = document.getElementById("quote");
  const warning = document.getElementById("slot-warning");
  const submit = document.getElementById("submit-btn");
  const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");
  const hour12 = (h) => ((h % 12) || 12) + ":00 " + (h % 24 < 12 ? "AM" : "PM");

  async function refresh() {
    const start = +$("start").value, end = +$("end").value;
    if (!(end > start)) { quoteBox.innerHTML = "<p class='meta'>Choose an end time after the start time.</p>"; submit.disabled = true; return; }

    let clash = false;
    if ($("date").value) {
      const res = await fetch(`/api/venues/${venueId}/day?date=${$("date").value}`);
      if (res.ok) {
        const taken = (await res.json()).taken;
        for (let h = start; h < end; h++) if (taken[h]) clash = true;
      }
    }
    warning.textContent = clash ? "Part of this time is already booked or on hold. Pick a free slot (see the calendar)." : "";
    submit.disabled = clash;

    const addons = [...form.querySelectorAll("input[name=addons]:checked")].map((c) => c.value).join(",");
    const q = new URLSearchParams({ venue_id: venueId, start, end, guests: $("guests").value || 1, addons });
    const res = await fetch("/api/quote?" + q);
    if (!res.ok) return;
    const data = await res.json();
    quoteBox.innerHTML =
      data.lines.map((l) => `<div class="row" style="justify-content:space-between"><span>${l.description.replace(/</g, "&lt;")}${l.quantity > 1 ? " × " + l.quantity : ""}</span><span>${inr(l.amount)}</span></div>`).join("") +
      `<div class="row" style="justify-content:space-between" class="meta"><span>GST 18%</span><span>${inr(data.tax)}</span></div>` +
      `<div class="quote-total"><span>Estimated total</span><span>${inr(data.total)}</span></div>`;
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  refresh();
})();

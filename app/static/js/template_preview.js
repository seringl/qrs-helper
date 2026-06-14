// Live card preview for the template editor (DESIGN.md §9.3)
// Drives five sliders (outer/inner radius, QR size, CTA & URL position),
// their − / + stepper buttons, and a live SVG preview.
(function () {
  const $ = (id) => document.getElementById(id);

  // Card geometry must match card_composer.py (1275 x 1650, 90px frame).
  const CARD_W = 1275;
  const FRAME = 90;
  const PANEL_X = FRAME;
  const PANEL_Y = FRAME;
  const PANEL_W = CARD_W - 2 * FRAME;   // 1095
  const PANEL_H = 1050;
  const TEXT_TARGET_W = PANEL_W - 80;   // matches card_composer (1015)

  // Size an SVG <text> so it renders exactly TEXT_TARGET_W wide — mirrors the
  // auto-fit in card_composer so the CTA and URL come out the same width.
  function fitText(el) {
    if (!el) return;
    el.setAttribute('font-size', 100);
    const len = el.getComputedTextLength() || 1;
    el.setAttribute('font-size', Math.max(12, Math.round(100 * TEXT_TARGET_W / len)));
  }

  const num = (id, fallback) => {
    const el = $(id);
    return el ? parseInt(el.value, 10) : fallback;
  };

  function sync() {
    const square = ($('t-style') && $('t-style').value === 'square');
    const outer = square ? 0 : num('corner_radius_px', 120);
    const inner = square ? 0 : num('inner_corner_radius_px', 30);
    const qrSize = num('qr_size_px', 880);
    const ctaY = num('cta_baseline_y', 1320);
    const urlY = num('url_baseline_y', 1480);

    // When the corner style is "square" the radius sliders are inert.
    const sizeBox = $('size-controls');
    if (sizeBox) {
      ['corner_radius_px', 'inner_corner_radius_px'].forEach((id) => {
        const row = $(id) && $(id).closest('.slider-row');
        if (row) row.style.opacity = square ? '0.45' : '1';
        if ($(id)) $(id).disabled = square;
      });
    }

    // Value badges
    const setVal = (id, v) => { if ($(id + '-val')) $(id + '-val').textContent = v; };
    setVal('corner_radius_px', outer);
    setVal('inner_corner_radius_px', inner);
    setVal('qr_size_px', qrSize);
    setVal('cta_baseline_y', ctaY);
    setVal('url_baseline_y', urlY);

    // Preview shapes
    if ($('p-card')) {
      $('p-card').setAttribute('rx', outer);
      if ($('t-bg')) $('p-card').setAttribute('fill', $('t-bg').value);
    }
    if ($('p-panel')) {
      $('p-panel').setAttribute('rx', inner);
      if ($('t-panel')) $('p-panel').setAttribute('fill', $('t-panel').value);
    }
    if ($('p-qr')) {
      // Centred horizontally in the card, vertically in the white panel.
      $('p-qr').setAttribute('width', qrSize);
      $('p-qr').setAttribute('height', qrSize);
      $('p-qr').setAttribute('x', (CARD_W - qrSize) / 2);
      $('p-qr').setAttribute('y', PANEL_Y + (PANEL_H - qrSize) / 2);
    }
    if ($('p-cta')) {
      $('p-cta').setAttribute('y', ctaY);
      if ($('t-text')) $('p-cta').setAttribute('fill', $('t-text').value);
    }
    if ($('p-url')) {
      $('p-url').setAttribute('y', urlY);
      if ($('t-text')) $('p-url').setAttribute('fill', $('t-text').value);
    }
    if ($('p-cta') && $('t-cta')) $('p-cta').textContent = $('t-cta').value || 'Scan for more info!';

    // Auto-fit both lines to the inner frame width (same as the printed card).
    fitText($('p-cta'));
    fitText($('p-url'));
  }

  // Wire live updates for every input that affects the preview.
  ['t-bg', 't-panel', 't-text', 't-cta',
   'corner_radius_px', 'inner_corner_radius_px', 'qr_size_px',
   'cta_baseline_y', 'url_baseline_y'].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener('input', sync);
  });
  if ($('t-style')) $('t-style').addEventListener('change', sync);

  // − / + stepper buttons nudge their slider by one step (or 1 unit).
  document.querySelectorAll('.step-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const slider = $(btn.dataset.target);
      if (!slider || slider.disabled) return;
      const step = parseInt(slider.step, 10) || 1;
      const dir = parseInt(btn.dataset.dir, 10);
      const min = parseInt(slider.min, 10);
      const max = parseInt(slider.max, 10);
      let next = (parseInt(slider.value, 10) || 0) + dir * step;
      next = Math.max(min, Math.min(max, next));
      slider.value = next;
      sync();
    });
  });

  sync();
  // Re-fit once Inter has actually loaded so the width measurement is correct.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(sync);
})();

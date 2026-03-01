/* =====================================================
   SmileLoop – Frontend Application
   Single-page: Upload → Email → Generate → Preview → Pay → Download
   ===================================================== */

(function () {
  'use strict';

  // ─── State ──────────────────────────────────────────
  const state = {
    currentPage: 'landing',
    selectedFile: null,
    email: '',
    jobId: null,
    pollTimer: null,
    turnstileToken: null,
    turnstileWidgetId: null,
    landingSlug: '',
    config: {
      stripe_publishable_key: '',
      price_cents: 499,
      price_display: '$4.99',
      turnstile_site_key: '',
    },
  };

  // ─── DOM References ─────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ─── Event Tracking ──────────────────────────────────
  function trackEvent(name, data = {}) {
    console.log('[SmileLoop]', name, data);
  }

  const pages = {
    landing: $('#page-landing'),
    processing: $('#page-processing'),
    preview: $('#page-preview'),
    success: $('#page-success'),
    error: $('#page-error'),
  };

  // ─── Navigation ─────────────────────────────────────
  function showPage(name) {
    Object.values(pages).forEach((p) => p.classList.remove('active'));
    const target = pages[name];
    if (target) {
      target.classList.add('active');
      target.classList.add('fade-in');
      state.currentPage = name;
      if (name !== 'landing') {
        window.scrollTo({ top: 0, behavior: 'instant' });
        hideStickyBar();
      }
    }
  }

  // ─── Toast ──────────────────────────────────────────
  function showToast(message, duration = 3000) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('visible');
    setTimeout(() => toast.classList.remove('visible'), duration);
  }

  // ─── Progressive Reveal ─────────────────────────────
  function revealUploadSteps() {
    const stepSubmit = $('#step-submit');
    if (stepSubmit) stepSubmit.style.display = 'block';
    hideStickyBar();
    setTimeout(() => {
      if (stepSubmit) {
        const scrollTarget = window.scrollY + stepSubmit.getBoundingClientRect().bottom - window.innerHeight + 40;
        if (scrollTarget > window.scrollY) {
          window.scrollTo({ top: scrollTarget, behavior: 'smooth' });
        }
      }
    }, 350);
  }

  // ─── Sticky mobile CTA bar ─────────────────────────
  let stickyObserver = null;

  function initStickyBar() {
    const stickyCta = $('#sticky-cta');
    const stickyBtn = $('#sticky-cta-btn');
    const dropzone = $('#dropzone');
    if (!stickyCta || !stickyBtn || !dropzone) return;

    stickyBtn.addEventListener('click', () => {
      dropzone.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => $('#file-input').click(), 400);
    });

    stickyObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (state.currentPage !== 'landing') return;
        if (state.selectedFile) {
          stickyCta.classList.remove('visible');
          return;
        }
        if (entry.isIntersecting) {
          stickyCta.classList.remove('visible');
        } else {
          stickyCta.classList.add('visible');
        }
      });
    }, { threshold: 0.1 });

    stickyObserver.observe(dropzone);
  }

  function hideStickyBar() {
    const stickyCta = $('#sticky-cta');
    if (stickyCta) stickyCta.classList.remove('visible');
  }

  // ─── Landing Page Detection ─────────────────────────
  function detectLandingPage() {
    var path = window.location.pathname.replace(/^\/+|\/$/, '').toLowerCase();
    // Ignore paths that are API or have query params like job_id (Stripe returns)
    if (path.startsWith('api/')) return '_default';
    return path || '_default';
  }

  function applyLandingContent() {
    if (typeof LANDING_PAGES === 'undefined') return;

    var slug = detectLandingPage();
    var data = LANDING_PAGES[slug] || LANDING_PAGES._default;
    state.landingSlug = data.slug || '';

    // Page title & meta
    document.title = data.pageTitle;
    var metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) metaDesc.setAttribute('content', data.metaDescription);

    // Hero content
    var headline = $('#lp-headline');
    if (headline) headline.textContent = data.headline;

    var sub = $('#lp-subheadline');
    if (sub) sub.textContent = data.subheadline;

    // Testimonial
    var testimonial = $('#lp-testimonial');
    if (testimonial) testimonial.innerHTML = data.testimonial.quote + ' — ' + data.testimonial.author;

    // Social proof
    var stars = $('#lp-stars');
    if (stars) stars.innerHTML = data.socialProof.stars + ' <span class="star-rating__count">' + data.socialProof.rating + '</span>';

    // Emotional section
    var emotional = $('#lp-emotional');
    if (emotional) emotional.innerHTML = data.emotionalText;

    // Trust badges
    var trustRow = $('#lp-trust-row');
    if (trustRow) {
      trustRow.innerHTML = data.trustBadges.map(function (b) { return '<span>' + b + '</span>'; }).join('');
    }

    // Demo before / after (images & videos)
    $$('.lp-demo-before').forEach(function (el) {
      el.src = data.demoBefore;
    });
    $$('.lp-demo-after').forEach(function (el) {
      var source = el.querySelector('source');
      if (source) { source.src = data.demoAfter; el.load(); }
    });

    // Add slug as body data-attribute for potential CSS theming
    document.body.setAttribute('data-landing', data.slug || 'home');
  }

  // ─── Init ───────────────────────────────────────────
  async function init() {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    window.scrollTo(0, 0);

    // Apply landing page content first (before anything shows)
    applyLandingContent();

    // Load config
    try {
      const resp = await fetch('/api/config');
      if (resp.ok) {
        state.config = await resp.json();
      }
    } catch (e) {
      console.warn('Could not load config:', e);
    }

    // Restore email from localStorage
    const savedEmail = localStorage.getItem('smileloop_email');
    if (savedEmail) {
      state.email = savedEmail;
      const emailInput = $('#email-input');
      if (emailInput) emailInput.value = savedEmail;
    }

    updatePriceDisplays();
    handleStripeReturn();
    bindEvents();
    initStickyBar();
  }

  function updatePriceDisplays() {
    const price = state.config.price_display || '$4.99';
    const unlockBtn = $('#unlock-btn');
    if (unlockBtn) {
      unlockBtn.textContent = 'Get My Video \u2013 ' + price;
      unlockBtn.disabled = false;
    }
  }

  // ─── Event Binding ──────────────────────────────────
  function bindEvents() {
    const dropzone = $('#dropzone');
    const fileInput = $('#file-input');

    dropzone.addEventListener('click', (e) => {
      if (e.target.id === 'change-photo' || e.target.closest('#change-photo')) {
        fileInput.click();
        return;
      }
      if (!state.selectedFile) {
        fileInput.click();
      }
    });

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      const files = e.dataTransfer.files;
      if (files.length > 0) handleFileSelect(files[0]);
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
    });

    $('#change-photo').addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });

    // Email input
    const emailInput = $('#email-input');
    if (emailInput) {
      emailInput.addEventListener('input', () => {
        state.email = emailInput.value.trim();
        validateForm();
      });

      emailInput.addEventListener('blur', () => {
        const error = $('#email-error');
        if (state.email && !isValidEmail(state.email)) {
          error.classList.add('visible');
        } else {
          error.classList.remove('visible');
        }
      });
    }

    // Submit
    $('#submit-btn').addEventListener('click', () => {
      trackEvent('submit_click');
      handleSubmit();
    });

    // Unlock (payment)
    $('#unlock-btn').addEventListener('click', () => {
      trackEvent('unlock_click');
      handlePayment();
    });

    // Download
    $('#download-btn').addEventListener('click', () => {
      trackEvent('download_click');
      handleDownload();
    });

    // Create another
    $('#create-another-btn').addEventListener('click', () => {
      resetState();
      showPage('landing');
    });

    // Retry
    $('#retry-btn').addEventListener('click', () => {
      resetState();
      showPage('landing');
    });
  }

  // ─── File Handling ──────────────────────────────────
  function handleFileSelect(file) {
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      showToast('Please upload a JPG or PNG image.');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      showToast('Photo is too large. Maximum size is 10 MB.');
      return;
    }

    state.selectedFile = file;
    trackEvent('photo_selected', { type: file.type, sizeKB: Math.round(file.size / 1024) });

    const reader = new FileReader();
    reader.onload = (e) => {
      const previewImg = $('#preview-image');
      previewImg.src = e.target.result;
      $('#dropzone-preview').classList.add('visible');

      const dropzone = $('#dropzone');
      dropzone.querySelector('.dropzone__icon').style.display = 'none';
      dropzone.querySelector('.dropzone__text').style.display = 'none';
      const hint = dropzone.querySelector('.text-small');
      if (hint) hint.style.display = 'none';

      revealUploadSteps();
    };
    reader.readAsDataURL(file);

    validateForm();
  }

  // ─── Validation ─────────────────────────────────────
  function isValidEmail(email) {
    return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
  }

  function validateForm() {
    const valid = state.selectedFile && isValidEmail(state.email);
    $('#submit-btn').disabled = !valid;
    return valid;
  }

  // ─── Submit ─────────────────────────────────────────
  async function handleSubmit() {
    if (!validateForm()) return;

    const btn = $('#submit-btn');

    // Step 1: If no Turnstile token, show the bot gate
    if (!state.turnstileToken) {
      showTurnstileGate();
      return;
    }

    // Step 2: We have a token — proceed
    btn.disabled = true;
    btn.textContent = 'Uploading\u2026';
    hideTurnstileGate();

    const formData = new FormData();
    formData.append('source_image', state.selectedFile);
    formData.append('email', state.email);
    formData.append('cf_turnstile_token', state.turnstileToken);

    try {
      const resp = await fetch('/api/generate', {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const status = resp.status;

        if (status === 403) {
          state.turnstileToken = null;
          resetTurnstileWidget();
          throw new Error(err.detail || 'Bot check failed. Please try again.');
        }
        if (status === 429) {
          throw new Error(err.detail || 'Too many requests. Try again later.');
        }
        throw new Error(err.detail || 'Upload failed.');
      }

      const data = await resp.json();
      state.jobId = data.job_id;

      // Save email for convenience
      localStorage.setItem('smileloop_email', state.email);

      showPage('processing');
      startPolling();
    } catch (e) {
      showToast(e.message || 'Something went wrong. Please try again.');
      btn.disabled = false;
      btn.textContent = 'Generate Preview \u2013 Free';
      state.turnstileToken = null;
      resetTurnstileWidget();
    }
  }

  // ─── Turnstile Bot Gate ─────────────────────────────
  function showTurnstileGate() {
    const gate = $('#turnstile-gate');
    if (!gate) return;

    gate.style.display = 'flex';

    if (state.turnstileWidgetId == null && typeof turnstile !== 'undefined') {
      state.turnstileWidgetId = turnstile.render('#turnstile-container', {
        sitekey: state.config.turnstile_site_key,
        callback: onTurnstileSuccess,
        'expired-callback': onTurnstileExpired,
        'error-callback': onTurnstileError,
        theme: 'light',
      });
    } else if (typeof turnstile === 'undefined') {
      setTimeout(() => showTurnstileGate(), 500);
    }
  }

  function hideTurnstileGate() {
    const gate = $('#turnstile-gate');
    if (gate) gate.style.display = 'none';
  }

  function resetTurnstileWidget() {
    if (state.turnstileWidgetId != null && typeof turnstile !== 'undefined') {
      try { turnstile.reset(state.turnstileWidgetId); } catch (e) { /* ok */ }
    }
    state.turnstileToken = null;
  }

  function onTurnstileSuccess(token) {
    state.turnstileToken = token;
    trackEvent('turnstile_passed');
    handleSubmit();
  }

  function onTurnstileExpired() {
    state.turnstileToken = null;
    showToast('Verification expired. Please try again.');
  }

  function onTurnstileError() {
    state.turnstileToken = null;
    showToast('Verification error. Please try again.');
  }

  // ─── Status Polling ─────────────────────────────────
  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);

    state.pollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/api/status/' + state.jobId);
        if (!resp.ok) throw new Error('Status check failed.');

        const data = await resp.json();

        if (data.status === 'preview_ready') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;

          const video = $('#preview-video');
          if (video && data.preview_url) {
            video.querySelector('source').src = data.preview_url;
            video.load();
            video.play().catch(() => {});
          }

          showPage('preview');
        } else if (data.status === 'paid') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          showPage('success');
        } else if (data.status === 'failed') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;

          // Show error message if available
          if (data.error) {
            const errMsg = $('#error-message');
            if (errMsg) errMsg.textContent = data.error;
          }
          showPage('error');
        }
      } catch (e) {
        console.error('Polling error:', e);
      }
    }, 2500);
  }

  // ─── Payment ────────────────────────────────────────
  async function handlePayment() {
    const btn = $('#unlock-btn');
    btn.disabled = true;
    btn.textContent = 'Redirecting\u2026';

    try {
      const resp = await fetch('/api/stripe/create-checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: state.jobId }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Payment setup failed.');
      }

      const data = await resp.json();

      if (data.already_paid) {
        showPage('success');
        return;
      }

      // Redirect to Stripe Checkout
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
      }

      // Fallback: use Stripe.js
      if (state.config.stripe_publishable_key && data.session_id) {
        const stripeClient = Stripe(state.config.stripe_publishable_key);
        await stripeClient.redirectToCheckout({ sessionId: data.session_id });
        return;
      }

      throw new Error('Payment is not configured yet. Please try again later.');
    } catch (e) {
      showToast(e.message);
      btn.disabled = false;
      updatePriceDisplays();
    }
  }

  // ─── Stripe Return / Email Deep-Link ─────────────────
  async function handleStripeReturn() {
    const params = new URLSearchParams(window.location.search);
    const jobId = params.get('job_id');
    const payment = params.get('payment');

    if (!jobId) return;

    state.jobId = jobId;

    // Clean URL — preserve landing slug
    var basePath = state.landingSlug ? '/' + state.landingSlug : '/';
    window.history.replaceState({}, '', basePath);

    if (payment === 'success') {
      try {
        const resp = await fetch('/api/verify-payment/' + jobId, { method: 'POST' });
        const data = await resp.json();

        if (data.paid) {
          showPage('success');
          return;
        }
      } catch (e) {
        console.error('Payment verification error:', e);
      }

      // Even if verification fails, show success (webhook will confirm)
      showPage('success');
    } else if (payment === 'cancelled') {
      try {
        const resp = await fetch('/api/status/' + jobId);
        const data = await resp.json();
        if (data.preview_url) {
          const video = $('#preview-video');
          video.querySelector('source').src = data.preview_url;
          video.load();
          video.play().catch(() => {});
        }
      } catch (e) { /* ignore */ }

      showPage('preview');
      showToast('Payment was cancelled. You can try again anytime.');
    } else {
      // Deep-link from email (no payment param) — show preview or download
      try {
        const resp = await fetch('/api/status/' + jobId);
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.status === 'paid') {
          // Already paid — go straight to download page
          showPage('success');
        } else if (data.status === 'preview_ready' && data.preview_url) {
          // Show watermarked preview
          const video = $('#preview-video');
          video.querySelector('source').src = data.preview_url;
          video.load();
          video.play().catch(() => {});
          showPage('preview');
        } else if (data.status === 'processing' || data.status === 'pending') {
          // Still processing — start polling
          showPage('processing');
          startPolling();
        } else if (data.status === 'failed') {
          const errMsg = $('#error-message');
          if (errMsg && data.error) errMsg.textContent = data.error;
          showPage('error');
        }
      } catch (e) {
        console.error('Deep-link status check error:', e);
      }
    }
  }

  // ─── Download ───────────────────────────────────────
  function handleDownload() {
    if (!state.jobId) return;
    window.open('/api/download/' + state.jobId, '_blank');
  }

  // ─── Reset ──────────────────────────────────────────
  function resetState() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.selectedFile = null;
    state.jobId = null;
    state.pollTimer = null;

    // Reset upload UI
    const dropzone = $('#dropzone');
    dropzone.querySelector('.dropzone__icon').style.display = '';
    dropzone.querySelector('.dropzone__text').style.display = '';
    const hint = dropzone.querySelector('.text-small');
    if (hint) hint.style.display = '';
    $('#dropzone-preview').classList.remove('visible');
    $('#file-input').value = '';

    // Hide progressive steps
    const stepSubmit = $('#step-submit');
    if (stepSubmit) stepSubmit.style.display = 'none';

    // Reset button
    const btn = $('#submit-btn');
    btn.disabled = true;
    btn.textContent = 'Generate Preview \u2013 Free';

    // Reset Turnstile
    state.turnstileToken = null;
    if (state.turnstileWidgetId != null && typeof turnstile !== 'undefined') {
      try { turnstile.remove(state.turnstileWidgetId); } catch (e) { /* ok */ }
      state.turnstileWidgetId = null;
    }
    hideTurnstileGate();

    // Reset email
    const emailInput = $('#email-input');
    if (emailInput) emailInput.value = '';
    state.email = '';

    // Reset unlock button
    updatePriceDisplays();
    const unlockBtn = $('#unlock-btn');
    if (unlockBtn) unlockBtn.disabled = false;
  }

  // ─── Boot ───────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();

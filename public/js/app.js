/* =====================================================
   SmileLoop – Frontend Application
   Single-page app: Landing → Upload → Processing → Preview → Payment → Success
   ===================================================== */

(function () {
  'use strict';

  // ─── State ──────────────────────────────────────────
  const state = {
    currentPage: 'landing',
    selectedFile: null,
    selectedAnimation: 'smile_wink',
    email: '',
    jobId: null,
    pollTimer: null,
    config: {
      stripe_publishable_key: '',
      price_cents: 799,
      price_display: '$7.99',
    },
  };

  // ─── DOM References ─────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const pages = {
    landing: $('#page-landing'),
    upload: $('#page-upload'),
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
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  // ─── Toast ──────────────────────────────────────────
  function showToast(message, duration = 3000) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('visible');
    setTimeout(() => toast.classList.remove('visible'), duration);
  }

  // ─── Init ───────────────────────────────────────────
  async function init() {
    // Load config
    try {
      const resp = await fetch('/api/config');
      if (resp.ok) {
        state.config = await resp.json();
      }
    } catch (e) {
      console.warn('Could not load config:', e);
    }

    // Update price displays
    updatePriceDisplays();

    // Check URL for returning from Stripe
    handleStripeReturn();

    // Bind events
    bindEvents();
  }

  function updatePriceDisplays() {
    const price = state.config.price_display || '$7.99';
    const unlockBtn = $('#unlock-btn');
    if (unlockBtn) {
      unlockBtn.textContent = `Unlock Full Video – ${price}`;
    }
  }

  // ─── Event Binding ──────────────────────────────────
  function bindEvents() {
    // CTA buttons → go to upload
    ['#hero-cta', '#bottom-cta', '#nav-cta'].forEach((sel) => {
      const el = $(sel);
      if (el) el.addEventListener('click', (e) => { e.preventDefault(); showPage('upload'); });
    });

    // Dropzone
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

    // Animation cards
    $$('.animation-card').forEach((card) => {
      card.addEventListener('click', () => {
        $$('.animation-card').forEach((c) => c.classList.remove('selected'));
        card.classList.add('selected');
        state.selectedAnimation = card.dataset.animation;
        validateForm();
      });
    });

    // Email input
    const emailInput = $('#email-input');
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

    // Submit
    $('#submit-btn').addEventListener('click', handleSubmit);

    // Unlock (payment)
    $('#unlock-btn').addEventListener('click', handlePayment);

    // Download
    $('#download-btn').addEventListener('click', handleDownload);

    // Create another
    $('#create-another-btn').addEventListener('click', () => {
      resetState();
      showPage('upload');
    });

    // Retry
    $('#retry-btn').addEventListener('click', () => {
      resetState();
      showPage('upload');
    });
  }

  // ─── File Handling ──────────────────────────────────
  function handleFileSelect(file) {
    // Validate type
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      showToast('Please upload a JPG or PNG image.');
      return;
    }

    // Validate size
    if (file.size > 10 * 1024 * 1024) {
      showToast('Photo is too large. Maximum size is 10 MB.');
      return;
    }

    state.selectedFile = file;

    // Show preview
    const reader = new FileReader();
    reader.onload = (e) => {
      const previewImg = $('#preview-image');
      previewImg.src = e.target.result;
      $('#dropzone-preview').classList.add('visible');

      // Hide default content
      const dropzone = $('#dropzone');
      dropzone.querySelector('.dropzone__icon').style.display = 'none';
      dropzone.querySelector('.dropzone__text').style.display = 'none';
      dropzone.querySelector('.text-small')?.style && (dropzone.querySelectorAll('.text-small')[0].style.display = 'none');
    };
    reader.readAsDataURL(file);

    validateForm();
  }

  // ─── Validation ─────────────────────────────────────
  function isValidEmail(email) {
    return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
  }

  function validateForm() {
    const valid = state.selectedFile && state.selectedAnimation && isValidEmail(state.email);
    $('#submit-btn').disabled = !valid;
    return valid;
  }

  // ─── Submit Upload ──────────────────────────────────
  async function handleSubmit() {
    if (!validateForm()) return;

    const btn = $('#submit-btn');
    btn.disabled = true;
    btn.textContent = 'Uploading…';

    const formData = new FormData();
    formData.append('photo', state.selectedFile);
    formData.append('animation', state.selectedAnimation);
    formData.append('email', state.email);

    try {
      const resp = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Upload failed.');
      }

      const data = await resp.json();
      state.jobId = data.job_id;

      // Go to processing page
      showPage('processing');

      // Start polling
      startPolling();
    } catch (e) {
      showToast(e.message || 'Something went wrong. Please try again.');
      btn.disabled = false;
      btn.textContent = 'Create My Preview';
    }
  }

  // ─── Status Polling ─────────────────────────────────
  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);

    state.pollTimer = setInterval(async () => {
      try {
        const resp = await fetch(`/api/status/${state.jobId}`);
        if (!resp.ok) throw new Error('Status check failed.');

        const data = await resp.json();

        if (data.status === 'preview_ready') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;

          // Set preview video
          const video = $('#preview-video');
          video.querySelector('source').src = data.preview_url;
          video.load();

          showPage('preview');
        } else if (data.status === 'paid') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          showPage('success');
        } else if (data.status === 'failed') {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
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
    btn.textContent = 'Redirecting…';

    try {
      const resp = await fetch('/api/create-checkout', {
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

  // ─── Stripe Return ──────────────────────────────────
  async function handleStripeReturn() {
    const params = new URLSearchParams(window.location.search);
    const jobId = params.get('job_id');
    const payment = params.get('payment');

    if (!jobId) return;

    state.jobId = jobId;

    // Clean URL
    window.history.replaceState({}, '', '/');

    if (payment === 'success') {
      // Verify payment server-side
      try {
        const resp = await fetch(`/api/verify-payment/${jobId}`, { method: 'POST' });
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
      // Show preview again
      try {
        const resp = await fetch(`/api/status/${jobId}`);
        const data = await resp.json();
        if (data.preview_url) {
          const video = $('#preview-video');
          video.querySelector('source').src = data.preview_url;
          video.load();
        }
      } catch (e) { /* ignore */ }

      showPage('preview');
      showToast('Payment was cancelled. You can try again anytime.');
    }
  }

  // ─── Download ───────────────────────────────────────
  function handleDownload() {
    if (!state.jobId) return;
    window.open(`/api/download/${state.jobId}`, '_blank');
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
    const smallTexts = dropzone.querySelectorAll('.text-small');
    if (smallTexts[0]) smallTexts[0].style.display = '';
    $('#dropzone-preview').classList.remove('visible');
    $('#file-input').value = '';

    // Reset button
    const btn = $('#submit-btn');
    btn.disabled = true;
    btn.textContent = 'Create My Preview';

    // Reset unlock button
    updatePriceDisplays();
    $('#unlock-btn').disabled = false;
  }

  // ─── Boot ───────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();

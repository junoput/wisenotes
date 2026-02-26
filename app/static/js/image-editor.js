/**
 * Image Editor — Full-screen overlay with crop, color correction, and color switching.
 *
 * Opens as a modal over the page. All edits are applied to an offscreen canvas
 * and saved back to the server when the user clicks "Save".
 */

(() => {
  let state = {
    imageUrl: null,
    noteId: null,
    chapterId: null,
    originalImage: null,   // HTMLImageElement of original
    canvas: null,          // visible <canvas>
    ctx: null,
    activeTool: null,      // 'crop' | 'color' | 'colorSwitch' | null
    // Crop state
    crop: { x: 0, y: 0, w: 0, h: 0, dragging: false, handle: null },
    // Color correction state
    color: { hue: 0, brightness: 0, whiteBalance: 0 },
    // Color switch state
    colorSwitch: { selectedColor: null, targetColor: null, tolerance: 30 },
  };

  /**
   * Open the image editor overlay.
   */
  window.openImageEditor = function (imageUrl, noteId, chapterId) {
    state.imageUrl = imageUrl;
    state.noteId = noteId;
    state.chapterId = chapterId;
    state.activeTool = null;
    state.color = { hue: 0, brightness: 0, whiteBalance: 0 };

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'image-editor-overlay';
    overlay.id = 'image-editor-overlay';

    overlay.innerHTML = `
      <button class="image-editor-close" onclick="closeImageEditor()" title="Close">&times;</button>
      <div class="image-editor-canvas-area" id="ie-canvas-area">
        <canvas id="ie-canvas"></canvas>
      </div>
      <div id="ie-panel"></div>
      <div class="image-editor-toolbar" id="ie-toolbar">
        <button class="image-editor-tool" data-tool="crop">
          <span class="image-editor-tool-icon">&#9986;</span> Crop
        </button>
        <button class="image-editor-tool" data-tool="color">
          <span class="image-editor-tool-icon">&#9728;</span> Color Correction
        </button>
        <button class="image-editor-tool" data-tool="colorSwitch">
          <span class="image-editor-tool-icon">&#127912;</span> Color Switch
        </button>
      </div>
      <div class="image-editor-actions" id="ie-actions">
        <button class="btn" onclick="applyImageEdit()">Save</button>
        <button class="btn ghost" onclick="closeImageEditor()">Cancel</button>
      </div>
    `;

    document.body.appendChild(overlay);

    // Load image
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      state.originalImage = img;
      state.canvas = document.getElementById('ie-canvas');
      state.ctx = state.canvas.getContext('2d');
      resetCanvas();
    };
    img.src = imageUrl;

    // Tool selection
    overlay.querySelectorAll('[data-tool]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tool = btn.dataset.tool;
        setActiveTool(tool === state.activeTool ? null : tool);
      });
    });

    // Close on Escape
    document.addEventListener('keydown', onEditorKeydown);
  };

  function onEditorKeydown(e) {
    if (e.key === 'Escape') closeImageEditor();
  }

  window.closeImageEditor = function () {
    const overlay = document.getElementById('image-editor-overlay');
    if (overlay) overlay.remove();
    document.removeEventListener('keydown', onEditorKeydown);
    state = {
      ...state,
      imageUrl: null,
      originalImage: null,
      canvas: null,
      ctx: null,
      activeTool: null,
    };
  };

  function resetCanvas() {
    const { canvas, ctx, originalImage: img } = state;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);
    // Reset crop to full image
    state.crop = { x: 0, y: 0, w: canvas.width, h: canvas.height, dragging: false, handle: null };
  }

  function setActiveTool(tool) {
    state.activeTool = tool;
    // Update toolbar buttons
    document.querySelectorAll('#ie-toolbar .image-editor-tool').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tool === tool);
    });
    // Render panel
    renderPanel(tool);
    // Reset canvas to original then apply corrections
    applyColorCorrection();
  }

  function renderPanel(tool) {
    const panel = document.getElementById('ie-panel');
    if (!panel) return;

    if (tool === 'crop') {
      panel.innerHTML = `
        <div class="image-editor-panel">
          <button class="btn" onclick="applyCrop()">Apply Crop</button>
          <button class="btn ghost" onclick="resetCrop()">Reset</button>
          <span style="color: var(--muted); font-size: 12px;">Click and drag on the image to select crop area</span>
        </div>
      `;
      enableCropMode();
    } else if (tool === 'color') {
      const { hue, brightness, whiteBalance } = state.color;
      panel.innerHTML = `
        <div class="image-editor-panel">
          <div class="image-editor-slider">
            <label>Hue</label>
            <input type="range" min="-180" max="180" value="${hue}" id="ie-hue">
            <span id="ie-hue-val">${hue}°</span>
          </div>
          <div class="image-editor-slider">
            <label>Brightness</label>
            <input type="range" min="-100" max="100" value="${brightness}" id="ie-brightness">
            <span id="ie-brightness-val">${brightness}</span>
          </div>
          <div class="image-editor-slider">
            <label>White Balance</label>
            <input type="range" min="-100" max="100" value="${whiteBalance}" id="ie-wb">
            <span id="ie-wb-val">${whiteBalance}</span>
          </div>
          <button class="btn ghost" onclick="resetColor()">Reset</button>
        </div>
      `;
      disableCropMode();
      // Bind sliders
      ['hue', 'brightness', 'wb'].forEach((name) => {
        const el = document.getElementById(`ie-${name}`);
        if (el) {
          el.addEventListener('input', () => {
            const val = parseInt(el.value);
            if (name === 'hue') state.color.hue = val;
            else if (name === 'brightness') state.color.brightness = val;
            else if (name === 'wb') state.color.whiteBalance = val;
            const label = document.getElementById(`ie-${name}-val`);
            if (label) label.textContent = name === 'hue' ? `${val}°` : `${val}`;
            applyColorCorrection();
          });
        }
      });
    } else if (tool === 'colorSwitch') {
      panel.innerHTML = `
        <div class="image-editor-panel">
          <span style="color: var(--muted); font-size: 12px;">Click on the image to select a color, then choose a replacement color</span>
          <div style="display:flex; gap:8px; align-items:center;">
            <label style="color:var(--muted); font-size:12px;">Selected:</label>
            <div id="ie-selected-color" style="width:24px; height:24px; border:1px solid #444; border-radius:4px; background:#333;"></div>
            <label style="color:var(--muted); font-size:12px;">Replace with:</label>
            <input type="color" id="ie-target-color" value="#ffffff" style="width:32px; height:24px; border:none; cursor:pointer;">
            <label style="color:var(--muted); font-size:12px;">or</label>
            <button class="btn" style="font-size:12px; padding:4px 8px;" onclick="makeColorTransparent()">Make Transparent</button>
          </div>
          <div class="image-editor-slider">
            <label>Tolerance</label>
            <input type="range" min="5" max="100" value="${state.colorSwitch.tolerance}" id="ie-tolerance">
            <span id="ie-tolerance-val">${state.colorSwitch.tolerance}</span>
          </div>
          <button class="btn" onclick="applyColorSwitch()">Apply</button>
        </div>
      `;
      disableCropMode();
      enableColorPick();
      const tolEl = document.getElementById('ie-tolerance');
      if (tolEl) {
        tolEl.addEventListener('input', () => {
          state.colorSwitch.tolerance = parseInt(tolEl.value);
          const label = document.getElementById('ie-tolerance-val');
          if (label) label.textContent = `${tolEl.value}`;
        });
      }
    } else {
      panel.innerHTML = '';
      disableCropMode();
    }
  }

  // ---- CROP ----

  function enableCropMode() {
    const canvas = state.canvas;
    if (!canvas) return;
    canvas.style.cursor = 'crosshair';
    canvas._cropMouseDown = (e) => cropMouseDown(e);
    canvas._cropMouseMove = (e) => cropMouseMove(e);
    canvas._cropMouseUp = (e) => cropMouseUp(e);
    canvas.addEventListener('mousedown', canvas._cropMouseDown);
    canvas.addEventListener('mousemove', canvas._cropMouseMove);
    canvas.addEventListener('mouseup', canvas._cropMouseUp);
  }

  function disableCropMode() {
    const canvas = state.canvas;
    if (!canvas) return;
    canvas.style.cursor = 'default';
    if (canvas._cropMouseDown) {
      canvas.removeEventListener('mousedown', canvas._cropMouseDown);
      canvas.removeEventListener('mousemove', canvas._cropMouseMove);
      canvas.removeEventListener('mouseup', canvas._cropMouseUp);
    }
  }

  function getCanvasCoords(e) {
    const rect = state.canvas.getBoundingClientRect();
    const scaleX = state.canvas.width / rect.width;
    const scaleY = state.canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }

  function cropMouseDown(e) {
    const pos = getCanvasCoords(e);
    state.crop.x = pos.x;
    state.crop.y = pos.y;
    state.crop.w = 0;
    state.crop.h = 0;
    state.crop.dragging = true;
  }

  function cropMouseMove(e) {
    if (!state.crop.dragging) return;
    const pos = getCanvasCoords(e);
    state.crop.w = pos.x - state.crop.x;
    state.crop.h = pos.y - state.crop.y;
    drawCropOverlay();
  }

  function cropMouseUp() {
    state.crop.dragging = false;
    // Normalize negative dimensions
    if (state.crop.w < 0) {
      state.crop.x += state.crop.w;
      state.crop.w = Math.abs(state.crop.w);
    }
    if (state.crop.h < 0) {
      state.crop.y += state.crop.h;
      state.crop.h = Math.abs(state.crop.h);
    }
  }

  function drawCropOverlay() {
    applyColorCorrection(); // Redraw base image
    const { ctx, crop } = state;
    // Dim outside crop
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    // Top
    ctx.fillRect(0, 0, state.canvas.width, crop.y);
    // Bottom
    ctx.fillRect(0, crop.y + crop.h, state.canvas.width, state.canvas.height - (crop.y + crop.h));
    // Left
    ctx.fillRect(0, crop.y, crop.x, crop.h);
    // Right
    ctx.fillRect(crop.x + crop.w, crop.y, state.canvas.width - (crop.x + crop.w), crop.h);
    // Border
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(crop.x, crop.y, crop.w, crop.h);
    ctx.setLineDash([]);
  }

  window.applyCrop = function () {
    const { crop, canvas, ctx, originalImage } = state;
    if (crop.w < 10 || crop.h < 10) return;
    // Extract cropped area
    const imageData = ctx.getImageData(crop.x, crop.y, crop.w, crop.h);
    canvas.width = crop.w;
    canvas.height = crop.h;
    ctx.putImageData(imageData, 0, 0);
    // Update original to cropped result for further edits
    const croppedImg = new Image();
    croppedImg.src = canvas.toDataURL();
    croppedImg.onload = () => {
      state.originalImage = croppedImg;
      state.crop = { x: 0, y: 0, w: canvas.width, h: canvas.height, dragging: false };
    };
  };

  window.resetCrop = function () {
    // Not resettable if already applied — would need undo stack
    state.crop = { x: 0, y: 0, w: state.canvas.width, h: state.canvas.height, dragging: false };
    applyColorCorrection();
  };

  // ---- COLOR CORRECTION ----

  function applyColorCorrection() {
    const { canvas, ctx, originalImage: img, color } = state;
    if (!img || !canvas) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    if (color.hue === 0 && color.brightness === 0 && color.whiteBalance === 0) return;

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;

    for (let i = 0; i < data.length; i += 4) {
      let r = data[i], g = data[i + 1], b = data[i + 2];

      // Brightness
      if (color.brightness !== 0) {
        const factor = color.brightness / 100;
        r = clamp(r + 255 * factor);
        g = clamp(g + 255 * factor);
        b = clamp(b + 255 * factor);
      }

      // White balance (shift blue-yellow axis)
      if (color.whiteBalance !== 0) {
        const wb = color.whiteBalance / 100;
        r = clamp(r + 40 * wb);
        g = clamp(g + 10 * wb);
        b = clamp(b - 40 * wb);
      }

      // Hue rotation
      if (color.hue !== 0) {
        const [h, s, l] = rgbToHsl(r, g, b);
        const [nr, ng, nb] = hslToRgb(((h + color.hue / 360) % 1 + 1) % 1, s, l);
        r = nr; g = ng; b = nb;
      }

      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
    }
    ctx.putImageData(imageData, 0, 0);
  }

  window.resetColor = function () {
    state.color = { hue: 0, brightness: 0, whiteBalance: 0 };
    ['hue', 'brightness', 'wb'].forEach((name) => {
      const el = document.getElementById(`ie-${name}`);
      if (el) el.value = 0;
      const label = document.getElementById(`ie-${name}-val`);
      if (label) label.textContent = name === 'hue' ? '0°' : '0';
    });
    applyColorCorrection();
  };

  // ---- COLOR SWITCH ----

  function enableColorPick() {
    const canvas = state.canvas;
    if (!canvas) return;
    canvas.style.cursor = 'crosshair';
    canvas._colorPickClick = (e) => {
      const pos = getCanvasCoords(e);
      const pixel = state.ctx.getImageData(pos.x, pos.y, 1, 1).data;
      const hex = `#${pixel[0].toString(16).padStart(2, '0')}${pixel[1].toString(16).padStart(2, '0')}${pixel[2].toString(16).padStart(2, '0')}`;
      state.colorSwitch.selectedColor = [pixel[0], pixel[1], pixel[2]];
      const swatch = document.getElementById('ie-selected-color');
      if (swatch) swatch.style.background = hex;
    };
    canvas.addEventListener('click', canvas._colorPickClick);
  }

  window.applyColorSwitch = function () {
    const { canvas, ctx, colorSwitch } = state;
    if (!colorSwitch.selectedColor) return;
    const targetHex = document.getElementById('ie-target-color')?.value || '#ffffff';
    const target = hexToRgb(targetHex);
    const tolerance = colorSwitch.tolerance;

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    const [sr, sg, sb] = colorSwitch.selectedColor;

    for (let i = 0; i < data.length; i += 4) {
      const dist = Math.sqrt(
        (data[i] - sr) ** 2 + (data[i + 1] - sg) ** 2 + (data[i + 2] - sb) ** 2
      );
      if (dist <= tolerance) {
        data[i] = target[0];
        data[i + 1] = target[1];
        data[i + 2] = target[2];
      }
    }
    ctx.putImageData(imageData, 0, 0);
    // Update original for further edits
    const newImg = new Image();
    newImg.src = canvas.toDataURL();
    newImg.onload = () => { state.originalImage = newImg; };
  };

  window.makeColorTransparent = function () {
    const { canvas, ctx, colorSwitch } = state;
    if (!colorSwitch.selectedColor) return;
    const tolerance = colorSwitch.tolerance;
    const [sr, sg, sb] = colorSwitch.selectedColor;

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;

    for (let i = 0; i < data.length; i += 4) {
      const dist = Math.sqrt(
        (data[i] - sr) ** 2 + (data[i + 1] - sg) ** 2 + (data[i + 2] - sb) ** 2
      );
      if (dist <= tolerance) {
        data[i + 3] = 0; // Make transparent
      }
    }
    ctx.putImageData(imageData, 0, 0);
    const newImg = new Image();
    newImg.src = canvas.toDataURL();
    newImg.onload = () => { state.originalImage = newImg; };
  };

  // ---- SAVE ----

  window.applyImageEdit = async function () {
    const { canvas, noteId, chapterId } = state;
    if (!canvas || !noteId) return;

    // Convert canvas to blob
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.85));
    if (!blob) return;

    const filename = `edited_${Date.now()}.webp`;
    const fd = new FormData();
    fd.append('file', blob, filename);

    try {
      // Upload edited image
      const uploadRes = await fetch(`/api/notes/${noteId}/media/upload`, {
        method: 'POST',
        body: fd,
      });
      if (!uploadRes.ok) throw new Error('Upload failed');

      const json = await uploadRes.json();
      const newFilename = json.filename || filename;

      // Select as current media
      if (chapterId) {
        const selectFd = new FormData();
        selectFd.append('url', `/api/notes/${noteId}/media/${newFilename}`);
        await fetch(`/notes/${noteId}/chapters/${chapterId}/media/select`, {
          method: 'POST',
          body: selectFd,
        });
      }

      closeImageEditor();

      // Refresh page
      if (window.htmx) {
        htmx.ajax('GET', `/notes/${noteId}`, { target: 'body', swap: 'none' });
      }
    } catch (err) {
      console.error('Save edited image error:', err);
      alert('Failed to save edited image: ' + err.message);
    }
  };

  // ---- HELPERS ----

  function clamp(val) {
    return Math.max(0, Math.min(255, Math.round(val)));
  }

  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;
    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
        case g: h = ((b - r) / d + 2) / 6; break;
        case b: h = ((r - g) / d + 4) / 6; break;
      }
    }
    return [h, s, l];
  }

  function hslToRgb(h, s, l) {
    let r, g, b;
    if (s === 0) {
      r = g = b = l;
    } else {
      const hue2rgb = (p, q, t) => {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
      };
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      const p = 2 * l - q;
      r = hue2rgb(p, q, h + 1 / 3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1 / 3);
    }
    return [clamp(r * 255), clamp(g * 255), clamp(b * 255)];
  }

  function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? [parseInt(result[1], 16), parseInt(result[2], 16), parseInt(result[3], 16)] : [255, 255, 255];
  }
})();

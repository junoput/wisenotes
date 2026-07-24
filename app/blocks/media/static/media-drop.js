/**
 * Drag-and-drop handler for media block drop zones.
 * Uploads dropped images then selects them as the block's current media.
 */

function initMediaDropZones() {
  document.querySelectorAll('.media-drop-zone').forEach((zone) => {
    // Avoid double-init
    if (zone.dataset.dropInit) return;
    zone.dataset.dropInit = '1';

    const noteId = zone.dataset.noteId;
    const chapterId = zone.dataset.chapterId;
    if (!noteId || !chapterId) return;

    zone.addEventListener('dragenter', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
    });

    zone.addEventListener('drop', async (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');

      const files = e.dataTransfer?.files;
      if (!files || files.length === 0) return;

      const uploadUrl = `/api/notes/${noteId}/media/upload`;
      const selectUrl = `/notes/${noteId}/chapters/${chapterId}/media/select`;

      let lastProcessedFilename = null;

      // Upload each file and track the server-provided filename
      for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        const fd = new FormData();
        fd.append('file', file);
        try {
          const res = await fetch(uploadUrl, { method: 'POST', body: fd });
          if (res.ok) {
            const json = await res.json();
            // Use the server's returned filename (processed/renamed)
            lastProcessedFilename = json.filename || file.name;
          }
        } catch (err) {
          console.error('Drop upload error:', err);
        }
      }

      // Auto-select the last uploaded image as current media
      if (lastProcessedFilename) {
        const mediaUrl = `/api/notes/${noteId}/media/${lastProcessedFilename}`;
        const fd = new FormData();
        fd.append('url', mediaUrl);
        try {
          await fetch(selectUrl, { method: 'POST', body: fd });
        } catch (err) {
          console.error('Drop select error:', err);
        }
        // Refresh the whole page to show the updated block
        if (window.htmx) {
          htmx.ajax('GET', `/notes/${noteId}`, { target: 'body', swap: 'none' });
        }
      }
    });
  });
}

// Initialize on page load and after HTMX swaps
document.addEventListener('DOMContentLoaded', initMediaDropZones);
document.addEventListener('htmx:afterSwap', initMediaDropZones);

// Expose for manual calls
window.initMediaDropZones = initMediaDropZones;

/**
 * Initialize media file picker upload handler
 */
export function initMediaPicker(chapterId, noteId) {
  const fileInput = document.getElementById(`file-input-${chapterId}`);
  const importBtn = document.getElementById(`import-btn-${chapterId}`);
  
  if (!fileInput) {
    console.warn(`File input not found: file-input-${chapterId}`);
    return;
  }

  // Attach click handler to Import button
  if (importBtn) {
    importBtn.addEventListener('click', (e) => {
      e.preventDefault();
      fileInput.click();
    });
  }

  // Handle file selection
  fileInput.addEventListener('change', async (e) => {
    const files = e.target.files;
    if (files.length === 0) return;

    const uploadUrl = `/api/notes/${noteId}/media/upload`;
    const pickerUrl = `/notes/${noteId}/chapters/${chapterId}/media/picker`;
    const selectUrl = `/notes/${noteId}/chapters/${chapterId}/media/select`;

    console.log(`Uploading ${files.length} files...`);

    let lastUploadedFilename = null;

    // Upload each file
    for (let file of files) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const response = await fetch(uploadUrl, {
          method: 'POST',
          body: fd
        });
        if (response.ok) {
          try {
            const json = await response.json();
            if (json.filename) lastUploadedFilename = json.filename;
          } catch {
            // Ignore parse errors
          }
        }
        console.log(`Uploaded ${file.name}:`, response.status);
      } catch (err) {
        console.error('Error uploading file:', err);
      }
    }

    // Refresh gallery
    try {
      const response = await fetch(pickerUrl);
      const html = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const newGallery = doc.getElementById(`media-gallery-${chapterId}`);
      if (newGallery) {
        document.getElementById(`media-gallery-${chapterId}`).innerHTML = newGallery.innerHTML;
        // Re-initialize picker for new gallery
        initMediaPicker(chapterId, noteId);
        // Re-initialize drop zones
        if (window.initMediaDropZones) window.initMediaDropZones();
      }
    } catch (err) {
      console.error('Error refreshing gallery:', err);
    }

    // Auto-select single uploaded file as current media
    if (files.length === 1 && lastUploadedFilename) {
      const mediaUrl = `/api/notes/${noteId}/media/${lastUploadedFilename}`;
      const fd = new FormData();
      fd.append('url', mediaUrl);
      try {
        await fetch(selectUrl, { method: 'POST', body: fd });
        // Refresh to show updated preview
        if (window.htmx) {
          htmx.ajax('GET', `/notes/${noteId}`, { target: 'body', swap: 'none' });
        }
      } catch (err) {
        console.error('Error auto-selecting media:', err);
      }
    }

    // Reset input
    e.target.value = '';
  });
}

// Auto-initialize on page load and HTMX swaps
document.addEventListener('DOMContentLoaded', initMediaPickersOnPage);
document.addEventListener('htmx:afterSwap', initMediaPickersOnPage);

export function initMediaPickersOnPage() {
  // Find all media picker containers and initialize them
  const containers = document.querySelectorAll('[data-media-chapter-id]');
  containers.forEach(container => {
    const chapterId = container.getAttribute('data-media-chapter-id');
    const noteId = container.getAttribute('data-media-note-id');
    if (chapterId && noteId) {
      initMediaPicker(chapterId, noteId);
    }
  });
}

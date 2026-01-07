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

    const uploadUrl = `/notes/${noteId}/media/upload`;
    const pickerUrl = `/notes/${noteId}/chapters/${chapterId}/media/picker`;

    console.log(`Uploading ${files.length} files...`);

    // Upload each file
    for (let file of files) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const response = await fetch(uploadUrl, {
          method: 'POST',
          body: fd
        });
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
      }
    } catch (err) {
      console.error('Error refreshing gallery:', err);
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

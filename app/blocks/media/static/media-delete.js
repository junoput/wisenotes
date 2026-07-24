// Global helper for deleting media items; used by media_gallery.html buttons.
export async function deleteMedia(event, noteId, filename, chapterId) {
  event.stopPropagation();

  const confirmed = window.confirm(`Delete "${filename}"?\n\nThis action cannot be undone.`);
  if (!confirmed) return;

  try {
    const res = await fetch(`/api/notes/${noteId}/media/${filename}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      throw new Error(`Failed to delete: ${res.status} ${res.statusText}`);
    }
    // Refresh the gallery via HTMX
    const target = `#media-gallery-${chapterId}`;
    if (window.htmx) {
      window.htmx.ajax("GET", `/notes/${noteId}/chapters/${chapterId}/media/picker`, {
        target,
        swap: "innerHTML",
      });
    }
  } catch (err) {
    console.error("Delete media error:", err);
    window.alert(`Error deleting media: ${err.message}`);
  }
}

// Attach to window for inline onclick usage
window.deleteMedia = deleteMedia;

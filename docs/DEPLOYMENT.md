# Wisenotes Deployment & Setup Guide

## Quick Start

### Development

```bash
# Prerequisites: Python 3.12+
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Option 1: Native (with auto-reload)
uvicorn app.main:app --reload --port 8000

# Option 2: Docker (with hot-reload via override)
docker compose up
```

The `docker-compose.override.yml` automatically applies in dev, providing:
- Hot reload on code changes (`--reload` flag)
- Full source mounting at `/app` for debugging
- Explicit static file mount to avoid macOS filesystem sync issues

### Production

```bash
# Build and run (data persisted via Docker volume)
docker compose build
docker compose up -d

# View logs
docker compose logs -f wisenotes

# Stop
docker compose down
```

## Data Storage Strategy

### Current: JSON File-Based (Recommended for <10k notes)

**Location:** Docker volume `wisenotes_data:/data`

**File Structure:**
```
data/
├── <note-name>/
│   ├── <note-name>.json    # Note metadata + chapters
│   ├── media/              # Images, files
│   └── <note-name>.lock    # FileLock for concurrent access
└── ...
```

**Pros:**
- Zero database setup
- Atomic writes (`.tmp` → `replace()`)
- FileLock prevents concurrent corruption
- Easy backups (copy `/data` directory)
- Works offline

**Cons:**
- Not suitable for >10k concurrent notes
- No transactions across multiple notes
- Search requires scanning all files
- Full-text search inefficient

**Backup Strategy:**
```bash
# Automated daily backup
docker compose exec wisenotes tar -czf /tmp/notes-backup-$(date +%Y%m%d).tar.gz /data
docker cp wisenotes-wisenotes-1:/tmp/notes-backup-*.tar.gz ./backups/
```

### Future: Migrate to Database (PostgreSQL)

When you need:
- Multi-note transactions
- Full-text search
- Concurrent user access
- Analytics/aggregation

Create `app/services/db.py` with SQLAlchemy models:
```python
# Example migration path
# - Keep NoteService interface unchanged
# - Swap JsonNoteRepository with PostgresNoteRepository
# - Data migrates via ETL script
```

## Production Checklist

### Environment

Set these before `docker compose up`:

```bash
# app/config.py reads these
export WISENOTES_DATA_DIR=/data              # Where notes are stored
export WISENOTES_ENABLE_SAMPLE_PLUGINS=false # Disable demo plugins
export LOG_LEVEL=info                        # or: debug, warning, error
```

### Networking

**HTTP Server:**
- Port: `8000` (configurable)
- Recommended: Behind reverse proxy (nginx, caddy)
  ```nginx
  location / {
    proxy_pass http://wisenotes:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
  ```

**HTTPS:**
- Use reverse proxy with Let's Encrypt (caddy handles auto)
- CSP headers already set in `app/main.py`

### Persistence

**Data Volume:**
- `wisenotes_data` docker volume survives container restarts
- For cloud: Use cloud provider's volume service
  - AWS EBS
  - Azure Managed Disks
  - DigitalOcean Volumes

**Backup Locations:**
- Weekly: `gs://bucket/backups/notes-$(date +%Y%m%d).tar.gz` (GCS)
- Or: `s3://bucket/backups/` (S3)

### Health Checks

Container runs `curl http://localhost:8000/health` every 30s. If fails 3x, container marked unhealthy.

Orchestrators (Docker Swarm, Kubernetes) can auto-restart based on this.

### Performance

**Current limits:**
- Single container: ~100 concurrent requests
- File I/O bottleneck at ~1000 notes

**If you hit limits:**

1. **Horizontal scaling (multiple containers):** Requires shared NFS for `/data`
   ```yaml
   # docker-compose.yml
   services:
     nfs-server:
       image: erichough/nfs-server
       volumes:
         - wisenotes_data:/export/data
   
     wisenotes-1:
       volumes:
         - nfs-server:/data  # Shared
   ```

2. **Database:** Simplest. Switch to PostgreSQL, scale horizontally.

3. **Caching:** Add Redis for frequently-accessed notes
   ```python
   # app/services/notes.py
   cache = Redis(host='redis', port=6379)
   ```

## Troubleshooting

### CSS/Static files not loading

**Cause:** Filesystem sync issues on macOS Docker Desktop

**Solution:** Already fixed in `docker-compose.override.yml` with explicit mount
```yaml
volumes:
  - ./app/static:/app/static:ro
```

### Data persists but Docker volume lost

**Location of data:**
```bash
# Find where Docker stores volumes
docker volume inspect wisenotes_data

# Manual backup
docker run --rm -v wisenotes_data:/data -v $(pwd)/backups:/backups \
  alpine tar -czf /backups/notes-$(date +%s).tar.gz -C /data .
```

### High disk usage

Monitor JSON file sizes:
```bash
docker exec wisenotes find /data -name "*.json" -exec wc -c {} + | sort -rn | head
```

If single notes grow >100MB, consider splitting chapters into separate files.

## Migration Path (JSON → PostgreSQL)

1. Keep `NoteService` API unchanged
2. Create `PostgresNoteRepository` implementing same interface
3. ETL script: `scripts/migrate_to_db.py`
4. Switch repository in `dependencies.py`
5. Test thoroughly, keep JSON as backup

This maintains zero downtime.

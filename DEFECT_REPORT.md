# Defect Report - Odiseo Email Service

**Date:** 2025-12-02
**Auditor:** Claude Code
**Version:** 2.0.0

---

## Summary

| Severity | Count |
|----------|-------|
| **Critical** | 1 |
| **High** | 3 |
| **Medium** | 5 |
| **Low** | 4 |

---

## Critical Defects

### D001: Memory Leak in Rate Limiter
**File:** `api/main.py:89`
**Severity:** Critical

**Description:**
The `RateLimiter._requests` dictionary stores client IDs as keys but never removes them. While `_clean_old_requests` removes old timestamps, the dictionary keys persist indefinitely. With many unique clients, memory grows unbounded.

**Code:**
```python
_requests: dict = field(default_factory=lambda: defaultdict(list))

def _clean_old_requests(self, client_id: str, window_seconds: int) -> None:
    # Only cleans timestamps, not the client_id key itself
    self._requests[client_id] = [
        t for t in self._requests[client_id] if now - t < window_seconds
    ]
```

**Impact:**
- Memory consumption grows over time
- In high-traffic scenarios, can lead to OOM (Out of Memory)
- No automatic cleanup of inactive clients

**Recommendation:**
```python
def _clean_old_requests(self, client_id: str, window_seconds: int) -> None:
    now = time.time()
    self._requests[client_id] = [
        t for t in self._requests[client_id] if now - t < window_seconds
    ]
    # Remove empty client entries
    if not self._requests[client_id]:
        del self._requests[client_id]
```

---

## High Severity Defects

### D002: Race Condition in Rate Limiter
**File:** `api/main.py:98-116`
**Severity:** High

**Description:**
The `is_allowed` method is not thread-safe. Multiple concurrent requests from the same client can pass the limit check before any of them records the request, allowing more requests than configured.

**Code:**
```python
def is_allowed(self, client_id: str) -> bool:
    # Check limit
    if len(self._requests[client_id]) >= self.requests_per_minute:
        return False
    # Time gap between check and record - race condition window
    self._requests[client_id].append(now)  # Another thread could have appended here
    return True
```

**Impact:**
- Rate limits can be bypassed under concurrent load
- API protection is weakened

**Recommendation:**
Add threading lock or use FastAPI middleware with async-safe rate limiting:
```python
from threading import Lock

@dataclass
class RateLimiter:
    _lock: Lock = field(default_factory=Lock)

    def is_allowed(self, client_id: str) -> bool:
        with self._lock:
            # ... existing logic
```

---

### D003: Missing SMTP Client Cleanup on Shutdown
**File:** `worker/processor.py:121-122`
**Severity:** High

**Description:**
On worker shutdown, `queue_manager.close()` is called but `smtp_client.close()` is never called, leaving SMTP connections open.

**Code:**
```python
logger.info("Shutting down email worker...")
self._print_stats()
self.queue_manager.close()  # Database closed
# smtp_client.close() is missing!
logger.info("Email worker stopped cleanly")
```

**Impact:**
- SMTP connections remain open until server timeout
- Resource leak on graceful shutdown
- May hit SMTP connection limits

**Recommendation:**
```python
logger.info("Shutting down email worker...")
self._print_stats()
self.smtp_client.close()  # Add this line
self.queue_manager.close()
```

---

### D004: Inconsistent Error Handling in get_email_by_id
**File:** `database/queue.py:483-495`
**Severity:** High

**Description:**
1. Missing `conn.rollback()` before retry on OperationalError
2. Returns `None` after all retries instead of raising exception like other methods

**Code:**
```python
except psycopg2.OperationalError as e:
    # Missing: conn.rollback()
    if attempt < max_retries - 1:
        continue
    raise EmailQueueError(...)

# After retry loop - returns None instead of raising
return None
```

**Impact:**
- Connection state may be corrupted after failed operation
- Silent failure vs explicit exception - inconsistent API behavior
- Caller may not know if email doesn't exist vs database error

**Recommendation:**
```python
except psycopg2.OperationalError as e:
    conn.rollback()  # Add rollback
    if attempt < max_retries - 1:
        continue
    raise EmailQueueError(f"Failed to retrieve email: {e}") from e

# After loop - should raise, not return None
raise EmailQueueError("Failed to get email after all retries")
```

---

## Medium Severity Defects

### D005: Redundant Status Update to PROCESSING
**File:** `worker/processor.py:180`
**Severity:** Medium

**Description:**
The `get_pending_emails()` SQL function already sets status to 'processing' (via FOR UPDATE), but the code also calls `update_email_status(email.id, EmailStatus.PROCESSING)`. This is redundant and wastes a database round-trip.

**Code:**
```python
# get_pending_emails already sets status to 'processing' via SQL function
pending_emails = self.queue_manager.get_pending_emails(...)

# Then we call this again - redundant!
self.queue_manager.update_email_status(email.id, EmailStatus.PROCESSING)
```

**Impact:**
- Unnecessary database query per email
- Increased database load
- Slightly slower processing

**Recommendation:**
Remove the redundant `update_email_status` call or document why it's needed.

---

### D006: Double EmailConfig Instantiation
**File:** `api/main.py:202, 232`
**Severity:** Medium

**Description:**
`EmailConfig()` is instantiated twice - once in `lifespan()` and once in `create_app()`. While functionally harmless, it's wasteful.

**Code:**
```python
def create_app() -> FastAPI:
    config = EmailConfig()  # First instantiation
    application = FastAPI(title=config.SERVICE_NAME, ...)
    return application

async def lifespan(app: FastAPI):
    config = EmailConfig()  # Second instantiation
    app_state = AppState(config=config)
```

**Impact:**
- Redundant environment variable parsing
- Potential for inconsistent config if env vars change between calls (unlikely)

**Recommendation:**
Pass config from `create_app` to `lifespan` or use a singleton pattern.

---

### D007: Missing Pool Size Validation
**File:** `config/settings.py:190-200`
**Severity:** Medium

**Description:**
No validation that `DB_POOL_SIZE_MIN <= DB_POOL_SIZE_MAX`. If misconfigured (MIN > MAX), the connection pool will fail with a cryptic psycopg2 error.

**Impact:**
- Confusing error message on misconfiguration
- Service fails to start with unclear reason

**Recommendation:**
Add validator:
```python
@model_validator(mode='after')
def validate_pool_sizes(self) -> 'EmailConfig':
    if self.DB_POOL_SIZE_MIN > self.DB_POOL_SIZE_MAX:
        raise ValueError(
            f"DB_POOL_SIZE_MIN ({self.DB_POOL_SIZE_MIN}) cannot be greater "
            f"than DB_POOL_SIZE_MAX ({self.DB_POOL_SIZE_MAX})"
        )
    return self
```

---

### D008: OTP Template Missing in Fallback Generator
**File:** `templates/renderer.py:145-210`
**Severity:** Medium

**Description:**
The `_generate_fallback_text` method doesn't have a specific case for `EmailType.OTP_VERIFICATION`. It falls through to the generic fallback which doesn't include the OTP code.

**Code:**
```python
def _generate_fallback_text(self, email_type: EmailType, context: dict) -> str:
    # Cases for: BOOKING_CREATED, BOOKING_CANCELLED, BOOKING_RESCHEDULED, REMINDER_*
    # Missing: OTP_VERIFICATION
    else:
        return f"Hola {customer_name}, Gracias por tu confianza."
```

**Impact:**
- OTP emails without .txt template will have no OTP code in plain text
- Users with plain-text email clients won't see their OTP

**Recommendation:**
Add OTP case:
```python
elif email_type == EmailType.OTP_VERIFICATION:
    otp_code = context.get("otp_code", "N/A")
    return f"""
Hola {customer_name},

Tu código de verificación es: {otp_code}

Este código expira en {context.get('expiry_minutes', 10)} minutos.
    """.strip()
```

---

### D009: Autoescape Applied to Plain Text Templates
**File:** `templates/renderer.py:60`
**Severity:** Medium

**Description:**
`autoescape=True` is set globally on the Jinja2 environment. This applies HTML escaping to `.txt` templates as well, which could escape characters like `&` to `&amp;`.

**Code:**
```python
env = Environment(
    loader=FileSystemLoader(self.template_dir),
    autoescape=True,  # Applied to ALL templates including .txt
)
```

**Impact:**
- Plain text emails might have HTML entities (`&amp;`, `&lt;`, etc.)
- Confusing content for users reading plain text emails

**Recommendation:**
Use selective autoescape:
```python
from jinja2 import select_autoescape

env = Environment(
    loader=FileSystemLoader(self.template_dir),
    autoescape=select_autoescape(['html', 'htm', 'xml']),
)
```

---

## Low Severity Defects

### D010: Unreachable Code After Retry Loop
**File:** `database/queue.py:278, 346`
**Severity:** Low

**Description:**
After for loops that always either return or raise, there's a raise statement that can never be reached in practice.

**Code:**
```python
for attempt in range(max_retries):
    try:
        # ... always returns on success
        return email_id
    except:
        if attempt < max_retries - 1:
            continue
        raise  # Always raises on last attempt

# This line is never reached
raise EmailQueueError("Failed to enqueue email after all retries")
```

**Impact:**
- Dead code clutters the codebase
- Indicates potential logic confusion

**Recommendation:**
Remove unreachable code or restructure logic.

---

### D011: Missing commit in get_queue_stats
**File:** `database/queue.py:568`
**Severity:** Low

**Description:**
The `get_queue_stats` method doesn't call `conn.commit()` before returning, unlike other read methods.

**Code:**
```python
cur.execute("SELECT status, COUNT(*) ...")
rows = cur.fetchall()
return {row["status"]: row["count"] for row in rows}
# Missing: conn.commit()
```

**Impact:**
- Inconsistent with other methods
- While psycopg2 handles this, explicit commit is cleaner

---

### D012: Potential AttributeError on request.client
**File:** `api/main.py:125`
**Severity:** Low

**Description:**
Code handles `request.client` being None, but doesn't handle case where `request.client` exists but has no `host` attribute.

**Code:**
```python
client_ip = request.client.host if request.client else "unknown"
# If request.client exists but has no 'host' attribute, AttributeError
```

**Impact:**
- Very unlikely in practice with FastAPI
- Could cause 500 error in edge case

**Recommendation:**
```python
client_ip = getattr(request.client, 'host', 'unknown') if request.client else "unknown"
```

---

### D013: Inaccurate Failed Count in Worker
**File:** `worker/processor.py:149-153`
**Severity:** Low

**Description:**
`failed_count` increments for any exception, but `_handle_send_failure` may schedule a retry (not a permanent failure). The counter conflates "retryable failures" with "permanent failures".

**Code:**
```python
for result in results:
    if isinstance(result, Exception):
        self.failed_count += 1  # Counts all failures, not just permanent
```

**Impact:**
- Misleading statistics on shutdown
- "Failed" count includes emails that were scheduled for retry

**Recommendation:**
Track retry count separately from permanent failure count.

---

## Recommendations Summary

| Priority | Defect | Action |
|----------|--------|--------|
| **Immediate** | D001 | Fix memory leak in rate limiter |
| **Immediate** | D002 | Add thread-safe rate limiting |
| **High** | D003 | Add SMTP cleanup on shutdown |
| **High** | D004 | Fix get_email_by_id error handling |
| **Medium** | D005-D009 | Fix in next release |
| **Low** | D010-D013 | Fix when convenient |

---

*Report generated by Claude Code - 2025-12-02*

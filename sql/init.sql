-- =============================================================================
-- Email Queue Database Schema
-- Based on REQ-1.md specification
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS test;

-- =============================================================================
-- Email Queue Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS test.email_queue (
    id BIGSERIAL PRIMARY KEY,
    client_message_id TEXT,

    -- Recipients
    to_addresses TEXT[] NOT NULL,
    cc_addresses TEXT[],
    bcc_addresses TEXT[],

    -- Content
    subject TEXT,
    body TEXT,
    template_id TEXT,
    template_vars JSONB,
    metadata JSONB,

    -- Legacy fields (for compatibility with worker)
    email_type TEXT NOT NULL DEFAULT 'transactional',
    recipient_email TEXT,
    recipient_name TEXT,
    body_html TEXT,
    body_text TEXT,
    booking_id BIGINT,
    template_context JSONB,
    priority INT NOT NULL DEFAULT 5,

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ DEFAULT now(),
    sent_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,

    -- Error tracking
    last_error TEXT,
    provider_response JSONB
);

-- =============================================================================
-- Indexes for Performance
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_email_queue_status ON test.email_queue (status);
CREATE INDEX IF NOT EXISTS idx_email_queue_next_attempt ON test.email_queue (next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_email_queue_scheduled_for ON test.email_queue (scheduled_for);
CREATE INDEX IF NOT EXISTS idx_email_queue_priority ON test.email_queue (priority);

-- =============================================================================
-- Function: enqueue_email
-- =============================================================================
CREATE OR REPLACE FUNCTION test.enqueue_email(
    p_email_type TEXT,
    p_recipient_email TEXT,
    p_recipient_name TEXT,
    p_subject TEXT,
    p_body_html TEXT,
    p_body_text TEXT,
    p_booking_id BIGINT,
    p_template_context TEXT,
    p_scheduled_for TIMESTAMPTZ,
    p_priority INT
) RETURNS BIGINT AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO test.email_queue (
        email_type,
        recipient_email,
        recipient_name,
        subject,
        body_html,
        body_text,
        booking_id,
        template_context,
        scheduled_for,
        priority,
        to_addresses,
        status
    ) VALUES (
        p_email_type,
        p_recipient_email,
        p_recipient_name,
        p_subject,
        p_body_html,
        p_body_text,
        p_booking_id,
        p_template_context::JSONB,
        p_scheduled_for,
        p_priority,
        ARRAY[p_recipient_email],
        'pending'
    ) RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Function: get_pending_emails (with FOR UPDATE SKIP LOCKED)
-- =============================================================================
CREATE OR REPLACE FUNCTION test.get_pending_emails(p_limit INT)
RETURNS SETOF test.email_queue AS $$
BEGIN
    RETURN QUERY
    UPDATE test.email_queue
    SET status = 'processing',
        updated_at = now()
    WHERE id IN (
        SELECT id FROM test.email_queue
        WHERE status IN ('pending', 'scheduled')
        AND (scheduled_for IS NULL OR scheduled_for <= now())
        ORDER BY priority ASC, created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Function: update_email_status
-- =============================================================================
CREATE OR REPLACE FUNCTION test.update_email_status(
    p_email_id BIGINT,
    p_status TEXT,
    p_error TEXT DEFAULT NULL,
    p_sent_at TIMESTAMPTZ DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE test.email_queue
    SET status = p_status,
        last_error = COALESCE(p_error, last_error),
        sent_at = COALESCE(p_sent_at, sent_at),
        updated_at = now()
    WHERE id = p_email_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Function: retry_email (with exponential backoff)
-- =============================================================================
CREATE OR REPLACE FUNCTION test.retry_email(
    p_email_id BIGINT,
    p_error TEXT,
    p_backoff_seconds INT
) RETURNS VOID AS $$
DECLARE
    v_retry_count INT;
    v_max_retries INT;
    v_backoff INTERVAL;
BEGIN
    SELECT retry_count, max_retries INTO v_retry_count, v_max_retries
    FROM test.email_queue WHERE id = p_email_id;

    -- Calculate exponential backoff with jitter
    v_backoff := (p_backoff_seconds * power(2, v_retry_count))::TEXT || ' seconds';

    IF v_retry_count < v_max_retries THEN
        UPDATE test.email_queue
        SET status = 'scheduled',
            retry_count = retry_count + 1,
            attempts = attempts + 1,
            last_error = p_error,
            last_attempt_at = now(),
            next_retry_at = now() + v_backoff,
            next_attempt_at = now() + v_backoff,
            updated_at = now()
        WHERE id = p_email_id;
    ELSE
        UPDATE test.email_queue
        SET status = 'failed',
            last_error = p_error,
            last_attempt_at = now(),
            updated_at = now()
        WHERE id = p_email_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Function: cleanup_old_emails
-- =============================================================================
CREATE OR REPLACE FUNCTION test.cleanup_old_emails(p_days_to_keep INT)
RETURNS INT AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM test.email_queue
    WHERE status IN ('sent', 'failed')
    AND created_at < now() - (p_days_to_keep || ' days')::INTERVAL;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Trigger: auto-update updated_at
-- =============================================================================
CREATE OR REPLACE FUNCTION test.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_email_queue_updated_at ON test.email_queue;
CREATE TRIGGER trigger_email_queue_updated_at
    BEFORE UPDATE ON test.email_queue
    FOR EACH ROW
    EXECUTE FUNCTION test.update_updated_at();

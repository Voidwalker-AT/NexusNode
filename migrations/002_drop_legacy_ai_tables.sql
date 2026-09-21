-- NexusNode Database Migration: 002_drop_legacy_ai_tables.sql
-- Phase 4.2C: Evidence-Gated Legacy Retirement
-- Drops genuinely obsolete, zero-row local AI inference and chat tables.
-- Verified preconditions:
--   - ai_inference_metrics: 0 rows (Ollama local inference telemetry retired)
--   - user_chats: 0 rows (local chatbot session store retired)
-- Note: consequential_audit_log is explicitly RETAINED as active security audit infrastructure.

DROP TABLE IF EXISTS ai_inference_metrics;
DROP TABLE IF EXISTS user_chats;

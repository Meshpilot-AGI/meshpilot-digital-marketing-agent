-- Baseline schema (source: glitch_signal.db.models), idempotent so it is a
-- safe no-op on the existing prod DB and builds fresh preview/shadow DBs.
-- Alembic->Supabase migration cutover (DB-OPT). New changes = new migration files.

CREATE TABLE IF NOT EXISTS comment_reply (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	published_post_id VARCHAR, 
	platform_post_id VARCHAR NOT NULL, 
	platform_comment_id VARCHAR NOT NULL, 
	commenter_handle VARCHAR, 
	commenter_name VARCHAR, 
	comment_text VARCHAR NOT NULL, 
	comment_created_at TIMESTAMP WITHOUT TIME ZONE, 
	triage_tier VARCHAR, 
	status VARCHAR NOT NULL, 
	drafted_reply VARCHAR, 
	posted_reply_id VARCHAR, 
	discord_message_id VARCHAR, 
	discord_channel_id VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (platform_comment_id)
);

CREATE INDEX IF NOT EXISTS ix_comment_reply_status ON comment_reply (status);
CREATE INDEX IF NOT EXISTS ix_comment_reply_brand_id ON comment_reply (brand_id);
CREATE INDEX IF NOT EXISTS ix_comment_reply_platform_post_id ON comment_reply (platform_post_id);
ALTER TABLE "comment_reply" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS mention_event (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	mention_id VARCHAR NOT NULL, 
	body VARCHAR NOT NULL, 
	from_handle VARCHAR NOT NULL, 
	author_id VARCHAR, 
	in_reply_to_id VARCHAR, 
	tier VARCHAR, 
	sentiment VARCHAR, 
	confidence FLOAT, 
	guardrail_hit BOOLEAN NOT NULL, 
	received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_mention_event_mention_id ON mention_event (mention_id);
CREATE INDEX IF NOT EXISTS ix_mention_event_brand_id ON mention_event (brand_id);
ALTER TABLE "mention_event" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS platform_auth (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	account_identifier VARCHAR, 
	access_token_enc VARCHAR NOT NULL, 
	refresh_token_enc VARCHAR, 
	access_token_expires_at TIMESTAMP WITHOUT TIME ZONE, 
	scopes VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	raw_provider_response VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_platform_auth_account_identifier ON platform_auth (account_identifier);
CREATE INDEX IF NOT EXISTS ix_platform_auth_platform ON platform_auth (platform);
CREATE INDEX IF NOT EXISTS ix_platform_auth_brand_id ON platform_auth (brand_id);
ALTER TABLE "platform_auth" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS scout_checkpoint (
	source_key VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	last_checked_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_ref VARCHAR, 
	PRIMARY KEY (source_key)
);

CREATE INDEX IF NOT EXISTS ix_scout_checkpoint_brand_id ON scout_checkpoint (brand_id);
ALTER TABLE "scout_checkpoint" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS signal (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	source_ref VARCHAR NOT NULL, 
	summary VARCHAR NOT NULL, 
	novelty_score FLOAT NOT NULL, 
	status VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_signal_brand_id ON signal (brand_id);
ALTER TABLE "signal" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS strategic_reply (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	target_platform VARCHAR NOT NULL, 
	target_post_url VARCHAR NOT NULL, 
	target_post_id VARCHAR, 
	target_author_handle VARCHAR, 
	target_post_text VARCHAR, 
	drafted_reply VARCHAR, 
	status VARCHAR NOT NULL, 
	requested_by_telegram_id VARCHAR, 
	posted_platform_post_id VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_strategic_reply_brand_id ON strategic_reply (brand_id);
CREATE INDEX IF NOT EXISTS ix_strategic_reply_status ON strategic_reply (status);
ALTER TABLE "strategic_reply" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS content_script (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	signal_id VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	script_body VARCHAR NOT NULL, 
	content_type VARCHAR NOT NULL, 
	key_visuals VARCHAR NOT NULL, 
	shots VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(signal_id) REFERENCES signal (id)
);

CREATE INDEX IF NOT EXISTS ix_content_script_signal_id ON content_script (signal_id);
CREATE INDEX IF NOT EXISTS ix_content_script_brand_id ON content_script (brand_id);
ALTER TABLE "content_script" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS orm_response (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	mention_id VARCHAR NOT NULL, 
	draft_body VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	auto_send_at TIMESTAMP WITHOUT TIME ZONE, 
	sent_at TIMESTAMP WITHOUT TIME ZONE, 
	sent_by VARCHAR, 
	discord_message_id VARCHAR, 
	discord_channel_id VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(mention_id) REFERENCES mention_event (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_orm_response_mention_id ON orm_response (mention_id);
CREATE INDEX IF NOT EXISTS ix_orm_response_brand_id ON orm_response (brand_id);
ALTER TABLE "orm_response" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS video_asset (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	script_id VARCHAR NOT NULL, 
	file_path VARCHAR NOT NULL, 
	duration_s FLOAT NOT NULL, 
	quality_score FLOAT, 
	qc_notes VARCHAR, 
	assembler_version VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(script_id) REFERENCES content_script (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_video_asset_script_id ON video_asset (script_id);
CREATE INDEX IF NOT EXISTS ix_video_asset_brand_id ON video_asset (brand_id);
ALTER TABLE "video_asset" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS video_job (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	script_id VARCHAR NOT NULL, 
	shot_index INTEGER NOT NULL, 
	model VARCHAR NOT NULL, 
	prompt VARCHAR NOT NULL, 
	api_job_id VARCHAR, 
	status VARCHAR NOT NULL, 
	video_url VARCHAR, 
	local_path VARCHAR, 
	cost_usd FLOAT, 
	last_error VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(script_id) REFERENCES content_script (id)
);

CREATE INDEX IF NOT EXISTS ix_video_job_script_id ON video_job (script_id);
CREATE INDEX IF NOT EXISTS ix_video_job_brand_id ON video_job (brand_id);
ALTER TABLE "video_job" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS scheduled_post (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	asset_id VARCHAR, 
	script_id VARCHAR, 
	platform VARCHAR NOT NULL, 
	scheduled_for TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status VARCHAR NOT NULL, 
	veto_deadline TIMESTAMP WITHOUT TIME ZONE, 
	attempts INTEGER NOT NULL, 
	last_attempt_at TIMESTAMP WITHOUT TIME ZONE, 
	last_error VARCHAR, 
	vendor_request_id VARCHAR, 
	variant_group VARCHAR, 
	product VARCHAR, 
	geo VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES video_asset (id), 
	FOREIGN KEY(script_id) REFERENCES content_script (id)
);

CREATE INDEX IF NOT EXISTS ix_scheduled_post_vendor_request_id ON scheduled_post (vendor_request_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_post_asset_id ON scheduled_post (asset_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_post_script_id ON scheduled_post (script_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_post_brand_id ON scheduled_post (brand_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_post_variant_group ON scheduled_post (variant_group);
ALTER TABLE "scheduled_post" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS published_post (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	scheduled_post_id VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	platform_post_id VARCHAR NOT NULL, 
	platform_url VARCHAR, 
	published_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (scheduled_post_id), 
	FOREIGN KEY(scheduled_post_id) REFERENCES scheduled_post (id)
);

CREATE INDEX IF NOT EXISTS ix_published_post_brand_id ON published_post (brand_id);
ALTER TABLE "published_post" ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS metrics_snapshot (
	id VARCHAR NOT NULL, 
	brand_id VARCHAR NOT NULL, 
	published_post_id VARCHAR NOT NULL, 
	captured_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	views INTEGER NOT NULL, 
	likes INTEGER NOT NULL, 
	comments INTEGER NOT NULL, 
	shares INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(published_post_id) REFERENCES published_post (id)
);

CREATE INDEX IF NOT EXISTS ix_metrics_snapshot_published_post_id ON metrics_snapshot (published_post_id);
CREATE INDEX IF NOT EXISTS ix_metrics_snapshot_brand_id ON metrics_snapshot (brand_id);
ALTER TABLE "metrics_snapshot" ENABLE ROW LEVEL SECURITY;


-- Speakr's user and api_token tables as created by the digest-pinned image
-- (learnedmachine/speakr v0.10.2-alpha, see containers.nix), copied from a
-- live deployment with `sqlite3 transcriptions.db .schema`. Used by
-- speakr-provision_test.py; update it together with the image pin.
CREATE TABLE user (
	id INTEGER NOT NULL, 
	username VARCHAR(20) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	password VARCHAR(60), 
	sso_provider VARCHAR(100), 
	sso_subject VARCHAR(255), 
	is_admin BOOLEAN, 
	can_share_publicly BOOLEAN, 
	transcription_language VARCHAR(10), 
	output_language VARCHAR(50), 
	ui_language VARCHAR(10), 
	summary_prompt TEXT, 
	extract_events BOOLEAN, 
	name VARCHAR(100), 
	job_title VARCHAR(100), 
	company VARCHAR(100), 
	diarize BOOLEAN, 
	default_naming_template_id INTEGER, 
	monthly_token_budget INTEGER, 
	monthly_transcription_budget INTEGER, 
	email_verified BOOLEAN, 
	email_verification_token VARCHAR(200), 
	email_verification_sent_at DATETIME, 
	password_reset_token VARCHAR(200), 
	password_reset_sent_at DATETIME, 
	auto_speaker_labelling BOOLEAN, 
	auto_speaker_labelling_threshold VARCHAR(10), 
	auto_summarization BOOLEAN, 
	transcription_hotwords TEXT, 
	transcription_initial_prompt TEXT, 
	summary_include_timestamps BOOLEAN, 
	summary_timestamp_template_id INTEGER, 
	chat_include_timestamps BOOLEAN, 
	chat_timestamp_template_id INTEGER, 
	show_timestamps_simple_view BOOLEAN, 
	editor_autosave BOOLEAN, 
	audio_player_position VARCHAR(10), 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	UNIQUE (email), 
	UNIQUE (sso_subject), 
	FOREIGN KEY(default_naming_template_id) REFERENCES naming_template (id) ON DELETE SET NULL, 
	FOREIGN KEY(summary_timestamp_template_id) REFERENCES transcript_template (id) ON DELETE SET NULL, 
	FOREIGN KEY(chat_timestamp_template_id) REFERENCES transcript_template (id) ON DELETE SET NULL
);
CREATE INDEX ix_user_email_verification_token ON user (email_verification_token);
CREATE INDEX ix_user_password_reset_token ON user (password_reset_token);
CREATE UNIQUE INDEX ix_user_sso_subject ON "user" (sso_subject);
CREATE TABLE api_token (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	name VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	last_used_at DATETIME, 
	expires_at DATETIME, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE UNIQUE INDEX ix_api_token_token_hash ON api_token (token_hash);
CREATE INDEX ix_api_token_revoked ON api_token (revoked);

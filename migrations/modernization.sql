ALTER TABLE runtimes ADD COLUMN desired_state VARCHAR(40) DEFAULT 'manual' NOT NULL;

ALTER TABLE runtimes ADD COLUMN autostart_policy VARCHAR(40) DEFAULT 'on_demand' NOT NULL;

CREATE TABLE policy_rules (
	id VARCHAR(36) NOT NULL,
	rule_id VARCHAR(80) NOT NULL,
	version INTEGER NOT NULL,
	service_id VARCHAR(36),
	severity VARCHAR(30) NOT NULL,
	actions JSONB NOT NULL,
	message TEXT NOT NULL,
	owner VARCHAR(80) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_policy_version UNIQUE (rule_id, version),
	CONSTRAINT ck_policy_version CHECK (version > 0),
	CONSTRAINT ck_policy_severity CHECK (severity IN ('block', 'requires_approval', 'warning', 'info')),
	FOREIGN KEY(service_id) REFERENCES services (id)
);

CREATE TABLE service_aliases (
	alias VARCHAR(80) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	PRIMARY KEY (alias),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE INDEX ix_service_aliases_service_id ON service_aliases (service_id);

CREATE TABLE service_profiles (
	service_id VARCHAR(36) NOT NULL,
	revision INTEGER NOT NULL,
	description TEXT NOT NULL,
	category VARCHAR(80) NOT NULL,
	protected BOOLEAN NOT NULL,
	archivable BOOLEAN NOT NULL,
	snapshot_supported BOOLEAN NOT NULL,
	paths JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (service_id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE TABLE deployment_sources (
	id VARCHAR(36) NOT NULL,
	runtime_id VARCHAR(36) NOT NULL,
	compose_service VARCHAR(120) NOT NULL,
	source_kind VARCHAR(40) NOT NULL,
	image_ref VARCHAR(255) NOT NULL,
	workflow_id VARCHAR(80) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_source_runtime_service UNIQUE (runtime_id, compose_service),
	CONSTRAINT ck_source_kind CHECK (source_kind IN ('registry_image', 'compose_build', 'external_build')),
	FOREIGN KEY(runtime_id) REFERENCES runtimes (id) ON DELETE CASCADE
);

CREATE TABLE operation_runs (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	runtime_id VARCHAR(36) NOT NULL,
	actor VARCHAR(120) NOT NULL,
	action VARCHAR(40) NOT NULL,
	status VARCHAR(40) NOT NULL,
	active_key VARCHAR(120),
	idempotency_key VARCHAR(120) NOT NULL,
	plan_hash VARCHAR(64) NOT NULL,
	plan JSONB NOT NULL,
	result JSONB NOT NULL,
	events JSONB NOT NULL,
	error TEXT NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_operation_actor_key UNIQUE (actor, idempotency_key),
	CONSTRAINT ck_operation_status CHECK (status IN ('planned', 'queued', 'running', 'completed', 'failed', 'interrupted')),
	FOREIGN KEY(service_id) REFERENCES services (id),
	FOREIGN KEY(runtime_id) REFERENCES runtimes (id),
	UNIQUE (active_key)
);

CREATE INDEX ix_operation_runs_service_id ON operation_runs (service_id);

CREATE TABLE route_options (
	route_id VARCHAR(36) NOT NULL,
	host_aliases JSONB NOT NULL,
	upstream_headers JSONB NOT NULL,
	response_headers JSONB NOT NULL,
	tls_profile VARCHAR(40) NOT NULL,
	owner_kind VARCHAR(40) NOT NULL,
	owner_ref VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (route_id),
	FOREIGN KEY(route_id) REFERENCES routes (id) ON DELETE CASCADE
);

CREATE TABLE deployment_releases (
	id VARCHAR(36) NOT NULL,
	operation_id VARCHAR(36) NOT NULL,
	runtime_id VARCHAR(36) NOT NULL,
	previous_images JSONB NOT NULL,
	images JSONB NOT NULL,
	compose_checksum VARCHAR(64) NOT NULL,
	status VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(operation_id) REFERENCES operation_runs (id),
	FOREIGN KEY(runtime_id) REFERENCES runtimes (id)
);

CREATE INDEX ix_deployment_releases_runtime_id ON deployment_releases (runtime_id);

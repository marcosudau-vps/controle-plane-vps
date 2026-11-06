CREATE TABLE activity_log (
	id VARCHAR(36) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	actor VARCHAR(120) NOT NULL,
	action VARCHAR(120) NOT NULL,
	entity_kind VARCHAR(40) NOT NULL,
	entity_id VARCHAR(36) NOT NULL,
	detail JSONB NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE comments (
	id VARCHAR(36) NOT NULL,
	entity_kind VARCHAR(40) NOT NULL,
	entity_id VARCHAR(36) NOT NULL,
	body TEXT NOT NULL,
	author VARCHAR(120) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE export_runs (
	id VARCHAR(36) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	export_type VARCHAR(40) NOT NULL,
	path VARCHAR(255) NOT NULL,
	status VARCHAR(40) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE generated_artifacts (
	id VARCHAR(36) NOT NULL,
	artifact_type VARCHAR(40) NOT NULL,
	path VARCHAR(255) NOT NULL,
	status VARCHAR(40) NOT NULL,
	checksum VARCHAR(128) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE lifecycle_runs (
	id VARCHAR(36) NOT NULL,
	service_slug VARCHAR(80) NOT NULL,
	action VARCHAR(40) NOT NULL,
	status VARCHAR(40) NOT NULL,
	plan_hash VARCHAR(128) NOT NULL,
	archive_dir VARCHAR(255) NOT NULL,
	archive_path VARCHAR(255) NOT NULL,
	quarantine_dir VARCHAR(255) NOT NULL,
	request_json JSONB NOT NULL,
	result_json JSONB NOT NULL,
	error TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_lifecycle_runs_service_slug ON lifecycle_runs (service_slug);

CREATE TABLE relations (
	id VARCHAR(36) NOT NULL,
	source_kind VARCHAR(40) NOT NULL,
	source_id VARCHAR(36) NOT NULL,
	relation_type VARCHAR(40) NOT NULL,
	target_kind VARCHAR(40) NOT NULL,
	target_id VARCHAR(36) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE services (
	id VARCHAR(36) NOT NULL,
	slug VARCHAR(80) NOT NULL,
	title VARCHAR(160) NOT NULL,
	summary TEXT NOT NULL,
	system VARCHAR(40) NOT NULL,
	component_type VARCHAR(40) NOT NULL,
	lifecycle VARCHAR(40) NOT NULL,
	owner VARCHAR(80) NOT NULL,
	criticality INTEGER NOT NULL,
	status VARCHAR(40) NOT NULL,
	tags JSONB NOT NULL,
	metadata_json JSONB NOT NULL,
	port_base INTEGER,
	large_port_space BOOLEAN NOT NULL,
	caddy_protection_enabled BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_services_slug ON services (slug);

CREATE TABLE sub_services (
	id VARCHAR(36) NOT NULL,
	slug VARCHAR(80) NOT NULL,
	title VARCHAR(160) NOT NULL,
	parent_type VARCHAR(40) NOT NULL,
	parent_id VARCHAR(36) NOT NULL,
	status VARCHAR(40) NOT NULL,
	metadata_json JSONB NOT NULL,
	caddy_protection_enabled BOOLEAN,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_sub_services_parent_id ON sub_services (parent_id);

CREATE UNIQUE INDEX ix_sub_services_slug ON sub_services (slug);

CREATE TABLE validation_runs (
	id VARCHAR(36) NOT NULL,
	scope VARCHAR(80) NOT NULL,
	status VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE apis (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	slug VARCHAR(80) NOT NULL,
	title VARCHAR(160) NOT NULL,
	api_type VARCHAR(40) NOT NULL,
	definition_path VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE,
	UNIQUE (slug)
);

CREATE TABLE docs (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	doc_type VARCHAR(40) NOT NULL,
	path VARCHAR(255) NOT NULL,
	title VARCHAR(160) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE TABLE healthchecks (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	check_type VARCHAR(40) NOT NULL,
	target VARCHAR(255) NOT NULL,
	expected_status INTEGER NOT NULL,
	timeout_seconds INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE TABLE ports (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36),
	number INTEGER NOT NULL,
	protocol VARCHAR(16) NOT NULL,
	bind VARCHAR(64) NOT NULL,
	purpose VARCHAR(160) NOT NULL,
	status VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_port_number_protocol UNIQUE (number, protocol),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE SET NULL
);

CREATE TABLE resources (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36),
	slug VARCHAR(80) NOT NULL,
	title VARCHAR(160) NOT NULL,
	resource_type VARCHAR(40) NOT NULL,
	owner VARCHAR(80) NOT NULL,
	metadata_json JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE SET NULL,
	UNIQUE (slug)
);

CREATE TABLE routes (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36),
	subservice_id VARCHAR(36),
	parent_type VARCHAR(40),
	parent_id VARCHAR(36),
	host VARCHAR(255) NOT NULL,
	path VARCHAR(255) NOT NULL,
	upstream VARCHAR(255) NOT NULL,
	tls BOOLEAN NOT NULL,
	auth_policy VARCHAR(80) NOT NULL,
	caddy_protection_enabled BOOLEAN,
	status VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_route_host_path UNIQUE (host, path),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE,
	FOREIGN KEY(subservice_id) REFERENCES sub_services (id) ON DELETE CASCADE
);

CREATE INDEX ix_routes_host ON routes (host);

CREATE INDEX ix_routes_parent_id ON routes (parent_id);

CREATE TABLE runtimes (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	runtime_type VARCHAR(40) NOT NULL,
	path VARCHAR(255) NOT NULL,
	compose_project VARCHAR(120) NOT NULL,
	systemd_unit VARCHAR(120) NOT NULL,
	restart_policy VARCHAR(80) NOT NULL,
	metadata_json JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE TABLE secret_refs (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36) NOT NULL,
	name VARCHAR(120) NOT NULL,
	provider VARCHAR(40) NOT NULL,
	ref VARCHAR(255) NOT NULL,
	target_env VARCHAR(120) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);

CREATE TABLE skills (
	id VARCHAR(36) NOT NULL,
	service_id VARCHAR(36),
	slug VARCHAR(80) NOT NULL,
	title VARCHAR(160) NOT NULL,
	skill_type VARCHAR(40) NOT NULL,
	path VARCHAR(255) NOT NULL,
	description TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE,
	UNIQUE (slug)
);

CREATE TABLE validation_results (
	id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	severity VARCHAR(20) NOT NULL,
	code VARCHAR(80) NOT NULL,
	message TEXT NOT NULL,
	entity_kind VARCHAR(40) NOT NULL,
	entity_id VARCHAR(36) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id) REFERENCES validation_runs (id) ON DELETE CASCADE
);

CREATE TABLE skill_items (
	id VARCHAR(36) NOT NULL,
	skill_id VARCHAR(36) NOT NULL,
	relative_path VARCHAR(255) NOT NULL,
	item_type VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE CASCADE
);

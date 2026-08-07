# Local PostgreSQL for the first-party API and worker. Credentials remain in
# runtime files/systemd credentials and never enter the Nix store.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.aiCoaching;
  pg = cfg.postgresql;
in
{
  options.services.aiCoaching.postgresql = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Manage PostgreSQL locally; disable to use an operator-managed external database.";
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.postgresql_16;
      description = "PostgreSQL package used for the local database and backup tools.";
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "host.containers.internal";
      description = "Database host visible from the Podman containers.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 5432;
      description = "PostgreSQL port.";
    };

    databaseName = lib.mkOption {
      type = lib.types.str;
      default = "evidence";
      description = "Database owned by the evidence role.";
    };

    username = lib.mkOption {
      type = lib.types.str;
      default = "evidence";
      description = "Database role used by the API and worker.";
    };

    passwordFile = lib.mkOption {
      type = lib.types.path;
      default = "${cfg.secretsDir}/postgresql-evidence-password";
      description = "Root-readable file containing the database role password.";
    };
  };

  config = lib.mkIf (cfg.enable && pg.enable) {
    assertions = [
      {
        assertion = cfg.network.subnet != null;
        message = "A fixed services.aiCoaching.network.subnet is required with local PostgreSQL so pg_hba can allow only that network.";
      }
      {
        assertion = builtins.match "[A-Za-z_][A-Za-z0-9_]*" pg.username != null;
        message = "services.aiCoaching.postgresql.username must be a simple PostgreSQL identifier.";
      }
      {
        assertion = builtins.match "[A-Za-z_][A-Za-z0-9_]*" pg.databaseName != null;
        message = "services.aiCoaching.postgresql.databaseName must be a simple PostgreSQL identifier.";
      }
      {
        assertion = builtins.stringLength pg.databaseName <= 30;
        message = "services.aiCoaching.postgresql.databaseName must be at most 30 characters so restore swap database names remain valid.";
      }
    ];

    services.postgresql = {
      enable = true;
      inherit (pg) package;
      enableTCPIP = true;
      ensureDatabases = [ pg.databaseName ];
      ensureUsers = [
        {
          name = pg.username;
          ensureDBOwnership = true;
        }
      ];
      authentication = lib.mkAfter ''
        host  ${pg.databaseName}  ${pg.username}  ${cfg.network.subnet}  scram-sha-256
      '';
    };

    systemd.services.ai-coaching-postgresql-password = {
      description = "Provision PostgreSQL password for the evidence API and worker";
      after = [ "postgresql.service" ];
      requires = [ "postgresql.service" ];
      wantedBy = [ "multi-user.target" ];
      before = [
        "podman-evidence-api.service"
        "podman-evidence-worker.service"
      ];
      serviceConfig = {
        Type = "oneshot";
        User = "postgres";
        LoadCredential = "db-password:${pg.passwordFile}";
      };
      script = ''
        set -euo pipefail
        export AI_COACHING_DB_CREDENTIAL
        AI_COACHING_DB_CREDENTIAL=$(cat "$CREDENTIALS_DIRECTORY/db-password")
        ${pg.package}/bin/psql \
          -v ON_ERROR_STOP=1 \
          -d postgres <<'SQL'
        \getenv role_password AI_COACHING_DB_CREDENTIAL
        ALTER ROLE "${pg.username}" WITH PASSWORD :'role_password';
        SQL
        unset AI_COACHING_DB_CREDENTIAL
      '';
    };
  };
}

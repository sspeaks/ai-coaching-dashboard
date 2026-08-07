{
  self,
  nixpkgs,
  system,
  pkgs,
  artifacts,
}:
let
  inherit (nixpkgs) lib;
  imgLib = import ./lib.nix { inherit lib; };

  disabledSystem = lib.nixosSystem {
    inherit system;
    modules = [
      self.nixosModules.aiCoaching
      { services.aiCoaching.enable = false; }
      (import ../deploy/eval-only-stub-hardware.nix)
    ];
  };

  deploySystem = lib.nixosSystem {
    inherit system;
    specialArgs.inputs.ai-coaching-dashboard = self;
    modules = [
      self.nixosModules.aiCoaching
      (import ../deploy/example-configuration.nix)
      (import ../deploy/eval-only-stub-hardware.nix)
    ];
  };

  deployConfig = deploySystem.config;
  containers = deployConfig.virtualisation.oci-containers.containers;
  caddyConfig = deployConfig.services.caddy.virtualHosts."coaching.example.org".extraConfig;
  writerRestoreCondition = "!/var/lib/ai-coaching/.ai-coaching-restore-in-progress";
  contractSystem = lib.nixosSystem {
    inherit system;
    specialArgs.inputs.ai-coaching-dashboard = self;
    modules = [
      self.nixosModules.aiCoaching
      (import ../deploy/example-configuration.nix)
      {
        services.aiCoaching = {
          domain = lib.mkForce "contract.invalid";
          postgresql.enable = lib.mkForce false;
          speakr.enable = lib.mkForce false;
          evidenceWorker.enable = lib.mkForce false;
          webFrontend.enable = lib.mkForce false;
          backup.enable = lib.mkForce false;
          oidc.port = lib.mkForce 19081;
          evidenceApi.hostPort = lib.mkForce 19082;
        };
      }
      (import ../deploy/eval-only-stub-hardware.nix)
    ];
  };
  contractCaddyConfig =
    contractSystem.config.services.caddy.virtualHosts."contract.invalid".extraConfig;
  extractionGatewaySystem = lib.nixosSystem {
    inherit system;
    specialArgs.inputs.ai-coaching-dashboard = self;
    modules = [
      self.nixosModules.aiCoaching
      (import ../deploy/example-configuration.nix)
      {
        services.aiCoaching = {
          extractionGateway = {
            enable = true;
            image = lib.mkForce "ai-coaching/extraction-gateway:flake";
            imageFile = lib.mkForce artifacts.extractionGatewayImage;
          };
          backup.enable = lib.mkForce false;
        };
      }
      (import ../deploy/eval-only-stub-hardware.nix)
    ];
  };
  extractionGatewayContainers =
    extractionGatewaySystem.config.virtualisation.oci-containers.containers;
  externalTlsSystem = lib.nixosSystem {
    inherit system;
    specialArgs.inputs.ai-coaching-dashboard = self;
    modules = [
      self.nixosModules.aiCoaching
      (import ../deploy/example-configuration.nix)
      {
        services.aiCoaching = {
          domain = lib.mkForce "external.invalid";
          caddy = {
            acmeEmail = lib.mkForce null;
            externalTls = {
              enable = true;
              httpPort = 18080;
            };
          };
          backup.enable = lib.mkForce false;
        };
      }
      (import ../deploy/eval-only-stub-hardware.nix)
    ];
  };
  externalTlsConfig =
    externalTlsSystem.config.services.caddy.virtualHosts."http://external.invalid:18080".extraConfig;
  badRegistryPin = builtins.tryEval (
    builtins.deepSeq
      (lib.nixosSystem {
        inherit system;
        specialArgs.inputs.ai-coaching-dashboard = self;
        modules = [
          self.nixosModules.aiCoaching
          (import ../deploy/example-configuration.nix)
          {
            services.aiCoaching.evidenceApi = {
              image = lib.mkForce "registry.example/evidence-api:latest";
              imageFile = lib.mkForce null;
            };
          }
          (import ../deploy/eval-only-stub-hardware.nix)
        ];
      }).config.system.build.toplevel
      true
  );

  backupScripts = import ./backup-scripts.nix { inherit lib pkgs; };
  fakeSystemctl = pkgs.writeShellScriptBin "systemctl" (builtins.readFile ./fake-systemctl.sh);
  fakePgDump = pkgs.writeShellScriptBin "pg_dump" (builtins.readFile ./fake-pg-dump.sh);
  fakePgRestore = pkgs.writeShellScriptBin "pg_restore" (builtins.readFile ./fake-pg-restore.sh);
  fakePsql = pkgs.writeShellScriptBin "psql" (builtins.readFile ./fake-psql.sh);
  fakePgTools = pkgs.symlinkJoin {
    name = "fake-pg-tools";
    paths = [
      fakePgDump
      fakePgRestore
      fakePsql
    ];
  };
  writerUnits = [
    "podman-speakr.service"
    "podman-evidence-api.service"
    "podman-evidence-worker.service"
  ];
  backupCheckData = "/build/ai-coaching-backup-restore-check";
  checkPg = {
    enable = true;
    package = fakePgTools;
    host = "127.0.0.1";
    port = 5432;
    username = "evidence";
    databaseName = "evidence";
    passwordFile = "${backupCheckData}/pg-password";
    adminCommandPrefix = [ ];
    adminHost = "127.0.0.1";
    adminUsername = "postgres";
    adminDatabase = "postgres";
  };
  backupCheckScript = backupScripts.mkBackupScript {
    dataDir = backupCheckData;
    targetDir = "${backupCheckData}/backups";
    retainCount = 2;
    pg = checkPg;
    serviceUnits = writerUnits;
    systemctlBin = "${fakeSystemctl}/bin/systemctl";
  };
  restoreCheckScript = backupScripts.mkRestoreScript {
    dataDir = backupCheckData;
    pg = checkPg;
    serviceUnits = writerUnits;
    systemctlBin = "${fakeSystemctl}/bin/systemctl";
  };

  realPgPackage = pkgs.postgresql_16;
  realPgCheckData = "/build/ai-coaching-real-pg-restore-check";
  realPgSocket = "${realPgCheckData}/socket";
  realPgPort = 55439;
  realPgDatabaseName = "evidence";
  realPgUsername = "evidence";
  realPgAdminUsername = "restore_admin";
  realPg = {
    enable = true;
    package = realPgPackage;
    host = realPgSocket;
    port = realPgPort;
    username = realPgUsername;
    databaseName = realPgDatabaseName;
    passwordFile = "${realPgCheckData}/pg-password";
    adminCommandPrefix = [ ];
    adminHost = realPgSocket;
    adminUsername = realPgAdminUsername;
    adminDatabase = "postgres";
  };
  realPgBackupScript = backupScripts.mkBackupScript {
    dataDir = realPgCheckData;
    targetDir = "${realPgCheckData}/backups";
    retainCount = 2;
    pg = realPg;
    manageServices = false;
    serviceUnits = [ ];
  };
  realPgRestoreScript = backupScripts.mkRestoreScript {
    dataDir = realPgCheckData;
    pg = realPg;
    manageServices = false;
    serviceUnits = [ ];
  };

  retentionCheckData = "/build/ai-coaching-retention-check";
  retentionCheckScripts = (import ./retention-scripts.nix { inherit pkgs; }).mkRetentionScripts {
    dataDir = retentionCheckData;
  };
in
{
  module-eval-disabled = pkgs.runCommand "ai-coaching-module-eval-disabled" { } ''
    echo ${lib.escapeShellArg disabledSystem.config.system.build.toplevel.drvPath} > "$out"
  '';

  fresh-deploy =
    assert containers.evidence-api.image == "ai-coaching/evidence-api:flake";
    assert containers.evidence-api.imageFile == artifacts.evidenceApiImage;
    assert builtins.elem "/var/lib/ai-coaching/media:/data/media:rw" containers.evidence-api.volumes;
    assert builtins.elem "/var/lib/ai-coaching/media:/data/media:rw" containers.evidence-worker.volumes;
    assert containers.evidence-api.environment.EVIDENCE_MEDIA_ROOT == "/data/media";
    assert containers.evidence-worker.environment.EVIDENCE_MEDIA_ROOT == "/data/media";
    assert containers.evidence-api.environment.EVIDENCE_AUTH_MODE == "trusted_proxy";
    assert containers.evidence-api.environment.EVIDENCE_TRUSTED_EMAIL_HEADER == "x-auth-request-email";
    assert
      containers.evidence-api.environment.EVIDENCE_TRUSTED_GROUPS_HEADER == "x-auth-request-groups";
    assert
      containers.evidence-api.environment.EVIDENCE_TRUSTED_PROXY_NETWORKS == "127.0.0.1/32,::1/128";
    assert containers.evidence-api.environment.EVIDENCE_ADMIN_GROUPS == "evidence-admins";
    assert containers.evidence-api.environment.EVIDENCE_EDITOR_GROUPS == "evidence-editors";
    assert
      deployConfig.systemd.services.podman-speakr.unitConfig.ConditionPathExists
      == writerRestoreCondition;
    assert
      deployConfig.systemd.services.podman-evidence-api.unitConfig.ConditionPathExists
      == writerRestoreCondition;
    assert
      deployConfig.systemd.services.podman-evidence-worker.unitConfig.ConditionPathExists
      == writerRestoreCondition;
    assert builtins.elem "/var/lib/ai-coaching/secrets/proxy-auth.env"
      containers.evidence-api.environmentFiles;
    assert
      !builtins.elem "/var/lib/ai-coaching/secrets/proxy-auth.env" containers.evidence-worker.environmentFiles;
    assert deployConfig.services.oauth2-proxy.provider == "oidc";
    assert deployConfig.services.oauth2-proxy.setXauthrequest;
    assert deployConfig.services.oauth2-proxy.extraConfig.skip-auth-strip-headers;
    assert deployConfig.services.oauth2-proxy.extraConfig.oidc-groups-claim == "groups";
    assert
      deployConfig.services.oauth2-proxy.trustedProxyIP == [
        "127.0.0.1/32"
        "::1/128"
      ];
    assert lib.hasInfix "handle /api/*" caddyConfig;
    assert !lib.hasInfix "strip_prefix /api" caddyConfig;
    assert lib.hasInfix "request_header -X-Auth-Request-Email" caddyConfig;
    assert lib.hasInfix "request_header -X-AI-Coaching-Proxy-Auth" caddyConfig;
    assert lib.hasInfix "request_header -X-Forwarded-For" caddyConfig;
    assert lib.hasInfix "copy_headers X-Auth-Request-User X-Auth-Request-Email X-Auth-Request-Groups"
      caddyConfig;
    assert lib.hasInfix "header_up X-AI-Coaching-Proxy-Auth {env.AI_COACHING_PROXY_AUTH_SECRET}"
      caddyConfig;
    pkgs.runCommand "ai-coaching-fresh-deploy" { } ''
      test -s ${artifacts.evidenceApiImage}
      test -s ${artifacts.evidenceWorkerImage}
      test -s ${artifacts.extractionGatewayImage}
      test -s ${artifacts.webFrontendImage}
      test -f ${artifacts.webFrontend}/index.html
      test -x ${artifacts.proxyGateway}/bin/ai-coaching-proxy-gateway
      ${pkgs.gnutar}/bin/tar -xOf ${artifacts.evidenceApiImage} manifest.json \
        | ${pkgs.gnugrep}/bin/grep -F '"ai-coaching/evidence-api:flake"'
      ${pkgs.gnutar}/bin/tar -xOf ${artifacts.evidenceWorkerImage} manifest.json \
        | ${pkgs.gnugrep}/bin/grep -F '"ai-coaching/evidence-worker:flake"'
      ${pkgs.gnutar}/bin/tar -xOf ${artifacts.extractionGatewayImage} manifest.json \
        | ${pkgs.gnugrep}/bin/grep -F '"ai-coaching/extraction-gateway:flake"'
      ${pkgs.gnutar}/bin/tar -xOf ${artifacts.webFrontendImage} manifest.json \
        | ${pkgs.gnugrep}/bin/grep -F '"ai-coaching/web-frontend:flake"'
      ${pkgs.caddy}/bin/caddy adapt \
        --adapter caddyfile \
        --config ${deployConfig.services.caddy.configFile} \
        >/dev/null
      cat > "$out" <<EOF
      evaluated=${deployConfig.system.build.toplevel.drvPath}
      api-image=${artifacts.evidenceApiImage}
      worker-image=${artifacts.evidenceWorkerImage}
      extraction-gateway-image=${artifacts.extractionGatewayImage}
      frontend-image=${artifacts.webFrontendImage}
      EOF
    '';

  extraction-gateway-module =
    assert extractionGatewayContainers.extraction-gateway.image == "ai-coaching/extraction-gateway:flake";
    assert extractionGatewayContainers.extraction-gateway.imageFile == artifacts.extractionGatewayImage;
    assert
      builtins.elem "/var/lib/ai-coaching/secrets/extraction-gateway.env"
        extractionGatewayContainers.extraction-gateway.environmentFiles;
    assert
      extractionGatewayContainers.evidence-worker.environment.EVIDENCE_EXTRACTION_PROVIDER
      == "http_json";
    assert
      extractionGatewayContainers.evidence-worker.environment.EVIDENCE_EXTRACTION_ENDPOINT
      == "http://extraction-gateway:8080/";
    assert
      builtins.elem "extraction-gateway" extractionGatewayContainers.evidence-worker.dependsOn;
    assert
      extractionGatewaySystem.config.systemd.services.podman-extraction-gateway.unitConfig.ConditionPathExists
      == writerRestoreCondition;
    pkgs.runCommand "ai-coaching-extraction-gateway-module" { } ''
      echo ${lib.escapeShellArg extractionGatewaySystem.config.system.build.toplevel.drvPath} > "$out"
    '';

  external-tls-proxy =
    assert !externalTlsSystem.config.services.caddy.virtualHosts ? "external.invalid";
    assert externalTlsSystem.config.networking.firewall.allowedTCPPorts == [ 18080 ];
    assert externalTlsSystem.config.services.oauth2-proxy.cookie.secure;
    assert externalTlsSystem.config.services.oauth2-proxy.reverseProxy;
    assert
      externalTlsSystem.config.services.oauth2-proxy.trustedProxyIP == [
        "127.0.0.1/32"
        "::1/128"
      ];
    assert lib.hasInfix "request_header -X-Forwarded-Proto" externalTlsConfig;
    assert lib.hasInfix "header_up X-Forwarded-Proto https" externalTlsConfig;
    assert lib.hasInfix "header_up X-Forwarded-Host {host}" externalTlsConfig;
    assert lib.hasInfix "header_up X-Forwarded-Port 443" externalTlsConfig;
    pkgs.runCommand "ai-coaching-external-tls-proxy" { } ''
      ${pkgs.caddy}/bin/caddy adapt \
        --adapter caddyfile \
        --config ${externalTlsSystem.config.services.caddy.configFile} \
        >/dev/null
      echo ${lib.escapeShellArg externalTlsSystem.config.system.build.toplevel.drvPath} > "$out"
    '';

  backup-restore = pkgs.runCommand "ai-coaching-backup-restore" { } ''
    set -euo pipefail
    rm -rf -- ${backupCheckData}
    mkdir -p ${backupCheckData}/{media/session-1,speakr,evidence-worker}
    printf 'original-media\n' > ${backupCheckData}/media/session-1/original.wav
    printf 'writer-active\n' > ${backupCheckData}/speakr/state
    printf 'worker-state\n' > ${backupCheckData}/evidence-worker/state
    printf 'fake-password\n' > ${backupCheckData}/pg-password
    state=${backupCheckData}/systemctl.state
    log=${backupCheckData}/systemctl.log
    pglog=${backupCheckData}/pg.log
    pgstate=${backupCheckData}/pg-state
    marker=${backupCheckData}/.ai-coaching-restore-in-progress
    mkdir -p "$pgstate/databases/evidence"
    printf '%s\n' evidence > "$pgstate/databases/evidence/owner"
    printf '%s\n' 'evidence=CTc/evidence,reporter=c/evidence' > "$pgstate/databases/evidence/acl"
    printf '%s\n' shared-object backup-only-object > "$pgstate/databases/evidence/objects"
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    : > "$pglog"
    export FAKE_SYSTEMCTL_STATE="$state"
    export FAKE_SYSTEMCTL_LOG="$log"
    export FAKE_PG_LOG="$pglog"
    export FAKE_PG_STATE="$pgstate"
    export FAKE_PG_PASSWORD=fake-password
    export FAKE_RESTORE_MARKER="$marker"
    export FAKE_FINALIZE_FILE=${backupCheckData}/speakr/state

    # --- Scenario 1: happy-path backup/restore round trip with PostgreSQL
    # --- enabled: locking, checksum manifest, and dump inclusion all verified.
    ${backupCheckScript}/bin/ai-coaching-backup
    archive=$(find ${backupCheckData}/backups -maxdepth 1 -name '*.tar.gz' -print -quit)
    test -n "$archive"
    test -f "$archive.sha256"
    sha256sum -c "$archive.sha256"
    tar -tzf "$archive" | grep -F './data/media/session-1/original.wav'
    tar -tzf "$archive" | grep -F './postgresql/evidence.dump'
    tar -tzf "$archive" | grep -F './MANIFEST.sha256'
    tar -xOzf "$archive" ./data/speakr/state | grep -Fx quiesced
    grep -F 'STOP podman-speakr.service podman-evidence-api.service podman-evidence-worker.service' "$log"
    grep -F 'START podman-speakr.service podman-evidence-api.service podman-evidence-worker.service' "$log"
    for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits}; do
      grep -Fx "$unit" "$state"
    done
    grep -F 'PG_DUMP' "$pglog"

    printf 'changed\n' > ${backupCheckData}/media/session-1/original.wav
    printf '%s\n' shared-object pre-restore-only-object > "$pgstate/databases/evidence/objects"
    unset FAKE_FINALIZE_FILE
    export FAKE_EXPECT_FILE=${backupCheckData}/media/session-1/original.wav
    export FAKE_EXPECT_CONTENT=original-media
    : > "$pglog"
    ${restoreCheckScript}/bin/ai-coaching-restore --yes "$archive"
    grep -Fx 'original-media' ${backupCheckData}/media/session-1/original.wav
    test -d ${backupCheckData}/media.pre-restore-*
    test "$(grep -c '^STOP ' "$log")" -eq 2
    test "$(grep -c '^START ' "$log")" -eq 2
    grep -F 'PG_RESTORE list' "$pglog"
    grep -F 'PG_RESTORE restore' "$pglog"
    grep -F -- '--single-transaction' "$pglog"
    if grep -F -- '--clean' "$pglog"; then
      echo "restore used pg_restore --clean instead of an empty replacement database" >&2
      exit 1
    fi
    grep -F 'AI_COACHING_PREPARE_REPLACEMENT' "$pglog"
    grep -F 'AI_COACHING_APPLY_DATABASE_METADATA' "$pglog"
    grep -F 'AI_COACHING_SWAP_DATABASES' "$pglog"
    grep -Fx backup-only-object "$pgstate/databases/evidence/objects"
    if grep -Fxq pre-restore-only-object "$pgstate/databases/evidence/objects"; then
      echo "faithful database replacement retained a pre-restore-only object" >&2
      exit 1
    fi
    grep -Fx evidence "$pgstate/databases/evidence/owner"
    grep -Fx 'evidence=CTc/evidence,reporter=c/evidence' "$pgstate/databases/evidence/acl"
    test ! -e "$marker"
    cp "$archive" ${backupCheckData}/reference-good.tar.gz
    cp "$archive.sha256" ${backupCheckData}/reference-good.tar.gz.sha256

    # --- PostgreSQL replacement prerequisites are validated before writers
    # --- stop: the application credential must be readable and the configured
    # --- role must own the target database used by the local admin swap. ---
    : > "$log"
    mv ${backupCheckData}/pg-password ${backupCheckData}/pg-password.missing
    if restore_output=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz 2>&1); then
      echo "restore accepted a missing PostgreSQL credential" >&2
      exit 1
    else
      echo "$restore_output" | grep -F 'password file is missing, unreadable, or empty'
    fi
    mv ${backupCheckData}/pg-password.missing ${backupCheckData}/pg-password
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    printf '%s\n' unexpected-owner > "$pgstate/databases/evidence/owner"
    if restore_output=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz 2>&1); then
      echo "restore accepted a database owned by the wrong role" >&2
      exit 1
    else
      echo "$restore_output" | grep -F 'must be owned by configured role evidence'
    fi
    printf '%s\n' evidence > "$pgstate/databases/evidence/owner"
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    # --- Existing writer-lifecycle error-propagation scenarios ---
    rm -rf ${backupCheckData}/backups
    mkdir -p ${backupCheckData}/backups
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    unset FAKE_EXPECT_FILE FAKE_EXPECT_CONTENT
    if FAKE_STOP_FAIL=true ${backupCheckScript}/bin/ai-coaching-backup; then
      echo "backup ignored a writer stop failure" >&2
      exit 1
    fi
    test -z "$(find ${backupCheckData}/backups -maxdepth 1 -name '*.tar.gz' -print -quit)"
    grep -F 'STOP podman-speakr.service' "$log"

    rm -rf ${backupCheckData}/backups
    mkdir -p ${backupCheckData}/backups
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    if FAKE_START_FAIL=true ${backupCheckScript}/bin/ai-coaching-backup; then
      echo "backup ignored a writer restart failure" >&2
      exit 1
    fi
    grep -F 'START podman-speakr.service' "$log"

    # --- Scenario: restore refuses an archive whose bytes don't match its
    # --- companion checksum file, before touching any service or data
    # --- state. The archive itself stays a valid, untouched gzip/tar
    # --- stream; only the recorded checksum is wrong. ---
    rm -rf ${backupCheckData}/backups
    mkdir -p ${backupCheckData}/backups
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    ${backupCheckScript}/bin/ai-coaching-backup
    good_archive=$(find ${backupCheckData}/backups -maxdepth 1 -name '*.tar.gz' -print -quit)
    test -n "$good_archive"
    cp "$good_archive" ${backupCheckData}/tampered.tar.gz
    zero_hash=$(printf '%064d' 0)
    printf '%s  %s\n' "$zero_hash" ${backupCheckData}/tampered.tar.gz > ${backupCheckData}/tampered.tar.gz.sha256
    : > "$log"
    if restore_output=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/tampered.tar.gz 2>&1); then
      echo "restore accepted an archive with a mismatched checksum" >&2
      echo "$restore_output" >&2
      exit 1
    else
      echo "$restore_output" | grep -F 'checksum mismatch'
    fi
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    # --- Scenario: restore refuses when the archive is missing the required
    # --- PostgreSQL dump, before stopping any writer. ---
    rm -rf ${backupCheckData}/build-no-pg
    mkdir -p ${backupCheckData}/build-no-pg/data/{media,speakr,evidence-worker}
    printf 'm\n' > ${backupCheckData}/build-no-pg/data/media/file
    printf 's\n' > ${backupCheckData}/build-no-pg/data/speakr/state
    printf 'w\n' > ${backupCheckData}/build-no-pg/data/evidence-worker/state
    (
      cd ${backupCheckData}/build-no-pg
      find . -type f ! -name MANIFEST.sha256 -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
    ) > ${backupCheckData}/build-no-pg/MANIFEST.sha256
    tar -C ${backupCheckData}/build-no-pg -czf ${backupCheckData}/no-pg.tar.gz .
    sha256sum ${backupCheckData}/no-pg.tar.gz > ${backupCheckData}/no-pg.tar.gz.sha256
    : > "$log"
    if restore_output=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/no-pg.tar.gz 2>&1); then
      echo "restore accepted an archive missing the required PostgreSQL dump" >&2
      echo "$restore_output" >&2
      exit 1
    else
      echo "$restore_output" | grep -F 'missing the required PostgreSQL dump'
    fi
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    # --- Scenario: restore refuses when the PostgreSQL dump fails structural
    # --- validation (pg_restore --list), before stopping any writer. ---
    rm -rf ${backupCheckData}/build-bad-pg
    mkdir -p ${backupCheckData}/build-bad-pg/data/{media,speakr,evidence-worker} ${backupCheckData}/build-bad-pg/postgresql
    printf 'm\n' > ${backupCheckData}/build-bad-pg/data/media/file
    printf 's\n' > ${backupCheckData}/build-bad-pg/data/speakr/state
    printf 'w\n' > ${backupCheckData}/build-bad-pg/data/evidence-worker/state
    printf 'not-a-real-dump\n' > ${backupCheckData}/build-bad-pg/postgresql/evidence.dump
    (
      cd ${backupCheckData}/build-bad-pg
      find . -type f ! -name MANIFEST.sha256 -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
    ) > ${backupCheckData}/build-bad-pg/MANIFEST.sha256
    tar -C ${backupCheckData}/build-bad-pg -czf ${backupCheckData}/bad-pg.tar.gz .
    sha256sum ${backupCheckData}/bad-pg.tar.gz > ${backupCheckData}/bad-pg.tar.gz.sha256
    : > "$log"
    if restore_output=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/bad-pg.tar.gz 2>&1); then
      echo "restore accepted a structurally invalid PostgreSQL dump" >&2
      echo "$restore_output" >&2
      exit 1
    else
      echo "$restore_output" | grep -F 'structural validation'
    fi
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    # --- Scenario: pg_restore fails after the filesystem swap. A directory
    # --- absent before restore is removed again by rollback, all prior
    # --- directories are restored, and the persistent marker fail-stops
    # --- writers until the operator completes explicit rollback. ---
    rm -rf ${backupCheckData}/media.pre-restore-* ${backupCheckData}/speakr.pre-restore-* ${backupCheckData}/evidence-worker.pre-restore-*
    printf 'known-good-before-failed-restore\n' > ${backupCheckData}/media/session-1/original.wav
    rm -rf ${backupCheckData}/evidence-worker
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    : > "$pglog"
    unset FAKE_EXPECT_FILE FAKE_EXPECT_CONTENT
    if FAKE_PG_RESTORE_FAIL=true ${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz 2>${backupCheckData}/failed-restore.log; then
      echo "restore ignored a PostgreSQL restore failure" >&2
      cat ${backupCheckData}/failed-restore.log >&2
      exit 1
    fi
    grep -F 'FAILED: writer services are left stopped' ${backupCheckData}/failed-restore.log
    grep -F 'rolling back filesystem' ${backupCheckData}/failed-restore.log
    grep -Fx 'known-good-before-failed-restore' ${backupCheckData}/media/session-1/original.wav
    test ! -e ${backupCheckData}/evidence-worker
    test -z "$(find ${backupCheckData} -maxdepth 1 -name 'media.pre-restore-*' -print -quit)"
    test -e "$marker"
    test "$(grep -c '^STOP ' "$log")" -eq 1
    test "$(grep -c '^START ' "$log" || true)" -eq 0
    if grep -Fxq "podman-speakr.service" "$state"; then
      echo "writer service was marked active after a failed restore" >&2
      exit 1
    fi
    ${restoreCheckScript}/bin/ai-coaching-restore --rollback
    test ! -e "$marker"
    test ! -e ${backupCheckData}/evidence-worker
    grep -F 'pre-restore.dump' "$pglog"
    for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits}; do
      grep -Fx "$unit" "$state"
    done

    # --- Scenario: failure is injected after the original directory has
    # --- moved away but before restored content is moved into place. The
    # --- original is restored immediately and remains recoverable through
    # --- the durable operator rollback path. ---
    mkdir -p ${backupCheckData}/evidence-worker
    printf 'worker-before-partial-swap\n' > ${backupCheckData}/evidence-worker/state
    printf 'original-before-partial-swap\n' > ${backupCheckData}/media/session-1/original.wav
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    : > "$pglog"
    if AI_COACHING_RESTORE_TEST_FAILPOINT=after-original-away:media \
      ${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz \
      2>${backupCheckData}/partial-swap.log; then
      echo "restore ignored the injected partial-swap failure" >&2
      exit 1
    fi
    grep -F 'injected failure after moving original media aside' ${backupCheckData}/partial-swap.log
    grep -Fx 'original-before-partial-swap' ${backupCheckData}/media/session-1/original.wav
    test -z "$(find ${backupCheckData} -maxdepth 1 -name 'media.pre-restore-*' -print -quit)"
    test -e "$marker"
    test "$(grep -c '^START ' "$log" || true)" -eq 0
    ${restoreCheckScript}/bin/ai-coaching-restore --rollback
    test ! -e "$marker"
    grep -Fx 'original-before-partial-swap' ${backupCheckData}/media/session-1/original.wav

    # --- Scenario: SIGKILL-like interruption after marker fsync. Direct
    # --- startup and a reboot-equivalent startup evaluation are both
    # --- refused while the marker persists. Resume completes the restore,
    # --- clears the marker, and only then restarts the saved writer set. ---
    printf 'before-interrupted-restore\n' > ${backupCheckData}/media/session-1/original.wav
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    : > "$pglog"
    set +e
    AI_COACHING_RESTORE_TEST_FAILPOINT=after-marker \
      ${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz \
      >${backupCheckData}/interrupted-restore.log 2>&1
    interrupted_status=$?
    set -e
    test "$interrupted_status" -ne 0
    test -e "$marker"
    test -d "$(cat "$marker")"
    test "$(grep -c '^START ' "$log" || true)" -eq 0

    if ${fakeSystemctl}/bin/systemctl start ${
      lib.concatMapStringsSep " " lib.escapeShellArg writerUnits
    }; then
      echo "writer startup ignored the persistent restore marker" >&2
      exit 1
    fi
    grep -F 'REFUSE_RESTORE_MARKER' "$log"

    : > "$state"
    if ${fakeSystemctl}/bin/systemctl start ${
      lib.concatMapStringsSep " " lib.escapeShellArg writerUnits
    }; then
      echo "reboot-equivalent writer startup ignored the persistent restore marker" >&2
      exit 1
    fi
    test ! -s "$state"

    if ${backupCheckScript}/bin/ai-coaching-backup >${backupCheckData}/blocked-backup.log 2>&1; then
      echo "backup ignored an interrupted restore marker" >&2
      exit 1
    fi
    grep -F 'restore recovery marker exists' ${backupCheckData}/blocked-backup.log

    ${restoreCheckScript}/bin/ai-coaching-restore --resume
    test ! -e "$marker"
    grep -Fx 'original-media' ${backupCheckData}/media/session-1/original.wav
    for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits}; do
      grep -Fx "$unit" "$state"
    done

    # --- An originally absent path is durably recorded before the marker.
    # --- After interruption, reboot-like tmpfiles recreation must not change
    # --- that fact. A failed resume and explicit rollback both restore absence.
    rm -rf ${backupCheckData}/evidence-worker
    printf '%s\n' shared-object before-interruption-only-object > "$pgstate/databases/evidence/objects"
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    : > "$pglog"
    set +e
    AI_COACHING_RESTORE_TEST_FAILPOINT=after-marker \
      ${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz \
      >${backupCheckData}/absent-interrupted-restore.log 2>&1
    absent_interrupted_status=$?
    set -e
    test "$absent_interrupted_status" -ne 0
    test -e "$marker"
    absent_recovery=$(cat "$marker")
    grep -Fx absent "$absent_recovery/directories/evidence-worker/original-state"
    grep -Fx ${backupCheckData}/evidence-worker \
      "$absent_recovery/directories/evidence-worker/live-path"
    grep -Fx "$absent_recovery/staged/data/evidence-worker" \
      "$absent_recovery/directories/evidence-worker/staged-path"

    # systemd-tmpfiles runs during boot even though writer startup is blocked.
    mkdir -p ${backupCheckData}/evidence-worker
    printf 'tmpfiles-recreated\n' > ${backupCheckData}/evidence-worker/tmpfiles-state
    : > "$state"
    if FAKE_PG_RESTORE_FAIL=true \
      ${restoreCheckScript}/bin/ai-coaching-restore --resume \
      >${backupCheckData}/absent-resume-failure.log 2>&1; then
      echo "resume ignored the injected PostgreSQL replacement failure" >&2
      exit 1
    fi
    grep -F 'preserving post-marker recreation of evidence-worker' \
      ${backupCheckData}/absent-resume-failure.log
    test -e "$marker"
    test ! -e ${backupCheckData}/evidence-worker
    test "$(grep -c '^START ' "$log" || true)" -eq 0

    # A second boot may recreate the path again before the operator chooses
    # rollback. The durable original-state record must still win.
    mkdir -p ${backupCheckData}/evidence-worker
    printf 'tmpfiles-recreated-again\n' > ${backupCheckData}/evidence-worker/tmpfiles-state
    ${restoreCheckScript}/bin/ai-coaching-restore --rollback
    test ! -e "$marker"
    test ! -e ${backupCheckData}/evidence-worker
    grep -Fx before-interruption-only-object "$pgstate/databases/evidence/objects"
    if grep -Fxq backup-only-object "$pgstate/databases/evidence/objects"; then
      echo "rollback retained a backup-only PostgreSQL object" >&2
      exit 1
    fi
    for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits}; do
      grep -Fx "$unit" "$state"
    done

    # --- Scenario: backup and restore share one exclusive host-level lock;
    # --- contention fails fast (exit 3) before any service is inspected. ---
    lock_path=${backupCheckData}/.ai-coaching-backup-restore.lock
    : > "$log"
    exec {lockfd}<>"$lock_path"
    ${pkgs.util-linux}/bin/flock -n "$lockfd"

    set +e
    lock_out=$(${backupCheckScript}/bin/ai-coaching-backup 2>&1)
    lock_status=$?
    set -e
    echo "$lock_out" | grep -F 'aborting (exit 3)'
    test "$lock_status" -eq 3
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    set +e
    lock_out=$(${restoreCheckScript}/bin/ai-coaching-restore --yes ${backupCheckData}/reference-good.tar.gz 2>&1)
    lock_status=$?
    set -e
    echo "$lock_out" | grep -F 'aborting (exit 3)'
    test "$lock_status" -eq 3
    test "$(grep -c '^STOP ' "$log" || true)" -eq 0

    exec {lockfd}>&-

    rm -rf ${backupCheckData}/backups
    mkdir -p ${backupCheckData}/backups
    printf '%s\n' ${lib.concatMapStringsSep " " lib.escapeShellArg writerUnits} > "$state"
    : > "$log"
    ${backupCheckScript}/bin/ai-coaching-backup
    test -n "$(find ${backupCheckData}/backups -maxdepth 1 -name '*.tar.gz' -print -quit)"

    touch "$out"
  '';

  postgresql-restore-metadata = pkgs.runCommand "ai-coaching-postgresql-restore-metadata" { } ''
    set -euo pipefail

    root=${realPgCheckData}
    pgdata="$root/cluster"
    socket=${realPgSocket}
    database_name=${lib.escapeShellArg realPgDatabaseName}
    app_role=${lib.escapeShellArg realPgUsername}
    admin_role=${lib.escapeShellArg realPgAdminUsername}
    report_role='reporter role "quoted"'
    database_setting="quote ' value = yes; \"still data\""
    marker="$root/.ai-coaching-restore-in-progress"

    rm -rf -- "$root"
    mkdir -p "$root"/{home,media,speakr,evidence-worker} "$socket"
    printf 'real-postgresql-test-password\n' > "$root/pg-password"
    printf 'archive-media\n' > "$root/media/state"
    printf 'archive-speakr\n' > "$root/speakr/state"
    printf 'archive-worker\n' > "$root/evidence-worker/state"
    export HOME="$root/home"

    ${realPgPackage}/bin/initdb \
      --pgdata="$pgdata" \
      --username=postgres \
      --auth=trust \
      --no-locale \
      --encoding=UTF8 \
      >/dev/null
    ${realPgPackage}/bin/pg_ctl \
      --pgdata="$pgdata" \
      --options="-k $socket -p ${toString realPgPort} -c listen_addresses=" \
      --wait \
      start \
      >"$root/postgres.log"
    stop_postgres() {
      ${realPgPackage}/bin/pg_ctl \
        --pgdata="$pgdata" \
        --mode=fast \
        --wait \
        stop \
        >/dev/null
    }
    trap stop_postgres EXIT

    admin_psql() {
      ${realPgPackage}/bin/psql \
        --host="$socket" \
        --port=${toString realPgPort} \
        --username=postgres \
        --no-password \
        --dbname=postgres \
        -v ON_ERROR_STOP=1 \
        "$@"
    }
    app_psql() {
      ${realPgPackage}/bin/psql \
        --host="$socket" \
        --port=${toString realPgPort} \
        --username="$app_role" \
        --no-password \
        --dbname="$database_name" \
        -v ON_ERROR_STOP=1 \
        "$@"
    }
    metadata_snapshot() {
      admin_psql \
        --tuples-only \
        --no-align \
        --set=target_db="$database_name" <<'SQL'
    SELECT line
    FROM (
      SELECT format('owner=%s', pg_get_userbyid(datdba)) AS line
      FROM pg_database
      WHERE datname = :'target_db'
      UNION ALL
      SELECT format('connection-limit=%s', datconnlimit)
      FROM pg_database
      WHERE datname = :'target_db'
      UNION ALL
      SELECT format(
        'acl=%s|%s|%s|grantor=%s',
        CASE
          WHEN acl.grantee = 0 THEN 'PUBLIC'
          ELSE pg_get_userbyid(acl.grantee)
        END,
        acl.privilege_type,
        acl.is_grantable,
        pg_get_userbyid(acl.grantor)
      )
      FROM pg_database AS database
      CROSS JOIN LATERAL aclexplode(database.datacl) AS acl
      WHERE database.datname = :'target_db'
      UNION ALL
      SELECT format(
        'setting=%s|%s',
        CASE
          WHEN setting.setrole = 0 THEN 'DATABASE'
          ELSE pg_get_userbyid(setting.setrole)
        END,
        config
      )
      FROM pg_database AS database
      JOIN pg_db_role_setting AS setting
        ON setting.setdatabase = database.oid
      CROSS JOIN LATERAL unnest(setting.setconfig) AS config
      WHERE database.datname = :'target_db'
    ) AS metadata
    ORDER BY line;
    SQL
    }
    assert_metadata() {
      local actual_metadata
      actual_metadata=$(metadata_snapshot)
      if [ "$actual_metadata" != "$expected_metadata" ]; then
        printf '%s\n' 'expected metadata:' "$expected_metadata" >&2
        printf '%s\n' 'actual metadata:' "$actual_metadata" >&2
        return 1
      fi
    }
    assert_archive_objects() {
      app_psql --tuples-only --no-align <<'SQL' | grep -Fx 't|f|archive'
    SELECT
      to_regclass('public.old_only') IS NOT NULL,
      to_regclass('public.new_only') IS NOT NULL,
      value
    FROM shared_state;
    SQL
    }
    assert_live_objects() {
      app_psql --tuples-only --no-align <<'SQL' | grep -Fx 'f|t|live'
    SELECT
      to_regclass('public.old_only') IS NOT NULL,
      to_regclass('public.new_only') IS NOT NULL,
      value
    FROM shared_state;
    SQL
    }
    make_live_objects() {
      app_psql <<'SQL'
    DROP TABLE old_only;
    CREATE TABLE new_only (id integer PRIMARY KEY);
    INSERT INTO new_only VALUES (2);
    UPDATE shared_state SET value = 'live';
    SQL
    }

    admin_psql \
      --set=app_role="$app_role" \
      --set=admin_role="$admin_role" \
      --set=report_role="$report_role" \
      --set=target_db="$database_name" <<'SQL'
    CREATE ROLE :"app_role" LOGIN;
    CREATE ROLE :"admin_role" LOGIN SUPERUSER CREATEDB;
    CREATE ROLE :"report_role";
    GRANT :"app_role" TO :"admin_role";
    CREATE DATABASE :"target_db" OWNER :"app_role" TEMPLATE template0;
    SQL

    app_psql <<'SQL'
    CREATE TABLE old_only (id integer PRIMARY KEY);
    INSERT INTO old_only VALUES (1);
    CREATE TABLE shared_state (value text NOT NULL);
    INSERT INTO shared_state VALUES ('archive');
    SQL

    admin_psql \
      --set=app_role="$app_role" \
      --set=report_role="$report_role" \
      --set=database_setting="$database_setting" \
      --set=target_db="$database_name" <<'SQL'
    ALTER DATABASE :"target_db" CONNECTION LIMIT 23;
    REVOKE ALL PRIVILEGES ON DATABASE :"target_db" FROM PUBLIC;
    REVOKE ALL PRIVILEGES ON DATABASE :"target_db" FROM :"app_role";
    GRANT CONNECT ON DATABASE :"target_db" TO PUBLIC;
    GRANT CONNECT ON DATABASE :"target_db" TO :"app_role";
    GRANT CONNECT, TEMPORARY ON DATABASE :"target_db"
      TO :"report_role" WITH GRANT OPTION;
    ALTER DATABASE :"target_db"
      SET "ai_coaching.test_setting" TO :'database_setting';
    ALTER ROLE :"report_role" IN DATABASE :"target_db"
      SET search_path TO '"odd schema", public';
    SQL

    expected_metadata=$(metadata_snapshot)
    ${realPgBackupScript}/bin/ai-coaching-backup
    archive=$(find "$root/backups" -maxdepth 1 -name '*.tar.gz' -print -quit)
    test -n "$archive"

    make_live_objects
    ${realPgRestoreScript}/bin/ai-coaching-restore --yes "$archive"
    assert_archive_objects
    assert_metadata
    test ! -e "$marker"

    make_live_objects
    if AI_COACHING_RESTORE_TEST_FAILPOINT=after-database-swap \
      ${realPgRestoreScript}/bin/ai-coaching-restore --yes "$archive" \
      >"$root/swap-failure.log" 2>&1; then
      echo "real PostgreSQL restore ignored the post-swap failure injection" >&2
      exit 1
    fi
    grep -F 'injected failure after PostgreSQL database swap' "$root/swap-failure.log"
    grep -F 'persistent fail-stop marker' "$root/swap-failure.log"
    test -e "$marker"
    assert_archive_objects
    assert_metadata

    ${realPgRestoreScript}/bin/ai-coaching-restore --rollback
    test ! -e "$marker"
    assert_live_objects
    assert_metadata

    admin_psql --set=admin_role="$admin_role" <<'SQL'
    ALTER ROLE :"admin_role" NOSUPERUSER;
    SQL
    if ${realPgRestoreScript}/bin/ai-coaching-restore --yes "$archive" \
      >"$root/metadata-sql-failure.log" 2>&1; then
      echo "real PostgreSQL restore ignored a metadata SQL error" >&2
      exit 1
    fi
    grep -F 'failed to extract or apply PostgreSQL database metadata' \
      "$root/metadata-sql-failure.log"
    grep -F 'persistent fail-stop marker' "$root/metadata-sql-failure.log"
    test -e "$marker"
    assert_live_objects

    admin_psql --set=admin_role="$admin_role" <<'SQL'
    ALTER ROLE :"admin_role" SUPERUSER;
    SQL
    ${realPgRestoreScript}/bin/ai-coaching-restore --rollback
    test ! -e "$marker"
    assert_live_objects
    assert_metadata

    stop_postgres
    trap - EXIT
    touch "$out"
  '';

  proxy-prefix-contract = pkgs.runCommand "ai-coaching-proxy-prefix-contract" { } ''
    set -euo pipefail
    mkdir work
    cd work
    cat > Caddyfile <<'EOF'
    {
      admin off
      auto_https off
    }
    http://127.0.0.1:19080 {
      ${contractCaddyConfig}
    }
    EOF
    export CADDY_BIN=${pkgs.caddy}/bin/caddy
    export CADDY_PORT=19080
    export AUTH_PORT=19081
    export BACKEND_PORT=19082
    export AI_COACHING_PROXY_AUTH_SECRET=0123456789abcdef0123456789abcdef
    ${pkgs.python3}/bin/python ${./proxy-contract-test.py}
    touch "$out"
  '';

  api-auth-contract = pkgs.runCommand "ai-coaching-api-auth-contract" { } ''
    set -euo pipefail
    mkdir work
    cd work
    export AI_COACHING_PROXY_AUTH_SECRET=0123456789abcdef0123456789abcdef
    export AI_COACHING_GATEWAY_LISTEN_ADDRESS=127.0.0.1:19100
    export AI_COACHING_GATEWAY_BACKEND_ADDRESS=127.0.0.1:19101
    export EVIDENCE_ENVIRONMENT=test
    export EVIDENCE_AUTH_MODE=trusted_proxy
    export EVIDENCE_DATABASE_URL=sqlite:///$PWD/evidence.db
    export EVIDENCE_MEDIA_ROOT=$PWD/media
    mkdir media

    ${artifacts.proxyGateway}/bin/ai-coaching-proxy-gateway >gateway.log 2>&1 &
    gateway_pid=$!
    cleanup() {
      kill "$gateway_pid" 2>/dev/null || true
      wait "$gateway_pid" 2>/dev/null || true
    }
    trap cleanup EXIT

    for _ in $(seq 1 100); do
      if ${pkgs.curl}/bin/curl -fsS \
        -H 'X-AI-Coaching-Proxy-Auth: 0123456789abcdef0123456789abcdef' \
        -H 'X-Auth-Request-Email: reviewer@example.invalid' \
        -H 'X-Auth-Request-Groups: evidence-editors' \
        http://127.0.0.1:19100/api/sessions >sessions.json; then
        break
      fi
      if ! kill -0 "$gateway_pid" 2>/dev/null; then
        cat gateway.log >&2
        exit 1
      fi
      sleep 0.1
    done
    test -s sessions.json
    grep -Fx '[]' sessions.json

    status=$(
      ${pkgs.curl}/bin/curl -sS -o created.json -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -H 'X-AI-Coaching-Proxy-Auth: 0123456789abcdef0123456789abcdef' \
        -H 'X-Auth-Request-Email: reviewer@example.invalid' \
        -H 'X-Auth-Request-Groups: evidence-editors' \
        --data '{"title":"Proxy contract"}' \
        http://127.0.0.1:19100/api/sessions
    )
    test "$status" = 201
    grep -F '"title":"Proxy contract"' created.json

    status=$(
      ${pkgs.curl}/bin/curl -sS -o missing-secret.json -w '%{http_code}' \
        -H 'X-Auth-Request-Email: forged@example.invalid' \
        -H 'X-Auth-Request-Groups: evidence-admins' \
        http://127.0.0.1:19100/api/sessions
    )
    test "$status" = 401

    status=$(
      ${pkgs.curl}/bin/curl -sS -o direct-backend.json -w '%{http_code}' \
        -H 'X-Auth-Request-Email: forged@example.invalid' \
        -H 'X-Auth-Request-Groups: evidence-admins' \
        http://127.0.0.1:19101/api/sessions
    )
    test "$status" = 401

    touch "$out"
  '';

  retention-path-safety = pkgs.runCommand "ai-coaching-retention-path-safety" { } ''
    set -euo pipefail
    rm -rf -- ${retentionCheckData}
    mkdir -p ${retentionCheckData}/media/session ${retentionCheckData}/outside
    : > ${retentionCheckData}/deletion-audit.log
    printf 'keep\n' > ${retentionCheckData}/outside/keep.wav
    printf 'delete\n' > ${retentionCheckData}/media/session/delete.wav
    ln -s ${retentionCheckData}/outside/keep.wav ${retentionCheckData}/media/escape.wav

    if ${retentionCheckScripts.deleteScript}/bin/ai-coaching-delete-recording --yes ../outside/keep.wav; then
      echo "parent traversal was accepted" >&2
      exit 1
    fi
    if ${retentionCheckScripts.deleteScript}/bin/ai-coaching-delete-recording --yes ${retentionCheckData}/outside/keep.wav; then
      echo "absolute path was accepted" >&2
      exit 1
    fi
    if ${retentionCheckScripts.deleteScript}/bin/ai-coaching-delete-recording --yes escape.wav; then
      echo "symlink escape was accepted" >&2
      exit 1
    fi
    grep -Fx 'keep' ${retentionCheckData}/outside/keep.wav

    ${retentionCheckScripts.deleteScript}/bin/ai-coaching-delete-recording --yes session/delete.wav
    test ! -e ${retentionCheckData}/media/session/delete.wav
    find ${retentionCheckData}/media/.quarantine -type f -name delete.wav | grep -q .
    mkdir -p ${retentionCheckData}/media/.quarantine/.hidden
    printf 'purge\n' | ${retentionCheckScripts.purgeScript}/bin/ai-coaching-purge-quarantine
    test -z "$(find ${retentionCheckData}/media/.quarantine -mindepth 1 -print -quit)"
    grep -F 'DELETE_REQUESTED' ${retentionCheckData}/deletion-audit.log
    grep -F 'DELETE_PURGED' ${retentionCheckData}/deletion-audit.log

    RETENTION_HELPER_SOURCE=${./retention-helper.py} \
      ${pkgs.python3}/bin/python ${./retention-helper_test.py}

    touch "$out"
  '';

  image-pin-assertions =
    assert !badRegistryPin.success;
    assert imgLib.isDigestPinned
      "registry.example/app@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    assert !imgLib.isDigestPinned "registry.example/app:latest";
    assert !imgLib.isDigestPinned "registry.example/app@sha256:1234";
    assert
      !imgLib.isDigestPinned "registry.example/app@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef-extra";
    assert
      deployConfig.services.aiCoaching.speakr.image
      == "docker.io/learnedmachine/speakr@sha256:425a39e101ee69abe67e86ad53fec0b4ef7b13caed2ab30f388022beca8fdaf6";
    pkgs.runCommand "ai-coaching-image-pin-assertions" { } ''
      touch "$out"
    '';
}

# Containerized components: Speakr (pinned, unmodified upstream), and the
# first-party evidence API/worker + optional containerized web frontend. The
# API image includes a credential-checking gateway in front of loopback-only
# Uvicorn so peer containers cannot submit forged proxy identity headers.
# All containers join a single private Podman network and are never bound
# to a public interface; only Caddy (via oauth2-proxy) is internet-facing.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.aiCoaching;
  imgLib = import ./lib.nix { inherit lib; };
  inherit (imgLib) mkImageOption mkImageFileOption imageAssertions;
  speakrImage = "docker.io/learnedmachine/speakr@sha256:425a39e101ee69abe67e86ad53fec0b4ef7b13caed2ab30f388022beca8fdaf6";

  networkServiceName = "podman-network-${cfg.network.name}";
  networkServiceUnit = "${networkServiceName}.service";
  restoreMarker = "${cfg.dataDir}/.ai-coaching-restore-in-progress";
  sharedMediaPath = "/data/media";
  evidenceEnvironment = {
    EVIDENCE_ENVIRONMENT = if cfg.devAuth.enable then "development" else "production";
    EVIDENCE_AUTH_MODE = if cfg.devAuth.enable then "development" else "trusted_proxy";
    EVIDENCE_TRUSTED_EMAIL_HEADER = "x-auth-request-email";
    EVIDENCE_TRUSTED_GROUPS_HEADER = "x-auth-request-groups";
    EVIDENCE_TRUSTED_PROXY_NETWORKS = "127.0.0.1/32,::1/128";
    EVIDENCE_ADMIN_GROUPS = lib.concatStringsSep "," cfg.oidc.adminGroups;
    EVIDENCE_EDITOR_GROUPS = lib.concatStringsSep "," cfg.oidc.editorGroups;
    EVIDENCE_MEDIA_ROOT = sharedMediaPath;
  }
  // lib.optionalAttrs cfg.speakr.enable {
    EVIDENCE_SPEAKR_BASE_URL = "http://speakr:${toString cfg.speakr.containerPort}";
  };
  extractionWorkerEnvironment = lib.optionalAttrs cfg.extractionGateway.enable {
    EVIDENCE_EXTRACTION_PROVIDER = "http_json";
    EVIDENCE_EXTRACTION_ENDPOINT = "http://extraction-gateway:${toString cfg.extractionGateway.containerPort}/";
  };
  apiEnvironment = evidenceEnvironment // {
    AI_COACHING_GATEWAY_LISTEN_ADDRESS = "0.0.0.0:${toString cfg.evidenceApi.containerPort}";
    AI_COACHING_GATEWAY_BACKEND_ADDRESS = "127.0.0.1:18000";
    FORWARDED_ALLOW_IPS = "";
  };

  # Common hardening/health defaults applied to every container-backed
  # systemd unit this module generates. `Restart` must use `mkForce` because
  # `virtualisation.oci-containers` sets it directly (not via `mkDefault`).
  commonServiceOverrides = {
    unitConfig.ConditionPathExists = "!${restoreMarker}";
    serviceConfig = {
      Restart = lib.mkForce "on-failure";
      RestartSec = 5;
      StartLimitIntervalSec = 60;
      StartLimitBurst = 5;
    };
    after = [ networkServiceUnit ];
    requires = [ networkServiceUnit ];
  };

  # Private bridge network shared by all containers, used for east-west
  # traffic between them (e.g. evidence-worker <-> evidence-api). This is a
  # normal (non-"--internal") Podman network so containers retain outbound
  # egress to cloud ASR/AI providers; ingress from the host is still
  # restricted because no container publishes a port to a public interface
  # (see the loopback-only `ports` bindings below) and nothing outside the
  # host can reach the bridge at all.
  networkServiceDefinition = {
    description = "Create the private ai-coaching Podman network";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    path = [ pkgs.podman ];
    serviceConfig.Type = "oneshot";
    serviceConfig.RemainAfterExit = true;
    script = ''
      set -euo pipefail
      if ! podman network exists ${lib.escapeShellArg cfg.network.name}; then
        podman network create \
          ${
            lib.optionalString (cfg.network.subnet != null) "--subnet=${lib.escapeShellArg cfg.network.subnet}"
          } \
          ${lib.escapeShellArg cfg.network.name}
      fi
    '';
    preStop = ''
      ${pkgs.podman}/bin/podman network rm --ignore ${lib.escapeShellArg cfg.network.name} || true
    '';
  };
in
{
  options.services.aiCoaching = {
    speakr = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Run the pinned, unmodified Speakr container as the media/transcription provider.";
      };

      image = lib.mkOption {
        type = lib.types.str;
        # murtaza-nasir/speakr v0.10.2-alpha, digest-pinned per Fact Checker
        # verification. Never change this to a tag (":latest" or otherwise)
        # -- resolve any upgrade to a new digest and update this default (or
        # the caller's override) deliberately. See deploy/OPERATIONS.md
        # "Upgrade".
        default = speakrImage;
        readOnly = true;
        description = ''
          Digest-pinned Speakr image reference. Defaults to the verified
          v0.10.2-alpha build. Do not point this at a tag.
        '';
      };

      containerPort = lib.mkOption {
        type = lib.types.port;
        default = 8899;
        description = ''
          Port Speakr listens on inside the container. NOTE: this default
          is the commonly documented Speakr port but has not been
          independently re-verified against the pinned digest by this
          module -- confirm against the running container (`podman exec
          speakr env` / upstream docs) before relying on it, and report
          back if it differs so this default can be corrected.
        '';
      };

      hostPort = lib.mkOption {
        type = lib.types.port;
        default = 8899;
        description = ''
          Port published on loopback (127.0.0.1) for Caddy/oauth2-proxy to
          reach Speakr. Never bound to a public interface.
        '';
      };

      environmentFiles = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [ "${cfg.secretsDir}/speakr.env" ];
        description = ''
          Env files (outside the Nix store) holding Speakr's auth token and
          any cloud ASR/AI provider credentials, in the `KEY=value` format
          Podman's `--env-file` expects. The operator populates these
          out-of-band; see deploy/OPERATIONS.md "Secrets". Exact variable
          names must match Speakr's own documented configuration -- verify
          against the pinned image before deploying.
        '';
      };

      extraEnvironment = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
        description = "Additional non-secret environment variables passed to the Speakr container.";
      };
    };

    evidenceApi = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Run the first-party evidence API service.";
      };

      image = mkImageOption {
        description = "Evidence API image. Use the flake's evidence-api-image package locally or a pinned registry digest.";
      };
      imageFile = mkImageFileOption "Locally built evidence API image tarball.";

      containerPort = lib.mkOption {
        type = lib.types.port;
        default = 8000;
        description = "Port the evidence API listens on inside its container.";
      };

      hostPort = lib.mkOption {
        type = lib.types.port;
        default = 8000;
        description = ''
          Port published on loopback (127.0.0.1) for Caddy/oauth2-proxy to
          reach the evidence API. Never bound to a public interface.
        '';
      };

      environmentFiles = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [ "${cfg.secretsDir}/evidence-api.env" ];
        description = ''
          Env files with the evidence API's database DSN, Speakr token,
          webhook secret, provider credentials, and signing keys. The module
          automatically appends proxyAuth.environmentFile for the gateway.
        '';
      };

      extraEnvironment = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
        description = "Additional non-secret environment variables passed to the evidence API container.";
      };
    };

    evidenceWorker = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Run the first-party evidence extraction worker.";
      };

      image = mkImageOption {
        description = "Evidence worker image. Use the flake's evidence-worker-image package locally or a pinned registry digest.";
      };
      imageFile = mkImageFileOption "Locally built evidence worker image tarball.";

      environmentFiles = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [ "${cfg.secretsDir}/evidence-worker.env" ];
        description = "Env files with the worker's database DSN, queue settings, and AI/ASR provider credentials.";
      };

      extraEnvironment = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
        description = "Additional non-secret environment variables passed to the evidence worker container.";
      };
    };

    extractionGateway = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Run the OpenAI-backed structured extraction gateway used by the evidence worker's http_json provider.";
      };

      image = mkImageOption {
        description = "Extraction gateway image. Use the flake's extraction-gateway-image package locally or a pinned registry digest.";
      };
      imageFile = mkImageFileOption "Locally built extraction gateway image tarball.";

      containerPort = lib.mkOption {
        type = lib.types.port;
        default = 8080;
        description = "Port the extraction gateway listens on inside its container.";
      };

      environmentFiles = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [ "${cfg.secretsDir}/extraction-gateway.env" ];
        description = ''
          Env files with `EXTRACTION_GATEWAY_OPENAI_API_KEY` and
          `EXTRACTION_GATEWAY_INBOUND_API_KEY`. The inbound key must match
          the worker's `EVIDENCE_EXTRACTION_API_KEY`.
        '';
      };

      extraEnvironment = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
        description = "Additional non-secret environment variables passed to the extraction gateway container.";
      };
    };

    webFrontend = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Serve the project-owned web UI.";
      };

      mode = lib.mkOption {
        type = lib.types.enum [
          "staticRoot"
          "container"
        ];
        default = "staticRoot";
        description = ''
          `staticRoot`: serve a pre-built static SPA directly from Caddy
          (no container) -- appropriate if the web UI is a static bundle,
          which is the current assumption for apps/web. `container`: run a
          containerized frontend service instead (e.g. if it needs
          server-side rendering or its own runtime). Confirm the correct
          mode with Trinity/Morpheus before relying on the default.
        '';
      };

      staticRoot = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Path to the built static frontend (e.g. a Nix package output).
          Required when `mode = "staticRoot"`. There is no floating default
          (such as fetching from the network at activation time); the
          build artifact must be produced by the flake/CI and passed in
          explicitly.
        '';
      };

      image = mkImageOption {
        description = "Web frontend container image, used when `mode = \"container\"`.";
      };
      imageFile = mkImageFileOption "Locally built web frontend image tarball, used when `mode = \"container\"`.";

      containerPort = lib.mkOption {
        type = lib.types.port;
        default = 3000;
        description = "Port the containerized web frontend listens on, used when `mode = \"container\"`.";
      };

      hostPort = lib.mkOption {
        type = lib.types.port;
        default = 3000;
        description = ''
          Port published on loopback (127.0.0.1) for Caddy/oauth2-proxy to
          reach the containerized web frontend. Never bound to a public
          interface. Used when `mode = "container"`.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions =
      (imageAssertions {
        componentPath = "services.aiCoaching.evidenceApi";
        enable = cfg.evidenceApi.enable;
        image = cfg.evidenceApi.image;
        imageFile = cfg.evidenceApi.imageFile;
      })
      ++ (imageAssertions {
        componentPath = "services.aiCoaching.evidenceWorker";
        enable = cfg.evidenceWorker.enable;
        image = cfg.evidenceWorker.image;
        imageFile = cfg.evidenceWorker.imageFile;
      })
      ++ (imageAssertions {
        componentPath = "services.aiCoaching.extractionGateway";
        enable = cfg.extractionGateway.enable;
        image = cfg.extractionGateway.image;
        imageFile = cfg.extractionGateway.imageFile;
      })
      ++ (imageAssertions {
        componentPath = "services.aiCoaching.webFrontend";
        enable = cfg.webFrontend.enable && cfg.webFrontend.mode == "container";
        image = cfg.webFrontend.image;
        imageFile = cfg.webFrontend.imageFile;
      })
      ++ [
        {
          assertion = cfg.speakr.image == speakrImage;
          message = "services.aiCoaching.speakr.image is fixed to the reviewed learnedmachine/speakr digest and cannot be changed by this module revision.";
        }
        {
          assertion = cfg.webFrontend.mode != "staticRoot" || cfg.webFrontend.staticRoot != null;
          message = "services.aiCoaching.webFrontend.mode is \"staticRoot\" but webFrontend.staticRoot is not set. Point it at the built static frontend output.";
        }
      ];

    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir}/speakr 0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.dataDir}/media 0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.dataDir}/evidence-worker 0750 ${cfg.user} ${cfg.group} - -"
    ];

    virtualisation.oci-containers.containers = lib.mkMerge [
      (lib.mkIf cfg.speakr.enable {
        speakr = {
          image = cfg.speakr.image;
          networks = [ cfg.network.name ];
          hostname = "speakr";
          environmentFiles = cfg.speakr.environmentFiles;
          environment = cfg.speakr.extraEnvironment;
          volumes = [ "${cfg.dataDir}/speakr:/data" ];
          ports = [ "127.0.0.1:${toString cfg.speakr.hostPort}:${toString cfg.speakr.containerPort}" ];
          pull = "missing";
        };
      })

      (lib.mkIf cfg.evidenceApi.enable {
        evidence-api = {
          image = cfg.evidenceApi.image;
          imageFile = cfg.evidenceApi.imageFile;
          networks = [ cfg.network.name ];
          hostname = "evidence-api";
          environmentFiles = cfg.evidenceApi.environmentFiles ++ [ cfg.proxyAuth.environmentFile ];
          environment = cfg.evidenceApi.extraEnvironment // apiEnvironment;
          volumes = [ "${cfg.dataDir}/media:${sharedMediaPath}:rw" ];
          ports = [
            "127.0.0.1:${toString cfg.evidenceApi.hostPort}:${toString cfg.evidenceApi.containerPort}"
          ];
          pull = "missing";
        };
      })

      (lib.mkIf cfg.evidenceWorker.enable {
        evidence-worker = {
          image = cfg.evidenceWorker.image;
          imageFile = cfg.evidenceWorker.imageFile;
          networks = [ cfg.network.name ];
          hostname = "evidence-worker";
          environmentFiles = cfg.evidenceWorker.environmentFiles;
          environment = cfg.evidenceWorker.extraEnvironment // evidenceEnvironment // extractionWorkerEnvironment;
          volumes = [
            "${cfg.dataDir}/media:${sharedMediaPath}:rw"
            "${cfg.dataDir}/evidence-worker:/data/worker:rw"
          ];
          dependsOn =
            (lib.optional cfg.evidenceApi.enable "evidence-api")
            ++ (lib.optional cfg.extractionGateway.enable "extraction-gateway");
          # No published ports: the worker is a background job consumer
          # only, reachable by nothing but other containers on the private
          # network (and nothing needs to reach it).
          pull = "missing";
        };
      })

      (lib.mkIf cfg.extractionGateway.enable {
        extraction-gateway = {
          image = cfg.extractionGateway.image;
          imageFile = cfg.extractionGateway.imageFile;
          networks = [ cfg.network.name ];
          hostname = "extraction-gateway";
          environmentFiles = cfg.extractionGateway.environmentFiles;
          environment = cfg.extractionGateway.extraEnvironment;
          # No published ports: only the evidence worker calls this service
          # over the private Podman network.
          pull = "missing";
        };
      })

      (lib.mkIf (cfg.webFrontend.enable && cfg.webFrontend.mode == "container") {
        web-frontend = {
          image = cfg.webFrontend.image;
          imageFile = cfg.webFrontend.imageFile;
          networks = [ cfg.network.name ];
          hostname = "web-frontend";
          ports = [
            "127.0.0.1:${toString cfg.webFrontend.hostPort}:${toString cfg.webFrontend.containerPort}"
          ];
          pull = "missing";
        };
      })
    ];

    systemd.services = lib.mkMerge [
      { ${networkServiceName} = networkServiceDefinition; }
      (lib.mkIf cfg.speakr.enable { podman-speakr = commonServiceOverrides; })
      (lib.mkIf cfg.evidenceApi.enable {
        podman-evidence-api = lib.mkMerge [
          commonServiceOverrides
          {
            # Only depend on the local password-provisioning unit when this
            # module manages PostgreSQL itself; in external-PostgreSQL mode
            # that unit does not exist, and a `Requires=` on a missing unit
            # would fail the container's start.
            after = lib.optional cfg.postgresql.enable "ai-coaching-postgresql-password.service";
          }
        ];
      })
      (lib.mkIf cfg.evidenceWorker.enable {
        podman-evidence-worker = lib.mkMerge [
          commonServiceOverrides
          {
            after = lib.optional cfg.postgresql.enable "ai-coaching-postgresql-password.service";
          }
        ];
      })
      (lib.mkIf cfg.extractionGateway.enable {
        podman-extraction-gateway = commonServiceOverrides;
      })
      (lib.mkIf (cfg.webFrontend.enable && cfg.webFrontend.mode == "container") {
        podman-web-frontend = commonServiceOverrides;
      })
    ];
  };
}

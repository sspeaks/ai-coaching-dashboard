# services.aiCoaching -- top-level module.
#
# This file declares the shared/top-level options (enable, domain, storage
# roots, network, host user/group) and pulls in the per-concern modules.
# Component-specific options (postgresql, speakr, evidenceApi, ...) live in
# the imported files so each concern stays reviewable on its own.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.aiCoaching;
in
{
  imports = [
    ./postgresql.nix
    ./containers.nix
    ./proxy.nix
    ./backup.nix
    ./retention.nix
  ];

  options.services.aiCoaching = {
    enable = lib.mkEnableOption "the AI coaching dashboard platform (Speakr + evidence API/worker + web UI behind Caddy/oauth2-proxy)";

    domain = lib.mkOption {
      type = lib.types.str;
      example = "coaching.example.org";
      description = ''
        Fully-qualified domain name Caddy serves as its virtual host. Used
        for TLS/automatic HTTPS and, when `oidc.enable` is true, the OIDC
        redirect URL. Always required; use "localhost" for a
        `devAuth`-only local deployment.
      '';
    };

    bindAddress = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = ''
        Interface Caddy listens on for public HTTP(S) traffic. Every other
        component (Speakr, evidence API/worker, web frontend, PostgreSQL,
        oauth2-proxy) binds only to loopback or the private container
        network and is never reachable directly from outside the host.
      '';
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/ai-coaching";
      description = ''
        Root of all persistent state owned by this module: recordings,
        transcripts, application data volumes, and backups. Nothing under
        this directory is managed by (or lives in) the Nix store; it must
        survive `nixos-rebuild switch`, reboots, and container image
        upgrades untouched.
      '';
    };

    secretsDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/ai-coaching/secrets";
      description = ''
        Directory the operator populates out-of-band (e.g. via `scp`,
        agenix, sops-nix, or a configuration-management run) with
        root-only-readable (mode 0400) credential/env files referenced by
        this module's `*EnvironmentFile`/`*File` options: the Speakr auth
        token, AI/ASR provider API keys, the Caddy-to-API proxy credential,
        the OIDC client secret, the oauth2-proxy cookie secret, and the
        PostgreSQL passwords used by the containerized services.

        This module never writes secret *contents* here and never embeds
        secret material in any option default or in the Nix store -- only
        paths are referenced. See deploy/OPERATIONS.md "Secrets" section.
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "ai-coaching";
      description = "System user that owns persistent data directories under `dataDir`.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "ai-coaching";
      description = "System group that owns persistent data directories under `dataDir`.";
    };

    network = {
      name = lib.mkOption {
        type = lib.types.strMatching "[A-Za-z0-9][A-Za-z0-9_.-]*";
        default = "ai-coaching";
        description = "Name of the private (internal) Podman network shared by the containerized components.";
      };

      subnet = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "10.89.1.0/24";
        description = ''
          Optional explicit subnet for the private container network. Leave
          null to let Podman pick a free range automatically.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.domain != "" && cfg.domain != null;
        message = "services.aiCoaching.domain must be set (used for the Caddy virtual host and, in production, the OIDC redirect URL). Use \"localhost\" for a devAuth-only local deployment.";
      }
    ];

    users.groups.${cfg.group} = { };
    users.users.${cfg.user} = {
      isSystemUser = true;
      inherit (cfg) group;
      description = "AI coaching dashboard platform (owns persistent data under ${cfg.dataDir})";
    };

    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.secretsDir} 0750 root root - -"
    ];

    # Podman is the OCI backend for all containerized components.
    virtualisation.podman.enable = true;
    virtualisation.oci-containers.backend = "podman";

    environment.systemPackages = [ pkgs.podman ];
  };
}

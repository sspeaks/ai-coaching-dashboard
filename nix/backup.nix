# Backup timer/service and manual restore tooling. Speakr, API, and worker are
# quiesced and verified inactive before persistent files or PostgreSQL are
# captured/restored, then exactly the previously active writers are restarted.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.aiCoaching;
  inherit (cfg) backup;
  pg = cfg.postgresql;
  backupPg = pg // {
    host = if pg.enable then "127.0.0.1" else pg.host;
    adminCommandPrefix = [
      "${pkgs.util-linux}/bin/runuser"
      "--user=postgres"
      "--"
    ];
    adminHost = "/run/postgresql";
    adminUsername = "postgres";
    adminDatabase = "postgres";
  };
  scripts = import ./backup-scripts.nix { inherit lib pkgs; };
  writerServiceUnits =
    lib.optional cfg.speakr.enable "podman-speakr.service"
    ++ lib.optional cfg.evidenceApi.enable "podman-evidence-api.service"
    ++ lib.optional cfg.evidenceWorker.enable "podman-evidence-worker.service";

  backupScript = scripts.mkBackupScript {
    inherit (cfg) dataDir;
    inherit (backup) targetDir retainCount;
    pg = backupPg;
    serviceUnits = writerServiceUnits;
  };

  restoreScript = scripts.mkRestoreScript {
    inherit (cfg) dataDir;
    pg = backupPg;
    serviceUnits = writerServiceUnits;
  };
in
{
  options.services.aiCoaching.backup = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Run a nightly backup of original media, service data, and the evidence database.";
    };

    onCalendar = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 03:30:00";
      description = "systemd OnCalendar expression for the backup timer.";
    };

    targetDir = lib.mkOption {
      type = lib.types.path;
      default = "${cfg.dataDir}/backups";
      description = ''
        Directory backup archives are written to. Replicate it to off-host
        storage separately; this module guarantees local archives, not an
        independent failure domain.
      '';
    };

    retainCount = lib.mkOption {
      type = lib.types.ints.positive;
      default = 14;
      description = "Number of most recent backup archives to retain locally.";
    };
  };

  config = lib.mkIf (cfg.enable && backup.enable) {
    assertions = [
      {
        assertion = backup.targetDir != cfg.dataDir;
        message = "services.aiCoaching.backup.targetDir must not equal dataDir.";
      }
    ];

    systemd = {
      tmpfiles.rules = [
        "d ${backup.targetDir} 0750 ${cfg.user} ${cfg.group} - -"
      ];

      services.ai-coaching-backup = {
        description = "Back up ai-coaching original media, service data, and database";
        serviceConfig = {
          Type = "oneshot";
        }
        // lib.optionalAttrs pg.enable {
          LoadCredential = "db-password:${pg.passwordFile}";
        };
        script = "${backupScript}/bin/ai-coaching-backup";
      };

      timers.ai-coaching-backup = {
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnCalendar = backup.onCalendar;
          Persistent = true;
          RandomizedDelaySec = 300;
        };
      };
    };

    environment.systemPackages = [
      backupScript
      restoreScript
    ];
  };
}

# Manual retention tooling for the authoritative original-media store.
# Deletion is explicit and two-stage. A descriptor-relative helper refuses
# symlinks/traversal and keeps validation, rename, and purge beneath already
# opened directory descriptors so path replacement cannot redirect root.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.aiCoaching;
  quarantineDir = "${cfg.dataDir}/media/.quarantine";
  auditLog = "${cfg.dataDir}/deletion-audit.log";
  scripts = (import ./retention-scripts.nix { inherit pkgs; }).mkRetentionScripts {
    inherit (cfg) dataDir;
  };
in
{
  options.services.aiCoaching.retention.autoDeleteEnable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    readOnly = true;
    description = ''
      Locked to false. Original media is retained until an operator runs
      ai-coaching-delete-recording and separately confirms
      ai-coaching-purge-quarantine.
    '';
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      scripts.deleteScript
      scripts.purgeScript
    ];

    systemd.tmpfiles.rules = [
      "f ${auditLog} 0640 root ${cfg.group} - -"
      "d ${quarantineDir} 0750 ${cfg.user} ${cfg.group} - -"
    ];
  };
}

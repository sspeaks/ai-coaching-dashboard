{ pkgs }:
{
  mkRetentionScripts =
    { dataDir }:
    let
      helper = pkgs.writeTextFile {
        name = "ai-coaching-retention-helper";
        destination = "/bin/ai-coaching-retention-helper";
        executable = true;
        text = ''
          #!${pkgs.python3}/bin/python3
          ${builtins.readFile ./retention-helper.py}
        '';
      };

      deleteScript = pkgs.writeShellApplication {
        name = "ai-coaching-delete-recording";
        runtimeInputs = [ helper ];
        text = ''
          set -euo pipefail
          if [ "$#" -ne 2 ] || [ "$1" != "--yes" ]; then
            echo "usage: ai-coaching-delete-recording --yes <relative-path-under-${dataDir}/media>" >&2
            echo "  Moves the item to ${dataDir}/media/.quarantine; permanent erasure" >&2
            echo "  requires a separate ai-coaching-purge-quarantine invocation." >&2
            exit 1
          fi

          destination=$(
            ai-coaching-retention-helper \
              --data-root ${pkgs.lib.escapeShellArg dataDir} \
              quarantine "$2"
          )
          echo "moved to quarantine: ${dataDir}/media/$destination"
          echo "run ai-coaching-purge-quarantine to permanently erase quarantined items."
        '';
      };

      purgeScript = pkgs.writeShellApplication {
        name = "ai-coaching-purge-quarantine";
        runtimeInputs = [ helper ];
        text = ''
          set -euo pipefail
          mapfile -t entries < <(
            ai-coaching-retention-helper \
              --data-root ${pkgs.lib.escapeShellArg dataDir} \
              list
          )
          if [ "''${#entries[@]}" -eq 0 ]; then
            echo "quarantine is empty: nothing to purge"
            exit 0
          fi

          echo "The following quarantined items will be PERMANENTLY erased:"
          printf '%s\n' "''${entries[@]}"
          read -r -p "Type 'purge' to continue: " confirm
          if [ "$confirm" != "purge" ]; then
            echo "aborted"
            exit 1
          fi

          ai-coaching-retention-helper \
            --data-root ${pkgs.lib.escapeShellArg dataDir} \
            purge >/dev/null
          echo "quarantine purged."
        '';
      };
    in
    {
      inherit deleteScript helper purgeScript;
    };
}

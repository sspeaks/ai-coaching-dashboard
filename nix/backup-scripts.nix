{
  lib,
  pkgs,
}:
let
  # Backup and restore share one exclusive, non-blocking host-level lock so
  # they can never inspect or mutate writer/service state concurrently. Lock
  # contention fails immediately with exit code 3; it never blocks silently.
  lockSetup =
    { flockBin }:
    ''
      mkdir -p "$data_dir"
      lock_file="$data_dir/.ai-coaching-backup-restore.lock"
      exec 9>"$lock_file"
      if ! ${lib.escapeShellArg flockBin} -n 9; then
        echo "[ai-coaching] another ai-coaching backup or restore operation holds $lock_file; aborting (exit 3)" >&2
        exit 3
      fi
    '';

  restoreMarkerGuard = ''
    restore_marker="$data_dir/.ai-coaching-restore-in-progress"
    if [ -e "$restore_marker" ]; then
      echo "[ai-coaching] restore recovery marker exists at $restore_marker; refusing to continue" >&2
      echo "[ai-coaching] run 'ai-coaching-restore --resume' or 'ai-coaching-restore --rollback' first" >&2
      exit 4
    fi
  '';

  serviceLifecycle =
    {
      manageServices,
      serviceUnits,
      systemctlBin,
    }:
    if !manageServices then
      ''
        declare -a active_units=()
        services_need_restart=false
        : "''${active_units[*]-}" "$services_need_restart"

        quiesce_services() {
          return 0
        }
        ensure_services_inactive() {
          return 0
        }
        restart_services() {
          return 0
        }
      ''
    else
      ''
        declare -a active_units=()
        services_need_restart=false

        read_unit_state() {
          local unit="$1"
          local status
          local result
          if result=$(${lib.escapeShellArg systemctlBin} is-active "$unit" 2>/dev/null); then
            status=0
          else
            status=$?
          fi
          unit_state="$result"
          case "$status:$unit_state" in
            0:active|0:activating|0:reloading)
              return 0
              ;;
            3:inactive|3:failed)
              return 1
              ;;
            *)
              echo "[ai-coaching] cannot determine safe state for $unit (status=$status state=$unit_state)" >&2
              return 2
              ;;
          esac
        }

        quiesce_services() {
          local unit
          local state_result
          for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg serviceUnits}; do
            if read_unit_state "$unit"; then
              active_units+=("$unit")
            else
              state_result=$?
              if [ "$state_result" -ne 1 ]; then
                return 1
              fi
            fi
          done

          if [ "''${#active_units[@]}" -eq 0 ]; then
            echo "[ai-coaching] no active writer services require quiescing"
            return 0
          fi

          services_need_restart=true
          echo "[ai-coaching] stopping writer services: ''${active_units[*]}"
          ${lib.escapeShellArg systemctlBin} stop "''${active_units[@]}"
          for unit in "''${active_units[@]}"; do
            if read_unit_state "$unit"; then
              echo "[ai-coaching] writer service remained active after stop: $unit" >&2
              return 1
            else
              state_result=$?
              if [ "$state_result" -ne 1 ]; then
                return 1
              fi
            fi
          done
          echo "[ai-coaching] all writer services are inactive"
        }

        ensure_services_inactive() {
          local unit
          local state_result
          for unit in ${lib.concatMapStringsSep " " lib.escapeShellArg serviceUnits}; do
            if read_unit_state "$unit"; then
              echo "[ai-coaching] writer service must remain stopped during restore recovery: $unit" >&2
              return 1
            else
              state_result=$?
              if [ "$state_result" -ne 1 ]; then
                return 1
              fi
            fi
          done
        }

        restart_services() {
          local unit
          if [ "$services_need_restart" != true ]; then
            return 0
          fi
          echo "[ai-coaching] restarting writer services: ''${active_units[*]}"
          if ! ${lib.escapeShellArg systemctlBin} start "''${active_units[@]}"; then
            echo "[ai-coaching] failed to restart writer services" >&2
            return 1
          fi
          for unit in "''${active_units[@]}"; do
            if ! read_unit_state "$unit" || [ "$unit_state" != active ]; then
              echo "[ai-coaching] writer service is not active after restart: $unit" >&2
              return 1
            fi
          done
          services_need_restart=false
        }
      '';
in
{
  mkBackupScript =
    {
      dataDir,
      targetDir,
      retainCount,
      pg,
      serviceUnits ? [ ],
      manageServices ? true,
      systemctlBin ? "${pkgs.systemd}/bin/systemctl",
      flockBin ? "${pkgs.util-linux}/bin/flock",
    }:
    pkgs.writeShellApplication {
      name = "ai-coaching-backup";
      runtimeInputs = [
        pkgs.coreutils
        pkgs.findutils
        pkgs.gnugrep
        pkgs.gnused
        pkgs.gnutar
        pkgs.gzip
        pkgs.util-linux
      ]
      ++ lib.optional pg.enable pg.package;
      text = ''
        set -euo pipefail
        data_dir="${dataDir}"
        target_dir="${targetDir}"
        work_dir=""
        ${lockSetup { inherit flockBin; }}
        ${restoreMarkerGuard}
        ${serviceLifecycle {
          inherit manageServices serviceUnits systemctlBin;
        }}

        finish() {
          local result=$?
          local restart_result=0
          trap - EXIT
          if [ -n "$work_dir" ]; then
            rm -rf -- "$work_dir"
          fi
          if ! restart_services; then
            restart_result=1
          fi
          if [ "$result" -ne 0 ]; then
            exit "$result"
          fi
          exit "$restart_result"
        }
        trap finish EXIT
        trap 'exit 130' INT TERM

        mkdir -p "$target_dir"
        quiesce_services

        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        work_dir=$(mktemp -d "$target_dir/.in-progress-$stamp-XXXXXX")
        dest="$target_dir/$stamp.tar.gz"

        echo "[ai-coaching-backup] staging quiesced persistent data..."
        mkdir -p "$work_dir/data"
        for directory in media speakr evidence-worker; do
          if [ -d "$data_dir/$directory" ]; then
            cp -a -- "$data_dir/$directory" "$work_dir/data/$directory"
          fi
        done

        ${lib.optionalString pg.enable ''
          echo "[ai-coaching-backup] dumping PostgreSQL database ${pg.databaseName}..."
          mkdir -p "$work_dir/postgresql"
          if [ -n "''${CREDENTIALS_DIRECTORY:-}" ]; then
            password_file="$CREDENTIALS_DIRECTORY/db-password"
          else
            password_file="${pg.passwordFile}"
          fi
          export PGPASSWORD
          PGPASSWORD=$(cat "$password_file")
          ${pg.package}/bin/pg_dump \
            --host=${lib.escapeShellArg pg.host} \
            --port=${toString pg.port} \
            --username=${lib.escapeShellArg pg.username} \
            --no-password \
            --format=custom \
            --file="$work_dir/postgresql/${pg.databaseName}.dump" \
            ${lib.escapeShellArg pg.databaseName}
          unset PGPASSWORD
          if [ ! -s "$work_dir/postgresql/${pg.databaseName}.dump" ]; then
            echo "[ai-coaching-backup] pg_dump produced an empty or missing dump file; aborting" >&2
            exit 1
          fi
        ''}

        echo "[ai-coaching-backup] generating archive manifest..."
        (
          cd "$work_dir"
          find . -type f ! -name MANIFEST.sha256 -print0 \
            | LC_ALL=C sort -z \
            | xargs -0 sha256sum
        ) > "$work_dir/MANIFEST.sha256"

        echo "[ai-coaching-backup] archiving to $dest"
        tar -C "$work_dir" -czf "$dest" .
        sha256sum "$dest" > "$dest.sha256"

        echo "[ai-coaching-backup] pruning archives beyond ${toString retainCount}..."
        find "$target_dir" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' \
          | sort -rn \
          | tail -n "+$(( ${toString retainCount} + 1 ))" \
          | sed 's/^[^ ]* //' \
          | while IFS= read -r archive; do
              if [ -n "$archive" ]; then
                rm -f -- "$archive" "$archive.sha256"
              fi
            done

        restart_services
        echo "[ai-coaching-backup] done: $dest"
      '';
    };

  mkRestoreScript =
    {
      dataDir,
      pg,
      serviceUnits,
      manageServices ? true,
      systemctlBin ? "${pkgs.systemd}/bin/systemctl",
      flockBin ? "${pkgs.util-linux}/bin/flock",
    }:
    pkgs.writeShellApplication {
      name = "ai-coaching-restore";
      runtimeInputs = [
        pkgs.coreutils
        pkgs.gnugrep
        pkgs.gnutar
        pkgs.gzip
        pkgs.util-linux
      ]
      ++ lib.optional pg.enable pg.package;
      text = ''
        set -euo pipefail
        umask 077
        data_dir="${dataDir}"
        restore_marker="$data_dir/.ai-coaching-restore-in-progress"
        mode=restore
        archive=""
        recovery_dir=""
        work_dir=""
        restore_id=""
        mutation_started=false
        ${lockSetup { inherit flockBin; }}
        ${serviceLifecycle {
          inherit manageServices serviceUnits systemctlBin;
        }}

        path_exists() {
          [ -e "$1" ] || [ -L "$1" ]
        }

        durable_write_line() {
          local destination="$1"
          local value="$2"
          local temporary="$destination.new.$$"
          printf '%s\n' "$value" > "$temporary"
          sync "$temporary"
          mv -- "$temporary" "$destination"
          sync "$(dirname "$destination")"
        }

        save_active_units() {
          local unit
          : > "$recovery_dir/active-units"
          for unit in "''${active_units[@]}"; do
            printf '%s\n' "$unit" >> "$recovery_dir/active-units"
          done
          sync "$recovery_dir/active-units"
          sync "$recovery_dir"
        }

        load_recovery_state() {
          local directory
          if [ ! -f "$restore_marker" ]; then
            echo "[ai-coaching-restore] no restore recovery marker exists at $restore_marker" >&2
            exit 1
          fi
          recovery_dir=$(cat "$restore_marker")
          case "$recovery_dir" in
            "$data_dir"/.restore-recovery-*) ;;
            *)
              echo "[ai-coaching-restore] recovery marker contains an invalid recovery path" >&2
              exit 1
              ;;
          esac
          if [ ! -d "$recovery_dir" ]; then
            echo "[ai-coaching-restore] recovery directory is missing: $recovery_dir" >&2
            exit 1
          fi
          work_dir="$recovery_dir/staged"
          if [ ! -d "$work_dir" ]; then
            echo "[ai-coaching-restore] staged restore data is missing: $work_dir" >&2
            exit 1
          fi
          restore_id=$(basename "$recovery_dir")
          restore_id="''${restore_id#.restore-recovery-}"
          for directory in media speakr evidence-worker; do
            load_directory_record "$directory"
          done
          ${lib.optionalString pg.enable ''
            load_database_recovery
          ''}
          active_units=()
          if [ -f "$recovery_dir/active-units" ]; then
            mapfile -t active_units < "$recovery_dir/active-units"
          fi
          if [ "''${#active_units[@]}" -gt 0 ]; then
            services_need_restart=true
          else
            services_need_restart=false
          fi
          mutation_started=true
        }

        create_restore_marker() {
          local temporary="$restore_marker.new.$$"
          printf '%s\n' "$recovery_dir" > "$temporary"
          sync "$temporary"
          mv -- "$temporary" "$restore_marker"
          sync "$data_dir"
          mutation_started=true
        }

        clear_restore_marker() {
          rm -f -- "$restore_marker"
          sync "$data_dir"
        }

        load_directory_record() {
          local directory="$1"
          local record_dir="$recovery_dir/directories/$directory"
          local expected_live="$data_dir/$directory"
          local expected_previous="$data_dir/$directory.pre-restore-$restore_id"
          local expected_staged="$work_dir/data/$directory"
          local expected_recreated="$recovery_dir/recreated-after-marker/$directory"
          local record
          for record in original-state live-path previous-path staged-path recreated-path; do
            if [ ! -f "$record_dir/$record" ]; then
              echo "[ai-coaching-restore] incomplete durable directory record for $directory: missing $record" >&2
              return 1
            fi
          done
          directory_state=$(cat "$record_dir/original-state")
          directory_live=$(cat "$record_dir/live-path")
          directory_previous=$(cat "$record_dir/previous-path")
          directory_staged=$(cat "$record_dir/staged-path")
          directory_recreated=$(cat "$record_dir/recreated-path")
          case "$directory_state" in
            present|absent) ;;
            *)
              echo "[ai-coaching-restore] invalid original-state record for $directory" >&2
              return 1
              ;;
          esac
          if [ "$directory_live" != "$expected_live" ] \
            || [ "$directory_previous" != "$expected_previous" ] \
            || [ "$directory_staged" != "$expected_staged" ] \
            || [ "$directory_recreated" != "$expected_recreated" ]; then
            echo "[ai-coaching-restore] invalid durable path record for $directory" >&2
            return 1
          fi
        }

        register_directory() {
          local directory="$1"
          local record_dir="$recovery_dir/directories/$directory"
          if [ -d "$record_dir" ]; then
            load_directory_record "$directory"
            return 0
          fi
          mkdir -p "$record_dir" "$recovery_dir/recreated-after-marker"
          if path_exists "$data_dir/$directory"; then
            durable_write_line "$record_dir/original-state" present
          else
            durable_write_line "$record_dir/original-state" absent
          fi
          durable_write_line "$record_dir/live-path" "$data_dir/$directory"
          durable_write_line "$record_dir/previous-path" "$data_dir/$directory.pre-restore-$restore_id"
          durable_write_line "$record_dir/staged-path" "$work_dir/data/$directory"
          durable_write_line "$record_dir/recreated-path" "$recovery_dir/recreated-after-marker/$directory"
          sync "$record_dir"
          sync "$recovery_dir/directories"
          sync "$recovery_dir/recreated-after-marker"
          sync "$recovery_dir"
        }

        register_all_directories() {
          local directory
          for directory in media speakr evidence-worker; do
            register_directory "$directory"
          done
        }

        # Roll back every registered directory, including a directory whose
        # original was moved aside but whose restored replacement never made
        # it into place. Restored content is moved back to staging when
        # possible so an operator can still choose --resume afterward.
        rollback_filesystem() {
          local directory
          local failed=false
          echo "[ai-coaching-restore] rolling back filesystem changes..." >&2
          for directory in evidence-worker speakr media; do
            if ! load_directory_record "$directory"; then
              failed=true
              continue
            fi

            if path_exists "$directory_previous"; then
              if path_exists "$directory_live"; then
                if ! path_exists "$directory_staged"; then
                  if ! mv -- "$directory_live" "$directory_staged"; then
                    echo "[ai-coaching-restore] failed to move restored $directory back to staging" >&2
                    failed=true
                    continue
                  fi
                else
                  rm -rf -- "''${directory_live:?}"
                fi
              fi
              if ! mv -- "$directory_previous" "$directory_live"; then
                echo "[ai-coaching-restore] failed to restore original $directory" >&2
                failed=true
                continue
              fi
              echo "[ai-coaching-restore] rolled back $directory to its original state" >&2
            elif [ "$directory_state" = absent ]; then
              if path_exists "$directory_live"; then
                if ! path_exists "$directory_staged"; then
                  if ! mv -- "$directory_live" "$directory_staged"; then
                    echo "[ai-coaching-restore] failed to remove restored $directory from live state" >&2
                    failed=true
                    continue
                  fi
                else
                  rm -rf -- "''${directory_live:?}"
                fi
              fi
              rm -rf -- "$directory_recreated"
              echo "[ai-coaching-restore] rolled back originally absent $directory to absence" >&2
            elif [ "$directory_state" = present ]; then
              if ! path_exists "$directory_live"; then
                echo "[ai-coaching-restore] original $directory is missing and no moved-aside copy exists" >&2
                failed=true
              elif ! path_exists "$directory_staged"; then
                echo "[ai-coaching-restore] cannot prove live $directory is the registered original" >&2
                failed=true
              fi
            fi
            rm -rf -- "$directory_recreated"
            sync "$data_dir"
          done
          [ "$failed" = false ]
        }

        swap_directory() {
          local directory="$1"
          load_directory_record "$directory"

          if ! path_exists "$directory_staged"; then
            if path_exists "$directory_live"; then
              return 0
            fi
            echo "[ai-coaching-restore] neither staged nor live $directory exists during recovery" >&2
            rollback_filesystem
            return 1
          fi

          if [ "$directory_state" = present ] && ! path_exists "$directory_previous"; then
            if ! path_exists "$directory_live"; then
              echo "[ai-coaching-restore] registered original $directory is missing" >&2
              rollback_filesystem
              return 1
            fi
            echo "[ai-coaching-restore] moving original $directory aside"
            mv -- "$directory_live" "$directory_previous"
            sync "$data_dir"
          elif path_exists "$directory_live"; then
            if path_exists "$directory_recreated"; then
              echo "[ai-coaching-restore] multiple unregistered recreations of $directory appeared during recovery" >&2
              rollback_filesystem
              return 1
            fi
            echo "[ai-coaching-restore] preserving post-marker recreation of $directory outside live state"
            mv -- "$directory_live" "$directory_recreated"
            sync "$recovery_dir"
          fi

          if [ "''${AI_COACHING_RESTORE_TEST_FAILPOINT:-}" = "after-original-away:$directory" ]; then
            echo "[ai-coaching-restore] injected failure after moving original $directory aside" >&2
            rollback_filesystem
            return 1
          fi

          echo "[ai-coaching-restore] moving restored $directory into place"
          if ! mv -- "$directory_staged" "$directory_live"; then
            echo "[ai-coaching-restore] failed to move staged $directory into place" >&2
            rollback_filesystem
            return 1
          fi
          sync "$data_dir"
        }

        ${lib.optionalString pg.enable ''
          declare -a pg_admin_prefix=(
            ${lib.concatMapStringsSep " " lib.escapeShellArg (pg.adminCommandPrefix or [ ])}
          )
          replacement_database=""
          displaced_database=""

          run_admin_psql() {
            "''${pg_admin_prefix[@]}" ${pg.package}/bin/psql \
              --host=${lib.escapeShellArg pg.adminHost} \
              --port=${toString pg.port} \
              --username=${lib.escapeShellArg pg.adminUsername} \
              --no-password \
              --dbname=${lib.escapeShellArg pg.adminDatabase} \
              -v ON_ERROR_STOP=1 \
              "$@"
          }

          run_admin_pg_restore() {
            "''${pg_admin_prefix[@]}" ${pg.package}/bin/pg_restore \
              --host=${lib.escapeShellArg pg.adminHost} \
              --port=${toString pg.port} \
              --username=${lib.escapeShellArg pg.adminUsername} \
              --no-password \
              "$@"
          }

          load_database_password() {
            if [ ! -r "${pg.passwordFile}" ] || [ ! -s "${pg.passwordFile}" ]; then
              echo "[ai-coaching-restore] PostgreSQL password file is missing, unreadable, or empty: ${pg.passwordFile}" >&2
              return 1
            fi
            PGPASSWORD=$(cat "${pg.passwordFile}")
            if [ -z "$PGPASSWORD" ]; then
              echo "[ai-coaching-restore] PostgreSQL password file is empty: ${pg.passwordFile}" >&2
              return 1
            fi
            export PGPASSWORD
          }

          register_database_recovery() {
            local suffix
            mkdir -p "$recovery_dir/postgresql"
            if [ -f "$recovery_dir/postgresql/replacement-database" ] \
              || [ -f "$recovery_dir/postgresql/displaced-database" ]; then
              load_database_recovery
              return 0
            fi
            suffix=$(printf '%s' "$restore_id" | sha256sum | cut -c1-12)
            durable_write_line \
              "$recovery_dir/postgresql/replacement-database" \
              "${pg.databaseName}_restore_$suffix"
            durable_write_line \
              "$recovery_dir/postgresql/displaced-database" \
              "${pg.databaseName}_previous_$suffix"
            sync -f "$recovery_dir/postgresql"
          }

          load_database_recovery() {
            if [ ! -f "$recovery_dir/postgresql/replacement-database" ] \
              || [ ! -f "$recovery_dir/postgresql/displaced-database" ]; then
              echo "[ai-coaching-restore] incomplete durable PostgreSQL recovery record" >&2
              return 1
            fi
            replacement_database=$(cat "$recovery_dir/postgresql/replacement-database")
            displaced_database=$(cat "$recovery_dir/postgresql/displaced-database")
            case "$replacement_database:$displaced_database" in
              "${pg.databaseName}_restore_"*:"${pg.databaseName}_previous_"*) ;;
              *)
                echo "[ai-coaching-restore] invalid PostgreSQL recovery database names" >&2
                return 1
                ;;
            esac
            if [ "$replacement_database" = "$displaced_database" ] \
              || [ "''${#replacement_database}" -gt 63 ] \
              || [ "''${#displaced_database}" -gt 63 ]; then
              echo "[ai-coaching-restore] invalid PostgreSQL recovery database names" >&2
              return 1
            fi
          }

          validate_database_configuration() {
            local target_owner
            load_database_password
            if ! ${pg.package}/bin/psql \
              --host=${lib.escapeShellArg pg.host} \
              --port=${toString pg.port} \
              --username=${lib.escapeShellArg pg.username} \
              --no-password \
              --dbname=${lib.escapeShellArg pg.databaseName} \
              -v ON_ERROR_STOP=1 \
              --command='SELECT 1;' \
              >/dev/null; then
              unset PGPASSWORD
              echo "[ai-coaching-restore] configured PostgreSQL application credentials cannot access ${pg.databaseName}" >&2
              return 1
            fi
            unset PGPASSWORD
            if ! target_owner=$(
              run_admin_psql \
                --tuples-only \
                --no-align \
                --set=target_db=${lib.escapeShellArg pg.databaseName} <<'SQL'
          SELECT pg_get_userbyid(datdba)
          FROM pg_database
          WHERE datname = :'target_db';
          SQL
            ); then
              echo "[ai-coaching-restore] local PostgreSQL administrative connection failed" >&2
              return 1
            fi
            if [ "$target_owner" != "${pg.username}" ]; then
              echo "[ai-coaching-restore] database ${pg.databaseName} must be owned by configured role ${pg.username}; found: $target_owner" >&2
              return 1
            fi
          }

          snapshot_database() {
            local destination="$recovery_dir/postgresql/pre-restore.dump"
            mkdir -p "$recovery_dir/postgresql"
            load_database_password
            if ! ${pg.package}/bin/pg_dump \
              --host=${lib.escapeShellArg pg.host} \
              --port=${toString pg.port} \
              --username=${lib.escapeShellArg pg.username} \
              --no-password \
              --format=custom \
              --file="$destination" \
              ${lib.escapeShellArg pg.databaseName}; then
              unset PGPASSWORD
              return 1
            fi
            unset PGPASSWORD
            if [ ! -s "$destination" ]; then
              echo "[ai-coaching-restore] pre-restore PostgreSQL snapshot is empty; refusing mutation" >&2
              return 1
            fi
            sync "$destination"
            sync "$recovery_dir/postgresql"
          }

          prepare_replacement_database() {
            if ! run_admin_psql \
              --set=target_db=${lib.escapeShellArg pg.databaseName} \
              --set=replacement_db="$replacement_database" \
              --set=displaced_db="$displaced_database" <<'SQL'
          -- AI_COACHING_PREPARE_REPLACEMENT
          SELECT pg_get_userbyid(datdba) AS database_owner
          FROM pg_database
          WHERE datname = :'target_db'
          \gset

          DROP DATABASE IF EXISTS :"replacement_db" WITH (FORCE);
          DROP DATABASE IF EXISTS :"displaced_db" WITH (FORCE);
          CREATE DATABASE :"replacement_db"
            WITH OWNER = :"database_owner"
            TEMPLATE = template0;
          SQL
            then
              echo "[ai-coaching-restore] failed to extract PostgreSQL owner or prepare the replacement database" >&2
              return 1
            fi
          }

          apply_database_metadata() {
            if ! run_admin_psql \
              --set=target_db=${lib.escapeShellArg pg.databaseName} \
              --set=replacement_db="$replacement_database" <<'SQL'
          -- AI_COACHING_APPLY_DATABASE_METADATA
          SELECT
            oid AS database_oid,
            pg_get_userbyid(datdba) AS database_owner,
            datconnlimit AS connection_limit
          FROM pg_database
          WHERE datname = :'target_db'
          \gset source_

          ALTER DATABASE :"replacement_db" OWNER TO :"source_database_owner";
          ALTER DATABASE :"replacement_db"
            CONNECTION LIMIT :source_connection_limit;

          SELECT format(
            'REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC;',
            :'replacement_db'
          )
          FROM pg_database
          WHERE oid = :source_database_oid
            AND datacl IS NOT NULL
          \gexec

          SELECT format(
            'REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I;',
            :'replacement_db',
            :'source_database_owner'
          )
          FROM pg_database
          WHERE oid = :source_database_oid
            AND datacl IS NOT NULL
          \gexec

          WITH RECURSIVE source_database AS (
            SELECT oid, datdba, datacl
            FROM pg_database
            WHERE oid = :source_database_oid
          ),
          source_acl AS (
            SELECT acl.*
            FROM source_database
            CROSS JOIN LATERAL aclexplode(datacl) AS acl
          ),
          grantor_depth (role_oid, privilege_type, depth, path) AS (
            SELECT
              roots.role_oid,
              privileges.privilege_type,
              0,
              ARRAY[roots.role_oid]
            FROM (
              SELECT datdba AS role_oid
              FROM source_database
              UNION
              SELECT oid
              FROM pg_roles
              WHERE rolsuper
            ) AS roots
            CROSS JOIN (
              VALUES ('CONNECT'), ('CREATE'), ('TEMPORARY')
            ) AS privileges(privilege_type)
            UNION ALL
            SELECT
              source_acl.grantee,
              source_acl.privilege_type,
              grantor_depth.depth + 1,
              grantor_depth.path || source_acl.grantee
            FROM grantor_depth
            JOIN source_acl
              ON source_acl.grantor = grantor_depth.role_oid
              AND source_acl.privilege_type = grantor_depth.privilege_type
              AND source_acl.is_grantable
            WHERE NOT source_acl.grantee = ANY(grantor_depth.path)
          )
          SELECT format(
            'SET ROLE %I; GRANT %s ON DATABASE %I TO %s%s; RESET ROLE;',
            pg_get_userbyid(source_acl.grantor),
            CASE privilege_type
              WHEN 'CONNECT' THEN 'CONNECT'
              WHEN 'CREATE' THEN 'CREATE'
              WHEN 'TEMPORARY' THEN 'TEMPORARY'
            END,
            :'replacement_db',
            CASE
              WHEN grantee = 0 THEN 'PUBLIC'
              ELSE format('%I', pg_get_userbyid(grantee))
            END,
            CASE WHEN is_grantable THEN ' WITH GRANT OPTION' ELSE ''' END
          )
          FROM source_acl
          LEFT JOIN LATERAL (
            SELECT min(depth) AS depth
            FROM grantor_depth
            WHERE grantor_depth.role_oid = source_acl.grantor
              AND grantor_depth.privilege_type = source_acl.privilege_type
          ) AS source_grantor ON true
          ORDER BY
            source_grantor.depth NULLS LAST,
            source_acl.is_grantable DESC,
            source_acl.grantor,
            source_acl.grantee,
            source_acl.privilege_type
          \gexec

          SELECT format(
            'SELECT pg_catalog.set_config(%L, %L, false); '
            'ALTER DATABASE %I SET %I FROM CURRENT; RESET %I;',
            split_part(setting, '=', 1),
            substr(setting, strpos(setting, '=') + 1),
            :'replacement_db',
            split_part(setting, '=', 1),
            split_part(setting, '=', 1)
          )
          FROM pg_db_role_setting
          CROSS JOIN LATERAL unnest(setconfig) AS setting
          WHERE setdatabase = :source_database_oid
            AND setrole = 0
          ORDER BY setting
          \gexec

          SELECT format(
            'SELECT pg_catalog.set_config(%L, %L, false); '
            'ALTER ROLE %I IN DATABASE %I SET %I FROM CURRENT; RESET %I;',
            split_part(setting, '=', 1),
            substr(setting, strpos(setting, '=') + 1),
            pg_get_userbyid(setrole),
            :'replacement_db',
            split_part(setting, '=', 1),
            split_part(setting, '=', 1)
          )
          FROM pg_db_role_setting
          CROSS JOIN LATERAL unnest(setconfig) AS setting
          WHERE setdatabase = :source_database_oid
            AND setrole <> 0
          ORDER BY pg_get_userbyid(setrole), setting
          \gexec
          SQL
            then
              echo "[ai-coaching-restore] failed to extract or apply PostgreSQL database metadata" >&2
              return 1
            fi
          }

          restore_database() {
            local dump_file="$1"
            local description="$2"
            if ! ${pg.package}/bin/pg_restore --list "$dump_file" >/dev/null; then
              echo "[ai-coaching-restore] $description PostgreSQL dump failed structural validation" >&2
              return 1
            fi
            if ! load_database_recovery; then
              return 1
            fi
            if ! prepare_replacement_database; then
              return 1
            fi
            if ! run_admin_pg_restore \
              --exit-on-error \
              --single-transaction \
              --dbname="$replacement_database" \
              "$dump_file"; then
              return 1
            fi
            if ! apply_database_metadata; then
              return 1
            fi

            if ! run_admin_psql \
              --set=target_db=${lib.escapeShellArg pg.databaseName} \
              --set=replacement_db="$replacement_database" \
              --set=displaced_db="$displaced_database" <<'SQL'
          -- AI_COACHING_SWAP_DATABASES
          ALTER DATABASE :"target_db" WITH ALLOW_CONNECTIONS false;
          SELECT pg_terminate_backend(pid)
          FROM pg_stat_activity
          WHERE datname IN (:'target_db', :'replacement_db', :'displaced_db')
            AND pid <> pg_backend_pid();
          BEGIN;
          ALTER DATABASE :"target_db" RENAME TO :"displaced_db";
          ALTER DATABASE :"replacement_db" RENAME TO :"target_db";
          COMMIT;
          SQL
            then
              echo "[ai-coaching-restore] failed to swap PostgreSQL replacement database into place" >&2
              return 1
            fi

            if [ "''${AI_COACHING_RESTORE_TEST_FAILPOINT:-}" = after-database-swap ]; then
              echo "[ai-coaching-restore] injected failure after PostgreSQL database swap" >&2
              return 1
            fi

            if ! run_admin_psql \
              --set=displaced_db="$displaced_database" <<'SQL'
          -- AI_COACHING_DROP_DISPLACED
          DROP DATABASE IF EXISTS :"displaced_db" WITH (FORCE);
          SQL
            then
              echo "[ai-coaching-restore] failed to drop the displaced PostgreSQL database" >&2
              return 1
            fi
          }
        ''}

        complete_restoration() {
          local directory
          for directory in media speakr evidence-worker; do
            swap_directory "$directory"
          done

          ${lib.optionalString pg.enable ''
            echo "[ai-coaching-restore] restoring PostgreSQL database ${pg.databaseName}"
            if ! restore_database "$work_dir/postgresql/${pg.databaseName}.dump" target; then
              echo "[ai-coaching-restore] PostgreSQL restore failed; rolling back filesystem to pre-restore state" >&2
              rollback_filesystem || true
              return 1
            fi
          ''}

          # Flush staged-file renames and restored file contents before the
          # fail-stop marker is removed. PostgreSQL's successful transaction
          # commit is durable before pg_restore returns.
          sync -f "$data_dir"
          clear_restore_marker

          if ! restart_services; then
            echo "[ai-coaching-restore] restore data succeeded but restarting writer services failed; manual intervention required" >&2
            return 1
          fi

          rm -rf -- "$recovery_dir"
          sync "$data_dir"
          recovery_dir=""
          work_dir=""
        }

        complete_rollback() {
          local rollback_failed=false
          if ! rollback_filesystem; then
            rollback_failed=true
          fi
          ${lib.optionalString pg.enable ''
            echo "[ai-coaching-restore] restoring the pre-restore PostgreSQL snapshot"
            if ! restore_database "$recovery_dir/postgresql/pre-restore.dump" pre-restore; then
              echo "[ai-coaching-restore] failed to restore the pre-restore PostgreSQL snapshot" >&2
              rollback_failed=true
            fi
          ''}
          if [ "$rollback_failed" = true ]; then
            return 1
          fi

          sync -f "$data_dir"
          clear_restore_marker
          if ! restart_services; then
            echo "[ai-coaching-restore] rollback succeeded but restarting writer services failed; manual intervention required" >&2
            return 1
          fi
          rm -rf -- "$recovery_dir"
          sync "$data_dir"
          recovery_dir=""
          work_dir=""
        }

        finish() {
          local result=$?
          local restart_result=0
          trap - EXIT
          if [ "$result" -ne 0 ]; then
            if [ -e "$restore_marker" ]; then
              echo "[ai-coaching-restore] FAILED: writer services are left stopped: ''${active_units[*]}" >&2
              echo "[ai-coaching-restore] persistent fail-stop marker: $restore_marker" >&2
              echo "[ai-coaching-restore] recover with: ai-coaching-restore --resume" >&2
              echo "[ai-coaching-restore] or restore the pre-operation state with: ai-coaching-restore --rollback" >&2
            elif [ "$mutation_started" != true ]; then
              if ! restart_services; then
                restart_result=1
              fi
              if [ -n "$recovery_dir" ] && [ -d "$recovery_dir" ]; then
                rm -rf -- "$recovery_dir"
              fi
            fi
            if [ "$restart_result" -ne 0 ]; then
              echo "[ai-coaching-restore] also failed to restart writers after a pre-mutation error" >&2
            fi
            exit "$result"
          fi
          exit 0
        }
        trap finish EXIT
        trap 'exit 130' INT TERM

        assume_yes=false
        case "''${1:-}" in
          --resume)
            mode=resume
            shift
            ;;
          --rollback)
            mode=rollback
            shift
            ;;
          --yes)
            assume_yes=true
            shift
            ;;
        esac

        if [ "$mode" != restore ]; then
          if [ "$#" -ne 0 ]; then
            echo "usage: ai-coaching-restore --resume | --rollback" >&2
            exit 1
          fi
          load_recovery_state
          ensure_services_inactive
          if [ "$mode" = resume ]; then
            echo "[ai-coaching-restore] resuming interrupted restore from $recovery_dir"
            complete_restoration
            echo "[ai-coaching-restore] interrupted restore completed successfully"
          else
            echo "[ai-coaching-restore] rolling back interrupted restore from $recovery_dir"
            complete_rollback
            echo "[ai-coaching-restore] pre-restore filesystem and PostgreSQL state restored"
          fi
          exit 0
        fi

        if [ "$#" -ne 1 ]; then
          echo "usage: ai-coaching-restore [--yes] /path/to/TIMESTAMP.tar.gz" >&2
          echo "       ai-coaching-restore --resume" >&2
          echo "       ai-coaching-restore --rollback" >&2
          exit 1
        fi
        ${restoreMarkerGuard}
        archive=$(realpath -e -- "$1")
        if [ ! -f "$archive" ]; then
          echo "archive not found: $archive" >&2
          exit 1
        fi

        # --- Validate archive completeness and integrity before touching any
        # --- live state (services are still untouched at this point).
        echo "[ai-coaching-restore] verifying archive integrity..."
        if ! gzip -t "$archive"; then
          echo "archive fails gzip integrity check; refusing restore" >&2
          exit 1
        fi

        checksum_file="$archive.sha256"
        if [ ! -f "$checksum_file" ]; then
          echo "missing companion checksum file $checksum_file; refusing restore" >&2
          exit 1
        fi
        expected_archive_sum=$(cut -d ' ' -f1 "$checksum_file")
        actual_archive_sum=$(sha256sum "$archive" | cut -d ' ' -f1)
        if [ "$expected_archive_sum" != "$actual_archive_sum" ]; then
          echo "archive checksum mismatch against $checksum_file; refusing restore" >&2
          exit 1
        fi

        if tar -tzf "$archive" | grep -E '(^/|(^|/)\.\.(/|$))' >/dev/null; then
          echo "archive contains an unsafe path; refusing restore" >&2
          exit 1
        fi

        mkdir -p "$data_dir"
        restore_stamp=$(date -u +%Y%m%dT%H%M%SZ)
        recovery_dir=$(mktemp -d "$data_dir/.restore-recovery-$restore_stamp-XXXXXX")
        restore_id=$(basename "$recovery_dir")
        restore_id="''${restore_id#.restore-recovery-}"
        work_dir="$recovery_dir/staged"
        mkdir -p "$work_dir" "$recovery_dir/directories"
        tar -C "$work_dir" -xzf "$archive"

        if [ ! -f "$work_dir/MANIFEST.sha256" ]; then
          echo "archive is missing MANIFEST.sha256; refusing restore" >&2
          exit 1
        fi
        if ! (cd "$work_dir" && sha256sum --strict --quiet -c MANIFEST.sha256); then
          echo "archive failed manifest checksum verification; refusing restore" >&2
          exit 1
        fi

        ${lib.optionalString pg.enable ''
          dump_file="$work_dir/postgresql/${pg.databaseName}.dump"
          if [ ! -s "$dump_file" ]; then
            echo "archive is missing the required PostgreSQL dump for ${pg.databaseName}; refusing restore" >&2
            exit 1
          fi
          if ! ${pg.package}/bin/pg_restore --list "$dump_file" >/dev/null; then
            echo "PostgreSQL dump failed structural validation; refusing restore" >&2
            exit 1
          fi
          validate_database_configuration
        ''}

        echo "This will stop ai-coaching writers and replace $data_dir/{media,speakr,evidence-worker}"
        echo "from $archive. Existing directories are moved aside, never deleted."
        if [ "$assume_yes" != true ]; then
          read -r -p "Type 'restore' to continue: " confirm
          if [ "$confirm" != "restore" ]; then
            echo "aborted"
            exit 1
          fi
        fi

        # --- Validation complete. From here on we mutate live state; any
        # --- failure leaves the durable marker in place and never restarts
        # --- writers automatically.
        register_all_directories
        ${lib.optionalString pg.enable ''
          register_database_recovery
        ''}
        quiesce_services
        save_active_units
        ${lib.optionalString pg.enable ''
          echo "[ai-coaching-restore] snapshotting current PostgreSQL state for operator rollback"
          snapshot_database
        ''}
        durable_write_line "$recovery_dir/archive-path" "$archive"
        sync -f "$recovery_dir"
        create_restore_marker

        if [ "''${AI_COACHING_RESTORE_TEST_FAILPOINT:-}" = after-marker ]; then
          echo "[ai-coaching-restore] simulating abrupt termination after durable marker creation" >&2
          kill -KILL "$$"
        fi

        complete_restoration
        echo "[ai-coaching-restore] done. Previous data remains in *.pre-restore-$restore_id."
      '';
    };
}

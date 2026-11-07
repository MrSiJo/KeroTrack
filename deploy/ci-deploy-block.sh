  kerotrack)
    REPO=KeroTrack; BRANCH=main
    IMAGES=("kerotrack-api:backend" "kerotrack-ui:frontend")
    TARGETS=("/dockerdata/compose-stacks/kerotrack:backend" "/dockerdata/compose-stacks/kerotrack:frontend")
    CHECKS=(kerotrack-api kerotrack-ui
            "GET http://127.0.0.1:9176/api/health 200"
            "GET http://127.0.0.1:9177/ 200")
    # Real data: an online SQLite snapshot (WAL included) before every deploy,
    # in the data volume (/dockerdata/kerotrack/data/ci-backups on the host).
    # Nothing prunes ci-backups: clear old snapshots by hand.
    pre_deploy() {
      [ "$(docker inspect -f '{{.State.Running}}' kerotrack-api 2>/dev/null)" = true ] \
        || { echo "kerotrack-api not running: no db snapshot"; return 0; }
      local ts; ts=$(date +%Y%m%d-%H%M%S)
      docker exec kerotrack-api python -c "import os, sqlite3; os.makedirs('/app/data/ci-backups', exist_ok=True); s=sqlite3.connect('/app/data/kerotrack.db'); d=sqlite3.connect('/app/data/ci-backups/kerotrack-$ts-ci.db'); s.backup(d); r=d.execute('PRAGMA integrity_check').fetchone()[0]; d.close(); assert r == 'ok', r"
      echo "db snapshot /app/data/ci-backups/kerotrack-$ts-ci.db (integrity ok)"
    }
    ;;

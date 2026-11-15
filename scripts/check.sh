#!/usr/bin/env bash
# Every check to run before a commit or pull request. There is no CI, so this is it.
#
#   ./scripts/check.sh          lint, Django checks, migrations, curriculum, static build, tests
#   ./scripts/check.sh --links  also check every resource link in content/curriculum/ (needs internet)
#
# Always uses a local SQLite database, whatever DATABASE_URL says in .env,
# so it can never touch production.
set -o errexit -o nounset -o pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="sqlite:///$PWD/db.sqlite3"
export DEBUG=True
PY=${PYTHON:-python}

step() { printf '\n== %s\n' "$1"; }

step "Lint (ruff)"
if command -v ruff >/dev/null; then ruff check .; else echo "ruff not installed: pip install -r requirements-dev.txt"; exit 1; fi

step "Compile every Python file"
$PY -m compileall -q accounts assistant config content diagnose learning

step "Django system checks"
$PY manage.py check
DEBUG=False SECRET_KEY=check-only $PY manage.py check --deploy --fail-level ERROR

step "Migrations match the models"
$PY manage.py makemigrations --check --dry-run

step "Curriculum files are valid"
$PY manage.py validate_curriculum

step "Static files build"
STATIC_TMP=$(mktemp -d)
DEBUG=False SECRET_KEY=check-only STATIC_ROOT_OVERRIDE="$STATIC_TMP" $PY manage.py collectstatic --no-input -v 0
rm -rf "$STATIC_TMP"

step "Tests"
$PY manage.py test

if [[ "${1:-}" == "--links" ]]; then
  step "Resource links"
  $PY manage.py validate_curriculum --links
fi

printf '\nAll checks passed.\n'

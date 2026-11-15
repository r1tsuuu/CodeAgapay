#!/usr/bin/env bash
# Render build command. Exit on the first error so a broken build never deploys.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Load content/curriculum/ on deploy once the team has switched it on (docs/CURRICULUM.md).
# Off by default, so admin edits not yet exported to the files are never overwritten.
if [ "${CURRICULUM_AUTO_IMPORT:-}" = "1" ]; then
  python manage.py import_curriculum
fi

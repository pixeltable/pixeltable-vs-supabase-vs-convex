#!/bin/sh
# pixeltable/app.py to a hosted Pixeltable database. No compute service, no second box.
#
#     PXT_DB=pxt://org:db sh cloud/deploy_pixeltable.sh
#
# Needs PIXELTABLE_API_KEY and a [[tool.pixeltable.database]] entry named PXT_DB in
# pixeltable/pyproject.toml, which sets the database's cpu, memory and workers. The
# documented order: upload the project and build the image, create the tables, start
# the service.
set -eu
: "${PXT_DB:?set PXT_DB=pxt://org:db}"
cd "$(dirname "$0")/../pixeltable"

pxt db update "$PXT_DB" -f
pxt schema update app.py "$PXT_DB" -f
pxt service update app.py "$PXT_DB" -f
pxt service list "$PXT_DB"

#!/bin/sh
# Runs once, on an empty data directory. POSTGRES_DB creates `perch`; this adds `perch_keys`.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c 'CREATE DATABASE perch_keys'

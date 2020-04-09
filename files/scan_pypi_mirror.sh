#!/bin/bash
set -e

if [ "$#" -ne 1 ]; then
  echo "You must provide a path to the offline PyPI mirror web folder" >>2;
  exit 1;
fi;

export AURA_MIRROR_PATH=$1;

if [ ! -d "${AURA_MIRROR_PATH}/json" ]; then
  echo "JSON directory not found at ${AURA_MIRROR_PATH}. You probably have not provided a correct path to the web mirror directory" >>2;
  exit 1;
fi

if [ ! -f "aura_mirror_scan/package_cache" ]; then
  ls $AURA_MIRROR_PATH/json >aura_mirror_scan/package_cache;
fi

if [ ! -f "aura_mirror_scan/processed_packages.log" ];then
  touch aura_mirror_scan/processed_packages.log
  PKGS=$(cat aura_mirror_scan/package_cache)
else
  PKGS=$(cat aura_mirror_scan/package_cache|fgrep -vf aura_mirror_scan/processed_packages.log)
fi

scan() {
  AURA_LOG_LEVEL="ERROR" aura scan --min-score=10 --async -f json mirror://$1 1> >(tee -a "aura_mirror_scan/$1.results.json" |jq .) 2> >(tee -a aura_mirror_scan/errors.log >&2)
  if [ $? -ne 0 ]; then
    echo $1 >>aura_mirror_scan/failed_packages.log
    # Remove results which has 0 score
    cat aura_mirror_scan/$1.results.json| jq -e '(.score == 0)' && rm aura_mirror_scan/$1.results.json
  else
    echo $1 >>aura_mirror_scan/processed_packages.log
  fi
}

export -f scan

echo "Starting Aura scan"

echo $PKGS|tr ' ' '\n'| parallel --load 80 --memfree 5G --timeout 180 --max-args 1 scan

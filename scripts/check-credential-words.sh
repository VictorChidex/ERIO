#!/usr/bin/env bash
# Credential-word check (decision D-08, spec section 9).
#
# Fails if any tracked or new (not ignored) file contains one of the three
# words the spec forbids. The pattern is assembled from fragments so this
# script does not match itself. Until D-09 settles an allow-list, the check
# covers the whole repo with no exceptions.
#
# Usage: scripts/check-credential-words.sh
set -euo pipefail

words=("pass""word" "api""_key" "sec""ret")
pattern=$(IFS='|'; echo "${words[*]}")

cd "$(git rev-parse --show-toplevel)"

if git grep --untracked -I -i -n -E "$pattern"; then
  echo "Credential-word check failed: remove or rename the words above (see docs/decisions.md, D-08)." >&2
  exit 1
fi

echo "Credential-word check passed."

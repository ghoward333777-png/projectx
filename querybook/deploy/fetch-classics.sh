#!/usr/bin/env bash
# Download the classic public-domain library (config/library/classics.tsv) as
# EPUBs from Project Gutenberg and write a manifest for `qb ingest --manifest`.
#
#   bash deploy/fetch-classics.sh /var/lib/querybook-books
#   sudo -u querybook qb -c /etc/querybook/querybook.toml ingest --manifest /var/lib/querybook-books/manifest.csv
#
# Polite: one request at a time with a pause, resumable (existing files are kept),
# every download is checked to be a complete EPUB before it is accepted.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
list="${LIST:-$here/config/library/classics.tsv}"
out="${1:-books}"
ua="QueryBook library fetch (${CONTACT:-ghoward333777@gmail.com})"
mkdir -p "$out"
manifest="$out/manifest.csv"
echo "path,rights,rights_note,genre,id" > "$manifest"
ok=0; failed=0
while IFS=$'\t' read -r gid id title author; do
  [[ -z "${gid:-}" || "$gid" == \#* ]] && continue
  file="$out/$id.epub"
  if [[ ! -s "$file" ]] || ! unzip -tq "$file" >/dev/null 2>&1; then
    got=""
    for url in "https://www.gutenberg.org/cache/epub/$gid/pg$gid.epub" \
               "https://www.gutenberg.org/ebooks/$gid.epub3.images" \
               "https://www.gutenberg.org/ebooks/$gid.epub.noimages"; do
      if curl -sfL -A "$ua" --retry 3 --retry-delay 5 -o "$file.part" "$url" && unzip -tq "$file.part" >/dev/null 2>&1; then
        mv "$file.part" "$file"; got=1; break
      fi
      rm -f "$file.part"; sleep 2
    done
    if [[ -z "$got" ]]; then echo "FAILED  $title ($gid)"; failed=$((failed+1)); continue; fi
    sleep 2
  fi
  echo "ok      $title — $author"
  echo "$id.epub,public-domain,\"Project Gutenberg #$gid\",fiction,$id" >> "$manifest"
  ok=$((ok+1))
done < "$list"
echo "$ok books in $out ($failed failed); manifest: $manifest"

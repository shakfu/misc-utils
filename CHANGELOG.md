# Changelog

## 2026-08-28

- Added `wordsub.py`: scans a file tree for a term dictionary, built in or given with `--dict`, and optionally substitutes in place. Matching is whole-word and case-insensitive with the substitute recased to the spelling it replaced, since a prose vocabulary has to be found in every casing it is written in; `--case-sensitive` narrows both to the exact dictionary spelling and `--exact-fix` decouples them, reporting every casing but rewriting only the exact one and marking the rest `[manual]`. Only `.md` files are scanned, the dictionary being prose: widening the walk to source trees flags identifiers and URLs. Scan mode exits 1 when matches remain, so it is usable as a CI check. `treesed.py` remains the tool for one-off arbitrary patterns.

## 2026-02-07

- Removed `webloc` external dependency; replaced with stdlib `plistlib` in `store_links.py` and `dump-links.py`
- Project now has zero external runtime dependencies

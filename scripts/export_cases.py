"""Validate, deduplicate and export scraped public design-case metadata. No network."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical(url):
    if not url:
        return None
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError(f'Invalid public HTTP(S) URL: {url!r}')
    # Only known tracking fields are removed; retain business query parameters.
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() != 'ref' and not k.lower().startswith('utm_')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(query), p.fragment))


def export(records, output_dir, target=None):
    if not isinstance(records, list) or not records:
        raise ValueError('Input must be a nonempty JSON array of case records')
    merged = {}
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ValueError(f'Record {index + 1} must be an object')
        r = dict(raw)
        for field in ('name', 'source', 'source_url', 'collected_date'):
            if not isinstance(r.get(field), str) or not r[field].strip():
                raise ValueError(f'Record {index + 1}: missing {field}')
        date.fromisoformat(r['collected_date'])
        if r.get('published_date'):
            date.fromisoformat(r['published_date'])
        tags = r.get('tags', [])
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise ValueError(f'Record {index + 1}: tags must be an array of strings')
        r['tags'] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        r['source_url'] = canonical(r['source_url'])
        r['website_url'] = canonical(r.get('website_url'))
        r['website_domain'] = r.get('website_domain') or (
            urlsplit(r['website_url']).hostname if r['website_url'] else None)
        r['url_precision'] = 'source_link' if r['website_url'] else 'domain_only' if r['website_domain'] else 'unavailable'
        r.setdefault('published_date', None)
        r.setdefault('preview_url', None)
        if r['preview_url']:
            canonical(r['preview_url'])  # Validate, but preserve image URLs as supplied.
        key = 'website:' + r['website_url'] if r['website_url'] else 'source:' + r['source_url']
        provenance = {'source': r['source'], 'source_url': r['source_url']}
        if key in merged:
            existing = merged[key]
            existing['tags'] = list(dict.fromkeys(existing['tags'] + r['tags']))
            if provenance not in existing['sources']:
                existing['sources'].append(provenance)
            continue
        r['id'] = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
        r['sources'] = [provenance]
        merged[key] = r
    rows = list(merged.values())
    report = {
        'input_count': len(records), 'case_count': len(rows),
        'duplicates_merged': len(records) - len(rows),
        'by_primary_source': dict(Counter(r['source'] for r in rows)),
        'missing_website_url': sum(not r['website_url'] for r in rows),
        'missing_tags': sum(not r['tags'] for r in rows),
        'target': target, 'target_met': len(rows) >= target if target is not None else None,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'design-cases.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    fields = ['id', 'name', 'website_url', 'website_domain', 'source', 'source_url', 'tags',
              'published_date', 'collected_date', 'url_precision', 'preview_url', 'sources']
    with (out / 'design-cases.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            flat = dict(r, tags='; '.join(r['tags']), sources=json.dumps(r['sources'], ensure_ascii=False))
            for k, value in flat.items():
                if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                    flat[k] = "'" + value
            writer.writerow(flat)
    with (out / 'design-cases.csv').open(encoding='utf-8-sig', newline='') as f:
        roundtrip = list(csv.DictReader(f))
    if len(roundtrip) != len(rows) or len({r['id'] for r in roundtrip}) != len(rows):
        raise ValueError('CSV round-trip or unique-ID validation failed')
    report['csv_roundtrip_rows'] = len(roundtrip)
    (out / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--target', type=int)
    args = parser.parse_args()
    if args.target is not None and args.target < 1:
        parser.error('--target must be positive')
    try:
        records = json.loads(args.input.read_text(encoding='utf-8-sig'))
        print(json.dumps(export(records, args.output_dir, args.target), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Export failed: {exc}\n')


if __name__ == '__main__':
    main()

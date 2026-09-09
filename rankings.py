"""Create a watchlist from dated, manually imported publisher rankings."""
import argparse
import csv
from datetime import date
from pathlib import Path


def select(path, source, as_of, top):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not {'published_date', 'source', 'rank', 'team'} <= set(reader.fieldnames or []):
            raise ValueError('Expected published_date,source,rank,team columns')
        rows = []
        for row in reader:
            published = date.fromisoformat(row['published_date'])
            rank = int(row['rank'])
            if rank < 1 or not row['team'].strip():
                raise ValueError('Invalid team or rank')
            if row['source'].strip().lower() == source.lower() and published <= as_of:
                rows.append((published, rank, row['team'].strip()))
    if not rows:
        raise ValueError('No matching ranking snapshot at or before as-of date')
    latest = max(r[0] for r in rows)
    selected = sorted((rank, team) for published, rank, team in rows if published == latest and rank <= top)
    if len({t for _, t in selected}) != len(selected):
        raise ValueError('Duplicate team in ranking snapshot')
    return latest, [team for _, team in selected]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--source', required=True, help='AP, Coaches, or CBS; ESPN can carry an AP poll, so label by poll')
    p.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    p.add_argument('--top', type=int, default=50)
    p.add_argument('--output', default='watchlist.txt')
    a = p.parse_args()
    if a.top < 1:
        p.error('--top must be positive')
    try:
        published, teams = select(a.input, a.source, a.as_of, a.top)
        Path(a.output).write_text('\n'.join(teams)+'\n', encoding='utf-8')
        print(f'Wrote {len(teams)} teams from {a.source}, published {published}, to {a.output}')
    except (ValueError, OSError) as e:
        p.error(str(e))


if __name__ == '__main__':
    main()

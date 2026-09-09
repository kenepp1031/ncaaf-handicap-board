"""Generate fictional data for smoke testing. These are NOT real games or odds."""
import csv
import random
from datetime import date, timedelta
from pathlib import Path


def main():
    rng = random.Random(42)
    folder = Path(__file__).parent / 'demo'
    folder.mkdir(exist_ok=True)
    teams = [f'Demo School {i:02d}' for i in range(1, 61)]
    strengths = {t: rng.gauss(0, 8) for t in teams}
    fields = ['date', 'home_team', 'away_team', 'home_score', 'away_score', 'neutral', 'home_spread', 'total', 'home_odds', 'away_odds']
    with (folder/'games.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for week in range(16):
            order = rng.sample(teams, len(teams))
            for h, a in zip(order[::2], order[1::2]):
                margin = strengths[h]-strengths[a]+3
                w.writerow(dict(date=date(2025, 8, 23)+timedelta(weeks=week), home_team=h, away_team=a,
                    home_score=max(0, round(27+margin/2+rng.gauss(0, 7))), away_score=max(0, round(27-margin/2+rng.gauss(0, 7))),
                    neutral=0, home_spread=round((-margin+rng.gauss(0, 4))*2)/2, total=54.5, home_odds=-110, away_odds=-110))
    with (folder/'fixtures.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'home_team', 'away_team', 'neutral', 'home_spread', 'total', 'home_bets_pct', 'home_handle_pct', 'market_observed_at'])
        for h, a in zip(teams[::2], teams[1::2]):
            w.writerow(['2025-12-20', h, a, 0, -3.5, 54.5, 45, 62, '2025-12-19T12:00:00-05:00'])
    print('Created fictional demo data in', folder)


if __name__ == '__main__':
    main()

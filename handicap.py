"""College football ratings and point-spread research. Python 3.10+, no dependencies."""
import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path


def read_games(path, completed=False):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = {'date', 'home_team', 'away_team'}
        if completed:
            required |= {'home_score', 'away_score'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Missing columns: ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                row['date'] = date.fromisoformat(row['date'].strip())
                for key in ('home_team', 'away_team'):
                    row[key] = row[key].strip()
                    if not row[key]:
                        raise ValueError('empty team name')
                if row['home_team'] == row['away_team']:
                    raise ValueError('teams must differ')
                neutral = row.get('neutral', '').strip().lower()
                if neutral not in ('', '0', '1', 'true', 'false'):
                    raise ValueError('neutral must be 0 or 1')
                row['neutral'] = neutral in ('1', 'true')
                for key in ('home_score', 'away_score', 'home_spread', 'total', 'home_odds', 'away_odds', 'home_adjustment', 'away_adjustment', 'home_bets_pct', 'home_handle_pct'):
                    value = row.get(key, '').strip()
                    row[key] = float(value) if value else None
                    if row[key] is not None and not math.isfinite(row[key]):
                        raise ValueError(key + ' must be finite')
                if completed and any(row[k] is None or row[k] < 0 for k in ('home_score', 'away_score')):
                    raise ValueError('completed games need nonnegative scores')
                for key in ('home_odds', 'away_odds'):
                    if row[key] is not None and abs(row[key]) < 100:
                        raise ValueError('American odds must have magnitude at least 100')
                for key in ('home_bets_pct', 'home_handle_pct'):
                    if row[key] is not None and not 0 <= row[key] <= 100:
                        raise ValueError(key + ' must be between 0 and 100')
                rows.append(row)
            except (ValueError, TypeError, AttributeError) as e:
                raise ValueError(f'{path}, line {line}: {e}') from e
    identities = [(r['date'], *sorted((r['home_team'], r['away_team']))) for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate game on the same date')
    return sorted(rows, key=lambda r: r['date'])


class Model:
    """Ridge offense/defense ratings fitted to points with recency weights.

    Positive defense coefficients mean more points conceded. Home advantage
    is an explicit prior, expressed as points of expected scoring margin.
    """
    def __init__(self, games, as_of, ridge=8., half_life=180., home_advantage=3.):
        games = [g for g in games if g['date'] < as_of]
        if not games:
            raise ValueError('No completed games before prediction date')
        self.teams = sorted({g[k] for g in games for k in ('home_team', 'away_team')})
        self.index = {t: i for i, t in enumerate(self.teams)}
        self.counts = {t: 0 for t in self.teams}
        self.hfa = home_advantage
        n = len(self.teams)
        samples = []
        for g in games:
            h, a = self.index[g['home_team']], self.index[g['away_team']]
            w = 2 ** (-(as_of - g['date']).days / half_life)
            venue = 0 if g['neutral'] else home_advantage / 2
            samples.extend([(h, n+a, g['home_score']-venue, w), (a, n+h, g['away_score']+venue, w)])
            self.counts[g['home_team']] += 1
            self.counts[g['away_team']] += 1
        self.base = sum(y*w for _, _, y, w in samples) / sum(w for _, _, _, w in samples)
        self.coef = [0.] * (2*n)
        columns = [[] for _ in self.coef]
        residual = [y-self.base for _, _, y, _ in samples]
        for i, (a, d, _, w) in enumerate(samples):
            columns[a].append((i, w))
            columns[d].append((i, w))
        for _ in range(1000):
            change = 0.
            shift = sum(residual[i]*s[3] for i, s in enumerate(samples)) / sum(s[3] for s in samples)
            self.base += shift
            residual = [r-shift for r in residual]
            change = abs(shift)
            for j, col in enumerate(columns):
                old = self.coef[j]
                new = sum(w*(residual[i]+old) for i, w in col) / (ridge+sum(w for _, w in col))
                self.coef[j] = new
                delta = new-old
                change = max(change, abs(delta))
                for i, _ in col:
                    residual[i] -= delta
            if change < 1e-7:
                break

    def predict(self, game):
        h, a = game['home_team'], game['away_team']
        unknown = [t for t in (h, a) if t not in self.index]
        if unknown:
            raise ValueError('Unrated team(s): ' + ', '.join(unknown))
        n = len(self.teams)
        venue = 0 if game['neutral'] else self.hfa / 2
        hp = max(0., self.base+self.coef[self.index[h]]+self.coef[n+self.index[a]]+venue+(game.get('home_adjustment') or 0))
        ap = max(0., self.base+self.coef[self.index[a]]+self.coef[n+self.index[h]]-venue+(game.get('away_adjustment') or 0))
        return hp, ap

    def ratings(self):
        n = len(self.teams)
        return sorted([{'team': t, 'rating': round(self.coef[i]-self.coef[n+i], 3), 'offense': round(self.coef[i], 3), 'defense': round(-self.coef[n+i], 3), 'games': self.counts[t]} for i, t in enumerate(self.teams)], key=lambda r: (-r['rating'], r['team']))


def projection(model, game):
    hp, ap = model.predict(game)
    edge = None if game['home_spread'] is None else hp-ap+game['home_spread']
    return {'date': game['date'].isoformat(), 'home_team': game['home_team'], 'away_team': game['away_team'],
            'home_points': round(hp, 2), 'away_points': round(ap, 2), 'fair_home_spread': round(ap-hp, 2),
            'projected_total': round(hp+ap, 2), 'market_home_spread': game['home_spread'],
            'home_edge_points': None if edge is None else round(edge, 2),
            'total_edge_points': None if game['total'] is None else round(hp+ap-game['total'], 2),
            'lean': 'none' if edge is None or abs(edge) < 1e-9 else (game['home_team'] if edge > 0 else game['away_team']),
            'home_bets_pct': game.get('home_bets_pct'), 'home_handle_pct': game.get('home_handle_pct'),
            'handle_minus_bets_pct': None if game.get('home_bets_pct') is None or game.get('home_handle_pct') is None else round(game['home_handle_pct']-game['home_bets_pct'], 2),
            'market_observed_at': game.get('market_observed_at', ''),
            'home_history_games': model.counts[game['home_team']], 'away_history_games': model.counts[game['away_team']]}


def backtest(games, args):
    errors, total_errors, results = [], [], []
    skipped = 0
    cached_date, model = None, None
    for g in games:
        if g['date'] != cached_date:
            cached_date = g['date']
            prior = [r for r in games if r['date'] < cached_date]
            model = Model(prior, cached_date, args.ridge, args.half_life, args.home_advantage) if prior else None
        if model is None or any(model.counts.get(g[k], 0) < args.min_games for k in ('home_team', 'away_team')):
            skipped += 1
            continue
        hp, ap = model.predict(g)
        margin = g['home_score']-g['away_score']
        errors.append(abs(hp-ap-margin))
        total_errors.append(abs(hp+ap-g['home_score']-g['away_score']))
        if g['home_spread'] is None:
            continue
        edge = hp-ap+g['home_spread']
        if abs(edge) < args.threshold or abs(edge) < 1e-9:
            continue
        home = edge > 0
        covered = (margin+g['home_spread']) * (1 if home else -1)
        odds = g['home_odds' if home else 'away_odds']
        odds = -110 if odds is None else odds
        profit = 0 if covered == 0 else (-1 if covered < 0 else (odds/100 if odds > 0 else 100/abs(odds)))
        results.append({'date': g['date'].isoformat(), 'team': g['home_team'] if home else g['away_team'], 'edge': round(abs(edge), 2), 'odds': odds, 'result': 'push' if covered == 0 else ('win' if covered > 0 else 'loss'), 'profit_units': profit})
    return {'evaluated_games': len(errors), 'skipped_games': skipped,
            'margin_mae': sum(errors)/len(errors) if errors else None,
            'total_mae': sum(total_errors)/len(total_errors) if total_errors else None,
            'bets': len(results), 'wins': sum(r['result']=='win' for r in results), 'losses': sum(r['result']=='loss' for r in results),
            'pushes': sum(r['result']=='push' for r in results), 'profit_units': sum(r['profit_units'] for r in results),
            'roi': sum(r['profit_units'] for r in results)/len(results) if results else None,
            'bet_log': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['ratings', 'predict', 'backtest'])
    p.add_argument('--games', required=True, help='Completed games CSV')
    p.add_argument('--fixtures', help='Upcoming games CSV for predict')
    p.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    p.add_argument('--top', type=int, default=50)
    p.add_argument('--watchlist', help='Text file: one exact team name per line; filters displayed ratings and fixtures')
    p.add_argument('--ridge', type=float, default=8.)
    p.add_argument('--half-life', type=float, default=180.)
    p.add_argument('--home-advantage', type=float, default=3.)
    p.add_argument('--min-games', type=int, default=5)
    p.add_argument('--threshold', type=float, default=3.)
    p.add_argument('--output', help='Save JSON report')
    args = p.parse_args()
    if not all(math.isfinite(v) for v in (args.ridge, args.half_life, args.home_advantage, args.threshold)) or args.ridge <= 0 or args.half_life <= 0 or args.top <= 0 or args.min_games < 1 or args.threshold < 0:
        p.error('Invalid model or filter settings')
    try:
        games = read_games(args.games, completed=True)
        watch = set(Path(args.watchlist).read_text(encoding='utf-8-sig').splitlines()) if args.watchlist else None
        watch = {t.strip() for t in watch if t.strip()} if watch is not None else None
        if args.command == 'backtest':
            report = backtest([g for g in games if g['date'] < args.as_of], args)
        else:
            model = Model(games, args.as_of, args.ridge, args.half_life, args.home_advantage)
            if watch and watch - set(model.teams):
                raise ValueError('Unknown watchlist teams: ' + ', '.join(sorted(watch-set(model.teams))))
            if args.command == 'ratings':
                report = [r for r in model.ratings() if watch is None or r['team'] in watch][:args.top]
            else:
                if not args.fixtures:
                    p.error('predict requires --fixtures')
                fixtures = read_games(args.fixtures)
                if any(g['date'] < args.as_of for g in fixtures):
                    raise ValueError('Fixture dates must be on or after --as-of')
                report = [projection(model, g) for g in fixtures if watch is None or {g['home_team'], g['away_team']} & watch]
                report.sort(key=lambda r: abs(r['home_edge_points'] or 0), reverse=True)
        output = json.dumps(report, indent=2, allow_nan=False)
        if args.output:
            Path(args.output).write_text(output+'\n', encoding='utf-8')
        print(output)
    except (ValueError, OSError) as e:
        p.error(str(e))


if __name__ == '__main__':
    main()

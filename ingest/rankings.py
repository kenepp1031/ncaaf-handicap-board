"""CBS / AP / Coaches poll ingest + composite Top-50 blend.

Ported from feeds.py's parse_cbs()/rankings-fetch/composite_teams(). Writes
one row per (team, poll_type) to `polls` instead of recomputing the blend
from a live.json blob on every dashboard load.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CBS, ESPN, clean, fetch_json, fetch_text, normal
from db.db import connect


def parse_cbs(page: str) -> dict[str, int]:
    ranks = {}
    for row in re.findall(r'<tr class="TableBase-bodyTr".*?</tr>', page, re.S):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 2:
            continue
        team = re.search(r'<span class="TeamName">(.*?)</span>', cells[1], re.S)
        rank = clean(cells[0])
        if team and rank.isdigit():
            ranks[normal(clean(team[1]))] = int(rank)
    if len(ranks) < 50:
        raise ValueError('CBS layout changed or fewer than 50 rankings returned')
    return ranks


def composite_teams(team_rows: list[dict], cbs: dict, ap: dict, coaches: dict) -> list[dict]:
    """team_rows: [{'id':..., 'name':...}, ...] every team seen in current games."""
    teams = {}
    for t in team_rows:
        key = t['id']
        cr = cbs.get(normal(t['name']))
        ar, ur = ap.get(key), coaches.get(key)
        if cr is None and ar is None and ur is None:
            continue
        scores = []
        for ranks, rank, size in ((cbs, cr, 50), (ap, ar, 25), (coaches, ur, 25)):
            if ranks:
                scores.append(max(0, (size + 1 - (rank or size + 1)) / size))
        teams[key] = dict(id=key, team=t['name'], cbs=cr, ap=ar, coaches=ur,
                           score=round(100 * sum(scores) / len(scores), 6) if scores else 0)
    ordered = sorted(teams.values(), key=lambda t: (-t['score'], t['cbs'] or 999, t['team']))[:50]
    for i, t in enumerate(ordered, 1):
        t['rank'] = i
    return ordered


def ingest(season: int) -> dict:
    with connect() as con:
        team_rows = [dict(r) for r in con.execute('SELECT team_id AS id, name FROM teams')]
    if not team_rows:
        raise ValueError('No teams in DB yet — run ingest.espn_scoreboard first')

    now = datetime.now().astimezone().isoformat(timespec='seconds')
    cbs = parse_cbs(fetch_text(CBS))

    rankings = fetch_json(ESPN + 'rankings')
    poll = next(r for r in rankings['rankings'] if r.get('type') == 'ap')
    ap = {str(r['team']['id']): r['current'] for r in poll['ranks']}
    coaches_poll = next((r for r in rankings['rankings'] if r.get('type') == 'usa'), None)
    coaches = {str(r['team']['id']): r['current'] for r in coaches_poll['ranks'] if r['current'] <= 25} if coaches_poll else {}

    top50 = composite_teams(team_rows, cbs, ap, coaches)
    # CBS's keys are themselves sometimes abbreviated ('missstate'); canonicalize
    # through the alias map before comparing against ESPN-side team names.
    fbs_names = {_fbs_alias(k) for k in cbs}

    with connect() as con:
        for row in team_rows:
            is_fbs = 1 if (not fbs_names) or _fbs_alias(normal(row['name'])) in fbs_names else 0
            con.execute('UPDATE teams SET fbs=? WHERE team_id=?', (is_fbs, row['id']))
        for team_id, rank in cbs_by_id(team_rows, cbs).items():
            _upsert_poll(con, team_id, season, 'cbs', rank, now)
        for team_id, rank in ap.items():
            _upsert_poll(con, team_id, season, 'ap', rank, now)
        for team_id, rank in coaches.items():
            _upsert_poll(con, team_id, season, 'coaches', rank, now)
        for t in top50:
            _upsert_poll(con, t['id'], season, 'combined', t['rank'], now)
        con.commit()
    return {'cbs': len(cbs), 'ap': len(ap), 'coaches': len(coaches), 'combined': len(top50)}


def cbs_by_id(team_rows, cbs):
    out = {}
    for row in team_rows:
        rank = cbs.get(normal(row['name']))
        if rank is not None:
            out[row['id']] = rank
    return out


# CBS's abbreviated school names, so the FBS-membership check doesn't miss
# teams CBS spells differently than ESPN. Ported from power.py's FBS_ALIASES.
_FBS_ALIASES = dict(zip(
    'missstate ndakotast iowast sandiegost michiganst wmichigan coloradost washingtonst gasouthern jacksonvillest arkansasst appst fresnost texasst utahst kennesawst fau ccarolina fiu newmexicost somiss emichigan cmichigan georgiast sacramentost missourist middletenn kentst ballst sanjosstate'.split(),
    'mississippistate northdakotastate iowastate sandiegostate michiganstate westernmichigan coloradostate washingtonstate georgiasouthern jacksonvillestate arkansasstate appalachianstate fresnostate texasstate utahstate kennesawstate floridaatlantic coastalcarolina floridainternational newmexicostate southernmiss easternmichigan centralmichigan georgiastate sacramentostate missouristate middletennessee kentstate ballstate sanjosestate'.split()))
_FBS_ALIASES.update(fiu='floridainternational', newmexicost='newmexicostate', somiss='southernmiss')


def _fbs_alias(key: str) -> str:
    return _FBS_ALIASES.get(key, key)


def _upsert_poll(con, team_id, season, poll_type, rank, now):
    con.execute(
        """INSERT INTO polls (team_id, season, poll_type, rank, captured_at) VALUES (?,?,?,?,?)
           ON CONFLICT(team_id, season, poll_type) DO UPDATE SET rank=excluded.rank, captured_at=excluded.captured_at""",
        (team_id, season, poll_type, rank, now))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(ingest(a.season))

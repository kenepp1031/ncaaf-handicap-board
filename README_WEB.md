# Publish the NCAAF board for free

This project now contains a phone-friendly Streamlit web edition in
`streamlit_app.py`. It reads `data/web_snapshot.json`, a small committed
snapshot, so the deployed board does not depend on the desktop program or
this PC staying on. It never touches `dashboard.py`, `app.js`, `storage.py`,
or any other file the live server uses, and it has no editing capability —
saving/editing picks still only happens in the desktop app.

## Why a separate snapshot file (not the live cache)

The desktop app's richest data — matchups, model projections, power ratings —
lives in `data/live.json`, which is 1.6MB+, regenerated on every refresh, and
deliberately gitignored (see `.gitignore`). The only files already tracked in
git are `data/picks.sqlite3` (your saved picks) and `data/rank_history.json`
(poll history), and `picks.sqlite3` alone doesn't contain the season's
matchups or model output — just your own bets. So `export_web_snapshot.py`
builds a small, purpose-made file (`data/web_snapshot.json`, a few hundred KB)
containing just what the public page needs: each Top-50 matchup this season
(teams, market spread/total, model lean/projection when available, your saved
pick), plus the combined rankings table.

## Publish it

1. Run the desktop app at least once this session (`Start Weekly Picks.cmd`)
   so `data/live.json` is fresh.
2. Generate the snapshot:

   ```
   python export_web_snapshot.py
   ```

   This writes `data/web_snapshot.json`.
3. Create a public GitHub repository and upload this folder, including
   `streamlit_app.py`, `requirements.txt`, `export_web_snapshot.py`, and
   `data/web_snapshot.json`. Do **not** upload `data/live.json`, `data/nil.json`,
   `data/talent.json`, `data/penalties.json`, `data/locations.json`, or
   `data/servers.json` — those stay gitignored, refetchable, and unnecessary
   for the public view.
4. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and sign in.
5. Select **Create app**, select the GitHub repository, and choose
   `streamlit_app.py` as the entry point.
6. Choose an app address and deploy. Save the resulting `https://…streamlit.app`
   address in your phone browser.

Streamlit Community Cloud is free and runs the published app independently of
your PC. The app is public if the GitHub repository/app is public.

## Keeping it current

The cloud app intentionally uses the snapshot committed to GitHub. To refresh:

1. Use the desktop app as usual (open it, let it sync) so `data/live.json`
   and the picks database are current.
2. Run `python export_web_snapshot.py` again.
3. Commit and push the updated `data/web_snapshot.json`.

Streamlit Cloud redeploys automatically on push. This prevents a public
website from needing access to your home computer.

## Limitations of the web edition

- No editing: saving, editing, or starring picks only works in the desktop
  app. The web page is read-only.
- The snapshot is only as fresh as your last `export_web_snapshot.py` run —
  there's no live polling like the desktop app's 5-second refresh.
- Only Top-50/ranked matchups are included (matching what the desktop app's
  print/board views consider "this week's games"); games between two
  unranked teams aren't in the snapshot.
- Weather details, injury-style notes, betting splits, spending/talent
  detail tables, and full model-detail breakdowns shown in the desktop app's
  "Model detail" panel are left out of the snapshot to keep it small; only
  the headline lean, projected score/total, and confidence are included.

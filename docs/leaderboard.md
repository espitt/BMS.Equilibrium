# Minigame leaderboard

The games on the Charging screen share one leaderboard between everyone who has the app. Players need
no GitHub account: they type a name beside the game and their best scores appear for everybody.

## How it works

- The scores are one file, `scores.json`, in a public GitHub repository (`REPO` in
  `app/equilibrium/leaderboard.py`, at present `espitt/BMS.Scores`).
- **Reading** is a plain download of that file, which needs no account and has no hourly limit.
- **Writing** uses GitHub's API with an access token that release builds carry. The app reads the file,
  adds the score, and saves it back as a commit. If two players save at the same moment, the second
  reads the file again and retries.
- There is a board for each game and level, holding the top 10. Each player has one place on a board,
  their best. A best set while offline is sent the next time the leaderboard is opened or refreshed.
- Only the name a player types and their scores are published. Nothing is sent until they enter a name.

## Setting it up (once)

1. **Make the scores repository.** On GitHub, create a public repository named `BMS.Scores` under
   `espitt`, with "Add a README" ticked so that it has a `main` branch. To use another name or owner,
   change `REPO` in `app/equilibrium/leaderboard.py`.
2. **Make the token.** In GitHub: Settings > Developer settings > Personal access tokens >
   Fine-grained tokens > Generate new token.
   - Repository access: "Only select repositories", and choose `BMS.Scores` alone.
   - Permissions: Repository permissions > Contents > "Read and write". Nothing else.
   - Expiration: as long as GitHub allows. When it expires, installed copies can still show the
     leaderboard but can no longer add to it, until a release is made with a new token.
3. **Give the token to the release build.** In the `BMS.Equilibrium` repository: Settings > Secrets and
   variables > Actions > New repository secret, named `LEADERBOARD_TOKEN`, holding the token.
4. **Release.** The next tagged release stamps the token into the app (`packaging/build.py`). Copies
   installed or updated from that release can post scores.

To post scores from a source run, set the environment variable `EQUILIBRIUM_LEADERBOARD_TOKEN` to the
token before starting the app. Without it, a source run shows the leaderboard but cannot add to it.

## What to know about the token

- **Never commit it.** GitHub scans public repositories and revokes any token it finds. That is why the
  token lives in a secret and is stamped in at build time. A test fails if `TOKEN` is ever non-empty in
  the source.
- **It is not truly secret.** Anyone determined can extract it from a released app. This is why it must
  be limited to the scores repository: the worst they can do is change the leaderboard. Scores are also
  sent by the app itself, so a modified app can post any score. Treat the leaderboard as for fun.
- **Repairing it.** `scores.json` is ordinary JSON and every change is a commit, so a spoiled board can
  be fixed by editing the file or reverting a commit on GitHub. To lock out a leaked token, revoke it,
  make a new one, update the secret and release again.

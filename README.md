# The Founder Hour — Final Migration Build

This repository generates the complete static website from:

- `source/squarespace.xml` — the Squarespace episode export
- `https://feeds.simplecast.com/C4Z8vbZb` — the live Simplecast RSS feed

## Deploy on Netlify

Connect this repository to Netlify. The included `netlify.toml` automatically uses:

- Build command: `python3 scripts/build.py`
- Publish directory: `dist`

During every deployment, the script downloads the Simplecast feed, matches it to the Squarespace pages, and creates the full episode archive.

## Preview locally

```bash
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

Then open `http://localhost:8000`.

If your computer cannot reach Simplecast, the pages will still generate from Squarespace. Netlify should retrieve the RSS feed during deployment.

## Before moving the domain

1. Check `migration-report.json` after a local build or inspect the Netlify build log.
2. Test at least 10 episode pages across different years.
3. Confirm images and Simplecast players work.
4. Compare old and new episode URLs.
5. Keep Squarespace active until the custom domain has been tested on Netlify.

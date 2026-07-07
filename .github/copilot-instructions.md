# Copilot Repository Instructions

Read `AGENTS.md` first. This is a static GitHub Pages site for `https://tendijournal.app`.

- On a fresh clone, run `npm ci` and `npm run install:browsers` before browser tests.
- Run `npm test` before handoff.
- Use `npm run verify` for static metadata/link/content checks.
- Use `npm run test:browser` for Playwright rendering screenshots and axe accessibility smoke tests.
- Keep the site plain HTML/CSS/JS. Do not add a framework or bundler.
- Do not reintroduce Bloomery, Classic Garden, Mind Garden, Past Gardens/Terrarium, Mossbear, or procedural Garden positioning.
- Cross-check `/Users/charistas/Dev/tendi/docs/README.md` when public app behavior or privacy wording depends on current Tendi app behavior.

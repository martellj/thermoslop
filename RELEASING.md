# Releasing ThermoSlop

One version covers the Python package, the CLI, the MCP server and the
Omarchy plugin. `src/thermoslop/__init__.py` is the source; `scripts/release`
copies it everywhere else.

## Cutting a release

1. Make sure `CHANGELOG.md` has everything under `## [Unreleased]`.
2. On a clean, pushed `main`:
   ```bash
   scripts/release 0.3.0
   ```
   It runs the tests, sets the version, dates the changelog, builds and
   inspects the wheel and sdist (including the private-strings scan, which
   only works on the owner's machine), checks the plugin, then commits
   "Release v0.3.0" and creates the tag. It doesn't push.
3. Review with `git show`, then:
   ```bash
   git push --follow-tags
   ```
4. In GitHub Actions, the **Release** workflow:
   1. tests on Linux and macOS
   2. builds and inspects the artifacts and scans them for secrets
   3. installs each one into a clean venv and tries it
   4. **waits for approval** of the `pypi` environment, then publishes to PyPI
      by trusted publishing (no API token exists)
   5. creates the GitHub Release from the changelog section
   6. copies the plugin to
      [martellj/thermoslop-omarchy](https://github.com/martellj/thermoslop-omarchy)
      as one commit, with the same tag. `omarchy plugin update` sees it from
      then on.

To check a release without publishing, run the Release workflow by hand
(Actions → Release → Run workflow). Everything up to the smoke tests runs;
the publish jobs only run for tags.

## When a run fails partway

Every publish step skips what already exists:
- PyPI uploads use `skip-existing`
- the GitHub Release is only created if missing
- the plugin sync stops if the plugin repo already has the tag

So fix the cause, then **re-run the failed jobs** of the same workflow run.
Don't make a new tag for the same version.

If the problem is in the release itself, such as a broken build, publish a
new version instead:
- PyPI never lets a version be replaced, so **yank** the bad one on pypi.org.
  Installs then skip it unless they ask for it exactly.
- Release a patch, e.g. 0.3.1.
- If the plugin repo got a bad commit, the next release supersedes it.
  Plugin users can also roll back in `~/.config/omarchy/plugins/martellj.thermoslop`
  with git.

## One-time setup (already done for the first release)

- **PyPI:** a trusted publisher for project `thermoslop`, repo
  `martellj/thermoslop`, workflow `release.yml`, environment `pypi`. A pending
  publisher does **not** reserve the name, so check that the name is still
  free right before the first release.
- **GitHub:**
  - the `pypi` environment, with the owner as required reviewer
  - a ruleset so only the owner can create `v*` tags
  - secret `PLUGIN_DEPLOY_KEY`: the private half of a deploy key with write
    access on `martellj/thermoslop-omarchy`

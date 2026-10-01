# CI and releases

Pull requests and pushes to `main`, `beta`, and `dev` run pytest and pre-commit.
The workflow can also be started manually to run these checks.

## Publish a release

1. Update `version`, the latest release in
   `share/metainfo/io.github.mall0r.Twinverse.metainfo.xml`, and the version
   references in the READMEs and AppImage packaging script.
2. Commit and push those changes yourself.
3. Tag that commit and push the tag, for example:

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

A pushed stable tag (`vMAJOR.MINOR.PATCH`) runs the checks, verifies that the tag,
version file, and latest AppStream release agree, builds the Flatpak, and creates
a GitHub release with generated notes and the bundle attached. The bundle is
also saved as a workflow artifact for 14 days. If publication fails, rerun only
the failed job to reuse the build artifact.

The workflows do not bump versions, create commits, push branches, or create
tags. Only the publication job has repository write permission, to publish the
release for your existing tag. AppImage builds and prerelease tags are not part
of this workflow.

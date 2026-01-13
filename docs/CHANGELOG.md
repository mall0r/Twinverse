## 1.0.0 (2026-01-10)

### ⚠ BREAKING CHANGES

* **cicd:** Tests are no longer executed during the Flatpak build

* build: remove aarch64 architecture support

Updated GitHub Actions workflow to build only for x86_64
                                                                                                                                  - Simplified Makefile to not depend on ARCH variable
- Removed ARM64 emulation steps
- Project now supports only x86_64 architecture

* chore: Updates GitHub Actions workflow script for safe changelog handling

- Modifies the semantic versioning script to avoid errors with special characters in CHANGELOG.md

- Implements a safe method for setting environment and output variables in GitHub Actions

- Uses multiline delimiter (EOF) to avoid formatting errors in changelog content

* chore: Updates artifact name in GitHub Actions workflow

- Changes the artifact name from 'flatpak-x86_64-{version}' to 'flatpak-{version}-x86_64'

- Ensures consistency in the artifact name between upload and download in the workflow

- Adjusts dependencies between jobs to maintain correct pipeline functionality

* chore: Updates GitHub Actions workflow for version consistency

- Adds a step to update metainfo.xml with the semantic-version version

- Implements a fallback to version 0.0.0 if the semantic version is invalid

- Ensures consistency between the version determined by semantic-version and the version used in the Flatpak build

- Maintains the correct execution order of the jobs: analyze → semantic → build → create-release

* chore: update version manager

add function force to uptade-version

* chore(workflow): updates workflow to include semantic step with make update-version-force

- Adds new 'semantic' step that executes make update-version-force

with the version obtained via semantic versioning
- Updates 'create-release' step to retrieve the version from the version file
- Maintains consistency in the artifact name between build and create-release
- Maintains functionality of the analyze, build, and publish flathub steps

This change only affects the CI/CD process and does not alter the application functionality for the end user.

* chore: remove redundant Update metainfo.xml

* Update version to 0.11.2

Remove redundant metainfo update from release workflow. Update version
number in READMEs, version file, and metainfo.xml. Adjust version format
validation message to reflect current version. Fix metainfo.xml version
update to handle the 'type' attribute correctly.

* Bump linxdeploy version to 0.11.2

* refactor: Improve release workflow with semantic-release

Enhance the release workflow by integrating semantic-release for
automated versioning and changelog generation. This change includes:

- Setting up Node.js and installing necessary semantic-release packages.
- Performing a dry-run of semantic-release to determine the next version
  and generate a changelog preview.
- Configuring Git for commits with the GitHub Actions bot.
- Updating version files and committing the changes with an automated
  message.
- Pushing changes to the current branch.
- Adjusting the Flatpak manifest path.
- Configuring the @semantic-release/git plugin with a list of assets to
  be included in commits and defining a commit message format.

* build: release pipeline to use semantic versioning

The release pipeline has been refactored to leverage semantic versioning
for tag creation and release management. This commit also updates the
workflow to correctly push changes to the appropriate branch and create
new tags.

* build: Update release workflow to use semantic-release

* build(refactor): release job to use semantic-release-action

Replace custom semantic-release logic with the official
`cycjimmy/semantic-release-action` to simplify the release workflow and
improve maintainability. This action handles version determination,
changelog generation, and Git operations.

* chore: Update release workflow for semantic-release

Add GITHUB_TOKEN to checkout action and update release tagging to use
the `v` prefix. Also, remove the unnecessary `get_version` step.

* choice: Update release workflow actions

* refactor: Update semantic-release action version

Pin the release action to v6 to ensure consistent behavior.

* chore: Update semantic-release-action to v25

* chore: Configure release notes generator preset

Update `@semantic-release/release-notes-generator` to use the
`conventionalcommits` preset for generating release notes. This ensures
consistency with the commit message format.

* chore: Update Node.js version and release branches

* chore: Remove exec plugin from semantic-release

* chore: Remove unnecessary GitHub Actions jobs

The `flathub.yml` workflow and parts of `release.yml` related to
creating releases and publishing to Flathub have been commented out.
These jobs are either redundant or no longer intended to be run directly
by these workflows.

* chore: Remove appimage build from release config

* chore: Configure release branches to not prerelease

* build: Simplify build dependencies

Remove version specifiers from setuptools and setuptools_scm
requirements. Update install command in build script to use pip install
.[test] for dependencies and development requirements.

* refactor(Makefile): update style to follow package-flatpak.sh pattern

- Add print_header, print_success and print_error functions with colored formatting
- Organize sections with comments in the format # ===== SECTION NAME =====
- Update all targets to use the new print functions
- Improve visual consistency with the package-flatpak.sh script
- Keep all existing functionalities intact

* ci(workflows): serialize CI and release execution

Refactors the GitHub Actions workflows to run sequentially, ensuring the release process only begins after all CI checks have successfully completed.

Previously, the CI and Release workflows were triggered in parallel by a push event. This could result in a new version being released by the `semantic-release` job before all tests in the CI workflow had finished, potentially leading to a release with failing tests.

This commit introduces the following changes:
- The `analyze` job (static analysis) has been moved from the `release.yml` workflow to the `ci.yml` workflow.
- The `release.yml` workflow is now triggered by the successful completion of the `ci.yml` workflow via the `workflow_run` event.
- The `on: push` trigger has been removed from `release.yml` to prevent parallel execution.

This new sequential process guarantees that releases are only created from commits that have passed all static analysis and testing stages.

* ci(fix): install correct dependencies

* chore(ci): refactor CI workflow configuration

- Remove redundant system dependencies installation steps
- Consolidate pip dependency installation process
- Streamline pytest execution steps
- Reorganize workflow to improve readability and maintainability

* chore(ci): configure release workflow to run after successful CI

- Add workflow_run trigger to release.yml to listen for CI completion
- Set types to 'completed' and add condition to only proceed on success
- Add conditional logic to ensure release only runs after successful CI
- Maintain existing manual dispatch functionality for releases

* ci(fix): configure release workflow to only run after successful CI

- Remove direct push/pull_request triggers from release workflow
- Keep only workflow_run trigger to listen for CI completion
- Add condition to ensure release only runs after successful CI
- Maintain manual dispatch functionality for releases

* ci(fix): add --user flag to flatpak install commands and update workflow triggers

- Add --user flag to flatpak install commands to avoid permission issues
- Remove direct push/pull_request triggers from release workflow
- Keep only workflow_run trigger to listen for CI completion
- Add condition to ensure release only runs after successful CI
- Maintain manual dispatch functionality for releases

* ci(fix): Add both user and system Flathub repository to fix flatpak-builder dependency issue

* refactor(ci): restructure CI workflow and update release dependencies

- Remove flatpak-builder steps from CI workflow
- Add system-wide Flathub repository configuration for both user and system
- Restructure release workflow to properly depend on CI completion
- Simplify CI workflow by removing redundant flatpak build steps
- Configure release workflow to only run after successful CI completion

* refactor(ci): remove GNOME runtime installation from CI workflow

- Remove GNOME runtime and SDK installation steps from CI workflow
- Keep only pip dependencies and pre-commit checks in CI workflow
- Allow release workflow to handle GNOME runtime dependencies separately

* build(fix): Remove unnecessary logic to initiate semantic-release.

* chore(workflow): consolidate CI and release workflows into single CI/CD pipeline

- Combine CI and release workflows into a unified ci_cd.yml file
- Maintain all functionality from both previous workflows
- Add dependency between unit-tests and semantic-release jobs
- Preserve manual dispatch functionality for releases
- Simplify workflow structure by consolidating into single pipeline

* chore(fix): Remove unnecessary logic to initiate semantic-release.

* style(formatting): reflow code to 120 character line length

Updated the black code formatter configuration in `pyproject.toml` to increase the maximum line length from 88 to 120 characters.

This change improves readability and developer experience on modern, wider displays by reducing aggressive and often unnatural line breaks in complex statements.

The codebase has been reformatted to apply the new line length standard.

* chore(refactor): update CI/CD workflow and release configuration

- Change monitored branches in CI/CD workflow from [main, master, build/workflow] to [main, beta, dev]
- Update release configuration to add draft property to main, beta, and dev branches
- Remove redundant draft property from flatpak release settings

* build(release): add changelog generation to release process

The CHANGELOG.md file was not being automatically updated during the release process. This was because the semantic-release configuration was missing the necessary plugin to handle changelog file generation.

This commit introduces the `@semantic-release/changelog` plugin to the release workflow. The plugin is now included in the CI installation step and configured in `.releaserc.json` to write the generated release notes to `CHANGELOG.md` before a new version is committed and released.

* style(changelog): reset changelog
* Complete project rebrand and architectural
simplification

# Changelog

All notable changes to this project will be documented in this file. This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

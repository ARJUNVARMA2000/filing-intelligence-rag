# Lessons

## PDF citation viewers

- Verify the exact asset names and module format for the pinned PDF.js distribution before integrating it; a version number alone does not make legacy `.js` paths compatible with an ES-module release.
- Browser-test at least one real PDF and one citation beyond page 1. HTML tests cannot detect blank canvases, incorrect viewer containers, stuck search states, or broken responsive layout.
- Build highlight anchors from source-only text, never from retrieval context such as `Document:` or `Section:` prefixes that do not exist in the PDF.
- Treat highlighting as a confirmed runtime state. Open the cited page first, report an explicit no-match state when needed, and keep a visible raw-PDF fallback.

## Deployment targeting

- Never infer that an existing Cloud Run service is the intended release target from repository configuration alone. Before deploying, confirm whether the user wants to update an existing URL or create an isolated deployment.
- For an isolated release, use unique backend and frontend service names, verify the resulting URLs before changing traffic, and leave or restore pre-existing services to their prior revisions.
- Record the repository identity, cloud project, service names, and public URLs as separate release facts; a GitHub fork and a Cloud Run deployment do not share identity automatically.
- Keep the README canonical and forward-looking. When the user wants only the current deployment documented, keep old URLs and migration history out of user-facing docs and explain them only in the handoff.
- Before associating a deployment with a GitHub project, verify the repository, default branch, release branch, and deployed build separately. A feature branch inside a shared repository is not a standalone repository.
- When the user requires ownership separation from contributors, create a clean-history standalone repository first, verify it, and only then remove the release branch and pull request from the shared repository.
- Brand portfolio infrastructure as a product, never as a person's account name. Repository slugs, service names, image packages, URLs, documentation headings, and deployment defaults should all reinforce the public product identity.
- Treat an instruction to preserve a shared repository as a hard write boundary: inventory it only with read-only commands, deploy new isolated resources first, and verify shared repository refs, service revisions, and traffic remain unchanged afterward.
- A cosmetic product rename should not cascade into IAM identities, data buckets, environment-variable contracts, or shared registries; retain compatibility infrastructure unless the user explicitly authorizes a migration.
- When the user changes a release name during an active build, cancel the build immediately, verify that no live service was created, amend the unpublished/private release commit, and restart deployment only after the final name is reflected everywhere.

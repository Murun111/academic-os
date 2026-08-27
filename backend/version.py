"""Single source of truth for the app version.

Bump this together with the git tag (v<APP_VERSION>) when cutting a release —
CI builds installers from tags, and the in-app update check compares this
value against the latest GitHub release tag.
"""
APP_VERSION = "0.5.0"

# GitHub repository the update check points at ("owner/name").
UPDATE_REPO = "Murun111/academic-os"

# SPDX-FileCopyrightText: 2026 CERN.
# SPDX-License-Identifier: MIT

"""Tests for building the release zipball URL."""

import json

import pytest
from invenio_webhooks.models import Event

from invenio_github.api import GitHubAPI, GitHubRelease
from invenio_github.errors import ReleaseZipballFetchError
from invenio_github.models import Release, ReleaseStatus, Repository

from .fixtures import PAYLOAD as github_payload_fixture


def _make_release(
    app,
    db,
    test_user,
    tag="v1.0",
    payload_zipball="https://evil.example/malicious.zip",
    repo_full_name="auser/repo-2",
    repo_id=2,
):
    """Build a GitHubRelease whose stored repo full name is ``repo_full_name``."""
    api = GitHubAPI(test_user.id)
    api.init_account()
    repo = Repository.create(test_user.id, repo_id, repo_full_name)
    repo.hook = 1234

    payload = github_payload_fixture("auser", "repo-2", repo_id, tag=tag)
    payload["release"]["zipball_url"] = payload_zipball

    ctx = app.test_request_context(
        headers=[("Content-Type", "application/json")], data=json.dumps(payload)
    )
    ctx.push()
    event = Event.create(receiver_id="github", user_id=test_user.id)
    db.session.add(event)
    db.session.commit()
    release = Release(
        release_id=payload["release"]["id"],
        tag=tag,
        repository=repo,
        event=event,
        status=ReleaseStatus.RECEIVED,
    )
    rel = GitHubRelease(release)
    return rel, ctx


def _zipball_url(app, db, test_user, **kwargs):
    """Return ``release_zipball_url`` for a release built with ``kwargs``."""
    rel, ctx = _make_release(app, db, test_user, **kwargs)
    try:
        return rel.release_zipball_url
    finally:
        ctx.pop()


def test_zipball_url_ignores_payload(app, db, test_user, github_api):
    """The zipball URL is built from the stored repo, not the payload."""
    url = _zipball_url(app, db, test_user)
    assert url == "https://api.github.com/repos/auser/repo-2/zipball/v1.0"


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("release/v1.0", "release/v1.0"),  # "/" is kept, as in GitHub's URLs
        ("v1?x#y z", "v1%3Fx%23y%20z"),  # special characters are encoded
    ],
)
def test_zipball_url_tag_encoding(app, db, test_user, github_api, tag, expected):
    """Tags with "/" or special characters still give a valid URL."""
    url = _zipball_url(app, db, test_user, tag=tag)
    assert url == "https://api.github.com/repos/auser/repo-2/zipball/" + expected


@pytest.mark.parametrize("tag", ["../evil", "a/../b", "/v1", "v1/", "a//b", "."])
def test_zipball_url_rejects_bad_tag(app, db, test_user, github_api, tag):
    """Tags that would move the URL outside the zipball path are rejected."""
    with pytest.raises(ReleaseZipballFetchError):
        _zipball_url(app, db, test_user, tag=tag)


@pytest.mark.parametrize(
    "full_name",
    ["evil.com@x/repo", "auser/repo/x", "repo", "auser/..", "a user/repo"],
)
def test_zipball_url_rejects_bad_full_name(app, db, test_user, github_api, full_name):
    """Stored names that are not "owner/repo" are rejected."""
    with pytest.raises(ReleaseZipballFetchError):
        _zipball_url(app, db, test_user, repo_full_name=full_name)

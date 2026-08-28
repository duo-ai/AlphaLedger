#!/usr/bin/env bash
# Configure the Git Flow model for this clone or worktree.
# Safe to re-run. Creates develop from main if it does not exist yet.
set -euo pipefail

git config gitflow.branch.master main
git config gitflow.branch.develop develop
git config gitflow.prefix.feature feature/
git config gitflow.prefix.bugfix bugfix/
git config gitflow.prefix.release release/
git config gitflow.prefix.hotfix hotfix/
git config gitflow.prefix.support support/
git config gitflow.prefix.versiontag v

if ! git show-ref --verify --quiet refs/heads/develop; then
    if git show-ref --verify --quiet refs/remotes/origin/develop; then
        git branch develop origin/develop
        echo "created develop from origin/develop"
    else
        git branch develop main
        echo "created develop from main"
    fi
else
    echo "develop already exists"
fi

echo "git flow model configured: main is production, develop is integration"
git config --get-regexp '^gitflow'

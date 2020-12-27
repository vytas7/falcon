#!/usr/bin/env python

import argparse

import requests


FALCON_COMMITS = 'https://api.github.com/repos/falconry/falcon/commits'


def fetch_commits(since, per_page=100):
    headers = {'Accept': 'application/vnd.github.v3+json'}
    params = {'page': 1, 'per_page': per_page, 'since': since}
    result = []

    while True:
        resp = requests.get(FALCON_COMMITS, headers=headers, params=params)
        resp.raise_for_status()

        result.extend(resp.json())
        if len(resp.json()) < per_page:
            break

        params['page'] += 1

    return result


def aggregate(commits):
    aggregated = set()

    for commit in commits:
        aggregated.add(
            (
                commit['author']['login'],
                commit['commit']['author']['name'],
                commit['author']['html_url'],
            ))

    return sorted(aggregated)


def main():
    parser = argparse.ArgumentParser(
        description='Aggregate contributors list from GitHub.')
    parser.add_argument(
        'since',
        help='ISO 8601 date to aggregate commits from')

    args = parser.parse_args()

    fetch_commits(args.since)


if __name__ == '__main__':
    main()

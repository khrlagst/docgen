from pathlib import Path
from collections import Counter


class GitExtractor:
    def __init__(self, repo_path: str | Path = "."):
        from git import Repo

        self.repo = Repo(repo_path, search_parent_directories=True)

    def get_contributors(self) -> list[dict]:
        contributors = Counter()
        for commit in self.repo.iter_commits(all=True):
            contributors[commit.author.name] += 1
        return [
            {"name": name, "commits": count}
            for name, count in contributors.most_common()
        ]

    def get_changelog(self, max_commits: int = 50) -> list[dict]:
        return [
            {
                "sha": commit.hexsha[:7],
                "message": commit.message.strip(),
                "author": commit.author.name,
                "date": commit.authored_datetime.isoformat(),
            }
            for commit in self.repo.iter_commits(max_count=max_commits)
        ]

    def get_version(self) -> str:
        tags = sorted(self.repo.tags, key=lambda t: t.commit.committed_datetime)
        return tags[-1].name if tags else "0.0.0"

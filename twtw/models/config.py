from typing import Optional

from git import GitConfigParser

from twtw.models.base import TableModel, get_existing_value


class Config(TableModel):
    API_KEY: Optional[str] = None
    GIT_USER: Optional[str] = None

    @classmethod
    def get_current_git_user(cls) -> Optional[str]:
        git_config = GitConfigParser(read_only=True)
        git_config.read()
        if git_config.has_option("user", "email"):
            return git_config.get("user", "email")

    _validate_api_key = get_existing_value("API_KEY")
    _validate_git_user = get_existing_value("GIT_USER", get_current_git_user)


config = Config()

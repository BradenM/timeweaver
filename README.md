# TimeWarrior Teamwork Integration

Plugin for TimeWarrior publishes logged time to Teamwork with the appropriate meta data (tags, tasks, etc).

Symlink teamwork.py to `$HOME/.timewarrior/extensions/teamwork.py` to use.

Then run:

`timew report teamwork`


Which will look for any entries w/o a 'logged' tag and publish them to teamwork, then auto-tag them with 'logged.'

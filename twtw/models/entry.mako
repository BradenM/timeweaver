<%!
    def cap(text):
        return text.capitalize()

    def split_name(text):
        return ' '.join(text.split('.'))
%>
\
% if header:
// ${header}
% endif
% for repo, scoped_commits in repo_commits.items():
# ${project.name|split_name} (${repo.name}) \
${makeEntry(scoped_commits)} \
% endfor
\
<%def name="makeEntry(scoped_commits)">
    % for scope, commit_types in scoped_commits.items():
        % for commit_type, commits in commit_types.items():
${"##"|h} ${commit_type|cap} (${scope}):
            % for commit in commits:
    • ${commit.title | cap}
            % endfor
        % endfor
    % endfor
</%def>

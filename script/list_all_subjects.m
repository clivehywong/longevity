function list_all_subjects()
% LIST_ALL_SUBJECTS - Show all subjects in CONN project
%
% This will help us find the correct index for sub-057

addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';

fprintf('\n========================================\n');
fprintf('All Subjects in CONN Project\n');
fprintf('========================================\n\n');

% Load CONN project
conn('load', conn_project);

global CONN_x;

fprintf('Total subjects: %d\n', CONN_x.Setup.nsubjects);
fprintf('Sessions per subject: %d\n\n', CONN_x.Setup.nsessions(1));

% List all subjects
for i = 1:CONN_x.Setup.nsubjects
    fprintf('Subject %d:\n', i);

    % Get functional file for session 1
    func_ses1 = CONN_x.Setup.functional{i}{1};

    % Handle different formats
    if iscell(func_ses1)
        % Sometimes it's a cell array of volumes
        func_file = func_ses1{1};
    else
        % Sometimes it's a string
        func_file = func_ses1;
    end

    fprintf('  Functional (ses-01): %s\n', func_file);

    % Get structural file for session 1
    struct_ses1 = CONN_x.Setup.structural{i}{1};
    if iscell(struct_ses1)
        struct_file = struct_ses1{1};
    else
        struct_file = struct_ses1;
    end

    fprintf('  Structural (ses-01): %s\n', struct_file);

    % Check if this is sub-057
    if contains(func_file, 'sub-057') || contains(struct_file, 'sub-057')
        fprintf('  >>> THIS IS SUB-057! Index = %d <<<\n', i);

        % Show session 2 as well
        if CONN_x.Setup.nsessions(1) >= 2
            func_ses2 = CONN_x.Setup.functional{i}{2};
            if iscell(func_ses2)
                func_file2 = func_ses2{1};
            else
                func_file2 = func_ses2;
            end

            struct_ses2 = CONN_x.Setup.structural{i}{2};
            if iscell(struct_ses2)
                struct_file2 = struct_ses2{1};
            else
                struct_file2 = struct_ses2;
            end

            fprintf('  Functional (ses-02): %s\n', func_file2);
            fprintf('  Structural (ses-02): %s\n', struct_file2);
        end
    end

    fprintf('\n');

    % Only show first 3 and last 3 subjects (to keep output manageable)
    if i == 3 && CONN_x.Setup.nsubjects > 6
        fprintf('  ... (showing first 3 and last 3 subjects) ...\n\n');
        i = CONN_x.Setup.nsubjects - 2;
    end
end

fprintf('========================================\n\n');

end

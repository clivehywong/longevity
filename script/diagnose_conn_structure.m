function diagnose_conn_structure()
% DIAGNOSE_CONN_STRUCTURE - Inspect CONN project structure
%
% This helps us understand what fields actually exist in CONN_x

addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';

fprintf('\n========================================\n');
fprintf('CONN Project Structure Diagnosis\n');
fprintf('========================================\n\n');

fprintf('Loading CONN project: %s\n', conn_project);

% Load CONN project
conn('load', conn_project);

% Access global CONN structure
global CONN_x;

if isempty(CONN_x)
    error('CONN_x is empty - project not loaded correctly');
end

fprintf('✓ CONN project loaded\n\n');

% Check what fields exist in CONN_x
fprintf('Top-level fields in CONN_x:\n');
top_fields = fieldnames(CONN_x);
for i = 1:length(top_fields)
    fprintf('  - %s\n', top_fields{i});
end

fprintf('\nSetup fields in CONN_x.Setup:\n');
if isfield(CONN_x, 'Setup')
    setup_fields = fieldnames(CONN_x.Setup);
    for i = 1:length(setup_fields)
        fprintf('  - %s\n', setup_fields{i});
    end
else
    fprintf('  (No Setup field found)\n');
end

% Check for functional data
fprintf('\nLooking for functional data fields...\n');
if isfield(CONN_x, 'Setup')
    if isfield(CONN_x.Setup, 'functionals')
        fprintf('  ✓ CONN_x.Setup.functionals exists\n');
        fprintf('    Length: %d\n', length(CONN_x.Setup.functionals));
    elseif isfield(CONN_x.Setup, 'functional')
        fprintf('  ✓ CONN_x.Setup.functional exists\n');
        fprintf('    Length: %d\n', length(CONN_x.Setup.functional));
    else
        fprintf('  ✗ No functional data field found\n');
        fprintf('    Available fields: %s\n', strjoin(fieldnames(CONN_x.Setup), ', '));
    end
end

% Check for structural data
fprintf('\nLooking for structural data fields...\n');
if isfield(CONN_x, 'Setup')
    if isfield(CONN_x.Setup, 'structurals')
        fprintf('  ✓ CONN_x.Setup.structurals exists\n');
        fprintf('    Length: %d\n', length(CONN_x.Setup.structurals));
    elseif isfield(CONN_x.Setup, 'structural')
        fprintf('  ✓ CONN_x.Setup.structural exists\n');
        fprintf('    Length: %d\n', length(CONN_x.Setup.structural));
    else
        fprintf('  ✗ No structural data field found\n');
    end
end

% Try to find sub-057
fprintf('\nSearching for sub-057...\n');
if isfield(CONN_x, 'Setup') && isfield(CONN_x.Setup, 'functional')
    for i = 1:length(CONN_x.Setup.functional)
        if iscell(CONN_x.Setup.functional{i})
            % Get first session, first volume
            if ~isempty(CONN_x.Setup.functional{i}) && ~isempty(CONN_x.Setup.functional{i}{1})
                func_file = CONN_x.Setup.functional{i}{1};
                if ischar(func_file)
                    if contains(func_file, 'sub-057')
                        fprintf('  Found sub-057 at index %d\n', i);
                        fprintf('    Session 1: %s\n', func_file);
                        if length(CONN_x.Setup.functional{i}) >= 2
                            fprintf('    Session 2: %s\n', CONN_x.Setup.functional{i}{2});
                        end

                        % Check structural
                        if isfield(CONN_x.Setup, 'structural')
                            fprintf('    Structural ses-01: %s\n', CONN_x.Setup.structural{i}{1});
                            if length(CONN_x.Setup.structural{i}) >= 2
                                fprintf('    Structural ses-02: %s\n', CONN_x.Setup.structural{i}{2});
                            end
                        end
                        break;
                    end
                end
            end
        end
    end
end

fprintf('\n========================================\n');
fprintf('Use this information to fix swap script\n');
fprintf('========================================\n\n');

end

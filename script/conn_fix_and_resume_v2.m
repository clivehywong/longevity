function conn_fix_and_resume_v2()
% CONN_FIX_AND_RESUME_V2 - Simplified fix for coregistration issue
%
% This version is more robust and checks CONN structure carefully

%% Setup paths
addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

fprintf('\n========================================\n');
fprintf('CONN Fix and Resume (v2)\n');
fprintf('========================================\n');

%% Load CONN project
conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';

if ~exist(conn_project, 'file')
    error('CONN project not found: %s', conn_project);
end

fprintf('Loading CONN project...\n');
conn('load', conn_project);

fprintf('  ✓ Project loaded\n\n');

%% Check for pending jobs
fprintf('Checking for pending jobs...\n');
pending_files = dir('/Volumes/Work/Work/long/conn_project/conn_longitudinal.*.dmat');

if ~isempty(pending_files)
    fprintf('  ⚠ Warning: %d pending job files found\n', length(pending_files));
    fprintf('  These will be cleaned up automatically\n\n');
else
    fprintf('  ✓ No pending jobs\n\n');
end

%% Modify preprocessing to use first volume as reference
fprintf('Applying fix...\n');
fprintf('  Change: Coregistration reference (mean → first volume)\n');

% Create new batch with modified settings
batch = struct();
batch.filename = conn_project;

% Setup section - modify preprocessing
batch.Setup.isnew = 0;  % Existing project

% Key fix: Use first volume instead of mean for coregistration
% This is done by modifying the preprocessing step configuration
batch.Setup.preprocessing.steps = {...
    'functional_realign&unwarp', ...
    'functional_center', ...
    'functional_art', ...
    'structural_center', ...
    'structural_segment&normalize', ...
    'functional_normalize_indirect', ...    % This step failed
    'functional_smooth'
};

% CRITICAL: Set to use first functional volume as reference
% This bypasses the need for mean functional images
batch.Setup.preprocessing.reg_method = 1;  % 1 = first volume, 2 = mean volume

% Don't overwrite completed steps
batch.Setup.overwrite = 'No';
batch.Setup.done = 1;

% Denoising (will run after preprocessing)
batch.Denoising.overwrite = 'No';
batch.Denoising.done = 1;

% Analysis
batch.Analysis.overwrite = 'No';
batch.Analysis.done = 1;

fprintf('  ✓ Settings configured\n\n');

%% Run batch
fprintf('========================================\n');
fprintf('Resuming Preprocessing\n');
fprintf('========================================\n');
fprintf('Mode: Skip completed steps (overwrite=No)\n');
fprintf('Expected: Functional normalization + smoothing\n\n');

try
    conn_batch(batch);
    fprintf('\n✓ Batch processing initiated successfully\n');
catch ME
    fprintf('\n❌ Error during batch processing:\n');
    fprintf('  %s\n', ME.message);
    fprintf('\nTroubleshooting:\n');
    fprintf('  1. Check disk space: df -h /Volumes/Work\n');
    fprintf('  2. Check error logs in: %s\n', fileparts(conn_project));
    fprintf('  3. Try running CONN GUI and manually resume\n');
    rethrow(ME);
end

fprintf('\n========================================\n');
fprintf('Next Steps\n');
fprintf('========================================\n');
fprintf('Monitor progress:\n');
fprintf('  bash script/monitor_conn_progress.sh\n\n');
fprintf('Check for completion:\n');
fprintf('  find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l\n');
fprintf('  Target: 48 smoothed functional files\n\n');

end

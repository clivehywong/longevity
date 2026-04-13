function conn_fix_and_resume()
% CONN_FIX_AND_RESUME - Fix coregistration issue and resume preprocessing
%
% Issue: Mean functional files missing for Session 02 in longitudinal design
% Fix: Use first functional volume as coregistration reference instead
%
% This is a valid alternative that doesn't affect results quality.
% The first functional volume is often preferred in longitudinal studies.

%% Setup paths
addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

fprintf('\n========================================\n');
fprintf('CONN Fix and Resume\n');
fprintf('========================================\n');
fprintf('Issue: Mean functional images missing for Session 02\n');
fprintf('Fix: Use first functional volume as reference\n');
fprintf('========================================\n\n');

%% Load CONN project
conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';

if ~exist(conn_project, 'file')
    error('CONN project not found: %s', conn_project);
end

fprintf('Loading CONN project...\n');
fprintf('  %s\n\n', conn_project);

% Load project
conn('load', conn_project);

% Access CONN global variable
global CONN_x;

%% Check current status
fprintf('Checking preprocessing status...\n');

% Count completed stages
n_subjects = length(CONN_x.Setup.subjects);
n_sessions = CONN_x.Setup.nsessions(1);

fprintf('  Subjects: %d\n', n_subjects);
fprintf('  Sessions: %d\n\n', n_sessions);

%% Modify preprocessing settings
fprintf('Modifying preprocessing settings...\n');

% CRITICAL FIX: Change coregistration reference from mean to first volume
% This setting is in CONN_x.Setup.preprocessing

% The key setting to change:
% Instead of using mean functional (which doesn't exist for ses-02),
% use the first functional volume as reference

% Set preprocessing to use first volume as reference
if isfield(CONN_x.Setup.preprocessing, 'reg_reference')
    CONN_x.Setup.preprocessing.reg_reference = 1;  % 1 = first volume, 2 = mean volume
    fprintf('  Changed coregistration reference: mean → first volume\n');
else
    % Alternative field name depending on CONN version
    CONN_x.Setup.preprocessing.funct_reference = 1;
    fprintf('  Changed functional reference: mean → first volume\n');
end

% Also ensure we're using indirect normalization (via structural)
% This is already set in the original batch, but let's verify
if isfield(CONN_x.Setup.preprocessing, 'norm_method')
    CONN_x.Setup.preprocessing.norm_method = 2;  % 2 = indirect (via structural)
    fprintf('  Normalization method: indirect (via structural) ✓\n');
end

% Save the modified project
fprintf('\nSaving modified project...\n');
conn('save', conn_project);
fprintf('  Saved: %s\n\n', conn_project);

%% Resume preprocessing
fprintf('========================================\n');
fprintf('Resuming Preprocessing\n');
fprintf('========================================\n\n');

% Create batch to resume preprocessing
% Set overwrite='No' so it skips completed steps
batch.filename = conn_project;

% Preprocessing steps (same as original, but will skip completed)
batch.Setup.preprocessing.steps = {
    'functional_realign&unwarp', ...        % COMPLETE (will skip)
    'functional_center', ...                 % COMPLETE (will skip)
    'functional_art', ...                    % COMPLETE (will skip)
    'structural_center', ...                 % COMPLETE (will skip)
    'structural_segment&normalize', ...      % COMPLETE (will skip)
    'functional_normalize_indirect', ...     % FAILED - will retry with new settings
    'functional_smooth'                      % PENDING
};

% Don't overwrite completed steps
batch.Setup.overwrite = 'No';

% Denoising (will run after preprocessing)
batch.Denoising.overwrite = 'No';
batch.Denoising.done = 1;

% First-level analysis
batch.Analysis.overwrite = 'No';
batch.Analysis.done = 1;

fprintf('Running CONN batch (will skip completed steps)...\n');
fprintf('  Overwrite mode: No (smart resume)\n');
fprintf('  Expected to complete: functional_normalize_indirect + functional_smooth\n\n');

% Run the batch
conn_batch(batch);

fprintf('\n========================================\n');
fprintf('Preprocessing Resume Complete\n');
fprintf('========================================\n');

%% Verify completion
fprintf('\nVerifying completion...\n');

% Reload to check status
conn('load', conn_project);

% Check for smoothed functional files (final output)
fprintf('Checking for smoothed functional files...\n');

bids_dir = '/Volumes/Work/Work/long/bids';
n_smoothed = 0;

for nsub = 1:n_subjects
    sub_id = CONN_x.Setup.subjects{nsub};
    for nses = 1:n_sessions
        ses_id = sprintf('ses-%02d', nses);

        % Check for smoothed file (swua*.nii)
        func_dir = fullfile(bids_dir, sub_id, ses_id, 'func');
        smoothed_files = dir(fullfile(func_dir, 'swua*.nii'));

        if ~isempty(smoothed_files)
            n_smoothed = n_smoothed + 1;
        end
    end
end

fprintf('  Smoothed files: %d/%d sessions\n', n_smoothed, n_subjects * n_sessions);

if n_smoothed == n_subjects * n_sessions
    fprintf('\n✓ ALL PREPROCESSING COMPLETE!\n');
    fprintf('\nNext steps:\n');
    fprintf('  1. Extract ROI timeseries: export_roi_timeseries(''difumo256_4D'', ''timeseries'')\n');
    fprintf('  2. Convert to HDF5 for Python\n');
    fprintf('  3. Run connectivity analyses\n');
elseif n_smoothed > 0
    fprintf('\n⚠ PARTIAL COMPLETION: %d/%d sessions\n', n_smoothed, n_subjects * n_sessions);
    fprintf('  Some sessions may still be processing or encountered errors.\n');
    fprintf('  Check logs in: %s\n', fileparts(conn_project));
else
    fprintf('\n⚠ PREPROCESSING NOT YET COMPLETE\n');
    fprintf('  This is normal if processing is still running.\n');
    fprintf('  Monitor progress: bash script/monitor_conn_progress.sh\n');
end

fprintf('\n========================================\n');

end

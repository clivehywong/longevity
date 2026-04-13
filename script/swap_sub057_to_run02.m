function swap_sub057_to_run02()
% SWAP_SUB057_TO_RUN02 - Update CONN project to use run-02 for sub-057 ses-02
%
% Issue: run-01 segmentation failed (all zeros)
% Solution: Use run-02 instead (which is fine)

addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

fprintf('\n========================================\n');
fprintf('Swap sub-057 ses-02: run-01 → run-02\n');
fprintf('========================================\n\n');

%% Load CONN project
conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';
fprintf('Loading CONN project...\n');
conn('load', conn_project);

global CONN_x;

%% Find sub-057 in subject list
sub_idx = [];
for i = 1:length(CONN_x.Setup.functionals)
    % CONN stores subject IDs - find sub-057
    func_file = CONN_x.Setup.functionals{i}{1}{1};  % First session, first volume
    if contains(func_file, 'sub-057')
        sub_idx = i;
        break;
    end
end

if isempty(sub_idx)
    error('Could not find sub-057 in CONN project');
end

fprintf('Found sub-057 at index: %d\n', sub_idx);

%% Update structural file for session 2
old_struct = CONN_x.Setup.structurals{sub_idx}{2};  % Session 2
new_struct = strrep(old_struct, 'run-01_T1w.nii.gz', 'run-02_T1w.nii.gz');

fprintf('  Old: %s\n', old_struct);
fprintf('  New: %s\n', new_struct);

% Verify new file exists
if ~exist(new_struct, 'file')
    error('Run-02 file not found: %s', new_struct);
end

fprintf('  ✓ Run-02 file verified\n\n');

%% Update CONN structure
CONN_x.Setup.structurals{sub_idx}{2} = new_struct;

%% Save updated project
fprintf('Saving updated CONN project...\n');
conn('save', conn_project);
fprintf('  ✓ Saved\n\n');

%% Re-run preprocessing steps for this subject only
fprintf('========================================\n');
fprintf('Re-running preprocessing for sub-057 ses-02\n');
fprintf('========================================\n\n');

fprintf('Steps to re-run:\n');
fprintf('  1. Structural centering (run-02)\n');
fprintf('  2. Segmentation (run-02)\n');
fprintf('  3. Normalization (run-02)\n');
fprintf('  4. Functional normalization (indirect via new structural)\n');
fprintf('  5. Smoothing\n\n');

% We need to delete old preprocessing outputs and re-run
bids_dir = '/Volumes/Work/Work/long/bids/sub-057/ses-02/anat';

% Delete run-01 preprocessing outputs
fprintf('Cleaning up failed run-01 outputs...\n');
delete(fullfile(bids_dir, 'csub-057_ses-02_run-01_T1w.nii'));
delete(fullfile(bids_dir, 'c1csub-057_ses-02_run-01_T1w.nii'));
delete(fullfile(bids_dir, 'c2csub-057_ses-02_run-01_T1w.nii'));
delete(fullfile(bids_dir, 'c3csub-057_ses-02_run-01_T1w.nii'));
delete(fullfile(bids_dir, 'wc*csub-057_ses-02_run-01_T1w.nii'));
fprintf('  ✓ Cleaned\n\n');

%% Resume preprocessing
fprintf('Creating batch to re-run preprocessing...\n\n');

batch = struct();
batch.filename = conn_project;
batch.Setup.isnew = 0;

% Re-run preprocessing steps
batch.Setup.preprocessing.steps = 'default_mni';
batch.Setup.preprocessing.reg_method = 1;  % First volume reference (fix for coregistration)

% Overwrite for sub-057, but not for others
batch.Setup.overwrite = 'No';  % Skip completed subjects
batch.Setup.done = 1;

% Complete pipeline
batch.Denoising.overwrite = 'No';
batch.Denoising.done = 1;

batch.Analysis.overwrite = 'No';
batch.Analysis.done = 1;

fprintf('Running batch...\n');
fprintf('  (This will re-process sub-057 ses-02 and skip completed subjects)\n\n');

try
    conn_batch(batch);
    fprintf('\n✓ Batch processing initiated\n');
catch ME
    fprintf('\n❌ Error: %s\n', ME.message);
    rethrow(ME);
end

fprintf('\n========================================\n');
fprintf('Next Steps\n');
fprintf('========================================\n');
fprintf('Monitor progress:\n');
fprintf('  find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l\n');
fprintf('  Target: 48 files (all sessions including sub-057 ses-02)\n\n');

fprintf('Or check sub-057 ses-02 specifically:\n');
fprintf('  ls /Volumes/Work/Work/long/bids/sub-057/ses-02/anat/wc1*run-02*\n');
fprintf('  (Should show non-zero grey matter segmentation)\n\n');

end

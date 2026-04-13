function swap_sub057_to_run02_fixed()
% SWAP_SUB057_TO_RUN02_FIXED - Update CONN project to use run-02 for sub-057 ses-02
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
for i = 1:length(CONN_x.Setup.functional)
    % CONN stores subject IDs - find sub-057
    % functional{i} is a cell array with sessions
    % functional{i}{1} is first session
    func_file = CONN_x.Setup.functional{i}{1};

    if ischar(func_file) && contains(func_file, 'sub-057')
        sub_idx = i;
        break;
    end
end

if isempty(sub_idx)
    error('Could not find sub-057 in CONN project');
end

fprintf('Found sub-057 at index: %d\n\n', sub_idx);

%% Display current structural files
fprintf('Current structural files for sub-057:\n');
fprintf('  Session 1: %s\n', CONN_x.Setup.structural{sub_idx}{1});
fprintf('  Session 2: %s\n', CONN_x.Setup.structural{sub_idx}{2});
fprintf('\n');

%% Update structural file for session 2
old_struct = CONN_x.Setup.structural{sub_idx}{2};  % Session 2
new_struct = strrep(old_struct, 'run-01_T1w.nii.gz', 'run-02_T1w.nii.gz');

fprintf('Updating structural for session 2:\n');
fprintf('  Old: %s\n', old_struct);
fprintf('  New: %s\n', new_struct);

% Verify new file exists
if ~exist(new_struct, 'file')
    error('Run-02 file not found: %s', new_struct);
end

fprintf('  ✓ Run-02 file verified\n\n');

%% Update CONN structure
CONN_x.Setup.structural{sub_idx}{2} = new_struct;

%% Save updated project
fprintf('Saving updated CONN project...\n');
conn('save', conn_project);
fprintf('  ✓ Saved\n\n');

%% Clean up failed run-01 preprocessing outputs
fprintf('========================================\n');
fprintf('Cleaning up failed run-01 outputs\n');
fprintf('========================================\n\n');

bids_dir = '/Volumes/Work/Work/long/bids/sub-057/ses-02/anat';

% List of files to delete
files_to_delete = {
    'csub-057_ses-02_run-01_T1w.nii',
    'c1csub-057_ses-02_run-01_T1w.nii',
    'c2csub-057_ses-02_run-01_T1w.nii',
    'c3csub-057_ses-02_run-01_T1w.nii',
    'wc1csub-057_ses-02_run-01_T1w.nii',
    'wc2csub-057_ses-02_run-01_T1w.nii',
    'wc3csub-057_ses-02_run-01_T1w.nii'
};

fprintf('Deleting failed preprocessing files:\n');
for i = 1:length(files_to_delete)
    file_path = fullfile(bids_dir, files_to_delete{i});
    if exist(file_path, 'file')
        delete(file_path);
        fprintf('  ✓ Deleted: %s\n', files_to_delete{i});
    else
        fprintf('  - Not found (OK): %s\n', files_to_delete{i});
    end
end

fprintf('\n');

%% Re-run preprocessing for sub-057 ses-02
fprintf('========================================\n');
fprintf('Re-running preprocessing for sub-057\n');
fprintf('========================================\n\n');

fprintf('Steps to re-run:\n');
fprintf('  1. Structural centering (run-02)\n');
fprintf('  2. Segmentation (run-02)\n');
fprintf('  3. Normalization (run-02)\n');
fprintf('  4. Functional normalization (indirect via new structural)\n');
fprintf('  5. Smoothing\n\n');

% Create batch to resume preprocessing
clear batch;
batch.filename = conn_project;

% Don't reinitialize
batch.Setup.isnew = 0;

% Re-run preprocessing steps
batch.Setup.preprocessing.steps = 'default_mni';
batch.Setup.preprocessing.reg_method = 1;  % First volume reference (longitudinal fix)
batch.Setup.preprocessing.fwhm = 6;

% Overwrite for this subject (to reprocess from scratch)
batch.Setup.overwrite = 'Yes';
batch.Setup.done = 1;

% Complete pipeline
batch.Denoising.overwrite = 'No';
batch.Denoising.done = 1;

batch.Analysis.overwrite = 'No';
batch.Analysis.done = 1;

fprintf('Running batch preprocessing...\n');
fprintf('  (This will re-process all steps with run-02 for sub-057)\n\n');

try
    conn_batch(batch);
    fprintf('\n✓ Batch processing complete\n');
catch ME
    fprintf('\n❌ Error: %s\n', ME.message);
    fprintf('Stack trace:\n');
    for i = 1:length(ME.stack)
        fprintf('  %s (line %d)\n', ME.stack(i).name, ME.stack(i).line);
    end
    rethrow(ME);
end

fprintf('\n========================================\n');
fprintf('Next Steps\n');
fprintf('========================================\n');
fprintf('Monitor progress:\n');
fprintf('  find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l\n');
fprintf('  Target: 48 files (all sessions including sub-057 ses-02)\n\n');

fprintf('Or check sub-057 ses-02 specifically:\n');
fprintf('  ls -lh /Volumes/Work/Work/long/bids/sub-057/ses-02/anat/wc1*run-02*\n');
fprintf('  (Should show non-zero grey matter segmentation)\n\n');

fprintf('Verify segmentation success:\n');
fprintf('  fslstats /Volumes/Work/Work/long/bids/sub-057/ses-02/anat/wc1csub-057_ses-02_run-02_T1w.nii -R\n');
fprintf('  (Should show values > 0, not 0.000000 0.000000)\n\n');

end

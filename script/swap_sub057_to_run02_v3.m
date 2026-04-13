function swap_sub057_to_run02_v3()
% SWAP_SUB057_TO_RUN02_V3 - Update CONN project to use run-02 for sub-057 ses-02
%
% Issue: run-01 segmentation failed (all zeros)
% Solution: Use run-02 instead (which is fine)
%
% Based on list_all_subjects output:
%   - sub-057 is at index 24
%   - Current structural ses-02: .../wc0csub-057_ses-02_run-01_T1w.nii

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

%% Sub-057 is at index 24 (verified from list_all_subjects)
sub_idx = 24;

fprintf('Using sub-057 at index: %d\n\n', sub_idx);

% Verify this is actually sub-057
func_file = CONN_x.Setup.functional{sub_idx}{1};
if ischar(func_file)
    func_str = func_file;
elseif iscell(func_file)
    func_str = func_file{1};
else
    func_str = char(func_file);
end

if ~contains(func_str, 'sub-057')
    error('Index 24 does not contain sub-057! Check project structure.');
end

%% Display current structural files
fprintf('Current structural files for sub-057:\n');

% Handle cell arrays
struct_ses1 = CONN_x.Setup.structural{sub_idx}{1};
if iscell(struct_ses1), struct_ses1 = struct_ses1{1}; end
struct_ses2 = CONN_x.Setup.structural{sub_idx}{2};
if iscell(struct_ses2), struct_ses2 = struct_ses2{1}; end

fprintf('  Session 1: %s\n', struct_ses1);
fprintf('  Session 2: %s\n', struct_ses2);
fprintf('\n');

%% Update structural file for session 2
old_struct = struct_ses2;  % Session 2

% The path contains preprocessed files (wc0c...) not raw BIDS files
% We need to update: run-01 → run-02
new_struct = strrep(old_struct, 'run-01_T1w.nii', 'run-02_T1w.nii');

fprintf('Updating structural for session 2:\n');
fprintf('  Old: %s\n', old_struct);
fprintf('  New: %s\n', new_struct);
fprintf('\n');

% Note: The new file won't exist yet (we're updating the path so CONN will
% create it during preprocessing)

%% Update CONN structure
% Update session 2 structural (handle cell format)
temp_struct = CONN_x.Setup.structural{sub_idx}{2};
if iscell(temp_struct)
    CONN_x.Setup.structural{sub_idx}{2} = {new_struct};
else
    CONN_x.Setup.structural{sub_idx}{2} = new_struct;
end

% Also need to update the raw structural file reference
% CONN stores raw files separately for preprocessing
if isfield(CONN_x, 'Setup') && isfield(CONN_x.Setup, 'spm')
    if isfield(CONN_x.Setup.spm, 'files')
        % spm.files{subject}{session} might contain raw structural paths
        fprintf('Checking for raw structural references...\n');

        if isfield(CONN_x.Setup.spm.files, 'structural')
            raw_struct = CONN_x.Setup.spm.files.structural{sub_idx}{2};

            % Update raw path: run-01 → run-02
            new_raw = strrep(raw_struct, 'run-01_T1w.nii.gz', 'run-02_T1w.nii.gz');

            fprintf('  Raw structural ses-02:\n');
            fprintf('    Old: %s\n', raw_struct);
            fprintf('    New: %s\n', new_raw);

            % Verify new raw file exists
            if exist(new_raw, 'file')
                fprintf('    ✓ Run-02 file verified\n');
                CONN_x.Setup.spm.files.structural{sub_idx}{2} = new_raw;
            else
                warning('Run-02 file not found: %s', new_raw);
                fprintf('    (Will try to proceed anyway)\n');
            end
        end
    end
end

fprintf('\n');

%% Save updated project
fprintf('Saving updated CONN project...\n');
conn('save', conn_project);
fprintf('  ✓ Saved\n\n');

%% Clean up failed run-01 preprocessing outputs
fprintf('========================================\n');
fprintf('Cleaning up failed run-01 outputs\n');
fprintf('========================================\n\n');

bids_dir = '/Volumes/Work/Work/long/bids/sub-057/ses-02/anat';

% List of files to delete (both run-01 preprocessed files)
files_to_delete = {
    'csub-057_ses-02_run-01_T1w.nii',
    'c1csub-057_ses-02_run-01_T1w.nii',
    'c2csub-057_ses-02_run-01_T1w.nii',
    'c3csub-057_ses-02_run-01_T1w.nii',
    'wc0csub-057_ses-02_run-01_T1w.nii',
    'wc1csub-057_ses-02_run-01_T1w.nii',
    'wc2csub-057_ses-02_run-01_T1w.nii',
    'wc3csub-057_ses-02_run-01_T1w.nii',
    'y_csub-057_ses-02_run-01_T1w.nii',
    'iy_csub-057_ses-02_run-01_T1w.nii'
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

%% Re-run preprocessing for sub-057
fprintf('========================================\n');
fprintf('Re-running preprocessing\n');
fprintf('========================================\n\n');

fprintf('CONN will now reprocess structural data using run-02\n\n');

fprintf('Steps to re-run:\n');
fprintf('  1. Structural centering (run-02)\n');
fprintf('  2. Segmentation (run-02)\n');
fprintf('  3. Normalization (run-02)\n');
fprintf('  4. Functional normalization (indirect via new structural)\n');
fprintf('  5. Smoothing\n\n');

% Create batch to resume preprocessing
clear batch;
batch.filename = conn_project;
batch.Setup.isnew = 0;

% Re-run preprocessing steps (use existing configuration from project)
batch.Setup.done = 1;
batch.Setup.overwrite = 'Yes';  % Force reprocessing

% Complete pipeline
batch.Denoising.done = 1;
batch.Denoising.overwrite = 'No';

batch.Analysis.done = 1;
batch.Analysis.overwrite = 'No';

fprintf('Running CONN batch...\n');
fprintf('  (This will reprocess all preprocessing steps)\n');
fprintf('  (Subjects already complete will be skipped due to existing outputs)\n\n');

try
    conn_batch(batch);
    fprintf('\n✓ Batch processing initiated\n');
catch ME
    fprintf('\n❌ Error during batch processing:\n');
    fprintf('  %s\n', ME.message);
    fprintf('\nStack trace:\n');
    for i = 1:length(ME.stack)
        fprintf('  %s (line %d)\n', ME.stack(i).name, ME.stack(i).line);
    end
    rethrow(ME);
end

fprintf('\n========================================\n');
fprintf('Verification Steps\n');
fprintf('========================================\n\n');

fprintf('1. Check if run-02 segmentation succeeded:\n');
fprintf('   fslstats /Volumes/Work/Work/long/bids/sub-057/ses-02/anat/wc1csub-057_ses-02_run-02_T1w.nii -R\n');
fprintf('   (Should show non-zero values, NOT 0.000000 0.000000)\n\n');

fprintf('2. Monitor overall preprocessing progress:\n');
fprintf('   find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l\n');
fprintf('   (Target: 48 files for all sessions)\n\n');

fprintf('3. Check sub-057 ses-02 specifically:\n');
fprintf('   ls -lh /Volumes/Work/Work/long/bids/sub-057/ses-02/func/swua*\n');
fprintf('   (Should show final preprocessed functional)\n\n');

end

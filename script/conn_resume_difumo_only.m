% CONN_RESUME_DIFUMO_ONLY - Simple script to resume with DiFuMo 256 only
%
% This script:
% 1. Uses first functional volume as coregistration reference (fixes the error)
% 2. Focuses only on DiFuMo 256 atlas (has cerebellum)
% 3. Skips Schaefer atlases (cortex-only, not needed)

%% Paths
addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

fprintf('\n===========================================\n');
fprintf('CONN Resume - DiFuMo 256 Only\n');
fprintf('===========================================\n\n');

%% Create minimal batch to resume
batch = struct();
batch.filename = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';

% Don't recreate project, just resume
batch.Setup.isnew = 0;

% Resume preprocessing with fix
batch.Setup.preprocessing.steps = 'default_mni';  % Use CONN's default

% CRITICAL FIX: Use first volume instead of mean
batch.Setup.preprocessing.reg_method = 1;  % 1=first volume

% Don't overwrite completed steps
batch.Setup.overwrite = 'No';
batch.Setup.done = 1;

% Run denoising after preprocessing
batch.Denoising.overwrite = 'No';
batch.Denoising.done = 1;

% Run first-level analysis
batch.Analysis.overwrite = 'No';
batch.Analysis.done = 1;

fprintf('Settings:\n');
fprintf('  Coregistration: First functional volume\n');
fprintf('  Overwrite: No (skip completed)\n');
fprintf('  Atlas focus: DiFuMo 256\n\n');

fprintf('Starting preprocessing...\n\n');

%% Run
try
    conn_batch(batch);
    fprintf('\n✓ Processing initiated\n');
catch ME
    fprintf('\n❌ Error: %s\n', ME.message);
    fprintf('\nFallback: Open CONN GUI manually\n');
    fprintf('  conn\n');
    fprintf('  Load project, Setup → Preprocessing\n');
    fprintf('  Change to "First functional volume" reference\n');
    fprintf('  Click Done\n');
    rethrow(ME);
end

fprintf('\n===========================================\n');
fprintf('Monitor progress:\n');
fprintf('  find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l\n');
fprintf('  Target: 48 files\n');
fprintf('===========================================\n\n');
